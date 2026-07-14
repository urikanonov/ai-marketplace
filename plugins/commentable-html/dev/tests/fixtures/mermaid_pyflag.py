#!/usr/bin/env python3
"""Emit, per corpus source, whether the SHIPPED mermaid checker flags it.

Used by build_mermaid_corpus.mjs to compute each entry's `py_flag` from the real
checker, so the corpus auto-detects a false positive (a source the checker flags
but the real mermaid parser accepts) instead of relying on hand-authored flags.

Reads a JSON array of {"name","src"} from argv[1]; prints one `name<TAB>0|1` line
per entry (1 = the checker flags it). Standard library only.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.normpath(os.path.join(HERE, "..", "..", "..", "pkg", "skills", "commentable-html"))
sys.path.insert(0, os.path.join(PKG, "tools", "validate"))

from cmhval.mermaid import check_mermaid_source  # noqa: E402


def main(argv):
    with open(argv[1], "r", encoding="utf-8") as fh:
        cases = json.load(fh)
    out = []
    for c in cases:
        flagged = bool(check_mermaid_source(c.get("src", "")))
        out.append("%s\t%s" % (c["name"], "1" if flagged else "0"))
    sys.stdout.write("\n".join(out) + ("\n" if out else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
