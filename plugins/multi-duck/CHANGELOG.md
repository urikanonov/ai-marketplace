# Changelog

All notable changes to the multi-duck plugin are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to semantic
versioning.

## [1.3.0] - 2026-08-06

### Changed

- Raised the bar for turning a panel finding into a tracked issue (MDUCK-SCOPE-12). A duck's scope is
  the CHANGE under review, so a PRE-EXISTING defect noticed incidentally - one equally present on the
  base revision - now goes to `SCOPED-OUT:` rather than `FINDINGS:`, unless it is user-observable
  breakage, data loss, or a security issue reachable under the declared threat model. Incidental
  pre-existing findings were 47 percent of the issues filed in one two-day window and were what held
  the issue branching factor at 1.52 - above the 1.0 at which a backlog stops growing - so a panel
  was manufacturing work faster than it could be done. The boundary is drawn carefully: a defect the
  change newly makes REACHABLE, triggers, or relocates stays in scope even when the defective line
  itself is untouched, so a latent fault that only a newly added caller can reach is still reported.

## [1.2.0] - 2026-08-04

### Added

- The panel now respects a project's DECLARED threat model instead of rediscovering its non-goals on
  every run (MDUCK-SCOPE-12). Bundle assembly collects the repo's written threat model, trust
  boundaries, and accepted residual risks into `context.md`, together with the list that stays in
  scope regardless (a weakened enforcement layer, a false positive that breaks benign input, and
  drift that makes a tool emit output its own validator rejects). Every duck's hard rules forbid
  reporting a finding whose attacker the project declares trusted, whose effect a named enforcement
  layer already blocks unconditionally, or which is one more instance of an already-accepted
  residual; a duck that disagrees with a non-goal raises it under `QUESTIONS:` rather than as a
  finding. Consolidation records such a finding as `Dismissed-as-out-of-scope` and does not open a
  follow-up issue for it. This closes the loop where each reviewed fix spawned its own successors.

## [1.1.0] - 2026-07-25

### Changed

- Refreshed the example duck roster to lead with the current strongest Anthropic flagship. The panel
  now leads with `claude-opus-5` as roster row 1 and duck 1 of the prisms example. The rows that
  changed are row 1 (`claude-opus-4.8` -> `claude-opus-5`), row 6 (`gpt-5.3-codex` ->
  `gpt-5.6-terra`), and the prior-generation tail rows 7 and 8 (`claude-opus-4.7` ->
  `claude-opus-4.8`, `gpt-5.4` -> `gpt-5.5`); the other rows (`gpt-5.6-sol`, `gemini-3.1-pro-preview`,
  `mai-code-1-flash-picker`, `claude-sonnet-5`) were already current and are unchanged. The roster
  stays an illustrative example of the diversity-first selection strategy - substitute the
  equivalents your host exposes (for example xAI's Grok or Moonshot's Kimi flagships on hosts that
  offer them, or Google's `gemini-3.6-flash` as a lighter distinct-family voice).

### Added

- Built-in guidance for repeated panel runs on the same work: rotate/refresh the non-anchor roster
  each run (and, in prisms mode, which model reviews which aspect) while keeping the top flagships
  pinned, and increase the duck `count` when weaker or lighter models are added so extra diversity is
  additive rather than displacing the flagships.

## [1.0.2] - 2026-07-19

### Changed

- Targetless runs no longer auto-select the newest matching HTML from the user's Downloads folder.
  The panel now reviews only a target that is explicit in the invocation or clearly identified by
  the current session; an explicit or session-identified target takes priority and is never
  overridden by a scratch or working-tree file, and scratch/cwd discovery runs only for a targetless
  invocation and only for a candidate unambiguously tied to this session. If none is clear, it stops
  and asks the user which document to review instead of reaching into Downloads.
- The commentable-HTML open-comments extractor is now a shipped script
  (`tools/extract_open_comments.py`) that the skill runs by resolving the plugin root, rather than a
  full parser listing rehydrated from SKILL.md on every activation. Behavior is unchanged.

## [1.0.1] - 2026-07-19

### Added

- The shipped plugin package now includes the MIT license text.

## [1.0.0]

- Initial release of multi-duck: convene a panel of independent rubber-duck reviewers over the
  work in flight (a diff, PR, plan, tests, or commentable-HTML plans with their open inline
  comments), each on a different model, all in parallel, then consolidate the findings and
  autonomously apply the safe fixes.
- Two panel modes: prisms (split the panel by review aspect, at least two differently-modeled ducks
  per aspect, for wide coverage) and consensus (every duck chases the same goal so cross-model
  agreement is a confidence signal).
- Auto-discovers what to review (diff, PR, markdown plan, and active commentable-HTML plans plus
  their open inline comments) and runs end to end with no extra prompt.
- Dual-host: runs on both Claude Code and the GitHub Copilot CLI, with a host mapping for the
  reviewer subagent, per-duck model selection, parallel launch, result collection, and tracking.
