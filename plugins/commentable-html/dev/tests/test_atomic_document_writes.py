#!/usr/bin/env python3
"""CMH-TOOL-22: every tool that rewrites a user's document writes it ATOMICALLY.

SKILL.md tells an agent to run these tools straight at a real document, so a truncating
`open(path, "w")` puts the user's ONLY copy at risk: the target is emptied before the
replacement bytes exist, and a full disk, an encoding error, a killed run or a Ctrl+C leaves
half a document (or none). #1087 closed that for the validated stamp; this module holds the
same line for the whole tools tree.

Two layers, because either alone rots:

- A behavioral case per tool. Each one first proves the tool really does rewrite the fixture
  (otherwise the sabotaged run would pass vacuously), then repeats it with every write failing
  halfway and asserts the original bytes survived byte for byte, no staged file leaked, and the
  failure was reported rather than swallowed.
- A static guard over the shipped tools tree, so a NEW tool cannot quietly reintroduce a
  truncating write that no behavioral case happens to cover.
"""
import ast
import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import _paths  # noqa: E402  shared pkg/dev split path constants
import _io_faults  # noqa: E402  the shared disk-full fault injector

sys.path.insert(0, _paths.TOOLS)
import _atomic_io  # noqa: E402
import checklist_apply  # noqa: E402
import checklist_scaffold  # noqa: E402
import content_extract  # noqa: E402
import content_replace  # noqa: E402
import deck_fix_fonts  # noqa: E402
import deck_scaffold  # noqa: E402
import doc_stats  # noqa: E402
import fix_skip  # noqa: E402
import generate_toc  # noqa: E402
import highlight_document  # noqa: E402
import inline_images  # noqa: E402
import mark_handled  # noqa: E402
import mark_reviewed  # noqa: E402
import new_document  # noqa: E402
import normalize_typography  # noqa: E402
import notes_apply  # noqa: E402
import notes_scaffold  # noqa: E402
import pptx_to_fragment  # noqa: E402
import vendored_libs  # noqa: E402
import wrap_sections  # noqa: E402

EM_DASH = "\u2014"

# A one-pixel PNG, so inline_images has a real local image to read and base64 in.
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00"
       b"\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
       b"\x00\x00\x00\x00IEND\xaeB`\x82")


def _root_doc(body, head=""):
    return ("<!doctype html>\n<html><head>%s</head><body>\n"
            '<main id="commentRoot" data-comment-key="k" data-cmh-content-root>\n'
            "%s\n</main>\n</body></html>\n" % (head, body))


HANDLED_DOC = (
    "<!DOCTYPE html>\n<html><body>\n"
    '<script type="application/json" id="handledCommentIds">\n[]\n</script>\n'
    "<main>body</main>\n</body></html>\n")

REVIEWED_DOC = (
    "<!doctype html>\n<html><head></head><body>\n"
    '<script type="application/json" id="reviewedSections">\n{}\n</script>\n'
    '<main id="commentRoot" data-cmh-content-root>\n'
    '<h2 id="goals">Goals</h2><p>The goals of the plan.</p>\n'
    "</main>\n</body></html>\n")

NOTES_DOC = (
    "<!DOCTYPE html><html><body>\n"
    '<div class="cmh-note" data-cmh-note="risk" data-cmh-note-label="Risk">No blocking risks yet.</div>\n'
    "</body></html>\n")

CHECKLIST_DOC = (
    "<!DOCTYPE html><html><body>\n"
    '<div class="cmh-checklist" data-cmh-checklist="release" data-cmh-checklist-label="Release">\n'
    "  <ul>\n"
    '    <li data-cmh-item="rel" data-cmh-state="blank">Release notes</li>\n'
    "  </ul>\n"
    "</div>\n</body></html>\n")

DECK_DOC = (
    "<!doctype html>\n<html><head>\n<style>\n"
    '@import url("https://fonts.googleapis.com/css2?family=Bebas+Neue");\n'
    ":root { --font-body: \"Inter\", sans-serif; }\n"
    "</style>\n</head><body>\n<div class=\"slide\">Slide</div>\n</body></html>\n")


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _doc_case(text, argv, name="doc.html"):
    """A setup that drops `text` at <dir>/<name> and hands back (path, argv-for-that-path)."""
    def setup(directory):
        path = os.path.join(directory, name)
        _write(path, text)
        return path, argv(path)
    return setup


def _images_setup(directory):
    path = os.path.join(directory, "doc.html")
    with open(os.path.join(directory, "pixel.png"), "wb") as fh:
        fh.write(PNG)
    _write(path, '<html><body><img src="pixel.png"></body></html>\n')
    return path, [path]


def _vendored_setup(directory):
    # A document with no mermaid/chart content but carrying the payload script: the tool
    # strips the payload, which is an in-place rewrite of the user's document.
    path = os.path.join(directory, "doc.html")
    blob = '<script id="%s">window.x=1;</script>\n' % vendored_libs.BLOB_ID
    _write(path, ("<!doctype html>\n<html><body>\n"
                  '<main id="commentRoot" data-comment-key="k"><p>plain prose</p></main>\n'
                  + blob + "</body></html>\n"))
    return path, ["vendored_libs.py", path]


def _extract_setup(directory):
    # content_extract reads a document and writes its CONTENT region to --out. The --out here is
    # an EXISTING file, which is the losable case a caller-named output has.
    source = os.path.join(directory, "source.html")
    _write(source, _root_doc(
        "<!-- BEGIN: commentable-html - CONTENT (agent edits ONLY between these markers) -->\n"
        "<p>content</p>\n"
        "<!-- END: commentable-html - CONTENT -->"))
    out = os.path.join(directory, "fragment.html")
    _write(out, "<p>the previous fragment, which must survive a failed write</p>\n")
    return out, [source, "--out", out]


def _notes_scaffold_setup(directory):
    out = os.path.join(directory, "note.html")
    _write(out, "<p>the previous scaffold, which must survive a failed write</p>\n")
    return out, ["notes_scaffold.py", "--id", "risk", "--label", "Risk",
                 "--text", "No blocking risks yet.", "--out", out]


def _checklist_scaffold_setup(directory):
    outline = os.path.join(directory, "outline.txt")
    _write(outline, "Backend\n\tMigrations\nDocs\n")
    out = os.path.join(directory, "checklist.html")
    _write(out, "<p>the previous scaffold, which must survive a failed write</p>\n")
    return out, ["checklist_scaffold.py", "--in", outline, "--id", "release", "--out", out]


def _pptx_setup(directory):
    slides = os.path.join(directory, "slides.json")
    _write(slides, '[{"title": "One", "bullets": ["a", "b"]}]\n')
    out = os.path.join(directory, "fragment.html")
    _write(out, "<p>the previous fragment, which must survive a failed write</p>\n")
    return out, ["--input", slides, "--out", out]


def _new_document_setup(directory):
    out = os.path.join(directory, "doc.html")
    _write(out, "<p>the previous document, which must survive a failed --force write</p>\n")
    content = os.path.join(directory, "content.html")
    _write(content, "<h1>Title</h1>\n<p>Body text.</p>\n")
    # --allow-unvalidated-output: the sabotaged run breaks the tool's own self-validation step
    # (it stages the candidate through a temp file too), and an abort there would never reach the
    # write this case exists to exercise.
    return out, ["new_document.py", "--out", out, "--force", "--content", content,
                 "--key", "atomic-write-case", "--label", "Doc", "--kind", "report",
                 "--allow-unvalidated-output"]


def _deck_scaffold_setup(directory):
    out = os.path.join(directory, "deck.html")
    _write(out, "<p>the previous deck, which must survive a failed --force write</p>\n")
    return out, ["--out", out, "--force", "--label", "Deck", "--key", "atomic-deck-case",
                 "--slides", "1"]


# (name, setup(directory) -> (target path, argv), run(argv) -> exit code or raise)
CASES = (
    ("mark_handled", _doc_case(HANDLED_DOC, lambda p: ["mark_handled.py", p, "cabc123"]),
     mark_handled.main),
    ("mark_reviewed", _doc_case(REVIEWED_DOC,
                                lambda p: [p, "goals", "--at", "2026-01-01T00:00:00Z"]),
     mark_reviewed.main),
    ("notes_apply", _doc_case(NOTES_DOC, lambda p: [
        "notes_apply.py", p, "--state-json", '{"risk": "One blocker: not reversible."}']),
     notes_apply.main),
    ("checklist_apply", _doc_case(CHECKLIST_DOC, lambda p: [
        "checklist_apply.py", p, "--state-json", '{"release": {"rel": "check"}}']),
     checklist_apply.main),
    ("generate_toc", _doc_case(_root_doc('<section><h2 id="alpha">Alpha</h2><p>one</p></section>'),
                               lambda p: ["generate_toc.py", p, "--in-place"]),
     generate_toc.main),
    ("doc_stats", _doc_case(_root_doc(
        '<h1>Title</h1>\n<section aria-labelledby="alpha"><h2 id="alpha">Alpha</h2><p>one two</p></section>'),
        lambda p: ["doc_stats.py", p, "--in-place"]), doc_stats.main),
    ("normalize_typography", _doc_case("<html><body><p>alpha%sbeta</p></body></html>\n" % EM_DASH,
                                       lambda p: ["normalize_typography.py", p]),
     normalize_typography.main),
    ("wrap_sections", _doc_case(_root_doc('<h2 id="alpha">Alpha</h2>\n<p>one</p>'),
                                lambda p: ["wrap_sections.py", p]), wrap_sections.main),
    ("fix_skip", _doc_case('<html><body><pre class="mermaid">graph TD; A-->B;</pre></body></html>\n',
                           lambda p: ["fix_skip.py", p]), fix_skip.main),
    ("inline_images", _images_setup, inline_images.main),
    ("vendored_libs", _vendored_setup, vendored_libs.main),
    ("highlight_document", _doc_case(
        '<html><body><pre><code class="language-python">def f(): pass</code></pre></body></html>\n',
        lambda p: ["highlight_document.py", p]), highlight_document.main),
    ("deck_fix_fonts", _doc_case(DECK_DOC, lambda p: [p]), deck_fix_fonts.main),
    # The --out tools: the target they overwrite is a file the CALLER named, so it can (and here
    # does) already exist and hold bytes the user would lose.
    ("content_extract", _extract_setup, content_extract.main),
    ("notes_scaffold", _notes_scaffold_setup, notes_scaffold.main),
    ("checklist_scaffold", _checklist_scaffold_setup, checklist_scaffold.main),
    ("pptx_to_fragment", _pptx_setup, pptx_to_fragment.main),
    ("new_document", _new_document_setup, new_document.main),
    # deck_scaffold self-validates through a NamedTemporaryFile before writing. That temp write
    # is sabotaged too, so the run would abort before reaching the write this case exists to
    # exercise; the in-memory deck contract check (deck_checks) still runs.
    ("deck_scaffold", _deck_scaffold_setup, deck_scaffold.main,
     ((deck_scaffold, "_validate", None),)),
)


class AtomicDocumentWriteTests(unittest.TestCase):
    """Every tool that rewrites the user's document survives an interrupted write."""

    def _tmpdir(self):
        directory = tempfile.mkdtemp(prefix="cmh-atomic-doc-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        return directory

    @staticmethod
    def _read(path):
        with open(path, "rb") as fh:
            return fh.read()

    @staticmethod
    def _run(run, argv):
        """Run the tool quietly. Returns (outcome, code): 'raised' or 'returned'."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                return "returned", run(list(argv))
            except OSError:
                return "raised", None

    def test_an_interrupted_write_leaves_the_document_untouched(self):
        for case in CASES:
            name, setup, run = case[0], case[1], case[2]
            patches = case[3] if len(case) > 3 else ()
            with self.subTest(tool=name):
                for owner, attribute, value in patches:
                    patcher = mock.patch.object(owner, attribute, value)
                    patcher.start()
                    self.addCleanup(patcher.stop)
                directory = self._tmpdir()
                path, argv = setup(directory)
                original = self._read(path)
                before = sorted(os.listdir(directory))

                # Control: the case must genuinely rewrite the target, or the sabotaged run below
                # would pass without ever reaching a write.
                outcome, code = self._run(run, argv)
                self.assertEqual(outcome, "returned", "%s failed on a clean run" % name)
                self.assertEqual(code, 0, "%s failed on a clean run" % name)
                self.assertNotEqual(self._read(path), original,
                                    "%s did not rewrite its target; the case proves nothing" % name)
                with open(path, "wb") as fh:
                    fh.write(original)

                # Sabotage every write halfway, by MODE not by path: a truncating tool writes the
                # target itself while an atomic one writes a staged temp file by descriptor, so a
                # path-based condition would stop testing the moment the write became atomic. The
                # patchers go on an ExitStack - never `mock.patch.stopall()`, which would also
                # tear down any patcher another module started in this process, and never a bare
                # loop, which leaks the first patcher if the second `start()` raises.
                reached = []
                real_write = _atomic_io.atomic_write

                def spy(target, text, fallback=None):
                    reached.append(os.path.realpath(target))
                    return real_write(target, text, fallback=fallback)

                with contextlib.ExitStack() as stack:
                    stack.enter_context(mock.patch.object(_atomic_io, "atomic_write", spy))
                    for target, real in (("io.open", io.open), ("builtins.open", open)):
                        stack.enter_context(
                            mock.patch(target, _io_faults.half_writing_opener(real)))
                    outcome, code = self._run(run, argv)

                self.assertNotEqual((outcome, code), ("returned", 0),
                                    "%s reported success after a failed write" % name)
                # Prove the run actually REACHED the shared writer for THIS target. Without it a
                # case can pass because the tool aborted earlier (a self-validation step, say)
                # and never tried to write the file at all - green, and testing nothing.
                self.assertIn(os.path.realpath(path), reached,
                              "%s never reached _atomic_io.atomic_write for its target; the case "
                              "is vacuous (writes seen: %s)" % (name, reached))
                self.assertEqual(self._read(path), original,
                                 "%s must leave the target byte for byte after a failed write" % name)
                # Assert on the WHOLE directory, not just a `.cmh-` prefix: a leaked staging file
                # under any other name is the same leak.
                self.assertEqual(sorted(os.listdir(directory)), before,
                                 "%s left a file behind after a failed write" % name)


class StagedWorkFileTests(unittest.TestCase):
    """CMH-CONTENT-IO-02: content_replace's work file cannot survive an INTERRUPT either.

    The `.cmh-replace-` work file holds a full copy of the user's document. Cleanup used to run
    from an `except Exception`, so a Ctrl+C (a `BaseException`) between staging and the swap left
    that copy sitting in the document's own directory - the same leak the atomic writer's
    `finally` exists to prevent.
    """

    def test_a_keyboard_interrupt_mid_transaction_leaves_no_work_file(self):
        directory = tempfile.mkdtemp(prefix="cmh-atomic-work-")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = os.path.join(directory, "doc.html")
        _write(path, _root_doc(
            "<!-- BEGIN: commentable-html - CONTENT (agent edits ONLY between these markers) -->\n"
            "<p>content</p>\n"
            "<!-- END: commentable-html - CONTENT -->"))
        before = sorted(os.listdir(directory))

        def interrupted(*args, **kwargs):
            raise KeyboardInterrupt()

        with mock.patch.object(content_replace, "finalize_document", interrupted):
            with self.assertRaises(KeyboardInterrupt):
                content_replace.replace(path, "<p>new content</p>")
        self.assertEqual(sorted(os.listdir(directory)), before,
                         "an interrupted transaction must not leave a copy of the document behind")


class NoTruncatingWriteTests(unittest.TestCase):
    """A static guard, so a NEW tool cannot reintroduce the truncating write.

    A behavioral case only covers the tools someone remembered to list. This walks every shipped
    tool module and fails on any call that can empty a named file, unless it is explicitly marked
    as a write with nothing to lose (the staged temp file the atomic writer itself owns).

    It FAILS CLOSED, because a guard that quietly under-reports is worse than no guard: an
    `open()` whose mode is not a literal (`open(p, mode)`, `open(p, "w" if force else "x")` - the
    exact spelling that hid a truncating write from an earlier version of this test) is treated as
    unsafe, and the pathlib and shutil write APIs are flagged too, since a future modernization
    would reach for those first.
    """

    MARKER = "atomic-write:"
    # Whole-file writers with no mode argument at all: they always truncate an existing target.
    # `copy`/`copy2`/`copyfile`/`move` are shutil's, and are matched only when they really come
    # from shutil - `dict.copy()` is not a file write, and a guard that cries wolf gets silenced.
    _SHUTIL_WRITERS = ("copyfile", "copy", "copy2", "move")
    _PATH_WRITERS = ("write_text", "write_bytes")
    # os.open flags that create or truncate. os.O_RDONLY (the directory fsync) is not one.
    _WRITE_FLAGS = ("O_TRUNC", "O_CREAT", "O_WRONLY", "O_RDWR")

    def _tool_sources(self):
        for root, dirs, names in os.walk(_paths.TOOLS):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in sorted(names):
                if name.endswith(".py"):
                    yield os.path.join(root, name)

    @classmethod
    def _is_marked(cls, lines, lineno):
        """True when the call carries the opt-out marker on its own line or in the comment
        block directly above it (a reason worth writing is often longer than one line)."""
        if cls.MARKER in lines[lineno - 1]:
            return True
        index = lineno - 2
        while index >= 0 and lines[index].strip().startswith("#"):
            if cls.MARKER in lines[index]:
                return True
            index -= 1
        return False

    @staticmethod
    def _argument(call, index, keyword):
        """The argument at `index` or under `keyword`. Returns (present, node)."""
        for kw in call.keywords:
            if kw.arg == keyword:
                return True, kw.value
        if len(call.args) > index:
            return True, call.args[index]
        return False, None

    @classmethod
    def _mode_verdict(cls, call, index):
        present, node = cls._argument(call, index, "mode")
        if not present:
            return ""  # no mode argument at all is a read
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            return "the mode is not a literal, so it cannot be shown to be non-truncating"
        return "mode %r truncates" % node.value if "w" in node.value else ""

    @classmethod
    def _os_open_verdict(cls, call):
        present, node = cls._argument(call, 1, "flags")
        if not present:
            return "os.open() with no visible flags"
        # Fail CLOSED, exactly as the mode check does: only an expression built purely out of
        # `os.O_*` names can be shown to be read-only. A variable or a bare number cannot.
        names = set()
        literal = True
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute):
                names.add(child.attr)
            elif isinstance(child, ast.Name):
                if child.id != "os":
                    literal = False
            elif not isinstance(child, (ast.BinOp, ast.BitOr, ast.Load, ast.expr_context)):
                literal = False
        if not literal:
            return "the os.open flags are not literal, so they cannot be shown to be read-only"
        if any(flag in names for flag in cls._WRITE_FLAGS):
            return "os.open() with create/truncate flags"
        return ""

    @classmethod
    def _truncates(cls, call, imports=None):
        """Whether this call can empty a file it did not create, and why.

        `imports` is the module's import map (see `_import_map`), so a writer reached under a
        bare or renamed name is judged by where it actually came from - `from shutil import copy`
        is a file write, `from copy import copy` is not."""
        modules, symbols = imports or ({}, {})
        func = call.func
        if isinstance(func, ast.Attribute):
            owner = func.value.id if isinstance(func.value, ast.Name) else ""
            origin = modules.get(owner, owner)
            if func.attr in cls._PATH_WRITERS:
                return "%s() always truncates an existing target" % func.attr
            if func.attr in cls._SHUTIL_WRITERS and origin == "shutil":
                return "shutil.%s() always truncates an existing target" % func.attr
            if func.attr == "open":
                if origin == "os":
                    # os.open takes integer FLAGS, not a mode string.
                    return cls._os_open_verdict(call)
                # io.open mirrors the builtin; anything else is a path object's .open().
                return cls._mode_verdict(call, 1 if origin == "io" else 0)
            return ""
        if isinstance(func, ast.Name):
            if func.id == "open":
                return cls._mode_verdict(call, 1)
            # `from shutil import copyfile` binds the writer to a bare (possibly renamed) name,
            # which an attribute-only check would never see.
            module, symbol = symbols.get(func.id, ("", ""))
            if symbol in cls._SHUTIL_WRITERS and module == "shutil":
                return "shutil.%s() (imported directly) always truncates an existing target" % symbol
            if symbol in cls._PATH_WRITERS:
                return "%s() (imported directly) always truncates an existing target" % symbol
        return ""

    @staticmethod
    def _import_map(tree):
        """(module aliases, symbol aliases) for a module.

        `import shutil as fs` -> modules["fs"] = "shutil"; `from shutil import copy as cp` ->
        symbols["cp"] = ("shutil", "copy"). Keeping the MODULE is what stops `from copy import
        copy` being read as a file write."""
        modules, symbols = {}, {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules[alias.asname or alias.name] = alias.name
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    symbols[alias.asname or alias.name] = (node.module or "", alias.name)
        return modules, symbols

    def test_no_shipped_tool_truncates_a_file_it_did_not_stage(self):
        offenders = []
        for path in self._tool_sources():
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            lines = source.splitlines()
            tree = ast.parse(source, filename=path)
            imports = self._import_map(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                reason = self._truncates(node, imports)
                if not reason or self._is_marked(lines, node.lineno):
                    continue
                offenders.append("%s:%d (%s)"
                                 % (os.path.relpath(path, _paths.TOOLS), node.lineno, reason))
        self.assertEqual(offenders, [], (
            "truncating write(s) found; route the document through _atomic_io.atomic_write, or - "
            "if the target is a file the tool itself staged and so has no bytes to lose - say so "
            "with an `# atomic-write: <reason>` comment on or just above the line: %s" % offenders))

    def test_the_guard_detects_every_truncating_spelling_it_claims_to(self):
        # The guard is the only thing standing between a future tool and this whole class of data
        # loss, so its detection surface is itself pinned. Each spelling below is one a real tool
        # in this repo used (or a plausible modernization of one) and MUST be seen; each safe
        # spelling MUST NOT be, or the guard becomes noise that gets suppressed.
        unsafe = (
            ('open(p, "w")', ""),
            ('io.open(p, "w")', "import io"),
            ('open(p, mode="w")', ""),
            ('open(p, "w" if force else "x")', ""),   # new_document's pre-fix spelling
            ("open(p, mode)", ""),                    # a mode held in a variable
            ('Path(p).open("w")', ""),                # mode is argument 0, not 1
            ('Path(p).write_text(text, encoding="utf-8")', ""),
            ("Path(p).write_bytes(data)", ""),
            ("shutil.copyfile(src, dst)", "import shutil"),
            ("shutil.copy(src, dst)", "import shutil"),
            ("shutil.copy2(src, dst)", "import shutil"),
            ("shutil.move(src, dst)", "import shutil"),
            ("fs.copyfile(src, dst)", "import shutil as fs"),      # a renamed MODULE import
            ("copyfile(src, dst)", "from shutil import copyfile"),
            ("cp(src, dst)", "from shutil import copy2 as cp"),
            ("os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)", "import os"),
            ("os.open(p, flags=os.O_WRONLY | os.O_CREAT)", "import os"),
            ("os.open(p, flags)", "import os"),       # flags in a variable: cannot be shown safe
            ("os.open(p, 577)", "import os"),         # a bare number: likewise
        )
        safe = (
            ("open(p)", ""),
            ('open(p, "r")', ""),
            ('open(p, "rb")', ""),
            ('open(p, "x")', ""),                     # exclusive create: nothing to lose
            ('open(p, "a")', ""),                     # append never truncates
            ('os.fdopen(fd, "w")', "import os"),      # a descriptor the caller already staged
            ("os.open(directory, os.O_RDONLY)", "import os"),
            ("state.copy()", ""),                     # a dict, not a file
            ("[1].copy()", ""),
            ("copy(spec)", "from copy import copy"),  # copy.copy is not a file write
        )
        for src, header in unsafe:
            with self.subTest(spelling=src):
                tree = ast.parse("%s\n%s" % (header, src) if header else src)
                call = tree.body[-1].value
                self.assertTrue(self._truncates(call, self._import_map(tree)),
                                "guard missed: %s" % src)
        for src, header in safe:
            with self.subTest(spelling=src):
                tree = ast.parse("%s\n%s" % (header, src) if header else src)
                call = tree.body[-1].value
                self.assertFalse(self._truncates(call, self._import_map(tree)),
                                 "guard false-positived: %s" % src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
