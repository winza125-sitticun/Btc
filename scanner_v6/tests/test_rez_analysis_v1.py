import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rez_analysis_v1 import analyze_rez_candidate


class RezAnalysisTests(unittest.TestCase):
    def test_missing_history_fails_closed(self):
        result = analyze_rez_candidate(
            side="LONG",
            candles_1h=[],
            candles_15m=[],
            atr_period=14,
            atr_buffer_mult=0.25,
            swing_window=2,
            analysis_version="REZ_V1",
        )
        self.assertEqual(result.structure_1h, "UNKNOWN")
        self.assertEqual(result.state, "REJECT")


if __name__ == "__main__":
    unittest.main()
