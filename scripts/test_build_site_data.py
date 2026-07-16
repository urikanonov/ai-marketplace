#!/usr/bin/env python3
"""Compatibility imports for the split site generator unit suite.

The focused ``test_build_site_data_<topic>.py`` modules are auto-discovered by
the broad ``test_*.py`` command. Import them here as well so the historical
exact command ``-p "test_build_site_data.py"`` continues to run the suite.
"""

from test_build_site_data_core import *  # noqa: F401,F403
from test_build_site_data_drift import *  # noqa: F401,F403
from test_build_site_data_render import *  # noqa: F401,F403
from test_build_site_data_sync import *  # noqa: F401,F403


if __name__ == "__main__":
    import unittest

    unittest.main(module=None)
