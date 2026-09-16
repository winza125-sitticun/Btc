import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import auto_scanner_v6 as scanner


class StructureRejectTelemetryTests(unittest.TestCase):
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

    def test_structure_reject_summary_is_observation_only(self):
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
        self.assertIn("[*] STRUCTURE_REJECTS: RR_TOO_LOW=1", rendered)
        score_setup.assert_not_called()
        astra.assert_not_called()
        send_alert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
