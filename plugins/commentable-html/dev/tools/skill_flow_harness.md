# Local skill-flow regression harness

`tools/skill_flow_harness.py` drives the installed **`copilot`** executable, non-interactively,
through the commentable-html skill's main routes - create, retrofit, deck, export (portable), and the
validation handoff - and then re-validates each produced document with this repo's own tools. It
answers one question that no hermetic unit test can: *does an agent, following the CURRENT shipped
`SKILL.md` and tools, still produce a strict-valid document for each flow?*

It is a **manual, local-only** tool. It is wired into no CI workflow, it HARD-refuses to run under CI,
it calls a live model (so it consumes AI credits and is non-deterministic), and every scratch file it
writes lives under the repo's gitignored `tmp/`.

## Prerequisites

- The GitHub Copilot CLI on `PATH` (`copilot --version`), logged in (`copilot` handles auth).
- Python 3 (the same interpreter the repo's tools use).
- Run it from anywhere inside the repo.

## Usage

```bash
# List the flows
python plugins/commentable-html/dev/tools/skill_flow_harness.py --list

# Print the exact copilot command per flow WITHOUT calling the model (no credits)
python plugins/commentable-html/dev/tools/skill_flow_harness.py --dry-run

# Run every flow (each calls the model once)
python plugins/commentable-html/dev/tools/skill_flow_harness.py

# Run a subset, pin a model, and keep the scratch workspaces for inspection
python plugins/commentable-html/dev/tools/skill_flow_harness.py --flows create,deck --model claude-sonnet-4.5 --keep
```

Exit code is `0` when every selected flow passed, `1` when any failed (scratch is kept on failure so
you can read `copilot.log` and the produced artifact), `2` when `copilot` is not found, and `3` when
it refuses because it detected a CI environment.

## What each flow does

For every flow the harness:

1. Makes an isolated workspace `tmp/skill-flow-harness/<run-id>/<flow>/`.
2. Copies the **shipped** skill (`pkg/skills/commentable-html`) into
   `<ws>/.github/skills/commentable-html/`, which is how `copilot -C <ws>` discovers it as a project
   skill (confirmed empirically), then extracts the shipped `skill-resources.zip` in place so the
   workspace holds the full `tools/` and `references/` tree exactly as an installed skill - so the
   harness exercises exactly what ships, not whatever skill is installed on the machine.
3. Writes any seed files the flow needs (a plain HTML page to retrofit, a Markdown draft to validate).
4. Invokes `copilot -C <ws> -p "<directed prompt>" --allow-all-tools --add-dir <ws>` - file access is
   SCOPED to the workspace (which lives under `tmp/`) instead of opened up with `--allow-all-paths`,
   so the agent's file tools cannot touch a tracked file.
5. **Re-validates the artifact itself** (independently of whatever the agent reported) at the pinned
   output path, READ-ONLY (it passes `--no-stamp`, so validation never mutates the artifact), with
   `validate.py --strict`, plus flow-specific checks (deck: `deck_validate.py`; export: a
   self-contained file that needs no companion asset yet still carries an embedded review layer). It
   also re-checks the AGENT-written `<meta name="commentable-html-validated">` stamp on EVERY flow -
   the harness never writes it, so a flow that skipped the mandatory finalize/validate handoff FAILs.

The flows and prompts are the single source of truth in `tools/skill_flow_prompts.py`.

## Limitations (read before trusting a red or green)

- **Non-deterministic.** It calls a live model; a transient model failure, a refusal, or a plausible
  alternate path (e.g. the agent writes to a different filename than the pinned one) shows up as a
  FAIL even when the skill is fine. Read `copilot.log` before concluding a regression.
- **PASS validates the OUTPUT of a COMPLETED run.** A flow passes when the pinned artifact exists
  inside the workspace and re-validates strict-clean (stamp included); `copilot`'s own exit code is
  recorded and surfaced but is not the pass criterion, so a run that completed with a non-zero exit
  but left a strict-valid artifact is PASS with an explicit `note: copilot exited rc=...` line. A
  TIMEOUT is different: a hung or looping agent is a hard FAIL even if a stale artifact exists.
- **Containment is best-effort, not a sandbox.** The harness's OWN scratch always stays under the
  gitignored `tmp/`, and the agent's file tools are scoped to the workspace. But the agent still has
  a shell, so this is not an OS-level sandbox - run it only with a trusted model (it is local-only by
  design).
- **Not a CI gate.** Deliberately. Model calls are non-hermetic and cost credits; CI coverage of the
  skill is the hermetic Python/Playwright suites plus `test_prompt_showcase.py`. This harness is a
  belt-and-suspenders manual check you run when you materially change `SKILL.md` or the tools.
- **User skills leak in.** `copilot` also loads the machine's `~/.copilot/skills/`, so the workspace
  is not perfectly isolated; the commentable-html skill is still the one relevant to each prompt.
- **The plumbing is tested; the live run is not.** `tests/test_skill_flow_harness.py` (CMH-HARNESS-01)
  covers the CI guard (in `main()` and `run_flow`), the scratch-under-tmp invariant, the corpus, the
  command construction, the read-only validators, the content checks, and the workspace bootstrap
  (shipped-tools extraction), but never invokes `copilot`. The end-to-end model run is an intentional
  manual coverage gap (see `dev/SPEC.md`).
