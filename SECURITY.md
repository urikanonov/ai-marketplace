# Security Policy

## Supported versions

Only the current `main` branch is supported. Fixes ship by updating the affected plugin in place; run
`copilot plugin update <name>@urikan-ai-marketplace` to pick them up.

## What you are installing

Plugins in this marketplace can ship skills, MCP servers, and session hooks that execute code on your
machine. For example, `urikan-ai-marketplace-auto-updater` runs a PowerShell hook on session start.
Review a plugin's contents before installing it, exactly as you would any other third-party tooling.

## Reporting a vulnerability

Please do not open a public issue for security problems. Instead, use one of:

- GitHub private vulnerability reporting: https://github.com/urikanonov/ai-marketplace/security/advisories/new
- Email: urikanonov@gmail.com (include details and reproduction steps)

Expect an initial response within a few days. Please allow a reasonable window to release a fix before
any public disclosure.
