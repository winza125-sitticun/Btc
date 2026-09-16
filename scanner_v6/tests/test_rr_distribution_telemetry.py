import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import auto_scanner_v6 as scanner


class RrDistributionTelemetryTests(unittest.TestCase):
    def test_rr_distribution_bucket_boundaries_and_statistics(self):
        summary = scanner._summarize_rr_distribution(
            [0.70, 1.00, 1.24, 1.25, 1.49, 1.50, 2.00],
            rejected_rr_values=[0.70, 1.00, 1.24, 1.25, 1.49],
        )
        self.assertEqual(summary["lt_1_00"], 1)
        self.assertEqual(summary["1_00_to_1_24"], 2)
        self.assertEqual(summary["1_25_to_1_49"], 2)
        self.assertEqual(summary["gte_1_50"], 2)
        self.assertAlmostEqual(summary["avg"], 1.3114285714)
        self.assertAlmostEqual(summary["median"], 1.25)
        self.assertAlmostEqual(summary["nearest_reject"], 1.49)

    @staticmethod
    def _analysis():
        return SimpleNamespace(
            summary={"RECOMMENDATION": "BUY"},
            indicators={
                "close": 100.0,
                "change": 1.0,
                "RSI": 50.0,
                "ADX": 30.0,
                "ADX+DI": 30.0,
                "ADX-DI": 15.0,
                "EMA200": 90.0,
            },
        )

    def test_cycle_logs_rr_distribution_without_changing_reject_flow(self):
        analysis = self._analysis()
        mapping = {"BINANCE:BTCUSDT.P": analysis}
        provider = mock.Mock()
        provider.get_klines.return_value = [{}] * (scanner.STRUCTURE_ATR_PERIOD + 5)
        session = SimpleNamespace(
            provider=provider,
            snapshot=SimpleNamespace(
                symbols=["BTCUSDT"],
                funding_pct={"BTCUSDT": 0.0},
                provider="BINANCE",
                last_price={"BTCUSDT": 100.0},
            ),
        )
        shadow_store = mock.Mock()
        rez_store = mock.Mock()
        rez_store.expire_due.return_value = 0

        def reject_plan(*args, **kwargs):
            diagnostics = kwargs.get("diagnostics")
            if diagnostics is not None:
                diagnostics["reason"] = "RR_TOO_LOW"
                diagnostics["rr_tp1"] = 1.49
            return None

        with mock.patch.object(scanner, "REZ_ANALYSIS_ENABLED", True), \
             mock.patch.object(scanner, "create_market_data_session", return_value=session), \
             mock.patch.object(scanner, "get_shadow_store", return_value=shadow_store), \
             mock.patch.object(scanner, "run_shadow_evaluation_cycle", return_value={"pending": 0, "evaluated": 0, "closed": 0, "provider_mismatch": 0}), \
             mock.patch.object(scanner, "market_price_basis_ok", return_value=True), \
             mock.patch.object(scanner, "determine_btc_bias", return_value="BULLISH"), \
             mock.patch.object(scanner, "setup_passes_filters", return_value=True), \
             mock.patch.object(scanner, "build_structure_trade_plan", side_effect=reject_plan), \
             mock.patch.object(scanner, "get_rez_watch_store", return_value=rez_store), \
             mock.patch.object(scanner, "score_setup") as score_setup, \
             mock.patch.object(scanner, "analyze_with_ai") as astra, \
             mock.patch.object(scanner, "send_telegram_alert") as send_alert, \
             mock.patch("tradingview_ta.get_multiple_analysis", side_effect=[mapping, mapping, mapping]), \
             mock.patch("builtins.print") as printed:
            scanner.run_scan_cycle(limit=1, recent_signals={})

        rendered = "\n".join(
            " ".join(str(value) for value in call.args)
            for call in printed.call_args_list
        )
        self.assertIn(
            "[*] RR_DISTRIBUTION: lt_1_00=0 1_00_to_1_24=0 1_25_to_1_49=1 "
            "gte_1_50=0 avg=1.49 median=1.49 nearest_reject=1.49",
            rendered,
        )
        score_setup.assert_not_called()
        astra.assert_not_called()
        send_alert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
