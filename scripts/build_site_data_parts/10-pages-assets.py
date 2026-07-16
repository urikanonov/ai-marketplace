def esc(value):
    return html.escape(str(value), quote=True)


def safe_url(url):
    """Allow https, mailto, and in-repo relative URLs; neutralize anything with a
    dangerous or insecure scheme (javascript:, data:, http:, ...) or a protocol-relative
    //host. Strip C0 control chars, DEL, and whitespace first, because browsers remove
    tabs/newlines from URLs (so a tab inside "javascript" would otherwise hide the scheme),
    and fold backslashes to forward slashes because browsers treat \\host like //host."""
    u = re.sub(r"[\x00-\x20\x7f]", "", url or "").replace("\\", "/")
    if u.startswith("//"):
        return "#"
    scheme = re.match(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):", u)
    if scheme and scheme.group(1).lower() not in ("https", "mailto"):
        return "#"
    return u


def read_text(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read().replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")


def _safe_makedirs(directory):
    """Create a directory tree, turning a directory-vs-file path conflict into a clear SystemExit
    instead of a raw NotADirectoryError/FileExistsError traceback."""
    if not directory:
        return
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        raise SystemExit("cannot create output directory %s (%s); a file may exist where a "
                         "directory is expected" % (directory, exc))


def write_text(path, text):
    _safe_makedirs(os.path.dirname(path))
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


# Render-critical assets whose URLs carry a content-hash query, so a browser never serves a
# stale stylesheet or script after a deploy (the query changes exactly when the file does).
# Icons are omitted: they change rarely and a cached favicon does not misrender page content.
# The generated pages always use double-quoted attributes, which this pattern targets.
CACHE_BUSTED_ASSETS = ("styles.css", "site.js")
_ASSET_REF_RE = re.compile(
    r'(?P<attr>href|src)="(?P<path>(?:\.{1,2}/)*assets/(?P<file>%s))(?:[?#][^"]*)?"'
    % "|".join(re.escape(name) for name in CACHE_BUSTED_ASSETS))


def _asset_hash(root, name):
    # styles.css is itself a build artifact (assembled from site/css/ partials), so hash the
    # freshly-built stylesheet rather than the on-disk copy: the page's ?v= stamp then reflects the
    # SOURCE partials directly (a pure artifact), it is normalization-independent, and a missing or
    # stale site/dist/assets/styles.css cannot crash --check or embed a stale hash. Other assets
    # (site.js) are copied verbatim from their site/src/ source, so the served bytes are the source.
    if name == "styles.css":
        return hashlib.sha256(build_styles(root).encode("utf-8")).hexdigest()[:12]
    path = os.path.join(root, SITE_OUT, "assets", name)
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        raise SystemExit("cannot read required cache-busted asset %s (%s); it is a committed "
                         "source, not generated - restore it" % (path, exc))
    return hashlib.sha256(data).hexdigest()[:12]


# The served site/dist/assets/styles.css is assembled from ALL ordered source partials under
# site/css/, discovered by directory sort (no hand-maintained list, so adding a partial does
# not edit this script and two PRs adding partials do not collide here). Each partial is named
# `NN-topic.css` with a zero-padded 2-digit prefix; the sorted order is the load-bearing CSS
# cascade. The concatenation is byte-for-byte the served bundle (same CSP, same cache-bust).
CSS_DIR = ("site", "css")
_CSS_PART_RE = re.compile(r"^\d{2}-[a-z0-9-]+\.css$")


def ordered_css_parts(root):
    css_dir = os.path.join(root, *CSS_DIR)
    if not os.path.isdir(css_dir):
        raise SystemExit("CSS source directory missing: %s" % css_dir)
    names = [n for n in os.listdir(css_dir) if os.path.isfile(os.path.join(css_dir, n)) and n.lower().endswith(".css")]
    stray = [n for n in names if not _CSS_PART_RE.match(n)]
    if stray:
        raise SystemExit("site/css/ holds .css files that are not `NN-topic.css` partials: %s "
                         "(rename to the numbered convention or remove them)" % ", ".join(sorted(stray)))
    if not names:
        raise SystemExit("no CSS partials found under %s" % css_dir)
    return sorted(names)


def build_styles(root):
    css_dir = os.path.join(root, *CSS_DIR)
    parts = [read_text(os.path.join(css_dir, name)) for name in ordered_css_parts(root)]
    return css_banner() + "".join(parts)


# Generated site artifacts carry a "DO NOT EDIT" banner that names their source, so a human who
# opens the built file under site/ is told to edit the source and rebuild instead. `--check` then
# guarantees the committed artifact still equals a fresh build, so a hand-edit (or a stale copy
# committed by a concurrent PR) fails CI instead of silently shipping.
GENERATED_BANNER_PREFIX = "GENERATED FILE - DO NOT EDIT."
_RUN_HINT = "run: python scripts/build_site_data.py"


def css_banner():
    return ("/* %s Built from site/css/*.css by scripts/build_site_data.py; %s */\n"
            % (GENERATED_BANNER_PREFIX, _RUN_HINT))


def page_banner(source_rel):
    return ("<!-- %s Built from %s by scripts/build_site_data.py; %s -->"
            % (GENERATED_BANNER_PREFIX, source_rel.replace(os.sep, "/"), _RUN_HINT))


_PAGE_BANNER_RE = re.compile(
    r"^[ \t]*<!-- %s[^\n]*?-->[ \t]*\r?\n?" % re.escape(GENERATED_BANNER_PREFIX))
_DOCTYPE_RE = re.compile(r"(?i)^(\s*<!doctype[^>]*>)([ \t]*\r?\n?)")


def apply_page_banner(html, source_rel):
    """Insert the DO NOT EDIT banner right after the doctype (replacing any prior banner in that
    exact slot), so the built page self-identifies as an artifact and points at its source. The
    strip is anchored to the position right after the doctype, so a body comment that happens to
    start with the banner prefix is never removed; the doctype match tolerates any doctype variant."""
    banner = page_banner(source_rel)
    m = _DOCTYPE_RE.match(html)
    if m:
        rest = _PAGE_BANNER_RE.sub("", html[m.end():], count=1)
        return m.group(1) + (m.group(2) or "\n") + banner + "\n" + rest
    return banner + "\n" + _PAGE_BANNER_RE.sub("", html, count=1)


def build_page(root, source_rel, region_fillers):
    """Assemble one site page ARTIFACT from its site/pages SOURCE: fill each marker region,
    cache-bust asset references, and inject the DO NOT EDIT banner. The source is independent of
    the built artifact under site/, so `--check` (comparing this result to the committed artifact)
    covers the whole page - not just the marker regions - which is what closes the site clobber gap."""
    out = read_text(os.path.join(root, source_rel))
    if not _DOCTYPE_RE.match(out):
        raise SystemExit("page source %s must begin with a <!doctype ...> declaration"
                         % source_rel.replace(os.sep, "/"))
    # Count only line-leading doctype declarations (how a real duplicate from a bad merge appears),
    # so a literal "<!doctype" embedded in prose, a script string, or a comment never false-trips.
    if len(re.findall(r"(?im)^[ \t]*<!doctype\b", out)) != 1:
        raise SystemExit("page source %s must contain exactly one <!doctype ...> declaration "
                         "(a second one is usually a merge artifact)" % source_rel.replace(os.sep, "/"))
    for kind, name, value in region_fillers:
        if kind == "inline":
            out = replace_region_inline(out, name, value)
        elif kind == "block":
            out = replace_region_block(out, name, value)
        else:
            raise SystemExit("build_page: unknown region filler kind %r (use 'inline' or 'block')" % kind)
    out = stamp_assets(out, root)
    return apply_page_banner(out, source_rel)


def _read_artifact(path):
    """Return the committed artifact text, or None when it is missing (or is not a regular file) so
    an absent built page counts as drift under --check."""
    return read_text(path) if os.path.isfile(path) else None


def stamp_assets(text, root):
    """Append a ?v=<content-hash> query to every reference to a cache-busted asset, replacing any
    existing query or fragment on it. The stamp is idempotent and always matches the committed
    asset, so the URL busts the browser cache exactly when the asset's bytes change."""
    cache = {}

    def repl(match):
        name = match.group("file")
        if name not in cache:
            cache[name] = _asset_hash(root, name)
        return '%s="%s?v=%s"' % (match.group("attr"), match.group("path"), cache[name])

    return _ASSET_REF_RE.sub(repl, text)


def replace_region_block(text, name, inner):
    pattern = re.compile(
        r"([ \t]*)<!-- BEGIN:%s -->.*?<!-- END:%s -->" % (re.escape(name), re.escape(name)),
        re.DOTALL)

    def repl(match):
        indent = match.group(1)
        lines = inner.strip("\n").split("\n")
        body = "\n".join((indent + ln) if ln.strip() else "" for ln in lines)
        return "%s<!-- BEGIN:%s -->\n%s\n%s<!-- END:%s -->" % (indent, name, body, indent, name)

    new_text, count = pattern.subn(repl, text)
    if count == 0:
        raise SystemExit("region not found: %s" % name)
    if count > 1:
        raise SystemExit("duplicate region: %s" % name)
    return new_text


def replace_region_inline(text, name, inner):
    pattern = re.compile(
        r"<!-- BEGIN:%s -->.*?<!-- END:%s -->" % (re.escape(name), re.escape(name)),
        re.DOTALL)
    replacement = "<!-- BEGIN:%s -->%s<!-- END:%s -->" % (name, inner, name)
    new_text, count = pattern.subn(lambda m: replacement, text)
    if count == 0:
        raise SystemExit("region not found: %s" % name)
    if count > 1:
        raise SystemExit("duplicate region: %s" % name)
    return new_text
