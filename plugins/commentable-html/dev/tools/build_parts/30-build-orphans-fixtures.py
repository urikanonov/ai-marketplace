def build_examples(portable_html, version, mermaid_version, out_dir):
    """Regenerate every shipped examples/report-*.html and examples/deck-*.html under out_dir
    from its INDEPENDENT content source in dev/examples/src/ (not from the shipped file itself).
    Returns {out_path: text}. An absent out_dir/examples directory (e.g. a temp-dir build) or an
    absent source dir yields no entries. Assembling from an independent source is what lets
    --check catch a stale or hand-edited shipped example instead of comparing it to itself."""
    examples_dir = os.path.join(out_dir, "examples")
    result = {}
    if not os.path.isdir(examples_dir) or not os.path.isdir(EXAMPLES_SRC):
        return result
    for name in sorted(os.listdir(EXAMPLES_SRC)):
        if not _EXAMPLE_NAME_RE.match(name):
            continue
        src_path = os.path.join(EXAMPLES_SRC, name)
        out_path = os.path.join(examples_dir, name)
        result[out_path] = regen_example(read(src_path), portable_html, version, mermaid_version, name)
    return result


def build_prompt_examples(out_dir):
    """Copy every dev/examples/src/prompt-*.md VERBATIM to the shipped examples/<same-name>.md.
    A one-shot prompt is plain Markdown with no layer/version/mermaid to stamp, so its 'assembly'
    is a byte copy from its independent source; --check then catches a stale or hand-edited shipped
    prompt. Only prompts that HAVE a source are written, so hand-maintained prompts without one are
    left untouched. Returns {out_path: text}; an absent examples or source dir yields no entries."""
    examples_dir = os.path.join(out_dir, "examples")
    result = {}
    if not os.path.isdir(examples_dir) or not os.path.isdir(EXAMPLES_SRC):
        return result
    for name in sorted(os.listdir(EXAMPLES_SRC)):
        if not _PROMPT_NAME_RE.match(name):
            continue
        src_path = os.path.join(EXAMPLES_SRC, name)
        out_path = os.path.join(examples_dir, name)
        result[out_path] = read(src_path)
    return result


def _orphan_examples(out_dir):
    """Shipped examples/report-*.html or examples/deck-*.html that have NO dev/examples/src source.
    build_examples only assembles examples that have a source, so an orphan shipped example would
    otherwise be a pure artifact validated against nothing (the exact self-sourced hole this split
    closed). --check reports it so it cannot drift undetected; the fix is to add its source or
    delete it."""
    examples_dir = os.path.join(out_dir, "examples")
    if not os.path.isdir(examples_dir) or not os.path.isdir(EXAMPLES_SRC):
        return []
    sources = set(os.listdir(EXAMPLES_SRC))
    return [name for name in sorted(os.listdir(examples_dir))
            if _EXAMPLE_NAME_RE.match(name) and name not in sources]


def build_all(assets_dir=None, out_dir=None):
    out_dir = HERE if out_dir is None else out_dir
    dist_dir = os.path.join(out_dir, "dist")
    css, js, shell, version = load_sources(assets_dir)
    mermaid_version = read_mermaid_version()
    js = _stamp_const(js, version, "commentable-html.js")
    css_name, js_name, assets_name = _names()
    assets_js = build_assets_js(css, js, version)
    css_file, js_file = css + "\n", js + "\n"
    manifest = {
        "version": version,
        "files": {
            css_name: {"sha256": sha256(css_file), "bytes": len(css_file.encode("utf-8"))},
            js_name: {"sha256": sha256(js_file), "bytes": len(js_file.encode("utf-8"))},
            assets_name: {"sha256": sha256(assets_js), "bytes": len(assets_js.encode("utf-8"))},
        },
    }
    portable = build_inline(css, js, shell, version, mermaid_version)
    outputs = {
        os.path.join(dist_dir, "PORTABLE.html"): portable,
        os.path.join(dist_dir, css_name): css_file,
        os.path.join(dist_dir, js_name): js_file,
        os.path.join(dist_dir, assets_name): assets_js,
        os.path.join(dist_dir, "manifest.json"): json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        os.path.join(dist_dir, "NONPORTABLE.html"): build_nonportable(shell, version, mermaid_version),
    }
    outputs.update(build_examples(portable, version, mermaid_version, out_dir))
    outputs.update(build_prompt_examples(out_dir))
    return outputs, version


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #
def _report(outputs, version, out_dir=None):
    out_dir = HERE if out_dir is None else out_dir
    portable = outputs[os.path.join(out_dir, "dist", "PORTABLE.html")]
    nonportable = outputs[os.path.join(out_dir, "dist", "NONPORTABLE.html")]
    inline_b = len(portable.encode("utf-8"))
    nonportable_b = len(nonportable.encode("utf-8"))
    saved = inline_b - nonportable_b
    pct = (saved / inline_b * 100) if inline_b else 0
    print("commentable-html build - version %s" % version)
    print("  inline  dist/PORTABLE.html : %6d bytes" % inline_b)
    print("  nonportable dist/NONPORTABLE.html  : %6d bytes" % nonportable_b)
    print("  per-regeneration boilerplate avoided in nonportable mode: %d bytes (%.0f%% smaller)"
          % (saved, pct))


def _check_fixtures():
    """Run the Playwright fixtures' own `generate.mjs --check` so the dist gate also catches stale
    fixtures. Returns (ok, message). A missing generator is a repo problem and fails (the caller
    explicitly asked to check fixtures); only a genuinely absent node runtime is a soft skip, since
    CI (plugin-tests) is the authoritative gate there."""
    if not os.path.exists(FIXTURES_GEN):
        return False, "fixtures --check FAILED: generate.mjs is missing (" + FIXTURES_GEN + ")"
    node = shutil.which("node")
    if not node:
        return True, "fixtures --check skipped (node not found; CI plugin-tests still runs it)"
    proc = subprocess.run([node, FIXTURES_GEN, "--check"], capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        return False, out.strip() or "fixtures --check FAILED; run `node tests/fixtures/generate.mjs`"
    return True, "fixtures --check OK"
