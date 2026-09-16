from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from typing import Any, Optional


FINAL_OUTCOMES = {"TP1", "TP2", "TP3", "SL", "EXPIRED"}


def _pct(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return numerator / denominator * 100.0


def _mean(values: list[float]) -> Optional[float]:
    clean = [float(value) for value in values if value is not None]
    return float(statistics.mean(clean)) if clean else None


def _median(values: list[float]) -> Optional[float]:
    clean = [float(value) for value in values if value is not None]
    return float(statistics.median(clean)) if clean else None


def _first_pass_rows(rows: list[dict]) -> list[dict]:
    first_by_watch: dict[Any, dict] = {}
    for row in sorted(rows, key=lambda item: int(item.get("created_at_ms") or 0)):
        if str(row.get("analysis_state", "")).upper() != "ANALYSIS_PASS":
            continue
        watch_id = row.get("watch_id")
        if watch_id not in first_by_watch:
            first_by_watch[watch_id] = row
    return list(first_by_watch.values())


def _sample_stats(rows: list[dict]) -> dict:
    rows = [dict(row) for row in rows]
    statuses = [str(row.get("outcome_status") or "").upper() for row in rows]
    finalized = [status for status in statuses if status in FINAL_OUTCOMES]
    denominator = len(finalized)
    tp1_hits = sum(status in {"TP1", "TP2", "TP3"} for status in finalized)
    tp2_hits = sum(status in {"TP2", "TP3"} for status in finalized)
    tp3_hits = sum(status == "TP3" for status in finalized)
    sl_hits = sum(status == "SL" for status in finalized)
    return {
        "sample_count": len(rows),
        "finalized_outcome_count": denominator,
        "tp1_hit_rate_pct": _pct(tp1_hits, denominator),
        "tp2_hit_rate_pct": _pct(tp2_hits, denominator),
        "tp3_hit_rate_pct": _pct(tp3_hits, denominator),
        "sl_rate_pct": _pct(sl_hits, denominator),
        "ambiguous_count": sum(status == "AMBIGUOUS" for status in statuses),
        "average_mfe_r": _mean([row.get("mfe_r") for row in rows]),
        "median_mfe_r": _median([row.get("mfe_r") for row in rows]),
        "average_mae_r": _mean([row.get("mae_r") for row in rows]),
        "median_mae_r": _median([row.get("mae_r") for row in rows]),
    }


def _breakdown(rows: list[dict], field: str) -> dict[str, dict]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        raw = row.get(field)
        key = "NONE" if raw is None or str(raw).strip() == "" else str(raw).upper()
        groups.setdefault(key, []).append(row)
    return {key: _sample_stats(group) for key, group in sorted(groups.items())}


def build_rez_report(rows: list[dict]) -> dict:
    rows = [dict(row) for row in (rows or [])]
    watch_ids = {row.get("watch_id") for row in rows if row.get("watch_id") is not None}
    waited = {
        row.get("watch_id") for row in rows
        if row.get("watch_id") is not None and str(row.get("analysis_state", "")).upper() == "ANALYSIS_WAIT"
    }
    passed = {
        row.get("watch_id") for row in rows
        if row.get("watch_id") is not None and str(row.get("analysis_state", "")).upper() == "ANALYSIS_PASS"
    }
    first_pass = _first_pass_rows(rows)
    score_gate_passed = 0
    astra_approved = 0
    for row in first_pass:
        try:
            score = int(row.get("score_total"))
        except (TypeError, ValueError):
            score = -1
        if score >= 75:
            score_gate_passed += 1
        if str(row.get("astra_verdict") or "").upper() == "APPROVED":
            astra_approved += 1

    expired = {
        row.get("watch_id") for row in rows
        if row.get("watch_id") is not None and str(row.get("watch_state") or "").upper() == "EXPIRED"
    }
    invalidated = {
        row.get("watch_id") for row in rows
        if row.get("watch_id") is not None
        and (
            row.get("invalidated_at_ms") is not None
            or str(row.get("watch_state") or "").upper() == "REJECT_ANALYSIS"
        )
    }

    return {
        "watch_count": len(watch_ids),
        "pass_sample_count": len(first_pass),
        "wait_to_pass_rate_pct": _pct(len(waited & passed), len(waited)),
        "pass_to_score_gate_rate_pct": _pct(score_gate_passed, len(first_pass)),
        "pass_to_astra_approved_rate_pct": _pct(astra_approved, len(first_pass)),
        "expiry_rate_pct": _pct(len(expired), len(watch_ids)),
        "invalidation_rate_pct": _pct(len(invalidated), len(watch_ids)),
        "overall_pass_samples": _sample_stats(first_pass),
        "by_structure": _breakdown(first_pass, "structure_1h"),
        "by_trigger": _breakdown(first_pass, "trigger_15m"),
        "by_analysis_version": _breakdown(first_pass, "analysis_version"),
        "automatic_tuning_allowed": False,
    }


def load_rez_rows(db_path: str) -> list[dict]:
    sql = """
        SELECT e.*, w.symbol, w.side, w.analysis_version,
               w.analysis_state AS watch_state, w.invalidated_at_ms,
               s.score_total, s.astra_verdict,
               o.status AS outcome_status, o.mfe_r, o.mae_r
        FROM rez_analysis_events e
        JOIN rez_watch_state w ON w.id = e.watch_id
        LEFT JOIN setup_snapshots s ON s.id = e.shadow_snapshot_id
        LEFT JOIN setup_outcomes o ON o.snapshot_id = s.id
        ORDER BY e.created_at_ms ASC
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def generate_report(db_path: str) -> dict:
    return build_rez_report(load_rez_rows(db_path))


def _fmt_pct(value: Optional[float]) -> str:
    return "N/A" if value is None else f"{value:.1f}%"


def render_text_report(report: dict) -> str:
    lines = [
        "REZ V1 Calibration Report",
        "=" * 72,
        f"Watches: {report.get('watch_count', 0)}",
        f"PASS samples: {report.get('pass_sample_count', 0)}",
        f"WAIT->PASS: {_fmt_pct(report.get('wait_to_pass_rate_pct'))}",
        f"PASS->Score>=75: {_fmt_pct(report.get('pass_to_score_gate_rate_pct'))}",
        f"PASS->Astra APPROVED: {_fmt_pct(report.get('pass_to_astra_approved_rate_pct'))}",
        f"Expiry: {_fmt_pct(report.get('expiry_rate_pct'))}",
        f"Invalidation: {_fmt_pct(report.get('invalidation_rate_pct'))}",
        "",
        "By 1H Structure:",
    ]
    for key, stats in report.get("by_structure", {}).items():
        lines.append(
            f"  {key}: samples={stats['sample_count']} TP1={_fmt_pct(stats['tp1_hit_rate_pct'])} "
            f"SL={_fmt_pct(stats['sl_rate_pct'])}"
        )
    lines.append("")
    lines.append("By 15m Trigger:")
    for key, stats in report.get("by_trigger", {}).items():
        lines.append(
            f"  {key}: samples={stats['sample_count']} TP1={_fmt_pct(stats['tp1_hit_rate_pct'])} "
            f"SL={_fmt_pct(stats['sl_rate_pct'])}"
        )
    lines.extend(["", "Automatic tuning: DISABLED"])
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="REZ V1 shadow calibration report")
    parser.add_argument("--db", default="shadow_eval_v6.sqlite3", help="SQLite shadow database path")
    parser.add_argument("--json", action="store_true", help="Print report as JSON")
    args = parser.parse_args(argv)
    report = generate_report(args.db)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(render_text_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
