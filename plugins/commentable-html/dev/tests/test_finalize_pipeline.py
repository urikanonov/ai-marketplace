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
<pre class="mermaid">graph TD; A--&gt;B;</pre>
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
_ALWAYS_ON_NAMES = ("normalize", "wrap_sections", "highlight", "toc_dedup", "stats")
_ALWAYS_ON_PHASES = (
    lambda html: finalize._apply_normalize(html)[0],
    lambda html: finalize._apply_wrap_sections(html)[0],
    lambda html: finalize._apply_highlight(html)[0],
    lambda html: finalize._apply_toc_dedup(html)[0],
    lambda html: finalize._apply_stats(html)[0],
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
        # The reference is a FILE-CYCLE pipeline - it reads the document, applies one phase,
        # and writes it back, once per phase, which is the shape finalize had before this
        # refactor. Driving the transforms in memory here instead would compare the new code
        # against itself; going through disk is what actually proves the removed round trips
        # (and any normalization they could have applied) changed nothing.
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
        # be proven on a no-op and the harness would silently lose its teeth.
        src = _read(self.doc)
        for name, phase in zip(_ALWAYS_ON_NAMES, _ALWAYS_ON_PHASES):
            # Compare booleans, not the documents: a failing assertEqual on two ~2 MB strings
            # dumps the whole document into the test output and buries the actual failure.
            self.assertTrue(phase(src) != src,
                            "the fixture must exercise the %s phase, not no-op through it" % name)

    def test_a_second_finalize_is_a_no_op(self):
        finalize.finalize(self.doc)
        once = _read(self.doc)
        finalize.finalize(self.doc)
        self.assertTrue(_read(self.doc) == once, "finalize must be idempotent")

    def test_the_toc_phase_still_runs_when_requested(self):
        finalize.finalize(self.doc, run_toc=True)
        self.assertIn("cm-toc", _read(self.doc))

    def test_the_result_validates(self):
        result = finalize.finalize(self.doc)
        self.assertEqual(result["errors"], [])


class IoAmplificationTests(_Case):
    """CMH-BUILD-20: one read and one write for the whole pipeline, not one pair per phase."""

    def _counted(self, run_toc=False):
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
            finalize.finalize(self.doc, run_toc=run_toc)
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

    def test_the_pipeline_reads_far_fewer_times_than_it_has_phases(self):
        reads, _writes = self._counted()
        # Exactly two: the pipeline's own read, plus validation's independent read. The old
        # shape was one read per phase on top of those.
        self.assertEqual(reads, 2,
                         "finalize must not re-read the document once per phase (got %d)" % reads)

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
        self.assertEqual(reads, 2)


if __name__ == "__main__":
    unittest.main()
