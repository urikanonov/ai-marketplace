#!/usr/bin/env python3
"""Thin facade for the split site-data generator topic modules."""
import os as _os

_PARTS_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "build_site_data_parts")
for _name in sorted(_os.listdir(_PARTS_DIR)):
    if _name.endswith(".py"):
        _path = _os.path.join(_PARTS_DIR, _name)
        with open(_path, "r", encoding="utf-8", newline="") as _fh:
            exec(compile(_fh.read(), _path, "exec"), globals(), globals())

del _name, _path, _fh, _os, _PARTS_DIR

if __name__ == "__main__":
    sys.exit(main(sys.argv))
