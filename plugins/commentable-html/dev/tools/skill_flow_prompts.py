"""Prompt corpus for the local commentable-html skill-flow regression harness.

Each flow is a directed prompt that drives the installed ``copilot`` executable through one
commentable-html skill route, plus the seed files it needs and the validators the harness re-runs
on the produced artifact. This module is pure data + a tiny accessor so the harness and its
hermetic test share one source of truth; it never invokes copilot itself.

Prompt conventions (kept identical across flows so the harness can locate and re-check the result):
- The agent MUST write the final HTML to the flow's ``output`` path (relative to the scratch
  workspace), so the harness knows exactly which file to re-validate.
- The agent MUST finalize and strict-validate per the skill's "Always validate before handoff" rule.
- No browser is opened (the flows are headless / CLI-only).

Validators (re-run by the harness independently of whatever the agent did, so a skill regression that
produces an invalid artifact is caught even if the agent wrongly reports success):
- ``validate``      - tools/validate/validate.py --strict <artifact>
- ``deck_validate`` - tools/deck/deck_validate.py --strict <artifact>
- ``portable``      - harness-side check that the artifact is a single self-contained file
- ``stamp``         - harness-side check that the artifact carries the validated stamp
"""

REQUIRED_FLOWS = ("create", "retrofit", "deck", "export", "validate")

# A minimal, plain (non-commentable) HTML page used as the retrofit input.
_PLAIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Weekly Ops Review</title></head>
<body>
  <main>
    <h1>Weekly Ops Review</h1>
    <p>Deploys were healthy this week. p95 latency dropped from 1.8s to 640ms after the cache change.</p>
    <h2>Risks</h2>
    <ul><li>The nightly export job is still flaky.</li><li>On-call coverage has a Friday gap.</li></ul>
  </main>
</body>
</html>
"""

FLOWS = [
    {
        "name": "create",
        "output": "output/create.html",
        "seed_files": {},
        "validators": ["validate", "stamp"],
        "prompt": (
            "Use the commentable-html skill to CREATE a new commentable review document from this "
            "Markdown content:\n\n"
            "# Q3 Onboarding Plan\n\n"
            "We will ship a redesigned onboarding flow in Q3.\n\n"
            "## Goals\n\n"
            "- Cut time-to-first-value from 5 days to under 1 day.\n"
            "- Reduce support tickets in week one by 30 percent.\n\n"
            "## Open questions\n\n"
            "- Do we gate the new flow behind a feature flag?\n"
            "- Who owns the migration of existing accounts?\n\n"
            "Follow the skill: use tools/authoring/new_document.py to "
            "build the document, then MUST finalize it and pass tools/validate/validate.py --strict. "
            "Write the final HTML to output/create.html relative to the current working directory. "
            "Do not open a browser. When finished, print the absolute path of output/create.html."
        ),
    },
    {
        "name": "retrofit",
        "output": "output/retrofit.html",
        "seed_files": {"input/plain.html": _PLAIN_HTML},
        "validators": ["validate", "stamp"],
        "prompt": (
            "Use the commentable-html skill to RETROFIT the existing plain HTML file at "
            "input/plain.html (relative to the current working directory) into a commentable review "
            "document, adding the review layer without rewriting the content. Follow the skill's "
            "tested retrofit route, give the content root a unique non-demo data-comment-key, then "
            "MUST finalize and pass tools/validate/validate.py --strict. Write the retrofitted HTML "
            "to output/retrofit.html. Do not open a browser. When finished, print the absolute path "
            "of output/retrofit.html."
        ),
    },
    {
        "name": "deck",
        "output": "output/deck.html",
        "seed_files": {},
        "validators": ["deck_validate", "validate", "stamp"],
        "prompt": (
            "Use the commentable-html skill's DECK capability to scaffold a short commentable slide "
            "deck (3 to 4 slides) titled 'Rolling Out Onboarding v2' with a title slide, one goals "
            "slide, one risks slide, and a next-steps slide. Follow the skill: pick a native deck "
            "theme preset and use tools/deck/deck_scaffold.py, then MUST pass "
            "tools/deck/deck_validate.py --strict and tools/validate/validate.py --strict. Write the "
            "final deck HTML to output/deck.html relative to the current working directory. Do not "
            "open a browser. When finished, print the absolute path of output/deck.html."
        ),
    },
    {
        "name": "export",
        "output": "output/export.html",
        "seed_files": {},
        "validators": ["validate", "portable", "stamp"],
        "prompt": (
            "Use the commentable-html skill to create a PORTABLE, self-contained commentable "
            "document (a single HTML file with the review layer and assets embedded, safe to share "
            "with no companion files) from this Markdown content:\n\n"
            "# Release Notes 2.0\n\nThe portable export bundles everything into one file.\n\n"
            "## Highlights\n\n- Single-file handoff.\n- No network needed to review.\n\n"
            "Follow the skill: build it in portable mode, then MUST finalize and pass "
            "tools/validate/validate.py --strict. Write the final self-contained HTML to "
            "output/export.html relative to the current working directory. Do not open a browser. "
            "When finished, print the absolute path of output/export.html."
        ),
    },
    {
        "name": "validate",
        "output": "output/validate.html",
        "seed_files": {"input/draft.md": (
            "# Incident Retro: Cache Outage\n\n"
            "A stale cache key served 500s for 22 minutes.\n\n"
            "## Timeline\n\n- 09:04 alert fires.\n- 09:26 rollback complete.\n\n"
            "## Follow-ups\n\n- Add a cache-key version guard.\n- Alert on 500-rate, not just latency.\n"
        )},
        "validators": ["validate", "stamp"],
        "prompt": (
            "Use the commentable-html skill's VALIDATION HANDOFF discipline. Build a commentable "
            "document from the Markdown draft at input/draft.md (relative to the current working "
            "directory), then run the MANDATORY handoff: tools/authoring/finalize.py <file> --strict "
            "followed by tools/validate/validate.py --strict <file>, and only report success once the "
            "file carries the commentable-html-validated stamp. Write the finalized, validated HTML "
            "to output/validate.html. Do not open a browser. When finished, print the absolute path "
            "of output/validate.html and confirm it is strict-valid and stamped."
        ),
    },
]


def flows_by_name():
    return {f["name"]: f for f in FLOWS}


def flow_names():
    return [f["name"] for f in FLOWS]
