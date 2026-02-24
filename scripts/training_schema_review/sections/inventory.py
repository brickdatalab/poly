from __future__ import annotations

from pathlib import Path
from typing import Any

from ..context import Ctx
from ..db import psql_json
from ..io_utils import write_json, write_md
from ..queries import sql_list_columns, sql_time_coverage, sql_training_inventory


KEY_TABLES = [
    ("training.spot_1m", "symbol", "ts"),
    ("training.spot_15m", "symbol", "open_time"),
    ("training.spot_1h", "symbol", "open_time"),
    ("training.spot_15m_indicators", "symbol", "open_time"),
    ("training.spot_1h_indicators", "symbol", "open_time"),
    ("training.unified_15m", "symbol", "open_time"),
    ("training.unified_1h", "symbol", "open_time"),
    ("training.synthetic_features", "symbol", "open_time"),
]


def _md_inventory(doc: dict[str, Any]) -> str:
    objs = doc.get("inventory", {}).get("objects", [])
    by_kind: dict[str, int] = {}
    for o in objs:
        by_kind[o["kind"]] = by_kind.get(o["kind"], 0) + 1

    lines: list[str] = []
    lines.append("# Training Schema Inventory")
    lines.append("")
    lines.append("## Object Counts")
    for k in sorted(by_kind.keys()):
        lines.append(f"- `{k}`: {by_kind[k]}")
    lines.append("")
    lines.append("## Key Tables Coverage")
    for t in doc.get("coverage", []):
        lines.append(f"- `{t['table']}` ({t['ts_col']}):")
        for g in t.get("groups", []):
            lines.append(
                f"  - `{g['symbol']}` rows={g['n_rows']} min={g['min_ts']} max={g['max_ts']}"
            )
    lines.append("")
    lines.append("## Key Columns (High-Level)")
    for item in doc.get("columns", []):
        cols = item.get("columns", [])
        lines.append(f"- `{item['table']}` columns={len(cols)}")
    lines.append("")
    return "\n".join(lines)


def run(ctx: Ctx) -> dict[str, Any]:
    ctx.logger.log("inventory: querying training schema object inventory")
    inv = psql_json(sql=sql_training_inventory(), settings=ctx.settings)

    coverage: list[dict[str, Any]] = []
    columns: list[dict[str, Any]] = []

    for table, symbol_col, ts_col in KEY_TABLES:
        schema, rel = table.split(".", 1)
        ctx.logger.log(f"inventory: coverage {table}")
        groups = psql_json(sql=sql_time_coverage(table, symbol_col, ts_col), settings=ctx.settings)
        coverage.append({"table": table, "symbol_col": symbol_col, "ts_col": ts_col, "groups": groups})

        ctx.logger.log(f"inventory: columns {table}")
        cols = psql_json(sql=sql_list_columns(schema, rel), settings=ctx.settings)
        columns.append({"table": table, "columns": cols})

    doc: dict[str, Any] = {"inventory": inv, "coverage": coverage, "columns": columns}

    out_json = ctx.paths.json_dir / "training_inventory.json"
    out_md = ctx.paths.md_dir / "training_inventory.md"
    write_json(out_json, doc)
    write_md(out_md, _md_inventory(doc))
    ctx.logger.log(f"inventory: wrote {out_json} and {out_md}")
    return doc

