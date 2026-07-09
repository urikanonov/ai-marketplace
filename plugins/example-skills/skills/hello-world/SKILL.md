---
name: hello-world
description: >
  Minimal example skill that greets the user. Use this as a starter template when
  creating a new skill for the marketplace, or invoke it to confirm the marketplace
  is wired up correctly. Trigger when the user asks for a hello-world or marketplace
  smoke test.
---

# Hello World

A minimal skill that demonstrates the structure every skill in this marketplace follows. Copy this directory to bootstrap a new skill.

## What this skill does

When invoked, greet the user and confirm the plugin loaded from `urikan-ai-marketplace`.

## Steps

1. Respond with a short greeting, for example: `Hello from urikan-ai-marketplace!`.
2. If the user asked for a smoke test, also report which marketplace and plugin the skill was loaded from so they can confirm installation worked.

## Anatomy of a skill

- The YAML front matter (`name`, `description`) is required. The `description` should say what the skill does and when to trigger it, so the model can decide when to use it.
- Everything below the front matter is free-form Markdown that instructs the model.
- Register the skill in `.github/plugin/marketplace.json` so it becomes installable. See [CONTRIBUTING.md](../../../../CONTRIBUTING.md).
