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


def main(argv):
    parser = argparse.ArgumentParser(prog="build.py", description="Build the commentable-html distributable set.")
    parser.add_argument("--check", action="store_true",
                        help="verify the generated files in --out-dir match a fresh build (no writes)")
    parser.add_argument("--regen-vendor-gz", action="store_true",
                        help="recompress the vendored rich libraries to their committed .gz artifacts "
                             "(run when a vendored library changes; the ONLY step that gzips) then exit")
    parser.add_argument("--check-fixtures", action="store_true",
                        help="with --check, also verify the Playwright fixtures are in sync "
                             "(runs generate.mjs --check; skipped when node is absent)")
    parser.add_argument("--assets-dir", default=None,
                        help="directory holding the canonical sources (default: <skill>/assets)")
    parser.add_argument("--out-dir", default=None,
                        help="directory that receives dist/PORTABLE.html and dist/ (default: the skill root)")
    parser.add_argument("--pkg-dir", default=None,
                        help="the shipped skill dir; when set, assemble skill-resources.zip and the "
                             "unzipped SKILL.md/LICENSE copies here and stamp the hook version there")
    parser.add_argument("--examples-dir", default=None,
                        help="directory that receives the built example reports/prompts "
                             "(default: <out-dir>/examples)")
    ns = parser.parse_args(argv[1:])
    assets_dir = ASSETS if ns.assets_dir is None else os.path.abspath(ns.assets_dir)
    out_dir = HERE if ns.out_dir is None else os.path.abspath(ns.out_dir)
    if ns.regen_vendor_gz:
        vendor_dir = os.path.join(assets_dir, "vendor")
        for name in VENDORED_LIB_SCRIPTS:
            regen_vendored_gz(vendor_dir, name)
            print("regenerated %s.gz" % name)
        return 0
    pkg_dir = os.path.abspath(ns.pkg_dir) if ns.pkg_dir else None
    examples_dir = (os.path.abspath(ns.examples_dir) if ns.examples_dir
                    else os.path.join(out_dir, "examples"))
    dist_dir = os.path.join(out_dir, "dist")
    outputs, version = build_all(assets_dir, out_dir, examples_dir)
    stamps = source_stamps(version, assets_dir, out_dir, pkg_dir)
    stamps.update(example_stamps(examples_dir, read_mermaid_version()))
    stale = _unexpected_dist_files(outputs.keys(), dist_dir)
    legacy = [p for p in _legacy_generated_files(out_dir) if os.path.exists(p)]
    if ns.check:
        drift = []
        vendor_dir = os.path.join(assets_dir, "vendor")
        for name in VENDORED_LIB_SCRIPTS:
            msg = vendored_gz_drift(vendor_dir, name)
            if msg:
                drift.append(os.path.join("assets", "vendor", msg))
        for path, text in list(outputs.items()) + list(stamps.items()):
            rel = os.path.relpath(path, out_dir)
            if not os.path.exists(path):
                drift.append(rel + " (missing)")
            elif _lf(read(path)) != _lf(text):
                drift.append(rel + " (out of date)")
        for name in stale:
            drift.append(os.path.join("dist", name) + " (stale - not produced by the current build; delete it)")
        for name in _orphan_examples(examples_dir):
            drift.append(os.path.join("examples", name)
                         + " (orphaned - no dev/examples/src source; add its source or delete it)")
        for path in legacy:
            drift.append(os.path.relpath(path, out_dir) + " (legacy generated file - delete it)")
        if pkg_dir:
            drift.extend(check_package(out_dir, pkg_dir, version))
        if drift:
            sys.stderr.write("build --check FAILED; run `python tools/build.py`:\n")
            for d in drift:
                sys.stderr.write("  - " + d + "\n")
            return 1
        if ns.check_fixtures:
            ok, msg = _check_fixtures()
            if not ok:
                sys.stderr.write("build --check FAILED (fixtures out of date):\n")
                sys.stderr.write("  " + msg.replace("\n", "\n  ") + "\n")
                return 1
            print("  " + msg)
        print("build --check OK (%d generated files in sync, version %s)" % (len(outputs), version))
        return 0
    for name in stale:
        os.remove(os.path.join(dist_dir, name))
    for path in legacy:
        os.remove(path)
    for path, text in outputs.items():
        write(path, text)
    for path, text in stamps.items():
        write(path, text)
    if pkg_dir:
        write_package(out_dir, pkg_dir, version)
    if stale:
        print("removed %d stale dist file(s): %s" % (len(stale), ", ".join(stale)))
    _report(outputs, version, out_dir)
    return 0
