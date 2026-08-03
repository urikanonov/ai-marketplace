# Repository guard scripts feature specification

The scripts under `scripts/` are the repository's own gates: the validators, drift checks, and
tracked-file guards that the required `validate` and `cross-platform` CI jobs run, plus the
`.githooks/pre-commit` and `.githooks/pre-push` hooks. They ship to nobody - they exist to stop a
bad change reaching `main` - but they are still behavior, so the spec-and-test discipline in
`AGENTS.md` applies to them: a change here needs a feature-id row naming a covering test.

This spec is seeded with `scripts/check_forbidden_files.py`, the tracked-file guard. Other guard
scripts are covered by their own `scripts/test_*.py` suites and join this table as they are
changed. Every row's test runs under `python scripts/run_script_tests.py` (the required `validate`
and `cross-platform` jobs, and the opt-in `PREPUSH_TESTS=1` hook path).

The rows below are self-enforcing: `SpecCoverageTest` in `scripts/test_check_forbidden_files.py`
fails if a row names no covering test, names one that does not exist, repeats a feature id, or
cites a suite it cannot resolve. That is local rather than an entry in the `SPEC_TARGETS` registry
of `scripts/check_spec_test_refs.py` for a structural reason, not a coverage one: that checker
locates a target's tests as `<spec dir>/tests` or `<base>/tests` and builds its reverse corpus from
`*.spec.*` / `*.test.*` files, neither of which fits a flat Python suite living beside the scripts
it covers, so registering this spec today would fail closed with "no tests directory found".
Teaching the checker that shape is tracked separately; until then the rows are held to the same
standard here, and a row that reaches outside this suite fails rather than going unchecked.

Coverage notation: each row names the covering test class and method in
`scripts/test_check_forbidden_files.py`.

| Feature id | Behavior | Covering test |
| --- | --- | --- |
| REPO-GUARD-01 | A secret-bearing file (`.env` and its variants, `.envrc`, `.netrc`, `.npmrc`, a private key, a keystore, a credentials or service-account JSON) is refused anywhere in the tree, case-insensitively, while a shareable `.example` / `.sample` / `.template` / `.dist` variant is allowed. This is the enforceable stand-in for a push rule, which GitHub does not offer on a public user-owned repo. | `IsForbiddenTest.test_flags_secret_bearing_files`, `IsForbiddenTest.test_allows_safe_files` |
| REPO-GUARD-02 | A scratch `*.diff` / `*.patch` dump is refused anywhere in the tree, not just at the root: an agent's working directory is usually a subdirectory, which is how a 180KB unreferenced `changes.diff` (and `diff_local.patch` before it) came to be tracked. Real sources whose names merely contain "diff" are untouched. | `IsScratchArtifactTest.test_flags_scratch_dumps_anywhere_in_the_tree`, `IsScratchArtifactTest.test_leaves_real_files_alone`, `IsScratchArtifactTest.test_the_repo_tracks_no_scratch_dumps` |
| REPO-GUARD-03 | The repository ROOT is guarded by an ALLOWLIST rather than a list of scratch shapes: a tracked file at the root whose name is not one of the documented top-level files is refused, whatever it is called. Names are compared exactly (a lowercase `readme.md` is a different file on Linux), a leading `./` is stripped, and a literal backslash stays part of the name so a root file cannot pose as a nested one. `ROOT_ALLOWED` is the escape hatch for a genuine new top-level file. | `RootScratchTest.test_flags_probes_at_the_repo_root`, `RootScratchTest.test_leaves_legitimate_files_alone`, `RootScratchTest.test_keeps_the_real_top_level_files`, `RootScratchTest.test_the_allowlist_is_the_escape_hatch`, `RootScratchTest.test_the_allowlist_is_case_exact`, `RootScratchTest.test_a_backslash_in_a_root_name_does_not_pose_as_a_subdirectory`, `RootScratchTest.test_every_tracked_root_file_is_allowed` |
| REPO-GUARD-04 | The top-level DIRECTORIES are allowlisted too, so a dump cannot dodge the root rule by being parked one level down: `captures/out.txt` and `_scratch/probe.html` have a slash, so a file-only rule waves them through on a plain `git add -A`. Anything under an approved directory is untouched. `tmp/` is pointedly NOT an approved directory - it is where this guard tells you to write scratch, so only its `.gitkeep` marker may be tracked - and both allowlists are checked against the tree so a stale name cannot quietly widen the closed set. | `RootDirectoryTest.test_flags_a_dump_parked_in_a_new_top_level_directory`, `RootDirectoryTest.test_allows_anything_under_an_approved_directory`, `RootDirectoryTest.test_tmp_admits_only_its_marker_file`, `RootDirectoryTest.test_every_tracked_directory_is_allowed`, `RootDirectoryTest.test_the_directory_allowlists_do_not_rot` |
| REPO-GUARD-05 | The scan is anchored to the repository this script lives in, not the ambient cwd: run from a subdirectory `git ls-files` would strip the directory from every path and make it look root-level, and run from the throwaway sandbox the script suite uses it would find no repository and scan nothing. | `TrackedFilesTest.test_paths_are_repo_root_relative_from_any_cwd`, `TrackedFilesTest.test_survives_being_run_from_an_unrelated_directory` |
| REPO-GUARD-06 | A non-ASCII path survives both hops that would otherwise corrupt it, each of which is a silent allowlist miss: `-z` changes only the delimiter, so `core.quotePath=false` is what stops git C-quoting the name, and an explicit UTF-8 decode is what stops Python reading git's path bytes with the locale codec (cp1252 on Windows). | `TrackedFilesEncodingTest.test_a_non_ascii_name_is_reported_literally` |
| REPO-GUARD-07 | The guard EXITS non-zero and names the offender, rather than merely classifying it. That is the behavior the required `validate` job and the pre-commit hook depend on, and it is what the classifier unit tests above cannot observe. An offender is named once even when git reports it several times (an unmerged path is listed once per stage), and a name that is not valid UTF-8 is rendered so it can always be printed - a `UnicodeEncodeError` on a narrow console would replace the refusal with a traceback at the one moment the message matters most. | `GuardExitStatusTest.test_a_root_scratch_dump_fails_the_guard`, `GuardExitStatusTest.test_a_dump_in_an_unapproved_directory_fails_the_guard`, `GuardExitStatusTest.test_an_offender_is_named_once`, `GuardExitStatusTest.test_a_clean_tree_passes`, `DisplayPathTest.test_a_surrogate_bearing_name_survives_a_narrow_console`, `DisplayPathTest.test_an_ordinary_name_is_unchanged` |
| REPO-GUARD-08 | Every row in this spec names at least one covering test that really exists in the suite, no feature id is declared twice, and a row that cites a suite this check cannot resolve fails rather than going unverified. | `SpecCoverageTest.test_every_named_test_exists`, `SpecCoverageTest.test_every_feature_id_is_declared_once` |

## Coverage gaps

None for the rows above. This spec deliberately does not yet enumerate every script under
`scripts/`; those behaviors are covered by their own `scripts/test_*.py` suites and are added here
as each is changed, rather than backfilled in one sweep.
