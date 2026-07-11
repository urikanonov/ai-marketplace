# Auto-updater feature spec

The `urikan-ai-marketplace-auto-updater` plugin runs a session-start hook that updates the other
plugins installed from this marketplace. This spec maps each promised behavior to the automated test
that covers it. Every behavior change must update a row here and its named test in the same change
(see the repo `AGENTS.md` "Spec-and-test discipline").

Covering test suite: `plugins/urikan-ai-marketplace-auto-updater/dev/tests/updater.Tests.ps1`
(a pwsh script; runs on `windows-latest` and `ubuntu-latest` via
`.github/workflows/auto-updater-tests.yml`). It exercises the real
`pkg/hooks/marketplace-update.ps1` against an isolated temp `COPILOT_HOME` sandbox with a stubbed
`copilot` command, so no real updates and no network calls occur.

| Feature id | Behavior | Covering test |
| --- | --- | --- |
| UPD-01 | The updater updates each installed marketplace plugin but never itself (self-exclusion by folder name). | `updater.Tests.ps1` -> "UPD-01 self-exclusion" |
| UPD-02 | When the `copilot` CLI is not on `PATH`, the pass is skipped, the skip is logged, and no throttle stamp is written (so the next session retries). | `updater.Tests.ps1` -> "UPD-02 missing CLI skip + log" |
| UPD-03 | A failing `copilot plugin update` for one plugin is isolated and logged; the remaining plugins are still attempted. | `updater.Tests.ps1` -> "UPD-03 per-plugin failure isolation" |
| UPD-04 | When `COPILOT_HOME` is unset, paths fall back to `$HOME/.copilot`. | `updater.Tests.ps1` -> "UPD-04 COPILOT_HOME fallback" |
| UPD-05 | Installed plugins are processed in a deterministic, name-sorted order, so the log order is stable across platforms. | `updater.Tests.ps1` -> "UPD-05 deterministic sorted log order" |
| UPD-06 | On Windows the hook is invoked with `powershell -NoProfile -ExecutionPolicy Bypass -File ...`, so the default `Restricted` policy cannot silently block it. | `updater.Tests.ps1` -> "UPD-06 ExecutionPolicy-bypass invocation" |
| UPD-07 | On macOS/Linux, when `pwsh` (PowerShell 7) is missing the bash field writes a dated skip note to the plugin-data log instead of silently no-opping, then succeeds. | `updater.Tests.ps1` -> "UPD-07 missing-pwsh log signal" |
| UPD-08 | A last-run throttle skips the whole update pass when the previous pass ran less than ~20 hours ago (logged), and a completed pass refreshes the stamp. | `updater.Tests.ps1` -> "UPD-08 last-run throttle" |

## Coverage gaps

- The UPD-07 functional check (actually executing the bash else-branch and asserting the log line) runs
  only on POSIX shells, which is where that field runs; on Windows the powershell field is used
  instead and git-bash mangles Windows paths, so on Windows UPD-07 falls back to structural assertions
  on the `hooks.json` bash field. This is intentional, not a missing test.
- A per-plugin update timeout is intentionally NOT implemented. A `Start-Job`/`Wait-Job` wrapper would
  add its own hang and PowerShell 5.1 compatibility risk, which conflicts with the non-blocking
  guarantee. The `hooks.json` `timeoutSec` (the CLI-enforced total budget) plus the UPD-08 last-run
  throttle bound the cost instead. Tracked here so the decision is explicit.
