#!/usr/bin/env python3
"""Equivalence and I/O-amplification tests for the finalize pipeline (CMH-BUILD-20).

finalize used to re-read, re-write and re-parse the WHOLE document once per phase - about
8 reads, 8 writes and 8 independent full-document parses of a 1.4 - 2.5 MB file, before
validation re-read it and the stamp re-read and re-parsed it again. `content_replace.py`
calls finalize on every write-back, so the agent edit loop paid that on each iteration.

The refactor is only safe behind an equivalence harness: the pipeline must produce
BYTE-IDENTICAL output to the phase-by-phase version. These tests pin that, and count the
actual file operations so the win is proven structurally rather than by a wall clock (a
timing assertion would be flaky, and the repo testing guidelines forbid it).
"""
import io
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402
sys.path.insert(0, _paths.TOOLS)
import finalize  # noqa: E402
import new_document  # noqa: E402

# Exercise EVERY always-on phase, so the equivalence claim is not proven on a fixture where
# most phases are no-ops. Flat (unwrapped) headings drive wrap_sections; the smart-typography
# glyphs (written as escapes to keep this source plain ASCII) drive normalize_typography; the
# author nav.cm-toc built from an <ol> with numbered labels drives strip_toc_numbers; the code
# blocks drive the highlighter, and mermaid gives it a block it must leave alone.
FRAGMENT = """<h1>Finalize Perf</h1>
<nav class="cm-toc">
<ol>
<li><a href="#one">1. One</a></li>
<li><a href="#two">2. Two</a></li>
<li><a href="#three">3. Three</a></li>
</ol>
</nav>
<h2 id="one">1. One</h2>
<p>Prose with an &amp; entity, a \u201Cquoted\u201D phrase and an \u2014 aside\u2026</p>
<pre><code class="language-python">def run(x):
    return x + 1
</code></pre>
<h2 id="two">2. Two</h2>
<p>More prose with \u2018single quotes\u2019.</p>
<pre><code class="language-sql">SELECT "col" FROM t WHERE a = 'x';</code></pre>
<pre class="mermaid cm-skip">graph TD; A--&gt;B;</pre>
<h2 id="three">3. Three</h2>
<p>A third section so wrapping has more than one boundary to find.</p>
<pre data-cmh-kql-no-cluster><code class="language-kql">T | where a == 1 | summarize count() by b</code></pre>"""


def _read(path):
    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


# The always-on phases, in the order finalize applies them, as plain text -> text callables.
# Named so a failure says WHICH phase stopped being exercised.
_ALWAYS_ON_NAMES = ("normalize", "wrap_sections", "highlight", "toc_dedup", "stats",
                    "vendored_libs")
_ALWAYS_ON_PHASES = (
    lambda html: finalize._apply_normalize(html)[0],
    lambda html: finalize._apply_wrap_sections(html)[0],
    lambda html: finalize._apply_highlight(html)[0],
    lambda html: finalize._apply_toc_dedup(html)[0],
    lambda html: finalize._apply_stats(html)[0],
    lambda html: finalize._apply_vendored_libs(html)[0],
)


class _Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cmh-finalize-perf-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.doc = os.path.join(self.tmp, "doc.html")
        _write(self.doc, new_document.make_document(
            _read(_paths.TEMPLATE), FRAGMENT, key="finalize-perf-test",
            label="Finalize Perf", source="doc.html", kind="report"))


class PipelineEquivalenceTests(_Case):
    """CMH-BUILD-20: the in-memory pipeline is byte-identical to the phase-by-phase one."""

    def test_finalize_output_matches_the_phase_by_phase_pipeline(self):
        # The reference applies one phase per read/modify/write cycle - the shape finalize had
        # before this refactor - so it is written independently of how finalize now threads the
        # document. Note what this does and does not prove: because both sides open with
        # utf-8 + newline="", the disk round trip is lossless, so this is really "naive
        # sequential phase application" rather than a test of disk normalization. What it
        # catches is a mis-threaded intermediate (a phase handed the ORIGINAL source instead of
        # the running text), a changed always-on default, and an added or dropped phase.
        #
        # It pins the I/O SHAPE, not the phase ORDER: every always-on phase commutes with its
        # neighbours on any fixture tried, so a shuffled pipeline would still produce identical
        # bytes here. test_the_phases_run_in_the_documented_order pins the order.
        reference = os.path.join(self.tmp, "reference.html")
        shutil.copyfile(self.doc, reference)
        for phase in _ALWAYS_ON_PHASES:
            _write(reference, phase(_read(reference)))

        finalize.finalize(self.doc)
        self._assert_same_bytes(_read(self.doc), _read(reference))

    def _assert_same_bytes(self, got, want):
        """Compare two whole documents without dumping ~2 MB into the failure output."""
        if got == want:
            return
        at = next((i for i in range(min(len(got), len(want))) if got[i] != want[i]),
                  min(len(got), len(want)))
        lo, hi = max(0, at - 90), at + 90
        self.fail(
            "the pipeline must be byte-identical to the phase-by-phase file cycle; "
            "first difference at offset %d (lengths %d vs %d)\n  pipeline : %r\n  reference: %r"
            % (at, len(got), len(want), got[lo:hi], want[lo:hi]))

    def test_the_fixture_actually_exercises_every_phase(self):
        # Guards the test above: if the fixture stopped triggering a phase, equivalence would
        # be proven on a no-op and the harness would silently lose its teeth. Apply the phases
        # CUMULATIVELY, so each is checked in the state the pipeline actually hands it - a
        # phase can be non-trivial on the raw document yet a no-op once an earlier phase has
        # rewritten its trigger.
        html = _read(self.doc)
        for name, phase in zip(_ALWAYS_ON_NAMES, _ALWAYS_ON_PHASES):
            after = phase(html)
            # Compare booleans, not the documents: a failing assertEqual on two ~2 MB strings
            # dumps the whole document into the test output and buries the actual failure.
            self.assertTrue(after != html,
                            "the fixture must exercise the %s phase in pipeline order, "
                            "not no-op through it" % name)
            html = after

    def test_the_phases_run_in_the_documented_order(self):
        """The byte-equivalence test above CANNOT pin ordering, so pin it directly.

        Every always-on phase commutes with its neighbours on any fixture tried, so a
        pipeline that shuffled them would still produce identical bytes and slip past the
        equivalence test. Record the actual call order instead, which no amount of
        commutation can disguise.
        """
        seen = []
        patches = []

        def make_spy(phase_name, original):
            # A factory, not a loop-local closure: a function defined in the loop body would
            # resolve the name `spy` at CALL time, by which point it refers to the LAST spy,
            # so every phase would report the last phase's name.
            def spy(*args, **kwargs):
                seen.append(phase_name)
                return original(*args, **kwargs)
            return spy

        for name in _ALWAYS_ON_NAMES:
            attr = "_apply_" + name
            original = getattr(finalize, attr)
            patches.append((attr, original))
            setattr(finalize, attr, make_spy(name, original))
        try:
            finalize.finalize(self.doc)
        finally:
            for attr, original in patches:
                setattr(finalize, attr, original)
        self.assertEqual(seen, list(_ALWAYS_ON_NAMES),
                         "finalize must apply the always-on phases in the documented order")

    def test_a_second_finalize_is_a_no_op(self):
        finalize.finalize(self.doc)
        once = _read(self.doc)
        finalize.finalize(self.doc)
        self.assertTrue(_read(self.doc) == once, "finalize must be idempotent")

    def test_the_toc_phase_still_runs_when_requested(self):
        finalize.finalize(self.doc, run_toc=True)
        self.assertIn("cm-toc", _read(self.doc))

    def test_the_optional_phases_are_threaded_equivalently_too(self):
        """The opt-in phases moved off the file cycle as well, so pin them byte-for-byte.

        Only the always-on phases are covered above, so a threading regression isolated to
        `--toc`, `--fix-skip` or `--inline-images` would otherwise slip through.
        """
        images = os.path.join(self.tmp, "images")
        os.mkdir(images)
        reference = os.path.join(self.tmp, "reference-optional.html")
        shutil.copyfile(self.doc, reference)
        # finalize's order: normalize, toc, wrap_sections, fix_skip, inline_images,
        # highlight, toc_dedup, stats, vendored_libs.
        cycle = (
            lambda h: finalize._apply_normalize(h)[0],
            lambda h: finalize._apply_toc(h)[0],
            lambda h: finalize._apply_wrap_sections(h)[0],
            lambda h: finalize._apply_fix_skip(h)[0],
            lambda h: finalize._apply_inline_images(h, images)[0],
            lambda h: finalize._apply_highlight(h)[0],
            lambda h: finalize._apply_toc_dedup(h)[0],
            lambda h: finalize._apply_stats(h)[0],
            lambda h: finalize._apply_vendored_libs(h)[0],
        )
        for phase in cycle:
            _write(reference, phase(_read(reference)))

        finalize.finalize(self.doc, run_toc=True, run_fix_skip=True, run_inline=True,
                          images_base=images)
        self._assert_same_bytes(_read(self.doc), _read(reference))

    def test_the_result_validates(self):
        result = finalize.finalize(self.doc)
        self.assertEqual(result["errors"], [])


class IoAmplificationTests(_Case):
    """CMH-BUILD-20: one read and one write for the whole pipeline, not one pair per phase."""

    def _counted(self, run_toc=False, stamp_when_clean=False):
        reads, writes = [], []
        real_open = io.open

        def counting_open(file, mode="r", *a, **kw):
            try:
                target = os.path.abspath(str(file))
            except Exception:
                target = ""
            if target == os.path.abspath(self.doc):
                (writes if any(m in mode for m in ("w", "a", "+")) else reads).append(target)
            return real_open(file, mode, *a, **kw)

        import builtins
        real_builtin_open = builtins.open

        def counting_builtin_open(file, mode="r", *a, **kw):
            try:
                target = os.path.abspath(str(file))
            except Exception:
                target = ""
            if target == os.path.abspath(self.doc):
                (writes if any(m in mode for m in ("w", "a", "+")) else reads).append(target)
            return real_builtin_open(file, mode, *a, **kw)

        io.open = counting_open
        builtins.open = counting_builtin_open
        try:
            finalize.finalize(self.doc, run_toc=run_toc,
                              stamp_when_clean=stamp_when_clean)
        finally:
            io.open = real_open
            builtins.open = real_builtin_open
        return len(reads), len(writes)

    def test_the_pipeline_writes_the_document_once(self):
        _reads, writes = self._counted()
        # EXACTLY one write for the finalized document. The old pipeline wrote once per
        # changed phase. An upper bound would also pass if a phase silently stopped running,
        # so pin the exact count.
        self.assertEqual(writes, 1,
                         "finalize must write the document exactly once (got %d)" % writes)

    def test_the_pipeline_reads_the_document_once(self):
        reads, _writes = self._counted()
        # EXACTLY one. Validation and the validated stamp now work on the in-memory document,
        # so neither adds a read; the old shape was one read per phase plus those.
        self.assertEqual(reads, 1,
                         "finalize must read the document exactly once (got %d)" % reads)

    def test_a_strict_clean_run_still_writes_only_once(self):
        # The validated stamp used to be a separate read+write AFTER the pipeline wrote, so a
        # clean CLI run cost three reads and two writes. Stamping in memory keeps it at 1/1.
        reads, writes = self._counted(stamp_when_clean=True)
        self.assertEqual(writes, 1, "a stamped run must still write once (got %d)" % writes)
        self.assertEqual(reads, 1, "a stamped run must still read once (got %d)" % reads)

    def test_the_document_is_actually_stamped_when_clean(self):
        # Guards the test above: identical counts would also hold if stamping silently stopped.
        result = finalize.finalize(self.doc, stamp_when_clean=True)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["stamped"], "a clean run must stamp the document")
        self.assertIn("commentable-html-validated", _read(self.doc))

    def test_an_unchanged_document_is_not_rewritten(self):
        finalize.finalize(self.doc)
        before = os.stat(self.doc)
        _reads, writes = self._counted()
        self.assertEqual(writes, 0,
                         "a finalize that changes nothing must not rewrite the file (got %d)" % writes)
        self.assertEqual(os.stat(self.doc).st_size, before.st_size)

    def test_the_toc_run_does_not_add_a_read_write_pair(self):
        reads, writes = self._counted(run_toc=True)
        self.assertEqual(writes, 1)
        self.assertEqual(reads, 1)


if __name__ == "__main__":
    unittest.main()
