# Changelog

All notable changes to the multi-duck plugin are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to semantic
versioning.

## [1.0.2] - 2026-07-19

### Changed

- Targetless runs no longer auto-select the newest matching HTML from the user's Downloads folder.
  The panel now reviews only a target that is explicit in the invocation or clearly identified by
  the current session; if none is clear, it stops and asks the user which document to review instead
  of reaching into Downloads.
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
