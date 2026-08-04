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
#
# `base-uri` and `frame-ancestors` are deliberately NOT here even though the export stamps them: a
# meta-delivered policy does not bind a `<base>` the parser already resolved (see the `<base>` pass
# in 68-export-offline.js, which neutralizes it for exactly that reason) and `frame-ancestors` is
# ignored in a meta policy outright. Asserting them would let the threat model claim an enforcement
# the browser does not actually provide - the overclaim this suite exists to prevent.
ENFORCING_DIRECTIVES = (
    "default-src 'none'",
    "connect-src 'none'",
    "frame-src 'none'",
    "object-src 'none'",
    "img-src data:",
    "font-src data:",
    "form-action 'none'",
)

# Channels no stamped directive governs, where the parser-level strip is the ONLY enforcement. A gap
# in these is a real egress bug, so the threat model must keep naming them as in-scope rather than
# folding them into the "the CSP already blocks it" dismissal.
STRIP_ENFORCED_CHANNELS = ("preconnect", "dns-prefetch", "prefetch", "prerender", "base")


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

    def test_the_threat_model_names_both_non_csp_coverable_residuals(self):
        """CMH-SEC-06: navigation and WebRTC are the acknowledged non-CSP-coverable residuals."""
        row = _sec_06_row()
        self.assertIn("CMH-OFFLINE-05", row)
        self.assertIn("navigation", row.lower())
        # A review panel disproved the original "navigation is the ONE residual" wording by showing
        # RTCPeerConnection ICE/STUN egresses under this exact policy. Keep both residuals named, so
        # the row cannot drift back to a claim that is not true.
        self.assertIn("WEBRTC", row.upper())
        self.assertIn("not a sanitizer", row)

    def test_an_inaccurate_enforcement_claim_is_never_dismissible_by_citing_this_row(self):
        """CMH-SEC-06: disproving a claim in the row is always in scope, never dismissible by it."""
        row = _sec_06_row()
        self.assertIn("EVIDENCE THAT AN ENFORCEMENT CLAIM IN THIS ROW IS INACCURATE", row)
        self.assertIn("never dismissed by citing this row", row)

    def test_strip_enforced_channels_are_named_and_really_are_strip_enforced(self):
        """CMH-SEC-06: channels no CSP directive covers stay in scope, and the strip still drops them."""
        row = _sec_06_row()
        self.assertIn("STRIP-ENFORCED", row)
        self.assertIn("never be dismissed by citing this row", row)
        for channel in STRIP_ENFORCED_CHANNELS:
            self.assertIn(
                channel, row,
                "CMH-SEC-06 must name '" + channel + "' as strip-enforced: no stamped CSP directive"
                " governs it, so a strip gap there is a real egress bug, not a dismissible spelling.",
            )
        # The claim is only true while the strip actually removes them, so pin that too - otherwise
        # the row would document an enforcement that had silently gone away.
        src = _read(EXPORT_OFFLINE)
        for rel in ("preconnect", "dns-prefetch", "prefetch", "prerender"):
            self.assertIn(
                '"' + rel + '"', src,
                "the offline link[href] pass no longer removes rel=" + rel + ", so the"
                " strip-enforced claim in CMH-SEC-06 is no longer true",
            )


if __name__ == "__main__":
    unittest.main()
