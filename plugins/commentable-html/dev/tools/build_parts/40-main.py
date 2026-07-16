def main(argv):
    parser = argparse.ArgumentParser(prog="build.py", description="Build the commentable-html distributable set.")
    parser.add_argument("--check", action="store_true",
                        help="verify the generated files in --out-dir match a fresh build (no writes)")
    parser.add_argument("--check-fixtures", action="store_true",
                        help="with --check, also verify the Playwright fixtures are in sync "
                             "(runs generate.mjs --check; skipped when node is absent)")
    parser.add_argument("--assets-dir", default=None,
                        help="directory holding the canonical sources (default: <skill>/assets)")
    parser.add_argument("--out-dir", default=None,
                        help="directory that receives dist/PORTABLE.html and dist/ (default: the skill root)")
    ns = parser.parse_args(argv[1:])
    assets_dir = ASSETS if ns.assets_dir is None else os.path.abspath(ns.assets_dir)
    out_dir = HERE if ns.out_dir is None else os.path.abspath(ns.out_dir)
    dist_dir = os.path.join(out_dir, "dist")
    outputs, version = build_all(assets_dir, out_dir)
    stamps = source_stamps(version, assets_dir, out_dir)
    stamps.update(example_stamps(out_dir, read_mermaid_version()))
    stale = _unexpected_dist_files(outputs.keys(), dist_dir)
    legacy = [p for p in _legacy_generated_files(out_dir) if os.path.exists(p)]
    if ns.check:
        drift = []
        for path, text in list(outputs.items()) + list(stamps.items()):
            rel = os.path.relpath(path, out_dir)
            if not os.path.exists(path):
                drift.append(rel + " (missing)")
            elif _lf(read(path)) != _lf(text):
                drift.append(rel + " (out of date)")
        for name in stale:
            drift.append(os.path.join("dist", name) + " (stale - not produced by the current build; delete it)")
        for name in _orphan_examples(out_dir):
            drift.append(os.path.join("examples", name)
                         + " (orphaned - no dev/examples/src source; add its source or delete it)")
        for path in legacy:
            drift.append(os.path.relpath(path, out_dir) + " (legacy generated file - delete it)")
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
    if stale:
        print("removed %d stale dist file(s): %s" % (len(stale), ", ".join(stale)))
    _report(outputs, version, out_dir)
    return 0
