"""The offline threat model (CMH-SEC-06) is DECLARED, and pinned to the code it relies on.

The point of this suite is to stop a documented non-goal from being rediscovered as a defect. The
spec row is only load-bearing if the CSP it names is really the one the exporter stamps, so the
directives are read out of the runtime source rather than restated here.
"""
import os
import re
import unittest

import _paths

EXPORT_OFFLINE = os.path.join(_paths.ASSETS, "js", "68-export-offline.js")
SEC_SPEC = os.path.join(_paths.DEV, "spec", "50-security.md")

# The directives the threat model leans on. Each one is what makes a whole class of "a new way to
# spell a subresource URL" unreachable, so weakening any of them must fail this suite rather than
# quietly reopen the class.
ENFORCING_DIRECTIVES = (
    "default-src 'none'",
    "connect-src 'none'",
    "frame-src 'none'",
    "object-src 'none'",
    "img-src data:",
    "font-src data:",
    "base-uri 'none'",
    "form-action 'none'",
)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _exported_csp():
    """The CSP string `_ensureOfflineCsp` stamps into every offline export."""
    src = _read(EXPORT_OFFLINE)
    m = re.search(
        r'setAttribute\(\s*"content"\s*,\s*"(default-src[^"]*)"\s*\)',
        src,
    )
    assert m, "could not find the offline CSP literal in 68-export-offline.js"
    return m.group(1)


def _sec_06_row():
    for line in _read(SEC_SPEC).splitlines():
        if line.startswith("| CMH-SEC-06 |"):
            return line
    return ""


class OfflineThreatModelTests(unittest.TestCase):
    def test_the_offline_csp_still_enforces_every_directive_the_threat_model_names(self):
        """CMH-SEC-06: the declared enforcement boundary is the CSP the exporter really stamps."""
        csp = _exported_csp()
        for directive in ENFORCING_DIRECTIVES:
            self.assertIn(
                directive,
                csp,
                "CMH-SEC-06 declares fetch egress enforced by the CSP, but the exporter no longer"
                " stamps " + directive + ". Either restore it or re-open the issue class the"
                " threat model closed - do not leave the spec claiming an enforcement that is gone.",
            )

    def test_the_spec_declares_the_offline_threat_model_and_its_non_goals(self):
        """CMH-SEC-06: the offline threat model and its three non-goals are written down."""
        row = _sec_06_row()
        self.assertTrue(row, "CMH-SEC-06 has no row in dev/spec/50-security.md")
        lowered = row.lower()
        for phrase in (
            "enforcement boundary",
            "not a vulnerability",
            "commentable-html layer",
            "trusted author is not a threat actor",
            "best-effort",
        ):
            self.assertIn(
                phrase,
                lowered,
                "CMH-SEC-06 must state the non-goal wording '" + phrase + "' so a reviewer can"
                " cite it when dismissing a finding.",
            )

    def test_the_threat_model_names_scripted_navigation_as_the_one_residual(self):
        """CMH-SEC-06: top-level scripted navigation stays the single acknowledged residual."""
        row = _sec_06_row()
        self.assertIn("CMH-OFFLINE-05", row)
        self.assertIn("navigation", row.lower())


if __name__ == "__main__":
    unittest.main()
