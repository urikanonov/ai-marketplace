#!/usr/bin/env python3
"""Generate the static, build-time content for the GitHub Pages site.

The site is fully static: the plugins grid, the commentable-html version badge, and
the commentable-html changelog are generated from the repository's own sources
(`.github/plugin/marketplace.json` and `CHANGELOG.md`) and written into marker
regions of the HTML. This keeps the pages self-contained (no client-side fetch, so
no CORS/file:// breakage, no GitHub API rate limits, and no runtime DOM injection),
and it is regenerated on every deploy so the published site never drifts from source.

All text is HTML-escaped and URLs are allowlisted (https or in-repo relative) before
being written, so repository content can never inject markup into the page.

Usage:
    python scripts/build_site_data.py            # write the generated regions + sync demos
    python scripts/build_site_data.py --check     # fail if the committed output is stale
"""
import argparse
import hashlib
import html
import io
import json
import os
import re
import subprocess
import sys
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

UPDATER_PLUGIN = "urikan-ai-marketplace-auto-updater"
MULTI_DUCK_PLUGIN = "multi-duck"
PLUGIN_PAGES = {
    "commentable-html": "./commentable-html/",
    UPDATER_PLUGIN: "./" + UPDATER_PLUGIN + "/",
    MULTI_DUCK_PLUGIN: "./" + MULTI_DUCK_PLUGIN + "/",
}
CHANGELOG_PLUGIN = "commentable-html"
DEMO_FILES = ["report-taxi.html", "report-community-garden.html", "report-triage.html", "report-metrics.html", "report-checklist.html", "deck-showcase.html"]
EXAMPLES_REL = os.path.join(
    "plugins", "commentable-html", "pkg", "skills", "commentable-html", "examples")
# Site layout (all under site/): sources and the generated publishable output live together.
#   site/pages/  page templates (source)        site/css/  CSS partials (source)
#   site/src/    hand-maintained static asset sources (site.js, logos, og-cover.png)
#   site/dist/   the generated publishable site (the Pages deploy artifact); DO NOT hand-edit
#   site/tests/  the site's Playwright suite
SITE_OUT = os.path.join("site", "dist")
SITE_PAGES = os.path.join("site", "pages")
SITE_STATIC_SRC = os.path.join("site", "src")

DEMO_REL = os.path.join(SITE_OUT, "commentable-html", "demo")
TUTORIAL_SRC = os.path.join(
    "plugins", "commentable-html", "pkg", "skills", "commentable-html", "docs", "TUTORIAL.md")
TUTORIAL_IMAGES_SRC = os.path.join(
    "plugins", "commentable-html", "pkg", "skills", "commentable-html", "docs", "assets")
TUTORIAL_PAGE = os.path.join(SITE_OUT, "commentable-html", "tutorial", "index.html")
TUTORIAL_IMAGES_DST = os.path.join(SITE_OUT, "commentable-html", "tutorial", "assets")

# Site pages: the hand-edited SOURCE templates live under site/pages/ and the committed pages
# under site/dist/ are PURE build artifacts assembled by build_page(). Keeping the source separate
# from the artifact (mirroring the site/css/ partials) is what lets --check cover the ENTIRE page,
# so a hand-edit or a stale copy committed by a concurrent PR fails CI instead of silently landing.
HUB_SRC = os.path.join(SITE_PAGES, "index.html")
HUB_OUT = os.path.join(SITE_OUT, "index.html")
PLUGIN_SRC = os.path.join(SITE_PAGES, "commentable-html", "index.html")
PLUGIN_OUT = os.path.join(SITE_OUT, "commentable-html", "index.html")
# The auto-updater plugin page: a REQUIRED page like the hub and the commentable-html page (its
# source must exist), built from its own site/pages source with only the version badge filled from
# the manifest so it never drifts from the shipped plugin version.
UPDATER_SRC = os.path.join(SITE_PAGES, UPDATER_PLUGIN, "index.html")
UPDATER_OUT = os.path.join(SITE_OUT, UPDATER_PLUGIN, "index.html")
# The multi-duck plugin page: another REQUIRED page like the hub and the commentable-html page (its
# source must exist), built from its own site/pages source with the version badge, install block, and
# per-plugin changelog filled from the manifest and the plugin CHANGELOG.md so it never drifts.
MULTI_DUCK_SRC = os.path.join(SITE_PAGES, MULTI_DUCK_PLUGIN, "index.html")
MULTI_DUCK_OUT = os.path.join(SITE_OUT, MULTI_DUCK_PLUGIN, "index.html")
TUTORIAL_PAGE_SRC = os.path.join(SITE_PAGES, "commentable-html", "tutorial", "index.html")

# The commentable-html skill root. The tutorial references example files with
# skill-root-relative display paths; locally (in the shipped skill) those links resolve to
# the local asset, while on the generated site they are rewritten to point at the live demo
# page (the site does not host the skill's examples/ tree at that path, but it does host the
# same reports under commentable-html/demo/).

# The full per-plugin changelog on GitHub, linked from the plugin page when older releases
# are folded away (the page shows only the most recent releases; the rest live in source).
CHANGELOG_GITHUB_URL = (
    "https://github.com/urikanonov/ai-marketplace/blob/main/plugins/"
    + CHANGELOG_PLUGIN + "/CHANGELOG.md")

# The plugins here install into BOTH Claude Code and the GitHub Copilot CLI. The install block is
# tabbed by agent: each agent shares the same marketplace name and git URL and differs only in the
# leading CLI binary. INSTALL_AGENTS is (key, tab label, CLI binary); Copilot is first (the default
# tab). The repo-root .claude-plugin/marketplace.json lists which plugins are Claude-installable, so
# the Claude tab is offered only for those (both currently shipped plugins are dual-agent; the
# carve-out remains for any future Copilot-only plugin). Both CLIs and their Desktop apps invoke the
# same installed skill.
MARKETPLACE_GIT_URL = "https://github.com/urikanonov/ai-marketplace"
CLAUDE_MARKETPLACE_REL = os.path.join(".claude-plugin", "marketplace.json")
INSTALL_AGENTS = [
    ("copilot", "GitHub Copilot", "copilot"),
    ("claude", "Claude Code", "claude"),
]

# Claude Desktop / claude.ai import a skill as a ZIP through Settings > Features (Pro/Max/Team/
# Enterprise with code execution). The install block offers a third "Claude Desktop" tab for the
# plugins listed here, linking to a downloadable ZIP of the shipped skill. The auto-updater is
# intentionally absent: its value is the session-start hook, which a Desktop skill import cannot
# provide, so it offers CLI tabs only. Each entry: skill_dir (repo-relative, the shipped skill
# whose contents are zipped under a single top-level `skill/` folder), skill (the folder/skill
# name), and zip (the site/dist-relative output path).
DESKTOP_SKILLS = {
    "commentable-html": {
        "skill_dir": "plugins/commentable-html/pkg/skills/commentable-html",
        "skill": "commentable-html",
        "zip": "skills/commentable-html.zip",
    },
}

# Absolute production URLs, used for canonical/OG links (hand-authored in the page heads) and for
# the JSON-LD graph, sitemap, and llms.txt generated below. The site is served from this fixed
# project sub-path on github.io, so these never vary per environment.
SITE_BASE_URL = "https://urikanonov.github.io/ai-marketplace/"
SITE_NAME = "AI Marketplace"
OWNER_GITHUB_URL = "https://github.com/urikanonov"
OWNER_LINKEDIN_URL = "https://www.linkedin.com/in/uri-kanonov-946761119"
