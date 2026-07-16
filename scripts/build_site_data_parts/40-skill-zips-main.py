def build_skill_zip_members(root, skill_dir_rel, skill_name):
    """The ordered [(arcname, bytes)] contents of a skill ZIP: every file under the shipped skill
    directory, placed under a single top-level `<skill_name>/` folder (with SKILL.md at its root),
    which is the structure Claude Desktop / claude.ai skill import expects. Sorted by arcname so the
    archive is deterministic.

    Files are the git-TRACKED set (exactly what `plugin install` ships), so untracked developer
    noise (`.DS_Store`, `__pycache__`, editor temp files) can never leak into the committed ZIP and
    break a clean-checkout `--check`. Outside a git checkout it falls back to a filtered walk."""
    skill_dir = os.path.join(root, skill_dir_rel.replace("/", os.sep))
    if not os.path.isdir(skill_dir):
        raise SystemExit("Claude Desktop skill ZIP: skill directory is missing: %s" % skill_dir_rel)
    rels = _tracked_skill_files(root, skill_dir_rel)
    if rels is None:
        rels = _walk_skill_files(skill_dir)
    members = []
    for rel in sorted(rels):
        full = os.path.join(skill_dir, rel.replace("/", os.sep))
        if not os.path.isfile(full):
            continue
        with open(full, "rb") as fh:
            members.append(("%s/%s" % (skill_name, rel), fh.read()))
    members.sort(key=lambda m: m[0])
    if not any(arcname == "%s/SKILL.md" % skill_name for arcname, _ in members):
        raise SystemExit("Claude Desktop skill ZIP: %s has no SKILL.md at the root of %s"
                         % (skill_name, skill_dir_rel))
    return members


# Untracked developer noise that must never be packaged into a skill ZIP (the git-tracked path
# already excludes all of this; these apply only to the non-git filtered-walk fallback).
_SKILL_ZIP_SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".idea", ".vscode",
                        ".pytest_cache", ".mypy_cache"}
_SKILL_ZIP_SKIP_NAMES = {".DS_Store", "Thumbs.db"}
_SKILL_ZIP_SKIP_SUFFIXES = (".pyc", ".pyo")


def _tracked_skill_files(root, skill_dir_rel):
    """The git-tracked files under the skill dir, relative to the skill dir (forward slashes), or
    None when git is unavailable or this is not a git checkout so the caller can fall back."""
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "-z", "--", skill_dir_rel],
                             capture_output=True, check=True).stdout.decode("utf-8")
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
        return None
    prefix = skill_dir_rel.rstrip("/") + "/"
    rels = [p[len(prefix):] for p in out.split("\0") if p and p.startswith(prefix)]
    return rels or None


def _walk_skill_files(skill_dir):
    """Fallback file enumeration for a skill dir outside a git checkout: a filtered walk that skips
    well-known untracked noise so the archive stays deterministic."""
    rels = []
    for dirpath, dirs, names in os.walk(skill_dir):
        dirs[:] = [d for d in dirs if d not in _SKILL_ZIP_SKIP_DIRS]
        for name in names:
            if name in _SKILL_ZIP_SKIP_NAMES or name.endswith(_SKILL_ZIP_SKIP_SUFFIXES):
                continue
            full = os.path.join(dirpath, name)
            rels.append(os.path.relpath(full, skill_dir).replace(os.sep, "/"))
    return rels


def _skill_zip_bytes(members):
    """A deterministic ZIP of `members`: fixed timestamps, permissions, and creator system, plus a
    stable member order, so a rebuild from the same skill files is reproducible across platforms."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for arcname, data in members:
            info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.create_system = 3  # Unix, so the host OS never changes the archive bytes.
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buf.getvalue()


def _zip_logical_members(path):
    """The logical {arcname -> uncompressed bytes} of a committed ZIP, or None when it is missing or
    cannot be read. Comparing logical members (not raw archive bytes) makes the --check drift guard
    immune to zlib/platform differences in the compressed container. A malformed, encrypted, or
    unsupported-compression archive is treated as unreadable (None) so --check flags it as stale and
    write mode repairs it, rather than crashing the build."""
    if not os.path.isfile(path):
        return None
    try:
        with zipfile.ZipFile(path, "r") as archive:
            return {info.filename: archive.read(info.filename) for info in archive.infolist()}
    except (OSError, zipfile.BadZipFile, NotImplementedError, RuntimeError):
        return None


def sync_skill_zips(root, check, skills=None):
    """Generate (or, in check mode, verify) a downloadable ZIP of each Claude-Desktop skill under
    site/dist/skills/. In check mode a stale or missing ZIP is drift (compared by logical contents,
    so compression/platform differences never cause a false failure). In write mode the ZIP is only
    rewritten when its logical contents changed, so an unchanged skill never produces a spurious
    multi-MB diff. An orphaned ZIP (its skill was removed) is flagged/deleted."""
    skills = list(DESKTOP_SKILLS.values()) if skills is None else skills
    dst_dir = os.path.join(root, SITE_OUT, "skills")
    drift = []
    written = []
    for descriptor in skills:
        zip_name = descriptor["zip"].split("/")[-1]
        written.append(zip_name)
        dst = os.path.join(dst_dir, zip_name)
        members = build_skill_zip_members(root, descriptor["skill_dir"], descriptor["skill"])
        expected = {arcname: data for arcname, data in members}
        if check:
            if _zip_logical_members(dst) != expected:
                drift.append(zip_name)
        elif _zip_logical_members(dst) != expected:
            _safe_makedirs(dst_dir)
            with open(dst, "wb") as fh:
                fh.write(_skill_zip_bytes(members))
    drift.extend(_orphans(dst_dir, set(written), check))
    return drift


def main(argv):
    parser = argparse.ArgumentParser(description="Generate static site data.")
    parser.add_argument("--check", action="store_true",
                        help="fail (exit 1) if the committed output is stale instead of writing")
    parser.add_argument("--root", default=REPO_ROOT, help="repository root")
    parser.add_argument("--manifest", default=None, help="path to marketplace.json")
    parser.add_argument("--changelog", default=None, help="path to CHANGELOG.md")
    args = parser.parse_args(argv[1:])

    root = args.root
    manifest_path = args.manifest or os.path.join(root, ".github", "plugin", "marketplace.json")

    if not os.path.isfile(manifest_path):
        raise SystemExit("manifest missing: %s (expected the marketplace manifest; pass --manifest "
                         "or restore it)" % manifest_path)
    with open(manifest_path, "r", encoding="utf-8") as fh:
        try:
            manifest = json.load(fh)
        except json.JSONDecodeError as exc:
            raise SystemExit("invalid JSON in manifest %s: %s" % (manifest_path, exc))

    # Assemble the served stylesheet from its source partials before anything stamps its hash.
    styles_text = build_styles(root)
    styles_path = os.path.join(root, SITE_OUT, "assets", "styles.css")
    if not args.check:
        write_text(styles_path, styles_text)
    static_drift = sync_static_assets(root, args.check)

    suffix = manifest.get("name", "")
    claude_names = claude_plugin_names(root)
    plugins_html = render_plugins(manifest, claude_names)
    changelog_html = render_changelog([])
    for path, filter_plugin in changelog_candidates(root, args.changelog):
        if not os.path.exists(path):
            continue
        releases = parse_changelog(read_text(path), filter_plugin)
        if releases:
            changelog_html = render_changelog(releases)
            break
    version = plugin_version(manifest, CHANGELOG_PLUGIN)
    updater_version = plugin_version(manifest, UPDATER_PLUGIN)

    for src_rel in (HUB_SRC, PLUGIN_SRC, UPDATER_SRC):
        if not os.path.isfile(os.path.join(root, src_rel)):
            raise SystemExit("page source missing: %s (a built page under site/dist/ has no source "
                             "to rebuild from; restore it)" % src_rel.replace(os.sep, "/"))

    hub_out = build_page(root, HUB_SRC, [
        ("block", "plugins", plugins_html),
        ("block", "install", render_install(
            "", suffix, bool(claude_names), "install-hub", marketplace_only=True)),
        ("block", "jsonld", render_jsonld(manifest, claude_names)),
    ])
    plugin_out = build_page(root, PLUGIN_SRC, [
        ("inline", "version", "v" + esc(version)),
        ("block", "install", render_install(
            CHANGELOG_PLUGIN, suffix, CHANGELOG_PLUGIN in claude_names, "install-cmh",
            desktop_zip=_desktop_install_args(CHANGELOG_PLUGIN, "../")[0],
            desktop_skill=_desktop_install_args(CHANGELOG_PLUGIN, "../")[1])),
        ("block", "changelog", changelog_html),
        ("inline", "demo-fullscreen", render_demo_fullscreen_link()),
    ])
    updater_out = build_page(root, UPDATER_SRC, [
        ("inline", "version", "v" + esc(updater_version)),
        ("block", "install", render_install(
            UPDATER_PLUGIN, suffix, UPDATER_PLUGIN in claude_names, "install-updater")),
        ("block", "changelog", render_plugin_changelog(root, UPDATER_PLUGIN)),
    ])
    hub_out_path = os.path.join(root, HUB_OUT)
    plugin_out_path = os.path.join(root, PLUGIN_OUT)
    updater_out_path = os.path.join(root, UPDATER_OUT)

    tutorial_src_page = os.path.join(root, TUTORIAL_PAGE_SRC)
    tutorial_out_path = os.path.join(root, TUTORIAL_PAGE)
    tutorial_md_path = os.path.join(root, TUTORIAL_SRC)
    tutorial_out = None
    # A built tutorial page whose source was removed is an ORPHAN: --check must flag it and a
    # normal build must delete it, so a stranded artifact can never silently linger.
    tutorial_orphaned = (not os.path.isfile(tutorial_src_page)
                         and os.path.isfile(tutorial_out_path))
    if os.path.isfile(tutorial_src_page):
        if not os.path.isfile(tutorial_md_path):
            raise SystemExit(
                "tutorial markdown missing: %s (restore it, or remove the tutorial source page it feeds)"
                % tutorial_md_path)
        tutorial_out = build_page(root, TUTORIAL_PAGE_SRC, [
            ("block", "tutorial",
             render_markdown(site_tutorial_markdown(read_text(tutorial_md_path)))),
        ])

    demo_drift = sync_demos(root, args.check)
    tutorial_img_drift = sync_tutorial_images(root, args.check)
    skill_zip_drift = sync_skill_zips(root, args.check)
    sitemap_drift = write_or_check(
        os.path.join(root, SITE_OUT, "sitemap.xml"), render_sitemap(root), args.check)
    llms_drift = write_or_check(
        os.path.join(root, SITE_OUT, "llms.txt"), render_llms(root, manifest, claude_names), args.check)

    if args.check:
        problems = []
        if static_drift:
            problems.append("static site assets differ from site/src/: " + ", ".join(static_drift))
        if styles_text != _read_artifact(styles_path):
            problems.append("site/dist/assets/styles.css is stale vs site/css/ partials")
        if hub_out != _read_artifact(hub_out_path):
            problems.append("site/dist/index.html is stale vs its site/pages/index.html source "
                            "(do not hand-edit the built page; edit the source and rebuild)")
        if plugin_out != _read_artifact(plugin_out_path):
            problems.append("site/dist/commentable-html/index.html is stale vs its "
                            "site/pages/commentable-html/index.html source "
                            "(do not hand-edit the built page; edit the source and rebuild)")
        if updater_out != _read_artifact(updater_out_path):
            problems.append("site/dist/%s/index.html is stale vs its "
                            "site/pages/%s/index.html source "
                            "(do not hand-edit the built page; edit the source and rebuild)"
                            % (UPDATER_PLUGIN, UPDATER_PLUGIN))
        if tutorial_out is not None and tutorial_out != _read_artifact(tutorial_out_path):
            problems.append("site/dist/commentable-html/tutorial/index.html is stale vs its "
                            "site/pages/commentable-html/tutorial/index.html source and "
                            "TUTORIAL.md (do not hand-edit the built page; edit the source and rebuild)")
        if tutorial_orphaned:
            problems.append("site/dist/commentable-html/tutorial/index.html is orphaned: its "
                            "site/pages source was removed but the built page lingers; "
                            "run build_site_data.py to remove it")
        if demo_drift:
            problems.append("demo reports differ from source: " + ", ".join(demo_drift))
        if tutorial_img_drift:
            problems.append("tutorial images differ from source: " + ", ".join(tutorial_img_drift))
        if skill_zip_drift:
            problems.append("Claude Desktop skill ZIP is stale or missing: "
                            + ", ".join(skill_zip_drift))
        if sitemap_drift:
            problems.append("site/dist/sitemap.xml is stale")
        if llms_drift:
            problems.append("site/dist/llms.txt is stale")
        if problems:
            for problem in problems:
                sys.stderr.write("drift: %s\n" % problem)
            sys.stderr.write("fix: run python scripts/build_site_data.py and commit\n")
            return 1
        print("site data up to date")
        return 0

    write_text(hub_out_path, hub_out)
    write_text(plugin_out_path, plugin_out)
    write_text(updater_out_path, updater_out)
    if tutorial_out is not None:
        write_text(tutorial_out_path, tutorial_out)
    elif tutorial_orphaned:
        try:
            os.remove(tutorial_out_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            sys.stderr.write("warning: could not remove orphaned tutorial page %s (%s); "
                             "delete it manually\n" % (tutorial_out_path, exc))
    print("site data generated (plugins, jsonld, version v%s, changelog, demos, tutorial, sitemap, llms)" % version)
    return 0
