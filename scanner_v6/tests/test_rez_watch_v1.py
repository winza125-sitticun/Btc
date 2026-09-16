import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rez_analysis_v1 import RezAnalysisResult
from rez_watch_v1 import RezWatchStore, build_watch_key


HOUR_MS = 3_600_000
M15_MS = 900_000


def result(*, state="WAIT", trigger="NO_TRIGGER", reason="WAIT_RETEST", closed_15m=M15_MS):
    return RezAnalysisResult(
        analysis_version="REZ_V1",
        state=state,
        structure_1h="PULLBACK",
        trigger_15m=trigger,
        supporting_triggers=(),
        reason=reason,
        protected_swing_timestamp=3_600_000,
        protected_swing_price=0.052,
        trigger_level_kind="BOS_HIGH",
        trigger_level_price=0.055,
        closed_1h_at_ms=7_199_999,
        closed_15m_at_ms=closed_15m,
    )


class RezWatchStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "shadow.sqlite3")
        self.store = RezWatchStore(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_initialization_creates_rez_tables_only(self):
        names = self.store.table_names()
        self.assertIn("rez_watch_state", names)
        self.assertIn("rez_analysis_events", names)
        self.assertNotIn("setup_snapshots", names)

    def test_watch_key_is_stable_and_normalized(self):
        key = build_watch_key("rezusdt", "long", 1234, "bos_high", "rez_v1")
        self.assertEqual(key, "REZUSDT|LONG|1234|BOS_HIGH|REZ_V1")

    def test_same_wait_same_closed_candle_is_deduped(self):
        first = self.store.record_analysis(
            symbol="REZUSDT", side="LONG", provider="BINANCE", result=result(), now_ms=2_000_000, ttl_hours=12
        )
        second = self.store.record_analysis(
            symbol="REZUSDT", side="LONG", provider="BINANCE", result=result(), now_ms=2_100_000, ttl_hours=12
        )
        self.assertTrue(first.event_inserted)
        self.assertFalse(second.event_inserted)
        self.assertEqual(first.watch_id, second.watch_id)
        self.assertEqual(first.event_id, second.event_id)

    def test_newer_closed_candle_appends_event_without_sliding_expiry(self):
        first = self.store.record_analysis(
            symbol="REZUSDT", side="LONG", provider="BINANCE", result=result(closed_15m=M15_MS),
            now_ms=2_000_000, ttl_hours=12,
        )
        second = self.store.record_analysis(
            symbol="REZUSDT", side="LONG", provider="BINANCE", result=result(closed_15m=2 * M15_MS),
            now_ms=5_000_000, ttl_hours=12,
        )
        self.assertTrue(second.event_inserted)
        watch = self.store.get_watch(first.watch_id)
        self.assertEqual(watch["first_seen_at_ms"], 2_000_000)
        self.assertEqual(watch["expires_at_ms"], 2_000_000 + 12 * HOUR_MS)
        self.assertEqual(watch["last_closed_15m_at_ms"], 2 * M15_MS)

    def test_wait_can_promote_to_pass(self):
        self.store.record_analysis(
            symbol="REZUSDT", side="LONG", provider="BINANCE", result=result(), now_ms=2_000_000, ttl_hours=12
        )
        promoted = self.store.record_analysis(
            symbol="REZUSDT", side="LONG", provider="BINANCE",
            result=result(state="PASS", trigger="RETEST", reason="PULLBACK_RETEST_CONFIRMED", closed_15m=2 * M15_MS),
            now_ms=2_900_000, ttl_hours=12,
        )
        self.assertTrue(promoted.promoted)
        self.assertEqual(promoted.previous_state, "ANALYSIS_WAIT")
        self.assertEqual(promoted.current_state, "ANALYSIS_PASS")

    def test_anchored_reject_marks_watch_invalidated(self):
        rejected = self.store.record_analysis(
            symbol="REZUSDT", side="LONG", provider="BINANCE",
            result=result(state="REJECT", trigger="NO_TRIGGER", reason="OPPOSITE_15M_BREAKOUT"),
            now_ms=3_000_000, ttl_hours=12,
        )
        watch = self.store.get_watch(rejected.watch_id)
        self.assertEqual(watch["analysis_state"], "REJECT_ANALYSIS")
        self.assertEqual(watch["invalidated_at_ms"], 3_000_000)

    def test_expire_due_changes_only_active_wait_rows(self):
        waiting = self.store.record_analysis(
            symbol="REZUSDT", side="LONG", provider="BINANCE", result=result(), now_ms=1_000, ttl_hours=12
        )
        passed = self.store.record_analysis(
            symbol="BTCUSDT", side="LONG", provider="BINANCE",
            result=RezAnalysisResult(
                analysis_version="REZ_V1", state="PASS", structure_1h="CONTINUATION", trigger_15m="BREAKOUT",
                supporting_triggers=(), reason="CONTINUATION_BREAKOUT_CONFIRMED",
                protected_swing_timestamp=3_600_001, protected_swing_price=100.0,
                trigger_level_kind="BOS_HIGH", trigger_level_price=101.0,
                closed_1h_at_ms=7_199_999, closed_15m_at_ms=M15_MS,
            ),
            now_ms=1_000, ttl_hours=12,
        )
        count = self.store.expire_due(1_000 + 12 * HOUR_MS + 1)
        self.assertEqual(count, 1)
        self.assertEqual(self.store.get_watch(waiting.watch_id)["analysis_state"], "EXPIRED")
        self.assertEqual(self.store.get_watch(passed.watch_id)["analysis_state"], "ANALYSIS_PASS")

    def test_snapshot_link_is_one_time_and_idempotent(self):
        record = self.store.record_analysis(
            symbol="REZUSDT", side="LONG", provider="BINANCE",
            result=result(state="PASS", trigger="RETEST", reason="PULLBACK_RETEST_CONFIRMED"),
            now_ms=2_000_000, ttl_hours=12,
        )
        self.store.link_event_snapshot(record.event_id, "snap-1")
        self.store.link_event_snapshot(record.event_id, "snap-1")
        event = self.store.get_event(record.event_id)
        self.assertEqual(event["shadow_snapshot_id"], "snap-1")
        with self.assertRaises(ValueError):
            self.store.link_event_snapshot(record.event_id, "snap-2")

    def test_existing_shadow_tables_are_left_untouched(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("CREATE TABLE setup_snapshots (id TEXT PRIMARY KEY, sentinel TEXT)")
            conn.execute("INSERT INTO setup_snapshots(id, sentinel) VALUES ('keep', 'yes')")
        RezWatchStore(self.db_path)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT sentinel FROM setup_snapshots WHERE id='keep'").fetchone()
        self.assertEqual(row[0], "yes")


if __name__ == "__main__":
    unittest.main()
