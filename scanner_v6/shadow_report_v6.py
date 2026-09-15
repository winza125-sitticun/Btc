from __future__ import annotations

import argparse
import json
import os
import time

from shadow_eval_v6 import ShadowStore, build_calibration_report


def render_text_report(report: dict) -> str:
    lines = [
        "V6 Shadow Calibration Report",
        "=" * 72,
        f"Analyzable samples: {report['analyzable_samples']}",
        f"Ambiguous samples:  {report['ambiguous_samples']}",
        f"No-data samples:    {report['no_data_samples']}",
        f"Calibration ready:  {'YES' if report['calibration_ready'] else 'NO'}",
        "",
        "Score   Samples  TP1<SL%  SL<TP1%  Median MFE(R)  Median MAE(R)  Sufficient",
        "-" * 72,
    ]
    for bucket in report["score_buckets"]:
        tp_rate = "N/A" if bucket["tp1_before_sl_rate_pct"] is None else f"{bucket['tp1_before_sl_rate_pct']:.1f}"
        sl_rate = "N/A" if bucket["sl_before_tp1_rate_pct"] is None else f"{bucket['sl_before_tp1_rate_pct']:.1f}"
        mfe = "N/A" if bucket["median_mfe_r"] is None else f"{bucket['median_mfe_r']:.2f}"
        mae = "N/A" if bucket["median_mae_r"] is None else f"{bucket['median_mae_r']:.2f}"
        lines.append(
            f"{bucket['label']:<7} {bucket['sample_count']:<8} {tp_rate:<8} {sl_rate:<8} "
            f"{mfe:<14} {mae:<14} {'YES' if bucket['sufficient_samples'] else 'NO'}"
        )
    lines.extend([
        "",
        f"Status: {report['recommendation']['status']}",
        report["recommendation"]["message"],
        "Automatic score/threshold changes: DISABLED",
    ])
    return "\n".join(lines)


def generate_report(db_path: str, min_total: int, min_bucket: int, created_at_ms: int | None = None) -> dict:
    store = ShadowStore(db_path)
    rows = store.calibration_rows()
    report = build_calibration_report(
        rows,
        min_total_samples=min_total,
        min_bucket_samples=min_bucket,
    )
    if created_at_ms is None:
        created_at_ms = int(time.time() * 1000)
    store.save_calibration_report(report, created_at_ms=created_at_ms)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Analysis Engine V6 shadow calibration report")
    parser.add_argument("--db", default="shadow_eval_v6.sqlite3", help="SQLite shadow database path")
    parser.add_argument("--json", action="store_true", help="Print report as JSON")
    parser.add_argument("--min-total", type=int, default=int(os.getenv("SHADOW_MIN_TOTAL_SAMPLES", "100")), help="Minimum analyzable samples before calibration review")
    parser.add_argument("--min-bucket", type=int, default=int(os.getenv("SHADOW_MIN_BUCKET_SAMPLES", "30")), help="Minimum samples per score bucket")
    args = parser.parse_args()

    report = generate_report(args.db, args.min_total, args.min_bucket)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(render_text_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
