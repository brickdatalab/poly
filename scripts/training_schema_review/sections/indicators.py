from __future__ import annotations

import math
from typing import Any

from ..context import Ctx
from ..db import psql_json
from ..io_utils import write_json, write_md
from ..queries import sql_distinct_values, sql_feature_stats_single_scan, sql_list_columns


TABLES = [
    # table, symbol_col, ts_col, key_cols
    ("training.spot_1m", "symbol", "ts", ["symbol", "ts"]),
    ("training.spot_15m_indicators", "symbol", "open_time", ["symbol", "open_time"]),
    ("training.spot_1h_indicators", "symbol", "open_time", ["symbol", "open_time"]),
    ("training.unified_15m", "symbol", "open_time", ["symbol", "open_time"]),
    ("training.unified_1h", "symbol", "open_time", ["symbol", "open_time"]),
    ("training.synthetic_features", "symbol", "open_time", ["symbol", "open_time"]),
]


NUMERIC_TYPES = {
    "double precision",
    "numeric",
    "real",
    "integer",
    "bigint",
    "smallint",
}


def _is_close(a: float | None, b: float | None, *, tol: float = 1e-12) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _flag_feature(
    *,
    table: str,
    symbol: str,
    feature: str,
    stats: dict[str, Any],
    n_rows: int,
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    n_nonnull = int(stats.get("n_nonnull") or 0)
    n_null = int(stats.get("n_null") or 0)
    not_finite = int(stats.get("not_finite") or 0)
    bounds_violations = int(stats.get("bounds_violations") or 0)
    mean = stats.get("mean")
    stddev = stats.get("stddev")
    min_v = stats.get("min")
    max_v = stats.get("max")

    null_rate = (n_null / n_rows) if n_rows > 0 else 0.0

    if not_finite > 0:
        flags.append(
            {
                "kind": "not_finite",
                "table": table,
                "symbol": symbol,
                "feature": feature,
                "not_finite": not_finite,
            }
        )

    if bounds_violations > 0:
        flags.append(
            {
                "kind": "bounds_violation",
                "table": table,
                "symbol": symbol,
                "feature": feature,
                "bounds_kind": stats.get("bounds_kind"),
                "bounds_violations": bounds_violations,
                "min": min_v,
                "max": max_v,
            }
        )

    if n_nonnull >= 500 and (stddev == 0 or _is_close(float(stddev or 0.0), 0.0)):
        flags.append(
            {
                "kind": "constant_or_near_constant",
                "table": table,
                "symbol": symbol,
                "feature": feature,
                "n_nonnull": n_nonnull,
                "stddev": stddev,
                "min": min_v,
                "max": max_v,
            }
        )

    if n_rows >= 500 and null_rate >= 0.8:
        flags.append(
            {
                "kind": "high_missingness",
                "table": table,
                "symbol": symbol,
                "feature": feature,
                "null_rate": null_rate,
                "n_rows": n_rows,
                "n_null": n_null,
            }
        )

    # Generic weirdness: huge magnitude means potential unit/skew bugs.
    try:
        if max_v is not None and isinstance(max_v, (int, float)) and math.isfinite(float(max_v)) and abs(float(max_v)) > 1e12:
            flags.append(
                {
                    "kind": "huge_magnitude",
                    "table": table,
                    "symbol": symbol,
                    "feature": feature,
                    "max": max_v,
                    "mean": mean,
                }
            )
    except Exception:
        pass

    return flags


def _md(doc: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Indicator Coverage + Quality Checks")
    lines.append("")
    lines.append("Phase A (single-scan stats): null rates, bounds sanity, constant detection, NaN/Inf checks.")
    lines.append("")

    for t in doc.get("tables", []):
        lines.append(f"## {t['table']}")
        lines.append(f"- numeric_features: {len(t.get('numeric_features', []))}")
        if t.get("label_distribution") is not None:
            lines.append(f"- label_distribution: {t['label_distribution']}")
        groups = (t.get("stats") or {}).get("groups", [])
        for g in groups:
            lines.append(f"- group `{g['symbol']}` rows={g['n_rows']} min_ts={g['min_ts']} max_ts={g['max_ts']}")
        lines.append("")

    flags = doc.get("flags", [])
    lines.append("## Flags (Potential Issues)")
    lines.append(f"- total_flags: {len(flags)}")
    # Show a small sample inline; full details are in JSON.
    for f in flags[:50]:
        lines.append(f"- {f['kind']} {f['table']} {f['symbol']} {f['feature']}")
    if len(flags) > 50:
        lines.append(f"- ... and {len(flags) - 50} more (see JSON)")
    lines.append("")
    return "\n".join(lines)


def run(ctx: Ctx) -> dict[str, Any]:
    ctx.logger.log("indicators: scanning training indicator/feature tables (Phase A)")

    tables_out: list[dict[str, Any]] = []
    flags: list[dict[str, Any]] = []

    deep = ctx.mode == "deep"

    for table, symbol_col, ts_col, key_cols in TABLES:
        schema, rel = table.split(".", 1)
        ctx.logger.log(f"indicators: list columns {table}")
        cols = psql_json(sql=sql_list_columns(schema, rel), settings=ctx.settings)

        numeric_cols: list[str] = []
        for c in cols or []:
            if c["name"] in key_cols:
                continue
            if c["data_type"] in NUMERIC_TYPES:
                numeric_cols.append(c["name"])

        # If there's a label column, capture distribution separately.
        label_dist = None
        if any(c["name"] == "label" for c in (cols or [])):
            ctx.logger.log(f"indicators: label distribution {table}.label")
            label_dist = psql_json(sql=sql_distinct_values(table, "label", limit=20), settings=ctx.settings)

        ctx.logger.log(f"indicators: stats single-scan {table} features={len(numeric_cols)}")
        stats = psql_json(
            sql=sql_feature_stats_single_scan(
                table=table,
                symbol_col=symbol_col,
                ts_col=ts_col,
                feature_cols=numeric_cols,
                deep_percentiles=False,  # Phase A only
            ),
            settings=ctx.settings,
        )

        # Flag anomalies from Phase A.
        for g in (stats or {}).get("groups", []):
            sym = g.get("symbol")
            n_rows = int(g.get("n_rows") or 0)
            feats = g.get("features") or {}
            for feat_name, feat_stats in feats.items():
                flags.extend(
                    _flag_feature(
                        table=table,
                        symbol=str(sym),
                        feature=str(feat_name),
                        stats=feat_stats,
                        n_rows=n_rows,
                    )
                )

        tables_out.append(
            {
                "table": table,
                "symbol_col": symbol_col,
                "ts_col": ts_col,
                "numeric_features": numeric_cols,
                "label_distribution": label_dist,
                "stats": stats,
            }
        )

        # Phase B: percentiles for flagged columns (deep mode only).
        if deep:
            flagged_cols = sorted(
                {
                    f["feature"]
                    for f in flags
                    if f["table"] == table and f["kind"] in ("bounds_violation", "not_finite", "huge_magnitude")
                }
            )
            if flagged_cols:
                ctx.logger.log(f"indicators: deep percentiles {table} flagged_features={len(flagged_cols)}")
                pct_batches: list[list[str]] = []
                batch: list[str] = []
                for c in flagged_cols:
                    batch.append(c)
                    if len(batch) >= 6:
                        pct_batches.append(batch)
                        batch = []
                if batch:
                    pct_batches.append(batch)

                deep_results: list[Any] = []
                for b in pct_batches:
                    deep_results.append(
                        psql_json(
                            sql=sql_feature_stats_single_scan(
                                table=table,
                                symbol_col=symbol_col,
                                ts_col=ts_col,
                                feature_cols=b,
                                deep_percentiles=True,
                            ),
                            settings=ctx.settings,
                        )
                    )
                tables_out[-1]["deep_percentiles_flagged_batches"] = deep_results

    doc: dict[str, Any] = {"tables": tables_out, "flags": flags}
    out_json = ctx.paths.json_dir / "indicator_coverage.json"
    out_flags = ctx.paths.json_dir / "indicator_anomalies.json"
    out_md = ctx.paths.md_dir / "indicator_coverage.md"
    write_json(out_json, doc)
    write_json(out_flags, {"flags": flags})
    write_md(out_md, _md(doc))
    ctx.logger.log(f"indicators: wrote {out_json}, {out_flags}, {out_md}")
    return doc

