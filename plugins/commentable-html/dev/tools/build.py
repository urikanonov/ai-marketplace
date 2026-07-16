#!/usr/bin/env python3
"""Thin facade for the split commentable-html layer build tool."""
from pathlib import Path

_PARTS_DIR = Path(__file__).with_name("build_parts")

for _part in sorted(_PARTS_DIR.glob("*.py")):
    exec(compile(_part.read_text(encoding="utf-8"), str(_part), "exec"), globals())

del _part

if __name__ == "__main__":
    sys.exit(main(sys.argv))
