"""Unit tests for scripts/build_site_data.py.

Run by the validate CI job via `python -m unittest discover -s scripts -p "test_*.py"`,
so the site generator's escaping, URL allowlist, and changelog parsing are covered by a
required status check.
"""
import json
import os
import re
import tempfile
import unittest
from unittest import mock

import build_site_data as bsd

__all__ = [name for name in globals() if name != "__all__" and not name.startswith("__")]
