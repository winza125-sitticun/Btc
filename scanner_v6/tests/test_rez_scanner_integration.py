import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import auto_scanner_v6 as scanner
from rez_analysis_v1 import RezAnalysisResult


class RezScannerConfigTests(unittest.TestCase):
    def setUp(self):
        scanner._REZ_WATCH_STORE = None
        scanner._REZ_WATCH_STORE_FAILED = False

    def test_rez_defaults_are_disabled_and_stable(self):
        self.assertFalse(scanner.REZ_ANALYSIS_ENABLED)
        self.assertEqual(scanner.REZ_ANALYSIS_VERSION, "REZ_V1")
        self.assertEqual(scanner.REZ_WATCH_TTL_HOURS, 12)

    def test_disabled_rez_store_is_not_constructed(self):
        self.assertFalse(scanner.REZ_ANALYSIS_ENABLED)
        with mock.patch.object(scanner, "RezWatchStore") as store_cls:
            self.assertIsNone(scanner.get_rez_watch_store())
            store_cls.assert_not_called()

    def test_enabled_rez_store_uses_shadow_db_path_and_is_cached(self):
        fake_store = object()
        with mock.patch.object(scanner, "REZ_ANALYSIS_ENABLED", True), mock.patch.object(
            scanner, "RezWatchStore", return_value=fake_store
        ) as store_cls:
            first = scanner.get_rez_watch_store()
            second = scanner.get_rez_watch_store()
        self.assertIs(first, fake_store)
        self.assertIs(second, fake_store)
        store_cls.assert_called_once_with(scanner.SHADOW_DB_PATH)

    def test_rez_store_failure_is_sticky_and_fail_closed(self):
        with mock.patch.object(scanner, "REZ_ANALYSIS_ENABLED", True), mock.patch.object(
            scanner, "RezWatchStore", side_effect=sqlite_error("boom")
        ) as store_cls:
            self.assertIsNone(scanner.get_rez_watch_store())
            self.assertIsNone(scanner.get_rez_watch_store())
        store_cls.assert_called_once()
        self.assertTrue(scanner._REZ_WATCH_STORE_FAILED)


class RezScannerGateTests(unittest.TestCase):
    def setUp(self):
        scanner._REZ_WATCH_STORE = None
        scanner._REZ_WATCH_STORE_FAILED = False

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

    @staticmethod
    def _plan():
        return {
            "entry": 100.0,
            "sl": 95.0,
            "sl_pct": 5.0,
            "structure_stop": 96.0,
            "atr": 2.0,
            "atr_buffer": 0.5,
            "tp1": 110.0,
            "tp1_pct": 10.0,
            "rr_tp1": 2.0,
            "tp2": None,
            "tp2_pct": None,
            "rr_tp2": None,
            "tp3": None,
            "tp3_pct": None,
            "rr_tp3": None,
            "invalidation": "1H close below protected swing",
        }

    @staticmethod
    def _score(value):
        return {
            "valid": True,
            "score": value,
            "reason": "OK",
            "components": {
                "trend": 18,
                "strength": 12,
                "structure": 22,
                "market": 13,
                "funding": 8,
                "timing": max(0, value - 73),
            },
        }

    @staticmethod
    def _rez(state, trigger="NO_TRIGGER", reason="WAIT_RETEST"):
        return RezAnalysisResult(
            analysis_version="REZ_V1",
            state=state,
            structure_1h="PULLBACK",
            trigger_15m=trigger,
            supporting_triggers=(),
            reason=reason,
            protected_swing_timestamp=3_600_000,
            protected_swing_price=96.0,
            trigger_level_kind="BOS_HIGH",
            trigger_level_price=100.0,
            closed_1h_at_ms=7_199_999,
            closed_15m_at_ms=8_999_999,
        )

    def _run_cycle(self, *, rez_enabled, rez_result=None, score_value=80, rez_store_available=True):
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
        shadow_store.record_snapshot.return_value = ("snap-1", True)
        rez_store = mock.Mock()
        rez_store.expire_due.return_value = 0
        rez_store.record_analysis.return_value = SimpleNamespace(
            event_id=7,
            event_inserted=True,
            watch_id=3,
            previous_state="ANALYSIS_WAIT" if rez_result and rez_result.state == "PASS" else None,
            current_state="ANALYSIS_PASS" if rez_result and rez_result.state == "PASS" else "ANALYSIS_WAIT",
            promoted=bool(rez_result and rez_result.state == "PASS"),
        )

        with mock.patch.object(scanner, "REZ_ANALYSIS_ENABLED", rez_enabled), \
             mock.patch.object(scanner, "create_market_data_session", return_value=session), \
             mock.patch.object(scanner, "get_shadow_store", return_value=shadow_store), \
             mock.patch.object(scanner, "run_shadow_evaluation_cycle", return_value={"pending": 0, "evaluated": 0, "closed": 0, "provider_mismatch": 0}), \
             mock.patch.object(scanner, "market_price_basis_ok", return_value=True), \
             mock.patch.object(scanner, "determine_btc_bias", return_value="BULLISH"), \
             mock.patch.object(scanner, "setup_passes_filters", return_value=True), \
             mock.patch.object(scanner, "build_structure_trade_plan", return_value=self._plan()), \
             mock.patch.object(scanner, "score_setup", return_value=self._score(score_value)) as score_setup, \
             mock.patch.object(scanner, "analyze_rez_candidate", return_value=rez_result) as analyze_rez, \
             mock.patch.object(scanner, "get_rez_watch_store", return_value=rez_store if rez_store_available else None), \
             mock.patch.object(scanner, "analyze_with_ai", return_value={"confidence": 90, "verdict": "APPROVED", "reason": "ok", "risk": "low"}) as astra, \
             mock.patch.object(scanner, "ai_decision_is_approved", return_value=True), \
             mock.patch.object(scanner, "send_telegram_alert", return_value=True) as send_alert, \
             mock.patch("tradingview_ta.get_multiple_analysis", side_effect=[mapping, mapping, mapping]):
            scanner.run_scan_cycle(limit=1, recent_signals={})

        return {
            "provider": provider,
            "shadow_store": shadow_store,
            "rez_store": rez_store,
            "score_setup": score_setup,
            "analyze_rez": analyze_rez,
            "astra": astra,
            "send_alert": send_alert,
        }

    def test_disabled_path_never_calls_rez_and_keeps_legacy_scoring(self):
        calls = self._run_cycle(rez_enabled=False, score_value=80)
        calls["analyze_rez"].assert_not_called()
        calls["score_setup"].assert_called_once()
        calls["astra"].assert_called_once()
        intervals = [call.args[1] for call in calls["provider"].get_klines.call_args_list]
        self.assertEqual(intervals, ["1h", "4h"])

    def test_rez_wait_stops_before_score_astra_and_telegram(self):
        calls = self._run_cycle(rez_enabled=True, rez_result=self._rez("WAIT"), score_value=80)
        calls["analyze_rez"].assert_called_once()
        calls["score_setup"].assert_not_called()
        calls["astra"].assert_not_called()
        calls["send_alert"].assert_not_called()
        calls["rez_store"].record_analysis.assert_called_once()

    def test_rez_reject_stops_before_score_astra_and_telegram(self):
        calls = self._run_cycle(
            rez_enabled=True,
            rez_result=self._rez("REJECT", reason="OPPOSITE_15M_BREAKOUT"),
            score_value=80,
        )
        calls["score_setup"].assert_not_called()
        calls["astra"].assert_not_called()
        calls["send_alert"].assert_not_called()
        calls["rez_store"].record_analysis.assert_called_once()

    def test_rez_pass_score_below_75_skips_astra_and_links_shadow(self):
        calls = self._run_cycle(
            rez_enabled=True,
            rez_result=self._rez("PASS", trigger="RETEST", reason="PULLBACK_RETEST_CONFIRMED"),
            score_value=74,
        )
        calls["score_setup"].assert_called_once()
        calls["astra"].assert_not_called()
        calls["send_alert"].assert_not_called()
        calls["rez_store"].link_event_snapshot.assert_called_once_with(7, "snap-1")

    def test_rez_pass_score_75_or_more_reaches_astra(self):
        calls = self._run_cycle(
            rez_enabled=True,
            rez_result=self._rez("PASS", trigger="RETEST", reason="PULLBACK_RETEST_CONFIRMED"),
            score_value=80,
        )
        calls["score_setup"].assert_called_once()
        calls["astra"].assert_called_once()
        calls["rez_store"].link_event_snapshot.assert_called_once_with(7, "snap-1")
        calls["rez_store"].expire_due.assert_called_once()

    def test_rez_store_unavailable_fails_closed_before_analysis_and_astra(self):
        calls = self._run_cycle(
            rez_enabled=True,
            rez_result=self._rez("PASS", trigger="RETEST"),
            score_value=80,
            rez_store_available=False,
        )
        calls["analyze_rez"].assert_not_called()
        calls["score_setup"].assert_not_called()
        calls["astra"].assert_not_called()
        calls["send_alert"].assert_not_called()


def sqlite_error(message):
    return RuntimeError(message)


if __name__ == "__main__":
    unittest.main()
