# Per-component size budget: the gate that stops the shipped payload drifting back up.
#
# The runtime grew 3.5x across the versions #1250 sampled (345 KB to 1191 KB) with nothing to
# notice it, because no single commit looked expensive. Every generated document, every offline
# export and the asset registry carry these components verbatim, so a kilobyte added here is a
# kilobyte added to every artifact a reviewer is ever sent.
#
# tools/size-budget.json names a byte ceiling per generated component. The builder checks it on
# every build AND on every `--check`, so the required `dist-in-sync` job fails a PR that blows a
# budget. Raising a ceiling is a deliberate, reviewed edit to that file - which is the point: the
# growth becomes a decision instead of a drift.
#
# Two limits, stated so a reader does not over-trust it. It is a CEILING, not a ratchet: growth
# under the headroom is invisible and a shrink does not tighten it automatically, because a true
# ratchet would make every unrelated feature PR edit this file. And it budgets the shipped LAYER
# components, which a document embeds verbatim, not the documents themselves - the 1.3 MB vendored
# diagram payload and a document's own generated DOM are workstreams A and D of #1250 and have no
# ceiling here.

BUDGET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "size-budget.json")


def read_size_budget(path=None):
    """Return {relative path: max bytes}. A missing or malformed budget is a build failure, not a
    silent skip - a gate that can disappear by deleting its own data file is not a gate."""
    path = BUDGET_FILE if path is None else path
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise SystemExit("build: cannot read the size budget at %s (%s)" % (path, exc))
    components = data.get("components") if isinstance(data, dict) else None
    if not isinstance(components, dict) or not components:
        raise SystemExit("build: %s has no non-empty `components` object" % path)
    budget = {}
    for name, limit in components.items():
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise SystemExit("build: size budget for %r must be a positive integer, got %r"
                             % (name, limit))
        budget[name.replace("/", os.sep)] = limit
    return budget


def size_budget_check(outputs, out_dir, budget=None):
    """Measure every budgeted component against its ceiling.

    Returns (report_lines, failures). A budgeted component that the build does not produce is a
    FAILURE, not a pass: a renamed or dropped output would otherwise retire its own budget.
    """
    budget = read_size_budget() if budget is None else budget
    sizes = {os.path.relpath(path, out_dir): len(text.encode("utf-8"))
             for path, text in outputs.items()}
    lines, failures = [], []
    for name in sorted(budget):
        limit = budget[name]
        if name not in sizes:
            failures.append("%s is budgeted but the build produced no such file "
                            "(update tools/size-budget.json)" % name.replace(os.sep, "/"))
            continue
        actual = sizes[name]
        lines.append("  %-34s %8d / %8d bytes (%3.0f%% of budget)"
                     % (name.replace(os.sep, "/"), actual, limit, 100.0 * actual / limit))
        if actual > limit:
            failures.append(
                "%s is %d bytes, over its %d byte budget by %d. Shrink it, or raise the ceiling "
                "in tools/size-budget.json deliberately and say why in the changelog."
                % (name.replace(os.sep, "/"), actual, limit, actual - limit))
    return lines, failures
