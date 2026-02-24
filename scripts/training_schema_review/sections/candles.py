from __future__ import annotations

from typing import Any

from ..context import Ctx
from ..db import psql_json
from ..io_utils import write_json, write_md
from ..queries import sql_candle_invariants, sql_duplicate_key_count


CANDLE_TABLES = [
    # table, timeframe, symbol_col, ts_col
    ("training.spot_1m", "1m", "symbol", "ts"),
    ("training.spot_15m", "15m", "symbol", "open_time"),
    ("training.spot_1h", "1h", "symbol", "open_time"),
    ("training.unified_15m", "15m", "symbol", "open_time"),
    ("training.unified_1h", "1h", "symbol", "open_time"),
]


def _md(doc: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Candle Usability Report")
    lines.append("")
    lines.append("This section checks OHLCV availability and basic invariants per table.")
    lines.append("")
    for item in doc.get("tables", []):
        lines.append(f"## {item['table']} ({item['timeframe']})")
        inv = item.get("invariants", {})
        for g in inv.get("groups", []):
            lines.append(
                f"- {g['symbol']}: rows={g['n_rows']} offgrid={g['n_offgrid']} neg_vol={g['n_neg_volume']} "
                f"high<low={g['n_high_lt_low']} high<ohlc={g['n_high_lt_ohlc']} low>ohlc={g['n_low_gt_ohlc']} "
                f"nulls(open/high/low/close/vol)={g['n_open_null']}/{g['n_high_null']}/{g['n_low_null']}/{g['n_close_null']}/{g['n_volume_null']} "
                f"min={g['min_ts']} max={g['max_ts']}"
            )
        dup = item.get("duplicates", {})
        lines.append(f"- duplicate_keys={dup.get('duplicate_keys')} duplicate_rows_extra={dup.get('duplicate_rows_extra')}")
        lines.append("")
    return "\n".join(lines)


def run(ctx: Ctx) -> dict[str, Any]:
    ctx.logger.log("candles: computing OHLCV invariants and duplicate-key counts")
    out_tables: list[dict[str, Any]] = []
    for table, tf, sym, ts in CANDLE_TABLES:
        ctx.logger.log(f"candles: invariants {table}")
        inv = psql_json(sql=sql_candle_invariants(table=table, symbol_col=sym, ts_col=ts, timeframe=tf), settings=ctx.settings)

        ctx.logger.log(f"candles: duplicates {table}")
        dups = psql_json(sql=sql_duplicate_key_count(table, [sym, ts]), settings=ctx.settings)
        out_tables.append({"table": table, "timeframe": tf, "invariants": inv, "duplicates": dups})

    doc: dict[str, Any] = {"tables": out_tables}
    out_json = ctx.paths.json_dir / "candles_profile.json"
    out_md = ctx.paths.md_dir / "candles_profile.md"
    write_json(out_json, doc)
    write_md(out_md, _md(doc))
    ctx.logger.log(f"candles: wrote {out_json} and {out_md}")
    return doc

