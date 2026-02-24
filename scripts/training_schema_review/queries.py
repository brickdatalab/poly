from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Col:
    name: str
    data_type: str
    udt_name: str
    is_nullable: bool


def sql_list_columns(schema: str, relname: str) -> str:
    return f"""
    select coalesce(jsonb_agg(jsonb_build_object(
      'name', column_name,
      'data_type', data_type,
      'udt_name', udt_name,
      'is_nullable', (is_nullable='YES')
    ) order by ordinal_position), '[]'::jsonb)
    from information_schema.columns
    where table_schema = '{schema}'
      and table_name = '{relname}';
    """


def sql_training_inventory() -> str:
    return """
    with objs as (
      select
        c.relname,
        c.relkind,
        pg_total_relation_size(c.oid)::bigint as bytes,
        coalesce(s.n_live_tup::bigint, 0) as est_rows
      from pg_class c
      join pg_namespace n on n.oid=c.relnamespace
      left join pg_stat_user_tables s on s.relid=c.oid
      where n.nspname = 'training'
        and c.relkind in ('r','p','v','m')
    ),
    mapped as (
      select
        relname,
        case relkind
          when 'r' then 'table'
          when 'p' then 'partitioned_table'
          when 'v' then 'view'
          when 'm' then 'matview'
          else 'other'
        end as kind,
        est_rows,
        bytes
      from objs
    )
    select jsonb_build_object(
      'schema', 'training',
      'objects', coalesce(jsonb_agg(to_jsonb(mapped) order by kind, relname), '[]'::jsonb)
    )
    from mapped;
    """


def sql_time_coverage(table: str, symbol_col: str, ts_col: str) -> str:
    return f"""
    with agg as (
      select
        case when grouping({symbol_col})=1 then '__overall__' else {symbol_col} end as symbol,
        count(*)::bigint as n_rows,
        min({ts_col}) as min_ts,
        max({ts_col}) as max_ts
      from {table}
      group by grouping sets (({symbol_col}), ())
    )
    select coalesce(jsonb_agg(to_jsonb(agg) order by symbol), '[]'::jsonb) from agg;
    """


def sql_distinct_values(table: str, col: str, limit: int = 50) -> str:
    return f"""
    with vals as (
      select {col} as v, count(*)::bigint as n
      from {table}
      group by {col}
      order by count(*) desc
      limit {limit}
    )
    select coalesce(jsonb_agg(to_jsonb(vals) order by n desc), '[]'::jsonb) from vals;
    """


def sql_duplicate_key_count(table: str, key_cols: Iterable[str]) -> str:
    cols = ", ".join(key_cols)
    return f"""
    with d as (
      select {cols}, count(*)::bigint as n
      from {table}
      group by {cols}
      having count(*) > 1
    )
    select jsonb_build_object(
      'duplicate_keys', (select count(*) from d),
      'duplicate_rows_extra', (select coalesce(sum(n-1),0) from d)
    );
    """


def sql_candle_invariants(
    *,
    table: str,
    symbol_col: str,
    ts_col: str,
    timeframe: str,
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    volume_col: str = "volume",
) -> str:
    if timeframe == "1m":
        offgrid = f"({ts_col} != date_trunc('minute', {ts_col}))"
    elif timeframe == "15m":
        offgrid = f"(extract(second from {ts_col}) != 0 or (extract(minute from {ts_col})::int % 15) != 0)"
    elif timeframe == "1h":
        offgrid = f"(extract(second from {ts_col}) != 0 or extract(minute from {ts_col}) != 0)"
    else:
        offgrid = "false"

    return f"""
    with agg as (
      select
        case when grouping({symbol_col})=1 then '__overall__' else {symbol_col} end as symbol,
        count(*)::bigint as n_rows,
        count(*) filter (where {open_col} is null)::bigint as n_open_null,
        count(*) filter (where {high_col} is null)::bigint as n_high_null,
        count(*) filter (where {low_col} is null)::bigint as n_low_null,
        count(*) filter (where {close_col} is null)::bigint as n_close_null,
        count(*) filter (where {volume_col} is null)::bigint as n_volume_null,
        count(*) filter (where {offgrid})::bigint as n_offgrid,
        count(*) filter (where {volume_col} < 0)::bigint as n_neg_volume,
        count(*) filter (where {high_col} < {low_col})::bigint as n_high_lt_low,
        count(*) filter (where {high_col} < greatest({open_col}, {close_col}, {low_col}))::bigint as n_high_lt_ohlc,
        count(*) filter (where {low_col} > least({open_col}, {close_col}, {high_col}))::bigint as n_low_gt_ohlc,
        min({ts_col}) as min_ts,
        max({ts_col}) as max_ts
      from {table}
      group by grouping sets (({symbol_col}), ())
    )
    select jsonb_build_object(
      'table', '{table}',
      'timeframe', '{timeframe}',
      'ts_col', '{ts_col}',
      'symbol_col', '{symbol_col}',
      'groups', coalesce(jsonb_agg(to_jsonb(agg) order by symbol), '[]'::jsonb)
    ) from agg;
    """


def _bounds_rule_for_col(col: str) -> tuple[str, float, float] | None:
    c = col.lower()
    if c == "rsi" or c.startswith("rsi_"):
        return ("range_0_100", 0.0, 100.0)
    if c.startswith("mfi_") or c == "mfi":
        return ("range_0_100", 0.0, 100.0)
    if c.startswith("adx_") or c == "adx":
        return ("range_0_100", 0.0, 100.0)
    if c.startswith("stoch") or c.startswith("stoch_") or c.startswith("stochrsi") or c.startswith("stoch_rsi"):
        return ("range_0_100", 0.0, 100.0)
    if "williams" in c:
        return ("range_-100_0", -100.0, 0.0)
    if c.startswith("cmf_") or c == "cmf" or c.startswith("bop_") or c == "bop":
        return ("range_-1_1", -1.0, 1.0)
    # Only apply R^2 bounds when it's actually an R^2 metric, not a pivot resistance label.
    if (c.endswith("_r2") or c.endswith("_rsq") or c.endswith("_r_squared")) and "linreg" in c:
        return ("range_0_1", 0.0, 1.0)
    if c.startswith("atr_") or c == "atr":
        return ("min_0", 0.0, 0.0)
    return None


def sql_feature_stats_single_scan(
    *,
    table: str,
    symbol_col: str,
    ts_col: str,
    feature_cols: list[str],
    deep_percentiles: bool,
) -> str:
    # Single scan per table using GROUPING SETS ((symbol), ()).
    # Output: JSON {table, groups:[{symbol,n_rows,features:{col:{...}}}, ...]}
    pairs: list[str] = []
    for col in feature_cols:
        rule = _bounds_rule_for_col(col)
        bounds_expr = "0"
        bounds_kind = "none"
        if rule:
            bounds_kind = rule[0]
            if bounds_kind == "min_0":
                bounds_expr = f"sum(case when {col} is null then 0 when {col} < 0 then 1 else 0 end)"
            else:
                lo, hi = rule[1], rule[2]
                bounds_expr = f"sum(case when {col} is null then 0 when {col} < {lo} or {col} > {hi} then 1 else 0 end)"

        pct = ""
        if deep_percentiles:
            # percentile_cont ignores nulls; cast to float8 for stability
            pct = (
                f", 'p50', percentile_cont(0.5) within group (order by {col}::float8)"
                f", 'p90', percentile_cont(0.9) within group (order by {col}::float8)"
                f", 'p99', percentile_cont(0.99) within group (order by {col}::float8)"
            )

        pairs.append(
            "    "
            + f"'{col}', jsonb_build_object("
            + f"'n_nonnull', count({col})"
            + f", 'n_null', sum(case when {col} is null then 1 else 0 end)"
            + f", 'mean', avg({col}::float8)"
            + f", 'stddev', stddev_samp({col}::float8)"
            + f", 'min', min({col}::float8)"
            + f", 'max', max({col}::float8)"
            # Detect NaN/Inf without relying on isfinite() availability.
            + f", 'not_finite', sum(case when {col} is null then 0 "
            + f"when ({col}::float8 <> {col}::float8) then 1 "
            + f"when ({col}::float8 = 'Infinity'::float8 or {col}::float8 = '-Infinity'::float8) then 1 "
            + f"else 0 end)"
            + f", 'bounds_kind', '{bounds_kind}'"
            + f", 'bounds_violations', {bounds_expr}"
            + pct
            + ")"
        )

    # jsonb_build_object has a hard limit on number of arguments (100),
    # so we chunk the key/value pairs and merge JSON objects with ||.
    if not pairs:
        features_expr = "jsonb_build_object()"
    else:
        chunk_size = 45  # 45 key/value pairs => 90 args, safely under 100
        chunks: list[list[str]] = []
        cur: list[str] = []
        for p in pairs:
            cur.append(p)
            if len(cur) >= chunk_size:
                chunks.append(cur)
                cur = []
        if cur:
            chunks.append(cur)

        exprs = []
        for ch in chunks:
            exprs.append("jsonb_build_object(\n" + ",\n".join(ch) + "\n        )")
        features_expr = (" ||\n        ").join(exprs)
    return f"""
    with agg as (
      select
        case when grouping({symbol_col})=1 then '__overall__' else {symbol_col} end as symbol,
        count(*)::bigint as n_rows,
        min({ts_col}) as min_ts,
        max({ts_col}) as max_ts,
        (
        {features_expr}
        ) as features
      from {table}
      group by grouping sets (({symbol_col}), ())
    )
    select jsonb_build_object(
      'table', '{table}',
      'symbol_col', '{symbol_col}',
      'ts_col', '{ts_col}',
      'deep_percentiles', {str(deep_percentiles).lower()},
      'groups', coalesce(jsonb_agg(to_jsonb(agg) order by symbol), '[]'::jsonb)
    )
    from agg;
    """
