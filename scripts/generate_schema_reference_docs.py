#!/usr/bin/env python3
"""
Generate reference docs for the `indicators` and `training` schemas.

Goal:
- Produce self-contained Markdown docs that allow an agent to understand the
  current DB surface area (tables/views/functions/columns/partitions/triggers),
  without needing to do MCP lookups before writing code.

Outputs (repo root):
- /Users/vitolo/Desktop/projects/poly/INDICATORS_SCHEMA.md
- /Users/vitolo/Desktop/projects/poly/TRAINING_SCHEMA.md

Connection:
- Uses SUPABASE_DB_URL + SUPABASE_DB_PASSWORD from /Users/vitolo/Desktop/projects/poly/.env
- Uses psql via subprocess (no external Python dependencies)
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Final


ROOT: Final[Path] = Path("/Users/vitolo/Desktop/projects/poly")
DOTENV: Final[Path] = ROOT / ".env"


@dataclasses.dataclass(frozen=True)
class TableStat:
    name: str
    kind: str  # table | partitioned_table | view | matview | other
    est_rows: int
    bytes: int


@dataclasses.dataclass(frozen=True)
class Column:
    name: str
    data_type: str
    is_nullable: bool
    default: str | None


@dataclasses.dataclass(frozen=True)
class ViewInfo:
    name: str
    has_rows: bool | None
    definition_sql: str
    columns: list[Column]


@dataclasses.dataclass(frozen=True)
class FunctionInfo:
    name: str
    args: str
    returns: str
    volatility: str
    security_definer: bool
    language: str


@dataclasses.dataclass(frozen=True)
class TriggerInfo:
    name: str
    table: str
    function: str
    definition_sql: str


@dataclasses.dataclass(frozen=True)
class PartitionInfo:
    parent: str
    child: str
    bound: str
    est_rows: int
    bytes: int


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw in dotenv_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip("'").strip('"')
        os.environ.setdefault(k, v)


def require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def psql_json(db_url: str, db_password: str, sql: str, timeout_s: int = 60) -> Any:
    env = os.environ.copy()
    env["PGPASSWORD"] = db_password
    env.setdefault("PGSSLMODE", "require")
    cmd = ["psql", "-X", db_url, "-v", "ON_ERROR_STOP=1", "-q", "-t", "-A", "-c", sql]
    out = subprocess.check_output(cmd, env=env, stderr=subprocess.STDOUT, timeout=timeout_s)
    s = out.decode("utf-8", errors="replace").strip()
    return None if not s else json.loads(s)


def fmt_bytes(n: int) -> str:
    # Human-ish, stable, no locales.
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n = n / 1024
    return f"{n:.1f}TB"


def md_table(rows: list[list[str]], headers: list[str]) -> str:
    out: list[str] = []
    out.append("| " + " | ".join(headers) + " |")
    out.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def get_db_meta(db_url: str, db_password: str) -> dict[str, str]:
    q = """
    select jsonb_build_object(
      'now_utc', to_char(now() at time zone 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'),
      'server_version', current_setting('server_version'),
      'server_version_num', current_setting('server_version_num'),
      'db_name', current_database(),
      'search_path', current_setting('search_path')
    );
    """
    return psql_json(db_url, db_password, q, timeout_s=20)


def get_table_inventory(db_url: str, db_password: str, schema: str) -> list[TableStat]:
    q = f"""
    with objs as (
      select c.oid, c.relname, c.relkind
      from pg_class c
      join pg_namespace n on n.oid=c.relnamespace
      where n.nspname = '{schema}'
        and c.relkind in ('r','p','v','m')
    ),
    stats as (
      select relid, n_live_tup::bigint as est_rows, pg_total_relation_size(relid)::bigint as bytes
      from pg_stat_user_tables
      where schemaname = '{schema}'
    )
    select jsonb_agg(jsonb_build_object(
      'name', o.relname,
      'relkind', o.relkind,
      'est_rows', coalesce(s.est_rows, 0),
      'bytes', coalesce(s.bytes, 0)
    ) order by o.relname)
    from objs o
    left join stats s on s.relid = o.oid;
    """
    raw = psql_json(db_url, db_password, q)
    out: list[TableStat] = []
    kind_map = {"r": "table", "p": "partitioned_table", "v": "view", "m": "matview"}
    for r in raw or []:
        out.append(
            TableStat(
                name=str(r["name"]),
                kind=kind_map.get(str(r["relkind"]), "other"),
                est_rows=int(r["est_rows"]),
                bytes=int(r["bytes"]),
            )
        )
    return out


def get_columns(db_url: str, db_password: str, schema: str) -> dict[str, list[Column]]:
    q = f"""
    select jsonb_agg(jsonb_build_object(
      'table_name', table_name,
      'column_name', column_name,
      'data_type', data_type,
      'is_nullable', is_nullable,
      'column_default', column_default
    ) order by table_name, ordinal_position)
    from information_schema.columns
    where table_schema = '{schema}';
    """
    raw = psql_json(db_url, db_password, q)
    by_table: dict[str, list[Column]] = {}
    for r in raw or []:
        t = str(r["table_name"])
        by_table.setdefault(t, []).append(
            Column(
                name=str(r["column_name"]),
                data_type=str(r["data_type"]),
                is_nullable=(str(r["is_nullable"]).upper() == "YES"),
                default=(None if r["column_default"] is None else str(r["column_default"])),
            )
        )
    return by_table


def get_views(db_url: str, db_password: str, schema: str, columns_by_table: dict[str, list[Column]]) -> list[ViewInfo]:
    # We keep `has_rows` best-effort with a short statement_timeout; if it times out, mark as None.
    q_views = f"""
    select jsonb_agg(jsonb_build_object('view_name', table_name) order by table_name)
    from information_schema.views
    where table_schema = '{schema}';
    """
    raw = psql_json(db_url, db_password, q_views)
    view_names = [str(r["view_name"]) for r in (raw or [])]
    if not view_names:
        return []

    # view definitions
    q_defs = f"""
    select jsonb_agg(jsonb_build_object(
      'view_name', c.relname,
      'definition', pg_get_viewdef(c.oid, true)
    ) order by c.relname)
    from pg_class c
    join pg_namespace n on n.oid=c.relnamespace
    where n.nspname='{schema}' and c.relkind='v';
    """
    defs_raw = psql_json(db_url, db_password, q_defs)
    defs = {str(r["view_name"]): str(r["definition"]) for r in (defs_raw or [])}

    infos: list[ViewInfo] = []
    for vn in view_names:
        has_rows: bool | None
        try:
            # Small timeout so we don't hang on expensive views.
            q_has = f"set local statement_timeout='750ms'; select jsonb_build_object('has_rows', exists(select 1 from {schema}.{vn} limit 1));"
            hr = psql_json(db_url, db_password, q_has, timeout_s=10)
            has_rows = bool(hr.get("has_rows"))
        except Exception:
            has_rows = None

        infos.append(
            ViewInfo(
                name=vn,
                has_rows=has_rows,
                definition_sql=defs.get(vn, ""),
                columns=columns_by_table.get(vn, []),
            )
        )
    return infos


def get_functions(db_url: str, db_password: str, schema: str) -> list[FunctionInfo]:
    q = f"""
    select jsonb_agg(jsonb_build_object(
      'proname', p.proname,
      'args', pg_get_function_identity_arguments(p.oid),
      'returns', pg_get_function_result(p.oid),
      'volatility', case p.provolatile when 'i' then 'IMMUTABLE' when 's' then 'STABLE' else 'VOLATILE' end,
      'security_definer', p.prosecdef,
      'language', l.lanname
    ) order by p.proname, pg_get_function_identity_arguments(p.oid))
    from pg_proc p
    join pg_namespace n on n.oid=p.pronamespace
    join pg_language l on l.oid=p.prolang
    where n.nspname='{schema}';
    """
    raw = psql_json(db_url, db_password, q)
    out: list[FunctionInfo] = []
    for r in raw or []:
        out.append(
            FunctionInfo(
                name=str(r["proname"]),
                args=str(r["args"]),
                returns=str(r["returns"]),
                volatility=str(r["volatility"]),
                security_definer=bool(r["security_definer"]),
                language=str(r["language"]),
            )
        )
    return out


def get_triggers_calling_schema_functions(db_url: str, db_password: str, schema: str) -> list[TriggerInfo]:
    # Triggers can live on any table (often public), but we care about those invoking functions in `schema`.
    q = f"""
    select jsonb_agg(jsonb_build_object(
      'tgname', t.tgname,
      'table', t.tgrelid::regclass::text,
      'function', pn.nspname || '.' || p.proname,
      'def', pg_get_triggerdef(t.oid, true)
    ) order by t.tgrelid::regclass::text, t.tgname)
    from pg_trigger t
    join pg_proc p on p.oid=t.tgfoid
    join pg_namespace pn on pn.oid=p.pronamespace
    where not t.tgisinternal
      and pn.nspname = '{schema}';
    """
    raw = psql_json(db_url, db_password, q)
    out: list[TriggerInfo] = []
    for r in raw or []:
        out.append(
            TriggerInfo(
                name=str(r["tgname"]),
                table=str(r["table"]),
                function=str(r["function"]),
                definition_sql=str(r["def"]),
            )
        )
    return out


def get_partitions(db_url: str, db_password: str, schema: str) -> list[PartitionInfo]:
    q = f"""
    with inh as (
      select
        pn.nspname as parent_schema,
        p.relname as parent,
        p.relkind as parent_kind,
        cn.nspname as child_schema,
        c.relname as child,
        c.relkind as child_kind,
        pg_get_expr(c.relpartbound, c.oid, true) as bound,
        c.oid as child_oid
      from pg_inherits i
      join pg_class p on p.oid=i.inhparent
      join pg_namespace pn on pn.oid=p.relnamespace
      join pg_class c on c.oid=i.inhrelid
      join pg_namespace cn on cn.oid=c.relnamespace
      where pn.nspname='{schema}' and cn.nspname='{schema}'
    ),
    stats as (
      select relid, n_live_tup::bigint as est_rows, pg_total_relation_size(relid)::bigint as bytes
      from pg_stat_user_tables
      where schemaname='{schema}'
    )
    select jsonb_agg(jsonb_build_object(
      'parent', inh.parent,
      'child', inh.child,
      'bound', inh.bound,
      'est_rows', coalesce(s.est_rows, 0),
      'bytes', coalesce(s.bytes, 0)
    ) order by inh.parent, inh.child)
    from inh
    left join stats s on s.relid=inh.child_oid
    where inh.parent_kind='p' and inh.child_kind='r';
    """
    raw = psql_json(db_url, db_password, q)
    out: list[PartitionInfo] = []
    for r in raw or []:
        out.append(
            PartitionInfo(
                parent=str(r["parent"]),
                child=str(r["child"]),
                bound=str(r["bound"]),
                est_rows=int(r["est_rows"]),
                bytes=int(r["bytes"]),
            )
        )
    return out


def render_schema_doc(
    *,
    schema: str,
    title: str,
    purpose: str,
    uniqueness: list[str],
    update_mechanics: list[str],
    db_meta: dict[str, str],
    inventory: list[TableStat],
    columns_by_table: dict[str, list[Column]],
    views: list[ViewInfo],
    functions: list[FunctionInfo],
    triggers: list[TriggerInfo],
    partitions: list[PartitionInfo],
) -> str:
    generated_at = db_meta["now_utc"]

    populated = [t for t in inventory if t.kind in ("table", "partitioned_table", "matview") and t.est_rows > 0]
    empty = [t for t in inventory if t.kind in ("table", "partitioned_table", "matview") and t.est_rows == 0]

    # Markdown
    out: list[str] = []
    out.append(f"# {title}")
    out.append("")
    out.append("```yaml")
    out.append(f"schema: {schema}")
    out.append(f"generated_at_utc: {generated_at}")
    out.append(f"server_version: {db_meta.get('server_version')}")
    out.append(f"database: {db_meta.get('db_name')}")
    out.append("```")
    out.append("")
    out.append("## Purpose")
    out.append(purpose.strip())
    out.append("")
    out.append("## Uniqueness")
    for line in uniqueness:
        out.append(f"- {line}")
    out.append("")
    out.append("## Update Mechanics")
    for line in update_mechanics:
        out.append(f"- {line}")
    out.append("")

    out.append("## Objects (TLDR)")
    out.append(
        md_table(
            rows=[
                [
                    str(sum(1 for t in inventory if t.kind in ('table','partitioned_table'))),
                    str(len(views)),
                    str(len(functions)),
                    str(len(triggers)),
                    str(len(partitions)),
                ]
            ],
            headers=["tables", "views", "functions", "triggers_calling_schema_fns", "partitions"],
        )
    )
    out.append("")

    out.append("## Tables With Data")
    if not populated:
        out.append("_None._")
    else:
        out.append(
            md_table(
                rows=[
                    [t.name, t.kind, f"{t.est_rows}", fmt_bytes(t.bytes)]
                    for t in sorted(populated, key=lambda x: (-x.est_rows, x.name))
                ],
                headers=["table", "kind", "est_rows (n_live_tup)", "size"],
            )
        )
    out.append("")

    out.append("## Tables Without Data (Est Rows = 0)")
    if not empty:
        out.append("_None._")
    else:
        out.append(
            md_table(
                rows=[[t.name, t.kind] for t in sorted(empty, key=lambda x: x.name)],
                headers=["table", "kind"],
            )
        )
    out.append("")

    if partitions:
        out.append("## Partitions")
        out.append(
            md_table(
                rows=[
                    [p.parent, p.child, p.bound, f"{p.est_rows}", fmt_bytes(p.bytes)]
                    for p in sorted(partitions, key=lambda x: (x.parent, x.child))
                ],
                headers=["parent", "child", "bound", "est_rows", "size"],
            )
        )
        out.append("")

    if views:
        out.append("## Views")
        out.append(
            md_table(
                rows=[
                    [v.name, "true" if v.has_rows else ("false" if v.has_rows is False else "unknown")]
                    for v in sorted(views, key=lambda x: x.name)
                ],
                headers=["view", "has_rows (best-effort)"],
            )
        )
        out.append("")

        out.append("## View Definitions")
        for v in sorted(views, key=lambda x: x.name):
            out.append(f"### {schema}.{v.name}")
            out.append("")
            if v.columns:
                out.append(
                    md_table(
                        rows=[
                            [c.name, c.data_type, "YES" if c.is_nullable else "NO"]
                            for c in v.columns
                        ],
                        headers=["column", "data_type", "nullable"],
                    )
                )
                out.append("")
            if v.definition_sql:
                out.append("```sql")
                out.append(v.definition_sql.strip())
                out.append("```")
            else:
                out.append("_Definition not available via pg_get_viewdef._")
            out.append("")

    if functions:
        out.append("## Functions")
        out.append(
            md_table(
                rows=[
                    [f.name, f"({f.args})", f.returns, f.volatility, "YES" if f.security_definer else "NO", f.language]
                    for f in functions
                ],
                headers=["name", "args", "returns", "volatility", "security_definer", "language"],
            )
        )
        out.append("")

    if triggers:
        out.append("## Triggers Calling This Schema’s Functions")
        out.append(
            md_table(
                rows=[[t.table, t.name, t.function] for t in triggers],
                headers=["table", "trigger", "function"],
            )
        )
        out.append("")
        out.append("## Trigger Definitions")
        for t in triggers:
            out.append(f"### {t.table} :: {t.name}")
            out.append("")
            out.append(f"- function: `{t.function}`")
            out.append("```sql")
            out.append(t.definition_sql.strip())
            out.append("```")
            out.append("")

    out.append("## Column Reference (Populated Tables Only)")
    for t in sorted(populated, key=lambda x: x.name):
        cols = columns_by_table.get(t.name, [])
        out.append(f"### {schema}.{t.name}")
        out.append("")
        if not cols:
            out.append("_No columns found (unexpected)._")
            out.append("")
            continue
        out.append(
            md_table(
                rows=[
                    [
                        c.name,
                        c.data_type,
                        "YES" if c.is_nullable else "NO",
                        "" if c.default is None else c.default,
                    ]
                    for c in cols
                ],
                headers=["column", "data_type", "nullable", "default"],
            )
        )
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def write_doc(path: Path, content: str) -> None:
    path.write_text(content)


def main() -> int:
    load_dotenv(DOTENV)
    db_url = require_env("SUPABASE_DB_URL")
    db_password = require_env("SUPABASE_DB_PASSWORD")

    db_meta = get_db_meta(db_url, db_password)

    # INDICATORS
    ind_inventory = get_table_inventory(db_url, db_password, "indicators")
    ind_cols = get_columns(db_url, db_password, "indicators")
    ind_views = get_views(db_url, db_password, "indicators", ind_cols)
    ind_functions = get_functions(db_url, db_password, "indicators")
    ind_triggers = get_triggers_calling_schema_functions(db_url, db_password, "indicators")
    ind_partitions = get_partitions(db_url, db_password, "indicators")

    indicators_doc = render_schema_doc(
        schema="indicators",
        title="INDICATORS_SCHEMA",
        purpose=(
            "Real-time computation layer for technical indicators.\n\n"
            "Consumes 1m OHLCV candles and produces:\n"
            "- multi-timeframe OHLCV rollups (`ohlcv_5m`..`ohlcv_12h`)\n"
            "- long-form indicator outputs in weekly partitions (`indicator_values_wYYYY_WW`)\n"
            "- order book derived indicators (`order_book_indicators`)\n"
            "- operational metadata (`job_queue`, `computation_log`, `readme`)\n"
        ),
        uniqueness=[
            "Config-driven indicator computation via `indicator_configs` (JSONB params, 156 active configs).",
            "Long-table design for indicators: `indicator_values(pair, bucket_time, config_id, v1..v5)`.",
            "Weekly partitioning for `indicator_values` to keep partitions manageable for recent-only queries.",
            "Separate OHLCV tables per timeframe for query isolation and predictable access paths.",
        ],
        update_mechanics=[
            "Trade ingestion happens upstream in `public` and then cascades here via trigger + job queue orchestration.",
            "`fn_process_new_trade` is a SECURITY DEFINER trigger function used to keep ingestion fast.",
            "Rollups are performed via `fn_rollup_ohlcv` / `fn_cascade_timeframes` and backfills via `fn_backfill_ohlcv`.",
            "Indicator computation runs via `fn_compute_all_indicators` and is decoupled through `job_queue`.",
        ],
        db_meta=db_meta,
        inventory=ind_inventory,
        columns_by_table=ind_cols,
        views=ind_views,
        functions=ind_functions,
        triggers=ind_triggers,
        partitions=ind_partitions,
    )
    write_doc(ROOT / "INDICATORS_SCHEMA.md", indicators_doc)

    # TRAINING
    tr_inventory = get_table_inventory(db_url, db_password, "training")
    tr_cols = get_columns(db_url, db_password, "training")
    tr_views = get_views(db_url, db_password, "training", tr_cols)
    tr_functions = get_functions(db_url, db_password, "training")
    tr_triggers = get_triggers_calling_schema_functions(db_url, db_password, "training")
    tr_partitions = get_partitions(db_url, db_password, "training")

    training_doc = render_schema_doc(
        schema="training",
        title="TRAINING_SCHEMA",
        purpose=(
            "Historical ML feature engineering layer.\n\n"
            "Contains multi-year spot OHLCV data and enriched indicator tables for model training.\n"
            "This schema is primarily batch-populated and is not the real-time ingestion path.\n"
        ),
        uniqueness=[
            "Large historical datasets (`spot_1m`, `spot_15m`, `spot_1h`) with consistent primary keys by (symbol, ts/open_time).",
            "Wide indicator-enriched tables (`spot_15m_indicators`, `spot_1h_indicators`).",
            "Curated training-ready tables (`unified_15m`, `unified_1h`) and pattern signals (`synthetic_features`).",
            "Reserved-but-empty Polymarket feature tables (planned integration).",
        ],
        update_mechanics=[
            "Historical tables are populated via offline/batch loads (not by the live streamer).",
            "No training-schema stored functions are currently defined; transformations appear to be external/script-driven.",
        ],
        db_meta=db_meta,
        inventory=tr_inventory,
        columns_by_table=tr_cols,
        views=tr_views,
        functions=tr_functions,
        triggers=tr_triggers,
        partitions=tr_partitions,
    )
    write_doc(ROOT / "TRAINING_SCHEMA.md", training_doc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
