#!/usr/bin/env python3
"""Regression tests for kusto_link.py (the Run in Azure Data Explorer deep-link builder)."""
import base64
import contextlib
import gzip
import io
import os
import runpy
import subprocess
import sys
import unittest
from urllib.parse import urlsplit, unquote
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
import _paths  # noqa: E402  shared pkg/dev split path constants
TOOLS = _paths.TOOLS
sys.path.insert(0, TOOLS)
import kusto_link  # noqa: E402

KUSTO_PY = os.path.join(TOOLS, "kusto", "kusto_link.py")

QUERY = "DetectionReports\n| where IsTestOrg == false\n| summarize dcount(DetectionId)"
# A query loaded with URL-reserved and non-ASCII characters, to prove they survive
# the gzip -> base64 -> percent-encode -> decode roundtrip untouched.
QUERY_HARD = 'T | where Name == "a&b?c#d %e+f/=g" and Msg == "\u65e5\u672c\u8a9e \U0001f680"'

# A frozen known-good link. If the encoding scheme drifts (mtime unpinned, safe=
# changed, zlib swapped in), this fails even though the self-consistent roundtrip
# would still pass. Generated once from the helper itself.
GOLDEN = ("https://dataexplorer.azure.com/clusters/help.kusto.windows.net/databases/Samples?query="
          "H4sIAAAAAAAC%2F3NJLUlNLsnMzwtKLcgvKinmqlEoz0gtSlXwLA5JLS7xL0pXsLVVSEvMKU4FShWX5uYmFmVWpSqk"
          "JOeX5pVouMC0e6ZoAgCrjgbiSwAAAA%3D%3D")


class _BinaryStdin:
    def __init__(self, text):
        self.buffer = io.BytesIO(text.encode("utf-8"))


def _decode_query_param(url):
    """Reverse the encoding once: read ?query=, percent-decode, base64-decode, gunzip.

    Uses unquote (not unquote_plus / parse_qs) so a decoded '+' stays '+' and the
    payload is decoded exactly once - a double decode could mask a double-encode bug.
    """
    param = urlsplit(url).query.split("query=", 1)[1]
    return gzip.decompress(base64.b64decode(unquote(param))).decode("utf-8")


class KustoLinkTests(unittest.TestCase):
    def test_roundtrip_recovers_query(self):
        url = kusto_link.kusto_link("help.kusto.windows.net", "Samples", QUERY)
        self.assertEqual(_decode_query_param(url), QUERY)

    def test_golden_link_is_stable(self):
        # Pins the exact URL contract so an encoding regression cannot ship silently.
        self.assertEqual(kusto_link.kusto_link("help.kusto.windows.net", "Samples", QUERY), GOLDEN)

    def test_url_special_and_unicode_query_roundtrips(self):
        url = kusto_link.kusto_link("c.kusto.windows.net", "db", QUERY_HARD)
        self.assertEqual(_decode_query_param(url), QUERY_HARD)
        # None of the reserved characters leak into the raw query param.
        param = urlsplit(url).query.split("query=", 1)[1]
        for ch in "&?#+/= ":
            self.assertNotIn(ch, param)

    def test_url_shape(self):
        url = kusto_link.kusto_link("help.kusto.windows.net", "Samples", QUERY)
        self.assertTrue(url.startswith(
            "https://dataexplorer.azure.com/clusters/help.kusto.windows.net/databases/Samples?query="))

    def test_gzip_magic_and_deterministic(self):
        # mtime is pinned, so the same query yields byte-identical links.
        a = kusto_link.kusto_link("c.kusto.windows.net", "db", QUERY)
        b = kusto_link.kusto_link("c.kusto.windows.net", "db", QUERY)
        self.assertEqual(a, b)
        param = urlsplit(a).query.split("query=", 1)[1]
        self.assertEqual(base64.b64decode(unquote(param))[:3], b"\x1f\x8b\x08")

    def test_cluster_scheme_and_slash_stripped(self):
        for raw in ("https://c.kusto.windows.net", "c.kusto.windows.net/", "HTTPS://c.kusto.windows.net"):
            self.assertEqual(kusto_link.normalize_cluster(raw), "c.kusto.windows.net")

    def test_cluster_full_url_with_path_keeps_host(self):
        self.assertEqual(
            kusto_link.normalize_cluster("https://c.kusto.windows.net/databases/x"), "c.kusto.windows.net")
        self.assertEqual(kusto_link.normalize_cluster("c.kusto.windows.net:443"), "c.kusto.windows.net:443")

    def test_bare_cluster_with_path_is_rejected(self):
        # A bare host (no scheme) that carries a path segment is almost certainly a
        # typo; silently truncating it would target a different cluster than intended.
        for bad in ("c.kusto.windows.net/some/path", "c.kusto.windows.net/databases/x"):
            with self.assertRaises(ValueError):
                kusto_link.normalize_cluster(bad)
        # A full URL with a path is still fine - netloc extraction there is intentional.
        self.assertEqual(
            kusto_link.normalize_cluster("https://c.kusto.windows.net/some/path"), "c.kusto.windows.net")

    def test_hostile_cluster_is_rejected(self):
        # A cluster with quotes / URL-structural characters would break the href it
        # is embedded in, so it must raise rather than emit a corrupt link.
        for bad in ('"evil.com"&x=1', 'evil" onmouseover="alert(1)', 'a b',
                    'ho#st', 'host?q=1', 'javascript:alert(1)', '',
                    'c.kusto.windows.net:99999', 'c.kusto.windows.net:0'):
            with self.assertRaises(ValueError):
                kusto_link.normalize_cluster(bad)
            with self.assertRaises(ValueError):
                kusto_link.kusto_link(bad, "db", QUERY)

    def test_full_url_cluster_is_normalized(self):
        url = kusto_link.kusto_link("https://c.kusto.windows.net/", "db", QUERY)
        self.assertIn("/clusters/c.kusto.windows.net/databases/db?query=", url)

    def test_database_with_space_is_encoded(self):
        url = kusto_link.kusto_link("c.kusto.windows.net", "Sample DB", QUERY)
        self.assertIn("/databases/Sample%20DB?query=", url)

    def test_payload_is_percent_encoded(self):
        # A raw '+' or '/' from base64 must not appear unencoded in the query param.
        url = kusto_link.kusto_link("c.kusto.windows.net", "db", QUERY * 5)
        param = urlsplit(url).query.split("query=", 1)[1]
        self.assertNotIn("+", param)
        self.assertNotIn("/", param)

    def test_empty_inputs_rejected(self):
        for args in (("", "db", QUERY), ("c", "", QUERY), ("c", "db", "  "),
                     ("   ", "db", QUERY), ("c.kusto.windows.net", "   ", QUERY)):
            with self.assertRaises(ValueError):
                kusto_link.kusto_link(*args)

    def test_cli_stdin(self):
        r = subprocess.run([sys.executable, KUSTO_PY, "c.kusto.windows.net", "db"],
                           input=QUERY, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(_decode_query_param(r.stdout.strip()), QUERY)

    def test_cli_stdin_trailing_newline_matches_arg_form(self):
        # A piped .kql file ends in a newline; the CLI must strip it so the piped and
        # argument forms of the same query produce the identical link (determinism).
        arg = subprocess.run([sys.executable, KUSTO_PY, "c.kusto.windows.net", "db", QUERY],
                             capture_output=True, text=True, encoding="utf-8")
        piped = subprocess.run([sys.executable, KUSTO_PY, "c.kusto.windows.net", "db"],
                               input=QUERY + "\n", capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(arg.stdout.strip(), piped.stdout.strip())

    def test_cli_stdin_unicode(self):
        r = subprocess.run([sys.executable, KUSTO_PY, "c.kusto.windows.net", "db"],
                           input=QUERY_HARD, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(_decode_query_param(r.stdout.strip()), QUERY_HARD)

    def test_cli_arg_query(self):
        r = subprocess.run([sys.executable, KUSTO_PY, "c.kusto.windows.net", "db", QUERY],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(_decode_query_param(r.stdout.strip()), QUERY)

    def test_cli_too_many_args_rejected(self):
        # An unquoted multi-word query would split across argv; reject it loudly
        # instead of silently encoding only the first token.
        r = subprocess.run([sys.executable, KUSTO_PY, "c.kusto.windows.net", "db", "SELECT", "extra"],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage:", r.stderr)

    def test_cli_usage_without_args(self):
        r = subprocess.run([sys.executable, KUSTO_PY], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage:", r.stderr)

    def test_main_usage_for_wrong_arg_count(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = kusto_link.main(["kusto_link.py"])
        self.assertEqual(code, 2)
        self.assertIn("usage:", err.getvalue())

    def test_main_arg_query_prints_url(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = kusto_link.main(["kusto_link.py", "c.kusto.windows.net", "db", QUERY])
        self.assertEqual(code, 0)
        self.assertEqual(_decode_query_param(out.getvalue().strip()), QUERY)

    def test_main_stdin_query_decodes_utf8_and_strips_trailing_newline(self):
        out = io.StringIO()
        with mock.patch.object(sys, "stdin", _BinaryStdin(QUERY_HARD + "\n")), contextlib.redirect_stdout(out):
            code = kusto_link.main(["kusto_link.py", "c.kusto.windows.net", "db"])
        self.assertEqual(code, 0)
        self.assertEqual(_decode_query_param(out.getvalue().strip()), QUERY_HARD)

    def test_main_invalid_input_reports_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = kusto_link.main(["kusto_link.py", "bad cluster", "db", QUERY])
        self.assertEqual(code, 2)
        self.assertIn("invalid cluster host", err.getvalue())

    def test_main_warns_when_url_exceeds_limit(self):
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(kusto_link, "_URL_WARN_LEN", 10), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = kusto_link.main(["kusto_link.py", "c.kusto.windows.net", "db", QUERY])
        self.assertEqual(code, 0)
        self.assertIn("generated URL is", err.getvalue())
        self.assertEqual(_decode_query_param(out.getvalue().strip()), QUERY)

    def test_module_entrypoint_uses_sys_argv(self):
        err = io.StringIO()
        with mock.patch.object(sys, "argv", [KUSTO_PY]), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                runpy.run_path(KUSTO_PY, run_name="__main__")
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("usage:", err.getvalue())


if __name__ == "__main__":
    unittest.main()
