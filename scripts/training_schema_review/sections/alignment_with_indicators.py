from __future__ import annotations

from difflib import get_close_matches
from typing import Any

from ..context import Ctx
from ..db import psql_json
from ..io_utils import write_json, write_md
from ..queries import sql_list_columns


PAIRS = [
    ("training", "unified_15m", "indicators", "v_model_15m"),
    ("training", "unified_1h", "indicators", "v_model_1h"),
]


def _normalize_type(t: str) -> str:
    x = t.lower().strip()
    if x in ("double precision", "float8"):
        return "float8"
    if x in ("numeric", "decimal"):
        return "numeric"
    if x in ("integer", "int4"):
        return "int4"
    if x in ("bigint", "int8"):
        return "int8"
    if x in ("smallint", "int2"):
        return "int2"
    if x in ("real", "float4"):
        return "float4"
    return x


def _compare(cols_a: list[dict[str, Any]], cols_b: list[dict[str, Any]]) -> dict[str, Any]:
    a = {c["name"]: c for c in (cols_a or [])}
    b = {c["name"]: c for c in (cols_b or [])}

    a_names = set(a.keys())
    b_names = set(b.keys())

    intersection = sorted(a_names & b_names)
    a_only = sorted(a_names - b_names)
    b_only = sorted(b_names - a_names)

    type_mismatches = []
    for n in intersection:
        ta = _normalize_type(a[n]["data_type"])
        tb = _normalize_type(b[n]["data_type"])
        if ta != tb:
            type_mismatches.append({"name": n, "training_type": a[n]["data_type"], "indicators_type": b[n]["data_type"]})

    # Heuristic: suggest close-name matches for missing columns (report-only).
    suggestions = []
    b_list = sorted(b_names)
    for n in a_only:
        matches = get_close_matches(n, b_list, n=3, cutoff=0.82)
        if matches:
            suggestions.append({"training_name": n, "indicator_candidates": matches})

    return {
        "intersection": intersection,
        "training_only": a_only,
        "indicators_only": b_only,
        "type_mismatches": type_mismatches,
        "name_suggestions": suggestions,
    }


def _md(doc: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Training vs Indicators Alignment")
    lines.append("")
    lines.append("This section answers: do training feature names/types line up with the serving `indicators.v_model_*` contract?")
    lines.append("")
    for item in doc.get("pairs", []):
        lines.append(f"## {item['training_table']} vs {item['indicators_view']}")
        lines.append(f"- intersection_count: {len(item['comparison']['intersection'])}")
        lines.append(f"- training_only_count: {len(item['comparison']['training_only'])}")
        lines.append(f"- indicators_only_count: {len(item['comparison']['indicators_only'])}")
        lines.append(f"- type_mismatches: {len(item['comparison']['type_mismatches'])}")
        if item["comparison"]["type_mismatches"]:
            for m in item["comparison"]["type_mismatches"][:30]:
                lines.append(f"  - {m['name']}: training={m['training_type']} indicators={m['indicators_type']}")
            if len(item["comparison"]["type_mismatches"]) > 30:
                lines.append("  - ... (see JSON for full list)")
        lines.append("")
    return "\n".join(lines)


def run(ctx: Ctx) -> dict[str, Any]:
    ctx.logger.log("alignment: comparing training unified_* columns to indicators v_model_* columns")

    out_pairs: list[dict[str, Any]] = []
    for a_schema, a_rel, b_schema, b_rel in PAIRS:
        ctx.logger.log(f"alignment: columns {a_schema}.{a_rel}")
        cols_a = psql_json(sql=sql_list_columns(a_schema, a_rel), settings=ctx.settings)
        ctx.logger.log(f"alignment: columns {b_schema}.{b_rel}")
        cols_b = psql_json(sql=sql_list_columns(b_schema, b_rel), settings=ctx.settings)

        cmp = _compare(cols_a, cols_b)
        out_pairs.append(
            {
                "training_table": f"{a_schema}.{a_rel}",
                "indicators_view": f"{b_schema}.{b_rel}",
                "training_columns": cols_a,
                "indicators_columns": cols_b,
                "comparison": cmp,
            }
        )

    doc: dict[str, Any] = {"pairs": out_pairs}
    out_json = ctx.paths.json_dir / "alignment_with_indicators.json"
    out_md = ctx.paths.md_dir / "alignment_with_indicators.md"
    write_json(out_json, doc)
    write_md(out_md, _md(doc))
    ctx.logger.log(f"alignment: wrote {out_json} and {out_md}")
    return doc

