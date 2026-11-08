# Local comment recovery performance

Issue #1366 compares the delivered 1.859.0 runtime at
`8bd2b3814f08d6c8d4d2dfddbe6437169c600053` with the 1.860.0 candidate.
The benchmark driver is `tests/benchmark-reattachment.mjs`. Measured samples,
source hashes, allocation diagnostics and environment metadata are retained in
`reattachment-results.json`.

## Method

Chromium 153.0.8010.12, Node 26.13.0, Windows x64, AMD EPYC 7763, 16 visible
logical CPUs. Baseline and candidate run serially in alternating order, without
concurrent test suites or review agents. This is a shared host, not an isolated
performance laboratory; these results are not universal latency guarantees.

The kernel comparison runs the original and candidate reattachment partials
with the same offset/context helpers. Those helper paths are not the kernels
being compared. Each runtime seeds its own selectors from identical original
content outside timing. Cold is the first invocation in a fresh document/isolate
after discarded-document seeding and a requested GC. Warm distributions contain
25 samples after three warmups. An independent 15-sample repeat checks stability.
DOM creation, IPC, selector seeding and instrumented profiling are not timed.
Upgrade fixtures remove the additive layout basis.

Whole-page measurements use the genuine original and freshly built candidate
Shareable templates, not a hybrid runtime. Five fresh contexts per version,
alternating order, measure navigation-to-runtime-ready, including parsing and
startup. Native comments have real captured context; the separate legacy case
omits it. Every persisted fixture root and attached highlight is counted, and
HTTP(S) requests are denied. No whole-page warmup is claimed.

All attachment offsets must be deterministic across samples. The insertion case
intentionally attaches more comments without increasing its shared scan budget.
Ambiguous duplicate deletion remains Detached. The driver records every raw
latency sample, cold outcome, inclusive phase profile and typed-array byte count.
Heap deltas after a requested GC are diagnostics, not peak memory, retained size,
or process RSS. Profile times are inclusive and must not be added together.

## Kernel results

Warm median milliseconds from the 25-sample run:

| Workload | Baseline | Candidate | Attachment outcome |
| --- | ---: | ---: | --- |
| Unchanged, 100 blocks / 20 comments | 1.8 | 0.3 | 20 / 20 in both |
| Unchanged, 1000 blocks / 200 comments | 48.5 | 2.9 | 200 / 200 in both |
| Unchanged, 3000 blocks / 500 comments | 186.6 | 9.8 | 500 / 500 in both |
| Upgrade without layout basis, 500 comments | 189.2 | 32.1 | 500 / 500 in both |
| Insertion, 3000 blocks / 30 comments | 182.4 | 32.1 | 11 -> 30 attached |
| Normalized revision, 30 comments | 52.4 | 22.7 | 27 / 30 in both |
| Small edits, 20 comments | 5.1 | 2.4 | 20 / 20 in both |
| New selector capture, 3000 blocks | 160.6 | 15.9 | Correct offsets in both |
| Index plus 1000 nested-block lookups | 33.3 | 23.9 | Same containing blocks |
| Eight near-cell-limit alignments | 28.5 | 15.0 | Same alignment |
| Unsafe duplicate deletion | 5.1 | 1.7 | Detached in both |
| Normalize 7.56 million source units | 1193.1 | 111.2 | Same text |
| Normalize 7.5 million densely spaced units | 1105.4 | 147.5 | Same text / boundaries |

The large unchanged resolver is about 19x faster; new capture is about 10x
faster. These are kernel improvements, not whole-page speedups. Cold and p95
values, which can differ materially from warmed kernels, are in the raw results.

Mapping allocations fall from 60,480,000 to zero bytes for length-preserving
normalization, and from 60,000,000 to 27,000,000 bytes for dense whitespace
collapses. Large capture/upgrade/insertion maps fall from about 8.49 MB to
24,000 bytes through sparse change points. These figures exclude transient
strings, DOM objects and edit matrices; they do not claim total memory fell by
the same amount.

## Whole-page results and bottleneck discovery

Five-sample medians, milliseconds:

| Native saved comments / source size | Baseline ready | Candidate ready |
| --- | ---: | ---: |
| 200 comments / about 296k source units | 1162.1 | 619.2 |
| 100 comments / about 1.06m source units | 1470.7 | 610.1 |
| 500 comments / about 1.06m source units | 7318.7 | 1253.6 |
| 30 comments after insertion / about 1.06m units | 762.6 | 559.8 |
| 200 legacy missing-context comments / about 296k units | 8471.8 | 630.1 |

The original full-page probe exposed about eight seconds of legacy context
backfill, overwhelming the resolver gains. Sharing one immutable context/layout
scan removed that repeated DOM/style walk. Scoping wrapping to selected
subtrees reduced highlight costs; updating split-node indexes in place removed
the remaining repeated whole-document highlight walks. Failed-wrap cleanup
still rebuilds its index, and historical context fields are never replaced.

Native medium startup improved about 47%, native large startup about 59% at
100 comments and 83% at 500 comments, and legacy startup about 93%.
The 500-comment highlight phase fell from 5935.0 to 63.2 ms while restoring
all 500 comments. Legacy context backfill fell from 7390.3 to 119.3 ms.
Parsing, unrelated startup and sidebar/layout work
remain in these totals, so a 19x resolver improvement does not imply a 19x page
improvement. The repeated linear offset lookups, occurrence scans, full edit
matrix allocation and browser rendering are deliberately still visible costs,
not hidden behind a persistent DOM cache or relaxed limits.

The independent repeat measured large unchanged recovery at 202.1 -> 10.8 ms
(18.7x) and near-limit normalization at 1532.9 -> 141.8 ms (10.8x).
Absolute times varied, particularly the long normalization run, while the
speedup ratios and attachment outcomes remained consistent. Raw repeated
samples are retained rather than selecting only the fastest run.

An early probe used invalid persisted IDs and loaded zero comments; its startup
numbers were rejected. A later large missing-context baseline exceeded the
60-second navigation budget. Neither failed probe is presented as a valid
startup measurement. The corrected driver checks roots and highlights before
accepting results.

## Reproduce

Run from a fresh worktree with existing development dependencies installed.
Extract the baseline from the exact delivered commit, not current main:

```powershell
New-Item -ItemType Directory -Force tmp\reattachment-bench | Out-Null
git show 8bd2b3814:plugins/commentable-html/dev/assets/js/16-reattachment.js |
  Set-Content -Encoding utf8 tmp\reattachment-bench\baseline.js
git show 8bd2b3814:plugins/commentable-html/dev/skill/dist/SHAREABLE.html |
  Set-Content -Encoding utf8 tmp\reattachment-bench\baseline-shareable.html
python scripts\setup_dev.py --check
python scripts\rebuild_all.py
Set-Location plugins\commentable-html\dev
node tests\benchmark-reattachment.mjs `
  --baseline ..\..\..\tmp\reattachment-bench\baseline.js `
  --baseline-template ..\..\..\tmp\reattachment-bench\baseline-shareable.html `
  --output ..\..\..\tmp\reattachment-bench\results.json --samples 25
node tests\benchmark-reattachment.mjs `
  --baseline ..\..\..\tmp\reattachment-bench\baseline.js `
  --output ..\..\..\tmp\reattachment-bench\repeat.json --samples 15
```

Use `--startup-only --filter unchanged-large-500` to isolate the 500-comment
whole-page case. Baseline seeding captures real historical context outside the
timed interval and can itself take considerably longer than optimized startup.
PowerShell text extraction can change newline/BOM bytes, so compare semantic
inputs and record the resulting hashes; the retained measurement used exact
LF baseline copies. Docker is needed only for pinned tutorial screenshot
regeneration, not these benchmarks.

## Safeguards

Eight red-first deterministic performance tests cover evidence recapture,
layout invalidation, block containment, identity/sparse/dense normalization,
banded alignment, intact-block proof, shared context and highlight indexing.
They assert work/allocation ceilings plus actual attachment/DOM correctness,
not flaky wall-clock limits. The full recovery, export, storage, skipped-text,
code and legacy-runtime regression suites remain required.

Source limits (8m units), snapshots (4096), candidate count (128), shared scan
budget (64m), fuzzy-block and alignment-cell limits are unchanged. No message,
thread, historical evidence or foreign metadata is discarded. The additive
layout basis does not require a new persisted format. Runtime/asset/Shareable
size ceilings rise by a deliberate 5000 bytes; every rebuilt payload remains
inside its enforced budget.
