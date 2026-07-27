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

FRAGMENT = """<h1>Finalize Perf</h1>
<section>
<h2 id="one">One</h2>
<p>Prose with an &amp; entity and a "quoted" phrase.</p>
<pre><code class="language-python">def run(x):
    return x + 1
</code></pre>
</section>
<section>
<h2 id="two">Two</h2>
<p>More prose.</p>
<pre><code class="language-sql">SELECT "col" FROM t WHERE a = 'x';</code></pre>
</section>"""


def _read(path):
    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write(path, text):
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


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
        # Reference: drive each phase's PURE transform in the documented order by hand.
        import generate_toc
        import highlight_document
        import normalize_typography
        import wrap_sections
        import doc_stats

        src = _read(self.doc)
        expected, _ = normalize_typography.normalize_typography(src)
        expected, _ = wrap_sections.fix(expected)
        expected, _ = highlight_document.highlight_document(expected)
        expected, _ = generate_toc.strip_toc_numbers(expected)
        expected = doc_stats.rewrite_html(expected)

        finalize.finalize(self.doc)
        self.assertEqual(_read(self.doc), expected,
                         "the pipeline must be byte-identical to running the phases in order")

    def test_a_second_finalize_is_a_no_op(self):
        finalize.finalize(self.doc)
        once = _read(self.doc)
        finalize.finalize(self.doc)
        self.assertEqual(_read(self.doc), once, "finalize must be idempotent")

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
        # One write for the finalized document. The old pipeline wrote once per changed phase.
        self.assertLessEqual(writes, 1,
                             "finalize must write the document at most once (got %d)" % writes)

    def test_the_pipeline_reads_far_fewer_times_than_it_has_phases(self):
        reads, _writes = self._counted()
        # One read for the pipeline plus validation's own read; the old shape was one per phase.
        self.assertLessEqual(reads, 3,
                             "finalize must not re-read the document once per phase (got %d)" % reads)

    def test_the_toc_run_does_not_add_a_read_write_pair(self):
        reads, writes = self._counted(run_toc=True)
        self.assertLessEqual(writes, 1)
        self.assertLessEqual(reads, 3)


if __name__ == "__main__":
    unittest.main()
