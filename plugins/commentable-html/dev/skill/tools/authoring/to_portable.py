#!/usr/bin/env python3
"""DEPRECATED alias for tools/authoring/to_shareable.py.

The "Portable" concept was renamed to "Shareable"; this thin shim keeps every existing script,
recipe, and doc that invokes `tools/authoring/to_portable.py` working unchanged. It forwards argv
verbatim and re-exports the module API (`to_shareable`, `is_nonshareable`, and the legacy
`is_nonportable` spelling) so an `import to_portable` also keeps working.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # tools/ root
import _toolpath  # noqa: E402
_toolpath.ensure()

import to_shareable  # noqa: E402
from to_shareable import (  # noqa: E402,F401
    COMPANIONS, DROPPED_COMPANION, is_nonportable, is_nonshareable, read_layer, to_shareable as to_portable,
)

_DEPRECATION = ("to_portable.py is DEPRECATED and will keep working as a thin alias: use "
                "tools/authoring/to_shareable.py instead (Portable was renamed to Shareable).\n")


def main(argv):
    sys.stderr.write(_DEPRECATION)
    return to_shareable.main([argv[0]] + list(argv[1:]))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
