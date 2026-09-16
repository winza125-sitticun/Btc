import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rez_report_v1 import build_rez_report, generate_report, render_text_report


class RezReportTests(unittest.TestCase):
    def test_report_groups_structure_trigger_and_conversion_rates(self):
        rows = [
            {
                "watch_id": 1, "created_at_ms": 1000,
                "analysis_state": "ANALYSIS_WAIT", "watch_state": "ANALYSIS_PASS",
                "structure_1h": "PULLBACK", "trigger_15m": "NO_TRIGGER",
                "analysis_version": "REZ_V1", "score_total": None,
                "astra_verdict": None, "outcome_status": None,
                "mfe_r": None, "mae_r": None, "invalidated_at_ms": None,
            },
            {
                "watch_id": 1, "created_at_ms": 2000,
                "analysis_state": "ANALYSIS_PASS", "watch_state": "ANALYSIS_PASS",
                "structure_1h": "PULLBACK", "trigger_15m": "RETEST",
                "analysis_version": "REZ_V1", "score_total": 82,
                "astra_verdict": "APPROVED", "outcome_status": "TP1",
                "mfe_r": 1.8, "mae_r": -0.4, "invalidated_at_ms": None,
            },
        ]
        report = build_rez_report(rows)
        self.assertEqual(report["watch_count"], 1)
        self.assertEqual(report["pass_sample_count"], 1)
        self.assertEqual(report["wait_to_pass_rate_pct"], 100.0)
        self.assertEqual(report["pass_to_score_gate_rate_pct"], 100.0)
        self.assertEqual(report["pass_to_astra_approved_rate_pct"], 100.0)
        self.assertEqual(report["by_structure"]["PULLBACK"]["sample_count"], 1)
        self.assertEqual(report["by_trigger"]["RETEST"]["tp1_hit_rate_pct"], 100.0)
        self.assertEqual(report["by_trigger"]["RETEST"]["median_mfe_r"], 1.8)
        self.assertEqual(report["by_trigger"]["RETEST"]["median_mae_r"], -0.4)

    def test_duplicate_pass_events_count_one_sample_per_watch(self):
        rows = [
            {"watch_id": 7, "created_at_ms": 100, "analysis_state": "ANALYSIS_PASS", "watch_state": "ANALYSIS_PASS",
             "structure_1h": "CONTINUATION", "trigger_15m": "BREAKOUT", "analysis_version": "REZ_V1",
             "score_total": 80, "astra_verdict": "WAIT", "outcome_status": "OPEN", "mfe_r": None, "mae_r": None,
             "invalidated_at_ms": None},
            {"watch_id": 7, "created_at_ms": 200, "analysis_state": "ANALYSIS_PASS", "watch_state": "ANALYSIS_PASS",
             "structure_1h": "CONTINUATION", "trigger_15m": "RETEST", "analysis_version": "REZ_V1",
             "score_total": 85, "astra_verdict": "APPROVED", "outcome_status": "TP2", "mfe_r": 2.4, "mae_r": -0.2,
             "invalidated_at_ms": None},
        ]
        report = build_rez_report(rows)
        self.assertEqual(report["pass_sample_count"], 1)
        self.assertIn("BREAKOUT", report["by_trigger"])
        self.assertNotIn("RETEST", report["by_trigger"])

    def test_expiry_and_invalidation_are_watch_level_rates(self):
        rows = [
            {"watch_id": 1, "created_at_ms": 1, "analysis_state": "ANALYSIS_WAIT", "watch_state": "EXPIRED",
             "structure_1h": "RANGE", "trigger_15m": "NO_TRIGGER", "analysis_version": "REZ_V1",
             "score_total": None, "astra_verdict": None, "outcome_status": None, "mfe_r": None, "mae_r": None,
             "invalidated_at_ms": None},
            {"watch_id": 2, "created_at_ms": 1, "analysis_state": "REJECT_ANALYSIS", "watch_state": "REJECT_ANALYSIS",
             "structure_1h": "PULLBACK", "trigger_15m": "NO_TRIGGER", "analysis_version": "REZ_V1",
             "score_total": None, "astra_verdict": None, "outcome_status": None, "mfe_r": None, "mae_r": None,
             "invalidated_at_ms": 2},
        ]
        report = build_rez_report(rows)
        self.assertEqual(report["expiry_rate_pct"], 50.0)
        self.assertEqual(report["invalidation_rate_pct"], 50.0)

    def test_generate_report_joins_rez_and_shadow_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "shadow.sqlite3")
            with sqlite3.connect(db_path) as conn:
                conn.executescript(
                    """
                    CREATE TABLE rez_watch_state (
                        id INTEGER PRIMARY KEY, symbol TEXT, side TEXT, analysis_version TEXT,
                        analysis_state TEXT, invalidated_at_ms INTEGER
                    );
                    CREATE TABLE rez_analysis_events (
                        id INTEGER PRIMARY KEY, watch_id INTEGER, shadow_snapshot_id TEXT,
                        created_at_ms INTEGER, structure_1h TEXT, trigger_15m TEXT,
                        analysis_state TEXT
                    );
                    CREATE TABLE setup_snapshots (
                        id TEXT PRIMARY KEY, score_total INTEGER, astra_verdict TEXT
                    );
                    CREATE TABLE setup_outcomes (
                        snapshot_id TEXT PRIMARY KEY, status TEXT, mfe_r REAL, mae_r REAL
                    );
                    INSERT INTO rez_watch_state VALUES (1,'REZUSDT','LONG','REZ_V1','ANALYSIS_PASS',NULL);
                    INSERT INTO rez_analysis_events VALUES (1,1,'snap-1',1000,'PULLBACK','RETEST','ANALYSIS_PASS');
                    INSERT INTO setup_snapshots VALUES ('snap-1',82,'APPROVED');
                    INSERT INTO setup_outcomes VALUES ('snap-1','TP2',2.1,-0.3);
                    """
                )
            report = generate_report(db_path)
            self.assertEqual(report["pass_sample_count"], 1)
            self.assertEqual(report["by_trigger"]["RETEST"]["tp2_hit_rate_pct"], 100.0)

    def test_text_report_states_automatic_tuning_disabled(self):
        text = render_text_report(build_rez_report([]))
        self.assertIn("REZ V1 Calibration Report", text)
        self.assertIn("WAIT->PASS", text)
        self.assertIn("Automatic tuning: DISABLED", text)


if __name__ == "__main__":
    unittest.main()
