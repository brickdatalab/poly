#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# Allow running as a script without installation.
THIS_DIR = Path(__file__).resolve().parent
ROOT = Path("/Users/vitolo/Desktop/projects/poly")
RUNS_DIR = ROOT / "scripts" / "training_schema_review" / "runs"

import sys

if str((ROOT / "scripts").resolve()) not in sys.path:
    sys.path.insert(0, str((ROOT / "scripts").resolve()))

from training_schema_review.db import PsqlSettings, psql_json
from training_schema_review.queries import sql_feature_stats_single_scan, sql_list_columns


def latest_run_dir() -> Path:
    runs = [p for p in RUNS_DIR.iterdir() if p.is_dir()]
    if not runs:
        raise RuntimeError(f"No runs found under {RUNS_DIR}")
    return sorted(runs, key=lambda p: p.name)[-1]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_time_coverage(training_inventory: dict[str, Any], table: str) -> dict[str, Any] | None:
    for item in training_inventory.get("coverage", []):
        if item.get("table") == table:
            # Use __overall__ row
            for g in item.get("groups", []):
                if g.get("symbol") == "__overall__":
                    return {"rows": g.get("n_rows"), "min_ts": g.get("min_ts"), "max_ts": g.get("max_ts")}
    return None


def flagged_features_by_table(flags: list[dict[str, Any]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for f in flags:
        out.setdefault(f["table"], set()).add(f["feature"])
    return out


def safe_feature_list(table_entry: dict[str, Any], flagged: set[str]) -> list[str]:
    feats = table_entry.get("numeric_features") or []
    return sorted([c for c in feats if c not in flagged])


def list_columns(schema: str, rel: str, settings: PsqlSettings) -> list[dict[str, Any]]:
    cols = psql_json(sql=sql_list_columns(schema, rel), settings=settings)
    return cols or []


def md_bullets(items: list[str]) -> str:
    return "\n".join([f"- `{x}`" for x in items]) if items else "_None._"


LABEL_COLS = {
    "outcome",
    "label",
    "next_label",
    "label_binary",
    "next_label_binary",
    "pct_change",
    "next_pct_change",
    "price_change",
    "price_change_pct",
    "start_price",
    "end_price",
    "event_end",
    "event_start",
    "label_version",
}


def split_cols(cols: list[str]) -> tuple[list[str], list[str]]:
    label = [c for c in cols if c in LABEL_COLS]
    features = [c for c in cols if c not in LABEL_COLS]
    return sorted(label), sorted(features)


def safe_features_for_view(
    *,
    view_name: str,
    key_cols: list[str],
    time_col: str,
    settings: PsqlSettings,
) -> tuple[list[str], list[str]]:
    schema, rel = view_name.split(".", 1)
    cols = list_columns(schema, rel, settings)
    col_names = [c["name"] for c in cols]

    # Exclude key/time and label/target columns from feature list (avoid leakage).
    non_key = [c for c in col_names if c not in set(key_cols + [time_col])]
    label_cols, candidate_features = split_cols(non_key)

    numeric_types = {
        "double precision",
        "numeric",
        "real",
        "integer",
        "bigint",
        "smallint",
    }
    numeric_features = [c["name"] for c in cols if c["name"] in candidate_features and c.get("data_type") in numeric_types]

    stats = psql_json(
        sql=sql_feature_stats_single_scan(
            table=view_name,
            symbol_col=key_cols[0] if key_cols else "pair",
            ts_col=time_col,
            feature_cols=numeric_features,
            deep_percentiles=False,
        ),
        settings=settings,
    )

    flagged: set[str] = set()
    for g in (stats or {}).get("groups", []):
        if g.get("symbol") != "__overall__":
            continue
        feats = g.get("features") or {}
        for feat, s in feats.items():
            if int(s.get("not_finite") or 0) > 0:
                flagged.add(feat)
            if int(s.get("bounds_violations") or 0) > 0:
                flagged.add(feat)

    safe = sorted([c for c in numeric_features if c not in flagged])
    return label_cols, safe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default="", help="Use an existing run dir. Default: latest.")
    ap.add_argument("--out", default=str(ROOT / "training_ready.md"))
    ap.add_argument("--include-spot-1m", action="store_true", help="Include training.spot_1m section.")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve() if args.run_dir else latest_run_dir()
    inv = load_json(run_dir / "json" / "training_inventory.json")
    ind = load_json(run_dir / "json" / "indicator_coverage.json")
    anomalies = load_json(run_dir / "json" / "indicator_anomalies.json")

    flags = anomalies.get("flags", [])
    flagged = flagged_features_by_table(flags)
    flagged_anywhere = {f["feature"] for f in flags}

    # Pull column lists for the training-ready dataset views directly from DB so the doc is accurate.
    settings = PsqlSettings(statement_timeout_s=120, work_mem_mb=128, max_parallel_workers_per_gather=2)

    # Map indicator coverage entries by table name.
    by_table = {t["table"]: t for t in ind.get("tables", [])}

    lines: list[str] = []
    lines.append("# Training Data (Ready)")
    lines.append("")
    lines.append(f"Source run: `{run_dir}`")
    lines.append("")
    lines.append("All timestamps are UTC (`timestamptz`).")
    lines.append("")

    # Primary dataset views (recommended)
    lines.append("## Primary Training Datasets (Views)")
    lines.append("")

    for view_name in [
        "training.v_rt_dataset_from_indicators_15m_scoreable_current",
        "training.v_rt_dataset_15m_from_unified_scoreable_current",
    ]:
        lines.append(f"### `{view_name}`")

        cols = list_columns("training", view_name.split(".", 1)[1], settings)
        col_names = [c["name"] for c in cols]
        time_col = "bucket_time" if "bucket_time" in col_names else "open_time"
        key_cols = ["pair", time_col] if "pair" in col_names else ["symbol", time_col]

        label_cols, safe_feats = safe_features_for_view(
            view_name=view_name,
            key_cols=key_cols,
            time_col=time_col,
            settings=settings,
        )
        safe_feats = [c for c in safe_feats if c not in flagged_anywhere]

        lines.append(f"- time_column: `{time_col}`")
        lines.append(f"- key_columns: " + ", ".join([f"`{c}`" for c in key_cols]))
        if label_cols:
            lines.append(f"- label_columns: " + ", ".join([f"`{c}`" for c in label_cols]))
        lines.append(f"- feature_columns (safe): {len(safe_feats)}")
        lines.append("")
        lines.append(md_bullets(safe_feats))
        lines.append("")

    # Base candle tables
    lines.append("## Candle Tables")
    lines.append("")

    for table, tf, time_col in [
        ("training.spot_15m", "15m", "open_time"),
        ("training.spot_1h", "1h", "open_time"),
    ]:
        cov = extract_time_coverage(inv, table) or {}
        lines.append(f"### `{table}` ({tf})")
        lines.append(f"- time_column: `{time_col}`")
        lines.append(f"- rows: {cov.get('rows')}")
        lines.append(f"- range_utc: {cov.get('min_ts')} -> {cov.get('max_ts')}")
        # Use columns from inventory JSON (already fetched).
        cols = None
        for item in inv.get("columns", []):
            if item.get("table") == table:
                cols = [c["name"] for c in item.get("columns", [])]
                break
        cols = cols or []
        label_cols, non_label = split_cols([c for c in cols if c not in ("symbol", time_col)])
        lines.append("- ohlcv_columns: `open`, `high`, `low`, `close`, `volume`")
        if label_cols:
            lines.append("- label_columns: " + ", ".join([f"`{c}`" for c in label_cols]))
        extra = [
            c
            for c in non_label
            if c
            not in (
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
            )
        ]
        if extra:
            lines.append("- extra_columns: " + ", ".join([f"`{c}`" for c in extra]))
        lines.append("")

    if args.include_spot_1m:
        table = "training.spot_1m"
        cov = extract_time_coverage(inv, table) or {}
        lines.append(f"### `{table}` (1m)")
        lines.append("- time_column: `ts`")
        lines.append(f"- rows: {cov.get('rows')}")
        lines.append(f"- range_utc: {cov.get('min_ts')} -> {cov.get('max_ts')}")
        cols = None
        for item in inv.get("columns", []):
            if item.get("table") == table:
                cols = [c["name"] for c in item.get("columns", [])]
                break
        cols = cols or []
        lines.append("- columns:")
        lines.append(md_bullets(cols))
        lines.append("")

    # Indicator-enriched wide tables
    lines.append("## Indicator-Enriched Tables (Safe Columns Only)")
    lines.append("")

    for table, tf in [
        ("training.spot_15m_indicators", "15m"),
        ("training.spot_1h_indicators", "1h"),
        ("training.unified_15m", "15m"),
        ("training.unified_1h", "1h"),
        ("training.synthetic_features", "15m/1h"),
    ]:
        t = by_table.get(table)
        if not t:
            continue
        cov = extract_time_coverage(inv, table)
        safe_cols = [c for c in safe_feature_list(t, flagged.get(table, set())) if c not in LABEL_COLS]
        safe_cols = [c for c in safe_cols if c not in flagged_anywhere]
        lines.append(f"### `{table}` ({tf})")
        if cov:
            lines.append(f"- rows: {cov.get('rows')}")
            lines.append(f"- range_utc: {cov.get('min_ts')} -> {cov.get('max_ts')}")
        lines.append(f"- safe_numeric_feature_columns: {len(safe_cols)}")
        lines.append("")
        lines.append(md_bullets(safe_cols))
        lines.append("")

    out_path = Path(args.out).resolve()
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
