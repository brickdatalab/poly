from __future__ import annotations

import datetime as dt
from typing import Any

from ..context import Ctx
from ..db import psql_json
from ..io_utils import write_json, write_md


def _sql_max_ts(table: str, ts_col: str) -> str:
    return f"select jsonb_build_object('table','{table}','ts_col','{ts_col}','max_ts', max({ts_col}), 'min_ts', min({ts_col}), 'n', count(*)::bigint) from {table};"


def _md(doc: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Ambiguities / Skew Risks (Training)")
    lines.append("")
    lines.append("This section calls out model-training pitfalls that can skew results even if the data is \"valid\".")
    lines.append("")

    lines.append("## Source / Semantics Mismatch Risks")
    lines.append("- Training OHLCV tables contain Binance-style fields (`taker_buy_*`, `num_trades`, `quote_volume`).")
    lines.append("- Realtime serving features in `indicators` are Coinbase-derived (per project baseline doc).")
    lines.append("- Expect training-serving skew unless you train on the RT-aligned datasets (snapshots of `indicators.v_model_15m`).")
    lines.append("")

    lines.append("## Timestamp / Grain Ambiguities")
    lines.append("- Training uses multiple timestamp column names: `ts` (spot_1m) vs `open_time` (spot_15m/1h, unified_*).")
    lines.append("- Row grain for most training sets is `(symbol, open_time)`; serving grain is `(pair, bucket_time)`.")
    lines.append("")

    lines.append("## Data Type Mismatches (Common Pitfall)")
    lines.append("- Training feature tables are mostly `double precision`.")
    lines.append("- Serving `indicators.v_model_*` is mostly `numeric`.")
    lines.append("- This is not inherently wrong, but can bite you when joining/casting or when comparing distributions.")
    lines.append("")

    lines.append("## Freshness Snapshot")
    for it in doc.get("freshness", []):
        lines.append(f"- `{it['table']}` max_ts={it.get('max_ts')} min_ts={it.get('min_ts')} rows={it.get('n')}")
    lines.append("")

    lines.append("## Planned-But-Empty Objects (Training)")
    lines.append("- `training.feature_matrix` and `training.event_labels` are empty (canonical pipeline incomplete).")
    lines.append("- `training.polymarket_*` tables are present but empty (training-time market features not available yet).")
    lines.append("")

    return "\n".join(lines)


def run(ctx: Ctx) -> dict[str, Any]:
    ctx.logger.log("ambiguities: computing freshness + writing skew-risk notes")

    freshness = []
    for table, ts_col in [
        ("training.spot_1m", "ts"),
        ("training.spot_15m", "open_time"),
        ("training.spot_1h", "open_time"),
        ("training.unified_15m", "open_time"),
        ("training.unified_1h", "open_time"),
    ]:
        freshness.append(psql_json(sql=_sql_max_ts(table, ts_col), settings=ctx.settings))

    doc: dict[str, Any] = {"generated_at_utc": dt.datetime.now(dt.UTC).isoformat(), "freshness": freshness}

    out_json = ctx.paths.json_dir / "ambiguities.json"
    out_md = ctx.paths.md_dir / "ambiguities.md"
    write_json(out_json, doc)
    write_md(out_md, _md(doc))
    ctx.logger.log(f"ambiguities: wrote {out_json} and {out_md}")
    return doc

