"""Thin facade for the split commentable-html layer validation checks."""
from pathlib import Path

_PARTS_DIR = Path(__file__).with_name("layer_parts")

for _part in sorted(_PARTS_DIR.glob("*.py")):
    exec(compile(_part.read_text(encoding="utf-8"), str(_part), "exec"), globals())

del _part
