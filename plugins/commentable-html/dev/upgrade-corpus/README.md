# Upgrade anti-regression corpus

Each `v<version>.html` here is a fully layered commentable-html document (a Portable snapshot)
produced by that version of the skill and then FROZEN. It is never regenerated: it represents what
that past version shipped.

`tests/test_upgrade_corpus.py` upgrades every snapshot with the CURRENT
`tools/authoring/upgrade.py` (swapping in the current layer regions) and asserts the result:

- validates strict-clean (no errors and no warnings), and
- is idempotent (upgrading the upgraded document again changes nothing).

This guards backward compatibility: a layer or tool change that breaks upgrading a document produced
by an older version fails the gate.

## Adding a snapshot

Add one per change only when the change actually warrants it (a layer-region change, a new
region, or anything that could break upgrading an older document). The agent decides per change.
To mint a snapshot for the current version, generate a small Portable report/plan with the current
tools and finalize it strict-clean, then save it here as `v<version>.html`. Do not hand-edit or
rebuild an existing snapshot: it is a frozen record of a past release.
