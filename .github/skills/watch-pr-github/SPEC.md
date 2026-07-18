# watch-pr-github decision-logic spec

The `watch-pr-github` skill drives a GitHub.com pull request to merge. A deterministic watcher polls
the PR with `gh` and only wakes the agent on an actionable event. The watcher's safety-critical
decision logic -- sticky opt-out precedence, effective-permission merge gating, auto-merge
cancellation, changes-requested handling, and the per-oid seen-key state transitions -- was previously
only an illustrative PowerShell loop embedded in `SKILL.md` (agent guidance, not committed executable
code), so it had no owning spec row or automated test.

That decision logic is now extracted into a committed, dot-sourceable pure module,
`watcher-decision.ps1` (`Get-WatcherDecision`, `Resolve-OptOut`, `ConvertFrom-WatcherState`,
`Get-FailedCheckIds`). It performs no I/O and makes no `gh`/network calls: the PR-state snapshot, the
seen-set, effective permission, and trust classification are all passed in, so a mocked snapshot fully
determines the emitted `EVENT`. The runnable watcher `watch-pr-github.ps1` is only the I/O shell (gh
queries, pagination, permission lookups, atomic state persistence) and delegates every decision to that
module, so the two never drift.

This spec maps each promised decision behavior to the automated test that covers it. Every behavior
change must update a row here and its named test in the same change (see the repo `AGENTS.md`
"Spec-and-test discipline").

Covering test suite: `.github/skills/watch-pr-github/tests/decision.Tests.ps1` (a pwsh script; runs on
`windows-latest` and `ubuntu-latest` via the `pwsh-tests` job in
`.github/workflows/pwsh-tests.yml`). It dot-sources `watcher-decision.ps1` and asserts the emitted
`EVENT` and persisted seen-set against mocked PR-state snapshots, with trust and viewer permission
injected as scriptblocks so the merge gating is fully deterministic.

| Feature id | Behavior | Covering test |
| --- | --- | --- |
| WPG-DECISION-01 | A merged or closed PR ends the loop: `PR_MERGED` / `PR_CLOSED` take precedence over every other signal (conflict, failing checks, draft). | `decision.Tests.ps1` -> "WPG-DECISION-01 merged/closed take precedence over everything" |
| WPG-DECISION-02 | A conflicting (`CONFLICTING`) or dirty (`DIRTY`) merge state raises `MERGE_CONFLICT` once per head commit (seen-guarded). | `decision.Tests.ps1` -> "WPG-DECISION-02 MERGE_CONFLICT fires once per oid, on CONFLICTING or DIRTY" |
| WPG-DECISION-03 | An active auto-merge that must not proceed (the user opted out, or a reviewer requested changes) raises `DISABLE_AUTO_MERGE` with the reason, and is deliberately NOT seen-guarded so it re-emits every poll until the API reports auto-merge is off. | `decision.Tests.ps1` -> "WPG-DECISION-03 DISABLE_AUTO_MERGE cancels an interrupted / objectionable auto-merge (NOT seen-guarded)" |
| WPG-DECISION-04 | A failing check rollup raises `CHECKS_FAILED` keyed by the identities of the currently-failing runs, so an identical repeated failure is suppressed but a rerun with new run ids re-fires. | `decision.Tests.ps1` -> "WPG-DECISION-04 CHECKS_FAILED keyed by failing run ids; a rerun re-fires" |
| WPG-DECISION-05 | Unseen review threads, issue comments, and review bodies raise `NEW_COMMENTS`, split into trusted vs untrusted; issue/review comments from a non-Copilot `[bot]` are filtered out, but a `[bot]` on a review thread is not; a custom `-CopilotLogins` allowlist is honored and a duplicate feedback key is de-duplicated. | `decision.Tests.ps1` -> "WPG-DECISION-05 NEW_COMMENTS classifies trusted vs untrusted and filters non-Copilot bots" |
| WPG-DECISION-06 | `USER_APPROVED` (proactive auto-merge on the viewer's own approval) fires only for a merge-capable actor and only when not opted out, not a draft, and no changes-requested review is outstanding; a draft records no `approved:` key, and once the per-commit key is seen it falls through to the readiness gate. | `decision.Tests.ps1` -> "WPG-DECISION-06 USER_APPROVED only for a merge-capable actor, honoring the merge guards" |
| WPG-DECISION-07 | A draft PR raises `DRAFT_HELD` once per head commit and never merges. | `decision.Tests.ps1` -> "WPG-DECISION-07 DRAFT_HELD once per oid, and a draft never merges" |
| WPG-DECISION-08 | A branch behind its base raises `BRANCH_BEHIND` once per head commit. | `decision.Tests.ps1` -> "WPG-DECISION-08 BRANCH_BEHIND when the base advanced" |
| WPG-DECISION-09 | A changes-requested review on an otherwise-ready PR raises `CHANGES_REQUESTED` (never a silent merge over the objection). | `decision.Tests.ps1` -> "WPG-DECISION-09 CHANGES_REQUESTED surfaces (never silently merges over an objection)" |
| WPG-DECISION-10 | When the user opted out (`-NoMerge`), a ready PR raises `READY_HELD` (on both `CLEAN` and `UNSTABLE`) instead of a merge event. | `decision.Tests.ps1` -> "WPG-DECISION-10 READY_HELD when the user opted out of the merge" |
| WPG-DECISION-11 | A merge-capable actor on a ready PR raises `READY_TO_MERGE`; both `CLEAN` and `UNSTABLE` (only a non-required check not green) count as ready, and it fires once per head commit. | `decision.Tests.ps1` -> "WPG-DECISION-11 READY_TO_MERGE for a maintainer; UNSTABLE is ready too" |
| WPG-DECISION-12 | A confirmed non-maintainer never merges: a ready PR raises `AWAITING_MAINTAINER_MERGE` once per head commit, never `READY_TO_MERGE`. | `decision.Tests.ps1` -> "WPG-DECISION-12 a non-maintainer NEVER merges: AWAITING_MAINTAINER_MERGE, once" |
| WPG-DECISION-13 | A transiently failed permission lookup (`unknown`) emits no event and records no ready/await key, so the actor is re-probed next poll rather than permanently demoted; a later successful write+ lookup is promoted to `READY_TO_MERGE`. The same re-probe guard protects the `USER_APPROVED` path (an `unknown` lookup never fires approval-merge and records no key). | `decision.Tests.ps1` -> "WPG-DECISION-13 transient-permission failure re-probes rather than demoting" |
| WPG-DECISION-14 | An active auto-merge (with no opt-out or objection) suppresses the readiness events, so the watcher does not fight a merge that is already queued. | `decision.Tests.ps1` -> "WPG-DECISION-14 an active auto-merge suppresses readiness events" |
| WPG-DECISION-15 | `Resolve-OptOut` gives `-NoMerge` precedence over `-AllowMerge`, makes the opt-out sticky when neither switch is passed, clears it on `-AllowMerge`, and reports whether the sticky value changed. | `decision.Tests.ps1` -> "WPG-DECISION-15 Resolve-OptOut: -NoMerge wins, sticky persists, -AllowMerge clears" |
| WPG-DECISION-16 | `ConvertFrom-WatcherState` fails CLOSED on any invalid state CONTENT -- a corrupt/unparseable string, an empty/whitespace one (an existing but truncated file), OR a partial/tampered object with a null or missing `noMerge` (a null/missing `seen` becomes an empty set) -- assuming the opt-out so a corrupt, blank, or partial file can never silently re-enable merging; it round-trips a valid state. (The genuine no-file first-run case is handled by the caller, not here.) | `decision.Tests.ps1` -> "WPG-DECISION-16 ConvertFrom-WatcherState fails CLOSED on a corrupt state file" |
| WPG-DECISION-17 | `Get-FailedCheckIds` reduces a status-check rollup to the sorted identities of only the failing runs (CheckRun failure conclusions and StatusContext FAILURE/ERROR), excluding passing and pending contexts, and is null-safe: null/empty contexts (a PR with no checks) yield an empty list and a null context entry is skipped rather than throwing under StrictMode. A CheckRun is keyed by its `databaseId` (changes on a rerun) and a StatusContext by its context name AND `createdAt` (changes on a repost). | `decision.Tests.ps1` -> "WPG-DECISION-17 Get-FailedCheckIds maps and sorts CheckRun / StatusContext failures" |
| WPG-DECISION-18 | `Test-CommenterTrusted` (the pure trust classifier the runnable watcher delegates to) trusts only an exact allowlisted Copilot login or an OWNER/effective-write+ human, and fails CLOSED on a generic `[bot]` even with a MEMBER/COLLABORATOR association or write permission, and on `read`/`unknown` permission; a custom `-CopilotLogins` allowlist is honored. | `decision.Tests.ps1` -> "WPG-DECISION-18 Test-CommenterTrusted fails closed on bots and unprivileged accounts" |
| WPG-DECISION-19 | When the poll's feedback could not be fetched (`-FeedbackAvailable $false`, a transient API failure), the decision fails CLOSED: the pre-feedback events (terminal, conflict, auto-merge cancellation, failing checks) still fire, but `NEW_COMMENTS` and everything after it (`USER_APPROVED`, `DRAFT_HELD`, and merge readiness) is suppressed, so the watcher never advances or merges a PR while an unseen review comment might exist. | `decision.Tests.ps1` -> "WPG-DECISION-19 feedback-unavailable holds NEW_COMMENTS onward (fail closed), pre-feedback events still fire" |
| WPG-DECISION-20 | `Test-ViewerApproved` decides whether the viewer's own review currently approves the PR from their LATEST meaningful review, where "latest" is fixed by an explicit sort on `Order` (the review's monotonic `databaseId`), NOT by the gh reviews-connection order (which takes no `orderBy`). APPROVED / CHANGES_REQUESTED / DISMISSED are meaningful (a later COMMENTED does not revoke a standing approval), a null-login (deleted-author) review is never attributed to the viewer, and it fails CLOSED if any ordering key is null (so bad data cannot let a stale APPROVED win). A stale earlier APPROVED does not count after the viewer later requested changes or dismissed. | `decision.Tests.ps1` -> "WPG-DECISION-20 Test-ViewerApproved reflects the viewer's LATEST review state" |
| WPG-DECISION-21 | `ConvertTo-ReviewStates` normalizes raw gh review nodes (`author{ login }`, `state`, `databaseId`) into the ordered `@{ Login; State; Order }` shape `Test-ViewerApproved` consumes, skipping a null connection node (which would otherwise throw under StrictMode and strand the poll) and mapping a null author to a null Login. | `decision.Tests.ps1` -> "WPG-DECISION-21 ConvertTo-ReviewStates normalizes gh review nodes and tolerates nulls" |
| WPG-DECISION-22 | A legacy StatusContext that fails, passes, then fails again on the same head commit re-fires `CHECKS_FAILED`: because a StatusContext keeps its context name across reposts but gets a new `createdAt`, keying by name-plus-`createdAt` makes the re-failure a new key (a CheckRun already re-fires via its changing `databaseId`). | `decision.Tests.ps1` -> "WPG-DECISION-22 a StatusContext re-failure (fail -> pass -> fail) re-fires CHECKS_FAILED" |
| WPG-DECISION-23 | A review thread is classified for trust LEAST-PRIVILEGED: it is trusted only if EVERY participant (all its comment authors) is trusted, so an external comment anywhere in an otherwise maintainer-led thread (or vice versa) marks the thread untrusted and is vetted, rather than being judged by only the latest comment's author. It fails CLOSED (untrusted) when the participant set cannot be confirmed complete -- a truncated comment window (`ParticipantsTruncated`, a thread with more comments than were fetched), an empty participant list, or a null-author (deleted) participant. An issue comment or review body (a single author, no participant list) is still classified by that author. | `decision.Tests.ps1` -> "WPG-DECISION-23 a review thread is trusted only if ALL participants are trusted (least-privileged)" |
| WPG-DECISION-24 | `ConvertTo-CanonicalTimestamp` normalizes a timestamp to a stable, culture-invariant UTC ISO string, so a key built from it is identical whether `ConvertFrom-Json` produced a `[datetime]` (pwsh 7) or a raw ISO string (Windows PowerShell 5.1), and regardless of the local timezone/culture; a null or blank value yields an empty string. | `decision.Tests.ps1` -> "WPG-DECISION-24 ConvertTo-CanonicalTimestamp normalizes datetimes and strings to a stable key" |

## Coverage gaps

The runnable I/O shell `watch-pr-github.ps1` (gh GraphQL queries, cursor pagination -- including the
`Get-RollupContexts` paging that fetches a commit's status-check contexts beyond the first 100 so a
failing context past position 100 still contributes to the `CHECKS_FAILED` key, and the
`comments(last:100)` fetch that collects a thread's participants and detects a truncated window --
the `gh api .../collaborators/<login>/permission` lookups, and the atomic temp+move state file writes)
is not unit-tested here because it only performs live `gh`/network I/O and filesystem persistence; all
of its DECISION behavior is delegated to `watcher-decision.ps1` and covered by the rows above --
including the security-critical trust rule (its `Test-Trusted` is a thin wrapper over the tested
`Test-CommenterTrusted`, injecting only the live permission lookup), the least-privileged thread
classification (with its fail-closed truncation/empty handling), the canonical StatusContext keying,
and the review-approval logic it feeds. The shell is kept thin on purpose so that what is untested is
only glue, not logic.
