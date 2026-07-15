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
import re

CREATED_META = "commentable-html-created"
VALIDATED_META = "commentable-html-validated"


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
