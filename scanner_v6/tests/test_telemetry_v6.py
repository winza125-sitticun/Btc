import os
import sys
import unittest
from unittest import mock

TESTS_DIR = os.path.dirname(__file__)
sys.path.insert(0, TESTS_DIR)

from test_rez_scanner_integration import RezScannerGateTests


class TelemetryV6Tests(unittest.TestCase):
    def test_completed_cycle_logs_full_funnel_counts(self):
        harness = RezScannerGateTests(methodName="test_rez_pass_score_75_or_more_reaches_astra")
        harness.setUp()
        rez = harness._rez(
            "PASS",
            trigger="RETEST",
            reason="PULLBACK_RETEST_CONFIRMED",
        )

        with mock.patch("builtins.print") as printed:
            harness._run_cycle(rez_enabled=True, rez_result=rez, score_value=80)

        rendered = "\n".join(
            " ".join(str(value) for value in call.args)
            for call in printed.call_args_list
        )
        self.assertIn(
            "[*] TELEMETRY: universe=1 tv_ready=1 aligned=1 filters_passed=1 "
            "structure_passed=1 rez_entered=1 rez_pass=1 rez_wait=0 rez_reject=0 "
            "score_ge_75=1 astra_called=1 alerts_sent=1",
            rendered,
        )


if __name__ == "__main__":
    unittest.main()
