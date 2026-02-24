from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from alpha_v4.config import PAIR_BY_SYMBOL
from alpha_v4.db import fetch_all, fetch_one, get_connection
from alpha_v4.time_utils import parse_iso_utc

SYMBOLS = ("BTC", "ETH", "SOL")
TIMEFRAMES = ("15m", "1h")
OHLCV_TABLE_BY_TIMEFRAME = {
    "15m": "indicators.ohlcv_15m",
    "1h": "indicators.ohlcv_1h",
}
FEATURE_TABLE_BY_TIMEFRAME = {
    "15m": "alpha_v4.features_15m",
    "1h": "alpha_v4.features_1h",
}
INTERVAL_BY_TIMEFRAME = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
}
CORE_FEATURE_COLUMNS_BY_TIMEFRAME = {
    "15m": (
        "rsi_14_pct_20",
        "macd_hist_slope_3",
        "hour_sin",
        "hour_cos",
        "dow_sin",
        "dow_cos",
        "trend_1h_alignment",
        "volatility_ratio_1h",
        "rsi_15m_vs_1h",
        "price_vs_1h_vwap",
        "is_1h_bullish",
    ),
    "1h": (
        "rsi_14_pct_20",
        "macd_hist_slope_3",
        "hour_sin",
        "hour_cos",
        "dow_sin",
        "dow_cos",
        "trend_4h_alignment",
        "trend_daily_alignment",
        "volatility_ratio_4h",
        "rsi_1h_vs_4h",
        "price_vs_daily_sma_20",
    ),
}
TEMPORAL_COLUMNS = ("hour_sin", "hour_cos", "dow_sin", "dow_cos")
CHECK_STATUS_PASS = "PASS"
CHECK_STATUS_WARN = "WARN"
CHECK_STATUS_FAIL = "FAIL"


@dataclass
class CheckResult:
    name: str
    passed: bool
    details: str
    status: str | None = None

    def __post_init__(self) -> None:
        if self.status is None:
            self.status = CHECK_STATUS_PASS if self.passed else CHECK_STATUS_FAIL
        self.status = self.status.upper()
        if self.status == CHECK_STATUS_WARN:
            self.passed = True
        elif self.status == CHECK_STATUS_PASS:
            self.passed = True
        else:
            self.passed = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "passed": self.passed,
            "details": self.details,
        }


@dataclass
class Check:
    name: str
    run: Callable[[Any], CheckResult]


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _bool_details(value: bool, success: str, failure: str) -> tuple[bool, str]:
    return (True, success) if value else (False, failure)


def _result(name: str, status: str, details: str) -> CheckResult:
    return CheckResult(
        name=name,
        passed=status in {CHECK_STATUS_PASS, CHECK_STATUS_WARN},
        details=details,
        status=status,
    )


def _pass(name: str, details: str) -> CheckResult:
    return _result(name, CHECK_STATUS_PASS, details)


def _warn(name: str, details: str) -> CheckResult:
    return _result(name, CHECK_STATUS_WARN, details)


def _fail(name: str, details: str) -> CheckResult:
    return _result(name, CHECK_STATUS_FAIL, details)


def _list_columns(
    connection,
    *,
    schema_name: str,
    table_name: str,
    like_pattern: str | None = None,
) -> list[str]:
    query = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
    """
    params: list[Any] = [schema_name, table_name]
    if like_pattern:
        query += " AND column_name LIKE %s"
        params.append(like_pattern)
    query += " ORDER BY ordinal_position"
    rows = fetch_all(connection, query, tuple(params))
    return [row["column_name"] for row in rows]


def _table_parts(table_name: str) -> tuple[str, str]:
    schema_name, bare_name = table_name.split(".", 1)
    return schema_name, bare_name


def _floor_to_timeframe(moment: datetime, timeframe: str) -> datetime:
    moment = moment.astimezone(timezone.utc)
    if timeframe == "15m":
        return moment.replace(minute=(moment.minute // 15) * 15, second=0, microsecond=0)
    if timeframe == "1h":
        return moment.replace(minute=0, second=0, microsecond=0)
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def _window_bounds(as_of: datetime, timeframe: str, lookback_days: int) -> tuple[datetime, datetime]:
    interval = INTERVAL_BY_TIMEFRAME[timeframe]
    closed_end = _floor_to_timeframe(as_of, timeframe) - interval
    closed_start = closed_end - timedelta(days=lookback_days) + interval
    return closed_start, closed_end


def _check_schema_exists(connection) -> CheckResult:
    row = fetch_one(
        connection,
        """
        SELECT COUNT(*)::int AS count
        FROM information_schema.schemata
        WHERE schema_name = 'alpha_v4'
        """,
    )
    passed, details = _bool_details(
        row["count"] == 1,
        "alpha_v4 schema exists.",
        "alpha_v4 schema missing.",
    )
    return CheckResult("Schema created", passed, details)


def _check_required_tables(connection) -> CheckResult:
    expected = {
        "models",
        "raw_features_15m",
        "raw_features_1h",
        "features_15m",
        "features_1h",
        "synthetic_indicators",
        "labels",
        "predictions",
        "performance_log",
        "schema_migrations",
        "pipeline_runs",
    }
    rows = fetch_all(
        connection,
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'alpha_v4'
        """,
    )
    found = {row["table_name"] for row in rows}
    missing = sorted(expected - found)
    passed, details = _bool_details(
        len(missing) == 0,
        "All required tables are present.",
        f"Missing tables: {', '.join(missing)}",
    )
    return CheckResult("Tables created", passed, details)


def _check_primary_keys(connection) -> CheckResult:
    row = fetch_one(
        connection,
        """
        SELECT COUNT(*)::int AS count
        FROM information_schema.table_constraints
        WHERE table_schema = 'alpha_v4'
          AND constraint_type = 'PRIMARY KEY'
        """,
    )
    passed, details = _bool_details(
        row["count"] >= 9,
        f"Found {row['count']} primary keys.",
        f"Only {row['count']} primary keys found.",
    )
    return CheckResult("Primary keys set", passed, details)


def _check_prediction_indexes(connection) -> CheckResult:
    rows = fetch_all(
        connection,
        """
        SELECT indexname
        FROM pg_indexes
        WHERE schemaname = 'alpha_v4'
          AND tablename = 'predictions'
        """,
    )
    names = {row["indexname"] for row in rows}
    required = {
        "idx_alpha_v4_predictions_symbol_timeframe_event",
        "idx_alpha_v4_predictions_created_at",
        "idx_alpha_v4_predictions_resolved_at",
    }
    missing = sorted(required - names)
    passed, details = _bool_details(
        len(missing) == 0,
        "Prediction indexes present.",
        f"Missing prediction indexes: {', '.join(missing)}",
    )
    return CheckResult("Indexes created", passed, details)


def _check_feature_column_count(connection) -> CheckResult:
    row_15m = fetch_one(
        connection,
        """
        SELECT COUNT(*)::int AS count
        FROM information_schema.columns
        WHERE table_schema = 'alpha_v4'
          AND table_name = 'features_15m'
        """,
    )
    row_1h = fetch_one(
        connection,
        """
        SELECT COUNT(*)::int AS count
        FROM information_schema.columns
        WHERE table_schema = 'alpha_v4'
          AND table_name = 'features_1h'
        """,
    )
    passed = row_15m["count"] > 180 and row_1h["count"] > 180
    details = f"features_15m={row_15m['count']} columns, features_1h={row_1h['count']} columns."
    return CheckResult("Feature count met", passed, details)


def _check_labels_coverage(connection) -> CheckResult:
    rows = fetch_all(
        connection,
        """
        SELECT symbol, timeframe, COUNT(*)::int AS count
        FROM alpha_v4.labels
        GROUP BY symbol, timeframe
        """,
    )
    combos = {(row["symbol"], row["timeframe"]) for row in rows}
    expected = {
        ("BTC", "15m"),
        ("ETH", "15m"),
        ("SOL", "15m"),
        ("BTC", "1h"),
        ("ETH", "1h"),
        ("SOL", "1h"),
    }
    missing = expected - combos
    passed, details = _bool_details(
        len(missing) == 0 and len(rows) >= 6,
        "All label symbol/timeframe combinations present.",
        f"Missing label combinations: {sorted(missing)}",
    )
    return CheckResult("Labels created", passed, details)


def _check_label_binary_mapping(connection) -> CheckResult:
    rows = fetch_all(
        connection,
        """
        SELECT label, label_binary
        FROM alpha_v4.labels
        WHERE label IN ('UP', 'DOWN')
        LIMIT 1000
        """,
    )
    if not rows:
        return CheckResult("Label binary mapping", False, "No labels available.")
    valid = True
    for row in rows:
        if row["label"] == "UP" and int(row["label_binary"]) != 1:
            valid = False
        if row["label"] == "DOWN" and int(row["label_binary"]) != 0:
            valid = False
    passed, details = _bool_details(
        valid,
        "UP/DOWN binary mapping is consistent.",
        "Found inconsistent label_binary mapping.",
    )
    return CheckResult("Next label binary correct", passed, details)


def _check_predictions_data_quality(connection) -> CheckResult:
    row = fetch_one(
        connection,
        """
        SELECT
            COUNT(*)::int AS total,
            SUM(CASE WHEN ensemble_probability < 0 OR ensemble_probability > 1 THEN 1 ELSE 0 END)::int AS bad_prob,
            SUM(CASE WHEN position_size < 1 OR position_size > 10 THEN 1 ELSE 0 END)::int AS bad_size,
            SUM(CASE WHEN confidence_tier NOT IN ('HIGH', 'MED', 'LOW') THEN 1 ELSE 0 END)::int AS bad_tier
        FROM alpha_v4.predictions
        """,
    )
    if row["total"] == 0:
        return CheckResult("Prediction data quality", False, "No predictions found.")
    passed = row["bad_prob"] == 0 and row["bad_size"] == 0 and row["bad_tier"] == 0
    details = (
        f"total={row['total']}, bad_prob={row['bad_prob']}, "
        f"bad_size={row['bad_size']}, bad_tier={row['bad_tier']}"
    )
    return CheckResult("Prediction data quality", passed, details)


def _check_resolution_backlog(connection) -> CheckResult:
    row = fetch_one(
        connection,
        """
        SELECT COUNT(*)::int AS pending
        FROM alpha_v4.predictions
        WHERE event_end < now() - interval '5 minutes'
          AND resolved_at IS NULL
        """,
    )
    passed, details = _bool_details(
        row["pending"] == 0,
        "No stale unresolved predictions.",
        f"{row['pending']} unresolved predictions are stale.",
    )
    return CheckResult("Resolution pipeline", passed, details)


def _check_view_exists(connection) -> CheckResult:
    row = fetch_one(
        connection,
        """
        SELECT COUNT(*)::int AS count
        FROM pg_views
        WHERE schemaname = 'alpha_v4'
          AND viewname = 'v_predictions_results'
        """,
    )
    passed, details = _bool_details(
        row["count"] == 1,
        "v_predictions_results exists.",
        "v_predictions_results is missing.",
    )
    return CheckResult("Prediction results view", passed, details)


def _check_view_columns(connection) -> CheckResult:
    expected = {
        "symbol",
        "timeframe",
        "event_start",
        "event_end",
        "bet",
        "magnitude",
        "probability",
        "confidence_tier",
        "actual_result",
        "is_correct",
        "result_display",
        "start_price",
        "end_price",
        "pct_change",
        "created_at",
    }
    rows = fetch_all(
        connection,
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'alpha_v4'
          AND table_name = 'v_predictions_results'
        """,
    )
    found = {row["column_name"] for row in rows}
    missing = sorted(expected - found)
    passed, details = _bool_details(
        len(missing) == 0,
        "View columns match expected output.",
        f"Missing view columns: {', '.join(missing)}",
    )
    return CheckResult("View columns match", passed, details)


def _check_feature_freshness(connection) -> CheckResult:
    row_15m = fetch_one(connection, "SELECT max(bucket_time) AS ts FROM alpha_v4.features_15m")
    row_1h = fetch_one(connection, "SELECT max(bucket_time) AS ts FROM alpha_v4.features_1h")
    ts_15m = row_15m["ts"]
    ts_1h = row_1h["ts"]
    if ts_15m is None or ts_1h is None:
        return CheckResult("Feature freshness", False, "features_15m or features_1h has no rows.")
    src_15m = fetch_one(connection, "SELECT max(bucket_time) AS ts FROM indicators.v_model_15m")["ts"]
    src_1h = fetch_one(connection, "SELECT max(bucket_time) AS ts FROM indicators.v_model_1h")["ts"]

    if src_15m is None or src_1h is None:
        age_ok = (
            fetch_one(connection, "SELECT (%s >= now() - interval '20 minutes') AS ok", (ts_15m,))["ok"]
            and fetch_one(connection, "SELECT (%s >= now() - interval '70 minutes') AS ok", (ts_1h,))["ok"]
        )
        details = (
            "indicators source is empty; fallback to wall-clock freshness. "
            f"latest_15m={ts_15m}, latest_1h={ts_1h}"
        )
        return CheckResult("Features current", bool(age_ok), details)

    alignment_ok = (
        fetch_one(connection, "SELECT (%s >= %s) AS ok", (ts_15m, src_15m))["ok"]
        and fetch_one(connection, "SELECT (%s >= %s) AS ok", (ts_1h, src_1h))["ok"]
    )
    details = f"latest_15m={ts_15m} (src={src_15m}), latest_1h={ts_1h} (src={src_1h})"
    return CheckResult("Features current", bool(alignment_ok), details)


def _check_historical_data_complete(connection, as_of: datetime) -> CheckResult:
    baseline = datetime(2021, 1, 1, tzinfo=timezone.utc)
    failures: list[str] = []
    details: list[str] = []
    for timeframe in TIMEFRAMES:
        table_name = OHLCV_TABLE_BY_TIMEFRAME[timeframe]
        freshness_cutoff = as_of - (INTERVAL_BY_TIMEFRAME[timeframe] * 2)
        for symbol in SYMBOLS:
            pair = PAIR_BY_SYMBOL[symbol]
            row = fetch_one(
                connection,
                f"""
                SELECT
                    MIN(bucket_time) AS min_ts,
                    MAX(bucket_time) AS max_ts,
                    COUNT(*)::bigint AS row_count
                FROM {table_name}
                WHERE pair = %s
                """,
                (pair,),
            )
            min_ts = row["min_ts"]
            max_ts = row["max_ts"]
            count = int(row["row_count"])
            details.append(f"{pair} {timeframe}: min={min_ts}, max={max_ts}, rows={count}")
            if count == 0 or min_ts is None or max_ts is None:
                failures.append(f"{pair} {timeframe} has no rows")
                continue
            if min_ts > baseline:
                failures.append(f"{pair} {timeframe} min {min_ts} > 2021-01-01")
            if max_ts < freshness_cutoff:
                failures.append(f"{pair} {timeframe} max {max_ts} older than {freshness_cutoff}")
    if failures:
        return _fail("Historical data complete", "; ".join(failures))
    return _pass("Historical data complete", " | ".join(details))


def _check_no_data_gaps_7d(connection, as_of: datetime) -> CheckResult:
    gap_messages: list[str] = []
    for timeframe in TIMEFRAMES:
        interval = INTERVAL_BY_TIMEFRAME[timeframe]
        interval_sql = "15 minutes" if timeframe == "15m" else "1 hour"
        table_name = OHLCV_TABLE_BY_TIMEFRAME[timeframe]
        window_start, window_end = _window_bounds(as_of, timeframe, lookback_days=7)
        if window_end < window_start:
            continue
        for symbol in SYMBOLS:
            pair = PAIR_BY_SYMBOL[symbol]
            count_row = fetch_one(
                connection,
                f"""
                WITH expected AS (
                    SELECT generate_series(%s::timestamptz, %s::timestamptz, %s::interval) AS bucket_time
                )
                SELECT COUNT(*)::int AS missing_count
                FROM expected e
                LEFT JOIN {table_name} o
                  ON o.pair = %s
                 AND o.bucket_time = e.bucket_time
                WHERE o.bucket_time IS NULL
                """,
                (window_start, window_end, interval_sql, pair),
            )
            missing_count = int(count_row["missing_count"])
            if missing_count == 0:
                continue
            sample_rows = fetch_all(
                connection,
                f"""
                WITH expected AS (
                    SELECT generate_series(%s::timestamptz, %s::timestamptz, %s::interval) AS bucket_time
                )
                SELECT e.bucket_time
                FROM expected e
                LEFT JOIN {table_name} o
                  ON o.pair = %s
                 AND o.bucket_time = e.bucket_time
                WHERE o.bucket_time IS NULL
                ORDER BY e.bucket_time
                LIMIT 3
                """,
                (window_start, window_end, interval_sql, pair),
            )
            samples = ", ".join(str(row["bucket_time"]) for row in sample_rows)
            gap_messages.append(
                f"{pair} {timeframe} missing={missing_count} sample=[{samples}]"
            )
    if gap_messages:
        return _warn("No data gaps (7d)", " ; ".join(gap_messages))
    return _pass("No data gaps (7d)", "No missing source intervals in the last 7 days.")


def _check_no_null_features(connection) -> CheckResult:
    failures: list[str] = []
    scanned: list[str] = []
    for timeframe in TIMEFRAMES:
        table_name = FEATURE_TABLE_BY_TIMEFRAME[timeframe]
        schema_name, bare_table = _table_parts(table_name)
        columns_present = set(_list_columns(connection, schema_name=schema_name, table_name=bare_table))
        total_row = fetch_one(connection, f"SELECT COUNT(*)::bigint AS row_count FROM {table_name}")
        row_count = int(total_row["row_count"])
        if row_count == 0:
            failures.append(f"{table_name} has no rows")
            continue
        for column in CORE_FEATURE_COLUMNS_BY_TIMEFRAME[timeframe]:
            if column not in columns_present:
                failures.append(f"{table_name}.{column} missing")
                continue
            quoted = _quote_identifier(column)
            row = fetch_one(
                connection,
                f"""
                SELECT AVG(CASE WHEN {quoted} IS NULL THEN 1.0 ELSE 0.0 END) AS null_ratio
                FROM {table_name}
                """,
            )
            ratio = float(row["null_ratio"] or 0.0)
            scanned.append(f"{table_name}.{column}={ratio:.4f}")
            if ratio > 0.01:
                failures.append(f"{table_name}.{column} null_ratio={ratio:.4f}")
    if failures:
        return _fail("No NULL features", "; ".join(failures))
    return _pass("No NULL features", " | ".join(scanned))


def _check_column_range(
    connection,
    *,
    check_name: str,
    table_names: Iterable[str],
    columns_by_table: dict[str, list[str]],
    lower: float,
    upper: float,
) -> CheckResult:
    failures: list[str] = []
    scanned = 0
    for table_name in table_names:
        for column in columns_by_table[table_name]:
            quoted = _quote_identifier(column)
            row = fetch_one(
                connection,
                f"""
                SELECT
                    SUM(CASE WHEN {quoted} IS NOT NULL AND ({quoted} < %s OR {quoted} > %s) THEN 1 ELSE 0 END)::bigint AS bad_count,
                    MIN({quoted}) AS min_value,
                    MAX({quoted}) AS max_value
                FROM {table_name}
                """,
                (lower, upper),
            )
            scanned += 1
            bad_count = int(row["bad_count"] or 0)
            if bad_count > 0:
                failures.append(
                    f"{table_name}.{column} bad={bad_count} min={row['min_value']} max={row['max_value']}"
                )
    if failures:
        return _fail(check_name, "; ".join(failures))
    return _pass(check_name, f"Scanned {scanned} columns in range [{lower}, {upper}].")


def _check_percentile_range_valid(connection) -> CheckResult:
    columns_by_table: dict[str, list[str]] = {}
    for timeframe in TIMEFRAMES:
        table_name = FEATURE_TABLE_BY_TIMEFRAME[timeframe]
        schema_name, bare_table = _table_parts(table_name)
        columns_by_table[table_name] = _list_columns(
            connection,
            schema_name=schema_name,
            table_name=bare_table,
            like_pattern="%_pct_%",
        )
    return _check_column_range(
        connection,
        check_name="Percentile range valid",
        table_names=FEATURE_TABLE_BY_TIMEFRAME.values(),
        columns_by_table=columns_by_table,
        lower=0.0,
        upper=1.0,
    )


def _check_slope_values_reasonable(connection) -> CheckResult:
    failures: list[str] = []
    scanned = 0
    for timeframe in TIMEFRAMES:
        table_name = FEATURE_TABLE_BY_TIMEFRAME[timeframe]
        schema_name, bare_table = _table_parts(table_name)
        columns = _list_columns(
            connection,
            schema_name=schema_name,
            table_name=bare_table,
            like_pattern="%_slope_%",
        )
        for column in columns:
            quoted = _quote_identifier(column)
            row = fetch_one(
                connection,
                f"""
                SELECT
                    SUM(CASE WHEN {quoted} IS NOT NULL AND ABS({quoted}) > 100 THEN 1 ELSE 0 END)::bigint AS bad_count,
                    MAX(ABS({quoted})) AS max_abs
                FROM {table_name}
                """,
            )
            scanned += 1
            bad_count = int(row["bad_count"] or 0)
            if bad_count > 0:
                failures.append(f"{table_name}.{column} bad={bad_count} max_abs={row['max_abs']}")
    if failures:
        return _fail("Slope values reasonable", "; ".join(failures))
    return _pass("Slope values reasonable", f"Scanned {scanned} slope columns within ±100.")


def _check_temporal_features_valid(connection) -> CheckResult:
    failures: list[str] = []
    scanned = 0
    for timeframe in TIMEFRAMES:
        table_name = FEATURE_TABLE_BY_TIMEFRAME[timeframe]
        schema_name, bare_table = _table_parts(table_name)
        columns = set(_list_columns(connection, schema_name=schema_name, table_name=bare_table))
        for column in TEMPORAL_COLUMNS:
            if column not in columns:
                failures.append(f"{table_name}.{column} missing")
                continue
            quoted = _quote_identifier(column)
            row = fetch_one(
                connection,
                f"""
                SELECT
                    SUM(CASE WHEN {quoted} IS NOT NULL AND ({quoted} < -1 OR {quoted} > 1) THEN 1 ELSE 0 END)::bigint AS bad_count
                FROM {table_name}
                """,
            )
            scanned += 1
            if int(row["bad_count"] or 0) > 0:
                failures.append(f"{table_name}.{column} has out-of-range values")
    if failures:
        return _fail("Temporal features valid", "; ".join(failures))
    return _pass("Temporal features valid", f"Scanned {scanned} temporal columns in [-1, 1].")


def _check_synthetic_table_populated(connection) -> CheckResult:
    rows = fetch_all(
        connection,
        """
        SELECT symbol, COUNT(*)::bigint AS row_count
        FROM alpha_v4.synthetic_indicators
        GROUP BY symbol
        """,
    )
    counts = {row["symbol"]: int(row["row_count"]) for row in rows}
    missing = [symbol for symbol in SYMBOLS if counts.get(symbol, 0) <= 0]
    if missing:
        return _fail("Synthetic table populated", f"Missing rows for: {', '.join(missing)}")
    detail = ", ".join(f"{symbol}={counts[symbol]}" for symbol in SYMBOLS)
    return _pass("Synthetic table populated", detail)


def _check_trend_strength_valid(connection) -> CheckResult:
    row = fetch_one(
        connection,
        """
        SELECT
            COUNT(*)::bigint AS row_count,
            SUM(CASE WHEN syn_trend_strength IS NOT NULL AND (syn_trend_strength < 0 OR syn_trend_strength > 100) THEN 1 ELSE 0 END)::bigint AS bad_count,
            MIN(syn_trend_strength) AS min_value,
            MAX(syn_trend_strength) AS max_value
        FROM alpha_v4.synthetic_indicators
        """,
    )
    if int(row["row_count"]) == 0:
        return _fail("Trend strength valid", "synthetic_indicators has no rows.")
    if int(row["bad_count"] or 0) > 0:
        return _fail(
            "Trend strength valid",
            f"bad={row['bad_count']} min={row['min_value']} max={row['max_value']}",
        )
    return _pass("Trend strength valid", f"min={row['min_value']} max={row['max_value']}")


def _check_volatility_regime_valid(connection) -> CheckResult:
    rows = fetch_all(
        connection,
        """
        SELECT DISTINCT syn_volatility_regime
        FROM alpha_v4.synthetic_indicators
        WHERE syn_volatility_regime IS NOT NULL
        ORDER BY syn_volatility_regime
        """,
    )
    values = [int(row["syn_volatility_regime"]) for row in rows]
    bad = [value for value in values if value not in {0, 1, 2}]
    if bad:
        return _fail("Volatility regime valid", f"Unexpected values: {bad}")
    return _pass("Volatility regime valid", f"values={values}")


def _check_market_structure_valid(connection) -> CheckResult:
    rows = fetch_all(
        connection,
        """
        SELECT DISTINCT syn_market_structure
        FROM alpha_v4.synthetic_indicators
        WHERE syn_market_structure IS NOT NULL
        ORDER BY syn_market_structure
        """,
    )
    values = [str(row["syn_market_structure"]) for row in rows]
    allowed = {"bull", "bear", "range"}
    bad = [value for value in values if value not in allowed]
    if bad:
        return _fail("Market structure valid", f"Unexpected values: {bad}")
    return _pass("Market structure valid", f"values={values}")


def _check_correlation_features_valid(connection) -> CheckResult:
    schema_name, table_name = _table_parts("alpha_v4.synthetic_indicators")
    columns = _list_columns(
        connection,
        schema_name=schema_name,
        table_name=table_name,
        like_pattern="syn_%_correlation_20",
    )
    if not columns:
        return _fail("Correlation features valid", "No synthetic correlation columns found.")
    failures: list[str] = []
    for column in columns:
        quoted = _quote_identifier(column)
        row = fetch_one(
            connection,
            f"""
            SELECT
                SUM(CASE WHEN {quoted} IS NOT NULL AND ({quoted} < -1 OR {quoted} > 1) THEN 1 ELSE 0 END)::bigint AS bad_count,
                MIN({quoted}) AS min_value,
                MAX({quoted}) AS max_value
            FROM alpha_v4.synthetic_indicators
            """,
        )
        if int(row["bad_count"] or 0) > 0:
            failures.append(
                f"{column} bad={row['bad_count']} min={row['min_value']} max={row['max_value']}"
            )
    if failures:
        return _fail("Correlation features valid", "; ".join(failures))
    return _pass("Correlation features valid", f"Scanned {len(columns)} correlation columns in [-1, 1].")


def build_checks(profile: str, as_of: datetime) -> list[Check]:
    core_checks = [
        Check("Schema created", _check_schema_exists),
        Check("Tables created", _check_required_tables),
        Check("Primary keys set", _check_primary_keys),
        Check("Indexes created", _check_prediction_indexes),
        Check("Feature count met", _check_feature_column_count),
        Check("Labels created", _check_labels_coverage),
        Check("Next label binary correct", _check_label_binary_mapping),
        Check("Prediction data quality", _check_predictions_data_quality),
        Check("Resolution pipeline", _check_resolution_backlog),
        Check("Prediction results view", _check_view_exists),
        Check("View columns match", _check_view_columns),
        Check("Features current", _check_feature_freshness),
    ]
    if profile == "core":
        return core_checks
    full_checks = [
        Check("Historical data complete", lambda connection: _check_historical_data_complete(connection, as_of)),
        Check("No data gaps (7d)", lambda connection: _check_no_data_gaps_7d(connection, as_of)),
        Check("No NULL features", _check_no_null_features),
        Check("Percentile range valid", _check_percentile_range_valid),
        Check("Slope values reasonable", _check_slope_values_reasonable),
        Check("Temporal features valid", _check_temporal_features_valid),
        Check("Synthetic table populated", _check_synthetic_table_populated),
        Check("Trend strength valid", _check_trend_strength_valid),
        Check("Volatility regime valid", _check_volatility_regime_valid),
        Check("Market structure valid", _check_market_structure_valid),
        Check("Correlation features valid", _check_correlation_features_valid),
    ]
    return core_checks + full_checks


def summarize_results(results: list[CheckResult]) -> dict[str, int]:
    passed = sum(1 for result in results if result.status == CHECK_STATUS_PASS)
    warnings = sum(1 for result in results if result.status == CHECK_STATUS_WARN)
    failed = sum(1 for result in results if result.status == CHECK_STATUS_FAIL)
    return {
        "passed": passed + warnings,
        "warnings": warnings,
        "failed": failed,
        "total": len(results),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run alpha_v4 success criteria checks.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    parser.add_argument("--profile", choices=("core", "full"), default="full")
    parser.add_argument("--as-of", help="Override current UTC time for deterministic windows.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    as_of = parse_iso_utc(args.as_of).astimezone(timezone.utc).replace(second=0, microsecond=0)
    connection = get_connection(autocommit=True)
    try:
        results = [check.run(connection) for check in build_checks(profile=args.profile, as_of=as_of)]
        summary = summarize_results(results)
        if args.json:
            payload = {
                "as_of": as_of.isoformat(),
                "profile": args.profile,
                "summary": summary,
                "checks": [result.as_dict() for result in results],
            }
            print(json.dumps(payload, indent=2, default=str))
        else:
            for result in results:
                print(f"[{result.status}] {result.name}: {result.details}")
            print(
                "\nSummary: "
                f"{summary['passed']} passed, {summary['warnings']} warnings, "
                f"{summary['failed']} failed, {summary['total']} total"
            )
        return 0 if summary["failed"] == 0 else 2
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
