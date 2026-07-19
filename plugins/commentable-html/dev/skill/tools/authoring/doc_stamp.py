#!/usr/bin/env python3
"""Read and write the commentable-html provenance <meta> stamps.

Two stamps let the runtime tell whether a document was actually validated:
- `commentable-html-created`  - written when a tool first produces the document.
- `commentable-html-validated` - written by `validate.py` (and `finalize.py`) only on a
  STRICT-CLEAN pass (no errors AND no warnings).

The runtime shows a small fallback banner when a document carries a created stamp but no
current validated stamp - a document that was produced but never strict-validated. This is a
last-resort signal; the skill MUST always finalize and strict-validate before handoff.
"""
import datetime
import ntpath
import os
import re

CREATED_META = "commentable-html-created"
VALIDATED_META = "commentable-html-validated"
# Provenance of the AI session that produced the document. `session-id` is the raw id string
# the runtime footer copies to the clipboard; `agent` is the producing tool's slug (e.g.
# "copilot", "claude") the footer maps to a friendly name in the copy tooltip.
SESSION_META = "commentable-html-session-id"
AGENT_META = "commentable-html-agent"

# Environment variables each supported agent exports for its own session id, in priority order.
# Copilot CLI exports COPILOT_AGENT_SESSION_ID; Claude Code exports CLAUDE_CODE_SESSION_ID (both
# confirmed live), with CLAUDE_SESSION_ID kept as a fallback name. The list is easy to extend.
_SESSION_ENV_VARS = (
    ("COPILOT_AGENT_SESSION_ID", "copilot"),
    ("CLAUDE_CODE_SESSION_ID", "claude"),
    ("CLAUDE_SESSION_ID", "claude"),
)

# "I am the running CLI" marker env vars each agent sets. When more than one agent's session id is
# visible (e.g. one CLI launched from another, so a parent's id is inherited by the child), these
# disambiguate which agent is the IMMEDIATE runtime actually executing the tool. Claude is checked
# first so a Claude-run tool under a Copilot parent is attributed to Claude.
_RUNTIME_MARKERS = (
    ("claude", ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")),
    ("copilot", ("COPILOT_CLI",)),
)


def source_basename(source):
    """Return only the filename portion of a source identifier on either path style."""
    value = str(source or "")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
        value = re.split(r"[?#]", value, maxsplit=1)[0]
    if value.endswith(("/", "\\")):
        return "document"
    return ntpath.basename(os.path.basename(value)) or "document"


def now_iso():
    """A second-precision UTC ISO-8601 timestamp, e.g. 2026-07-15T10:21:31Z."""
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return now.isoformat().replace("+00:00", "Z")


def _meta_re(name):
    return re.compile(r'(<meta\s+name="%s"\s+content=")[^"]*(")' % re.escape(name), re.IGNORECASE)


def get_meta(html, name):
    """Return the content of `<meta name=NAME>`, or None when it is absent."""
    m = re.search(r'<meta\s+name="%s"\s+content="([^"]*)"' % re.escape(name), html, re.IGNORECASE)
    return m.group(1) if m else None


def set_meta(html, name, content):
    """Set (or insert into <head>) `<meta name=NAME content=CONTENT>`; returns the new html.
    The content is attribute-escaped so a stray quote can never break the tag."""
    esc = content.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
    new_html, n = _meta_re(name).subn(lambda m: m.group(1) + esc + m.group(2), html, count=1)
    if n:
        return new_html
    tag = '<meta name="%s" content="%s" />' % (name, esc)
    m = re.search(r"<head[^>]*>", html, re.IGNORECASE)
    if m:
        return html[:m.end()] + "\n" + tag + html[m.end():]
    return tag + html


def stamp_created(html, when=None):
    """Stamp the creation time (idempotent: an existing created stamp is preserved)."""
    if get_meta(html, CREATED_META) is not None:
        return html
    return set_meta(html, CREATED_META, when or now_iso())


def stamp_validated_html(html, when=None):
    """Return html with the validated stamp set to `when` (default: now)."""
    return set_meta(html, VALIDATED_META, when or now_iso())


def detect_session(environ=None):
    """Return `(session_id, agent)` auto-detected from the environment, or `(None, None)`.

    Collects every `_SESSION_ENV_VARS` entry present in the environment. With one match it is
    returned; with several (a nested launch where a parent CLI's id was inherited) the agent that
    is the IMMEDIATE runtime - identified by its `_RUNTIME_MARKERS` - wins, falling back to list
    order when no marker resolves it. Pass `environ` to test without mutating `os.environ`."""
    env = os.environ if environ is None else environ
    present = [(var, agent) for var, agent in _SESSION_ENV_VARS if (env.get(var) or "").strip()]
    if not present:
        return None, None
    if len(present) > 1:
        runtime = _current_runtime(env)
        for var, agent in present:
            if agent == runtime:
                return (env.get(var) or "").strip(), agent
    var, agent = present[0]
    return (env.get(var) or "").strip(), agent


def _current_runtime(env):
    """Return the slug of the agent CLI actually running this process, or None, from the
    `_RUNTIME_MARKERS`. Used only to break ties when several agents' session ids are visible."""
    for agent, markers in _RUNTIME_MARKERS:
        if any((env.get(m) or "").strip() for m in markers):
            return agent
    return None


def stamp_session(html, session_id, agent=None):
    """Stamp the producing AI session id (and optional agent slug) as provenance meta.

    Idempotent on the session id: an existing `commentable-html-session-id` stamp is preserved
    (so a re-scaffold never rewrites the original producer), and a blank/None session id is a
    no-op. When a session id is written and `agent` is given, the agent slug is written too."""
    sid = (session_id or "").strip()
    if not sid or get_meta(html, SESSION_META) is not None:
        return html
    html = set_meta(html, SESSION_META, sid)
    ag = (agent or "").strip()
    if ag:
        html = set_meta(html, AGENT_META, ag)
    return html
