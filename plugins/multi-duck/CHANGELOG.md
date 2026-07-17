# Changelog

All notable changes to the multi-duck plugin are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to semantic
versioning.

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
