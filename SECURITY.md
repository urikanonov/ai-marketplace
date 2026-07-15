# Security Policy

## Supported versions

Only the current `main` branch is supported. Fixes ship by updating the affected plugin in place; run
`copilot plugin update <name>@urikan-ai-marketplace` (or `claude plugin update <name>@urikan-ai-marketplace`
under Claude Code) to pick them up.

## What you are installing

Plugins in this marketplace can ship skills, MCP servers, and session hooks that execute code on your
machine. For example, `urikan-ai-marketplace-auto-updater` runs a PowerShell hook on session start.
Review a plugin's contents before installing it, exactly as you would any other third-party tooling.

## Auto-updater trust model

`urikan-ai-marketplace-auto-updater` is opt-in, but once installed it runs a PowerShell hook on every
Copilot or Claude Code session start that calls `copilot plugin update` (or `claude plugin update` under
Claude Code) for each installed plugin from this marketplace.
That means:

- Installing it is a persistent grant to execute future versions of your installed plugins - a new or
  changed session hook, MCP server, or script merged to `main` runs on your next session without a prompt.
- The trust anchor is the `@urikanonov` GitHub account and the branch protection on `main`.
- If you want to review each update yourself, do not install the auto-updater; run
  `copilot plugin update <name>@urikan-ai-marketplace` (or `claude plugin update <name>@urikan-ai-marketplace`
  under Claude Code) manually instead.

## Reporting a vulnerability

Please do not open a public issue for security problems. Instead, use one of:

- GitHub private vulnerability reporting: https://github.com/urikanonov/ai-marketplace/security/advisories/new
- Email: urikanonov@gmail.com (include details and reproduction steps)

Expect an initial response within a few days. Please allow a reasonable window to release a fix before
any public disclosure.
