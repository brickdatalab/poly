#!/usr/bin/env python3
"""Mine a single-indicator "law" from ETH non-rolling fired events.

Given a fired-events CSV (defaulting to the latest ETH 72h run), this script:
- loads event-level correctness labels (accurate=1, inaccurate=0),
- pulls aligned indicator features for those event timestamps from indicators schema,
- searches single-threshold rules per feature:
    - rule form A: feature >= T => "likely accurate"
    - rule form B: feature <= T => "likely accurate"
- ranks rules by separability and practical behavior.

Outputs:
- scripts/output/window_edge_eth_law_mining/<UTC>/rules_all.csv
- scripts/output/window_edge_eth_law_mining/<UTC>/rules_filtered.csv
- scripts/output/window_edge_eth_law_mining/<UTC>/REPORT.md
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Event:
    t0: str
    correct: int  # 1=accurate, 0=inaccurate


def load_db_url(env_path: Path) -> str:
    env: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    db_url = env.get("SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("SUPABASE_DB_URL missing in .env")
    return db_url


def psql_copy_to_csv(db_url: str, sql: str, out_csv: Path) -> None:
    q = sql.strip()
    if q.endswith(";"):
        q = q[:-1]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "psql",
        db_url,
        "-v",
        "ON_ERROR_STOP=1",
        "-P",
        "pager=off",
        "-c",
        f"\\copy ({q}) TO STDOUT WITH CSV HEADER",
    ]
    with out_csv.open("w", newline="") as f:
        subprocess.check_call(cmd, stdout=f)


def load_events(csv_path: Path) -> list[Event]:
    out: list[Event] = []
    with csv_path.open() as f:
        r = csv.DictReader(f)
        for d in r:
            pred = d.get("prediction")
            corr = d.get("correct")
            if not pred or corr in (None, ""):
                continue
            out.append(Event(t0=d["t0"], correct=int(corr)))
    if not out:
        raise SystemExit(f"No fired events found in {csv_path}")
    return out


def sql_values_t0(events: list[Event]) -> str:
    vals = ",\n".join(f"('{e.t0}'::timestamptz)" for e in events)
    return vals


def query_indicator_values_long(events: list[Event], pair: str = "ETH-USD") -> str:
    vals = sql_values_t0(events)
    return f"""
with fired(t0) as (
  values
{vals}
)
select
  iv.bucket_time as t0,
  ('iv.' || iv.config_id || '.v1')::text as feature_key,
  iv.v1::float8 as feature_value
from fired f
join indicators.indicator_values iv
  on iv.pair = '{pair}'
 and iv.bucket_time = f.t0
where iv.v1 is not null
union all
select
  iv.bucket_time as t0,
  ('iv.' || iv.config_id || '.v2')::text as feature_key,
  iv.v2::float8 as feature_value
from fired f
join indicators.indicator_values iv
  on iv.pair = '{pair}'
 and iv.bucket_time = f.t0
where iv.v2 is not null
union all
select
  iv.bucket_time as t0,
  ('iv.' || iv.config_id || '.v3')::text as feature_key,
  iv.v3::float8 as feature_value
from fired f
join indicators.indicator_values iv
  on iv.pair = '{pair}'
 and iv.bucket_time = f.t0
where iv.v3 is not null
union all
select
  iv.bucket_time as t0,
  ('iv.' || iv.config_id || '.v4')::text as feature_key,
  iv.v4::float8 as feature_value
from fired f
join indicators.indicator_values iv
  on iv.pair = '{pair}'
 and iv.bucket_time = f.t0
where iv.v4 is not null
union all
select
  iv.bucket_time as t0,
  ('iv.' || iv.config_id || '.v5')::text as feature_key,
  iv.v5::float8 as feature_value
from fired f
join indicators.indicator_values iv
  on iv.pair = '{pair}'
 and iv.bucket_time = f.t0
where iv.v5 is not null
order by t0, feature_key
"""


def query_oi_open_interest_long(events: list[Event], pair: str = "ETH-USD") -> str:
    vals = sql_values_t0(events)
    return f"""
with fired(t0) as (
  values
{vals}
),
oi as (
  select
    f.t0,
    o.*
  from fired f
  join indicators.open_interest o
    on o.pair = '{pair}'
   and o.bucket_time = f.t0
),
oif as (
  select
    f.t0,
    x.*
  from fired f
  join indicators.oi_features x
    on x.pair = '{pair}'
   and x.bucket_time = f.t0
)
select t0, 'open_interest.open_interest'::text as feature_key, open_interest::float8 as feature_value from oi where open_interest is not null
union all select t0, 'open_interest.oi_change', oi_change::float8 from oi where oi_change is not null
union all select t0, 'open_interest.oi_change_pct', oi_change_pct::float8 from oi where oi_change_pct is not null
union all select t0, 'open_interest.close_price', close_price::float8 from oi where close_price is not null
union all select t0, 'open_interest.volume', volume::float8 from oi where volume is not null
union all select t0, 'open_interest.price_change_pct', price_change_pct::float8 from oi where price_change_pct is not null
union all select t0, 'open_interest.oi_volume_ratio', oi_volume_ratio::float8 from oi where oi_volume_ratio is not null
union all select t0, 'open_interest.oi_divergence', oi_divergence::float8 from oi where oi_divergence is not null
union all select t0, 'open_interest.weak_rally', weak_rally::float8 from oi where weak_rally is not null
union all select t0, 'open_interest.weak_selloff', weak_selloff::float8 from oi where weak_selloff is not null
union all select t0, 'open_interest.mark_price', mark_price::float8 from oi where mark_price is not null
union all select t0, 'open_interest.open_interest_notional', open_interest_notional::float8 from oi where open_interest_notional is not null
union all select t0, 'open_interest.funding_rate', funding_rate::float8 from oi where funding_rate is not null
union all select t0, 'open_interest.funding_rate_8h_avg', funding_rate_8h_avg::float8 from oi where funding_rate_8h_avg is not null
union all select t0, 'oi_features.divergence_1h', divergence_1h::float8 from oif where divergence_1h is not null
union all select t0, 'oi_features.divergence_4h', divergence_4h::float8 from oif where divergence_4h is not null
union all select t0, 'oi_features.funding_oi_pressure', funding_oi_pressure::float8 from oif where funding_oi_pressure is not null
union all select t0, 'oi_features.funding_oi_pressure_1h', funding_oi_pressure_1h::float8 from oif where funding_oi_pressure_1h is not null
union all select t0, 'oi_features.basis_pct', basis_pct::float8 from oif where basis_pct is not null
union all select t0, 'oi_features.oi_roc_1h', oi_roc_1h::float8 from oif where oi_roc_1h is not null
union all select t0, 'oi_features.oi_roc_4h', oi_roc_4h::float8 from oif where oi_roc_4h is not null
union all select t0, 'oi_features.oi_roc_24h', oi_roc_24h::float8 from oif where oi_roc_24h is not null
union all select t0, 'oi_features.oi_acceleration', oi_acceleration::float8 from oif where oi_acceleration is not null
union all select t0, 'oi_features.weak_rally_streak', weak_rally_streak::float8 from oif where weak_rally_streak is not null
union all select t0, 'oi_features.weak_selloff_streak', weak_selloff_streak::float8 from oif where weak_selloff_streak is not null
union all select t0, 'oi_features.oi_ema_8', oi_ema_8::float8 from oif where oi_ema_8 is not null
union all select t0, 'oi_features.oi_ema_24', oi_ema_24::float8 from oif where oi_ema_24 is not null
union all select t0, 'oi_features.oi_ema_dev_8', oi_ema_dev_8::float8 from oif where oi_ema_dev_8 is not null
union all select t0, 'oi_features.oi_ema_dev_24', oi_ema_dev_24::float8 from oif where oi_ema_dev_24 is not null
union all select t0, 'oi_features.price_oi_corr_16', price_oi_corr_16::float8 from oif where price_oi_corr_16 is not null
union all select t0, 'oi_features.price_oi_corr_24', price_oi_corr_24::float8 from oif where price_oi_corr_24 is not null
union all select t0, 'oi_features.oi_change_vol_pctile_24h', oi_change_vol_pctile_24h::float8 from oif where oi_change_vol_pctile_24h is not null
union all select t0, 'oi_features.turnover_1h', turnover_1h::float8 from oif where turnover_1h is not null
union all select t0, 'oi_features.turnover_4h', turnover_4h::float8 from oif where turnover_4h is not null
order by t0, feature_key
"""


def query_order_book_long(events: list[Event], pair: str = "ETH-USD") -> str:
    vals = sql_values_t0(events)
    return f"""
with fired(t0) as (
  values
{vals}
),
ob as (
  select
    f.t0,
    l.*
  from fired f
  left join lateral (
    select *
    from indicators.order_book_indicators o
    where o.pair = '{pair}'
      and o.captured_at <= f.t0
      and o.captured_at > f.t0 - interval '5 minutes'
    order by o.captured_at desc
    limit 1
  ) l on true
)
select t0, 'order_book.depth_ratio'::text as feature_key, depth_ratio::float8 as feature_value from ob where depth_ratio is not null
union all select t0, 'order_book.imbalance', imbalance::float8 from ob where imbalance is not null
union all select t0, 'order_book.spread_pct', spread_pct::float8 from ob where spread_pct is not null
union all select t0, 'order_book.mid_price', mid_price::float8 from ob where mid_price is not null
union all select t0, 'order_book.bid_depth_10bps', bid_depth_10bps::float8 from ob where bid_depth_10bps is not null
union all select t0, 'order_book.ask_depth_10bps', ask_depth_10bps::float8 from ob where ask_depth_10bps is not null
union all select t0, 'order_book.bid_depth_25bps', bid_depth_25bps::float8 from ob where bid_depth_25bps is not null
union all select t0, 'order_book.ask_depth_25bps', ask_depth_25bps::float8 from ob where ask_depth_25bps is not null
union all select t0, 'order_book.bid_depth_50bps', bid_depth_50bps::float8 from ob where bid_depth_50bps is not null
union all select t0, 'order_book.ask_depth_50bps', ask_depth_50bps::float8 from ob where ask_depth_50bps is not null
union all select t0, 'order_book.bid_slope', bid_slope::float8 from ob where bid_slope is not null
union all select t0, 'order_book.ask_slope', ask_slope::float8 from ob where ask_slope is not null
union all select t0, 'order_book.slippage_buy_100', slippage_buy_100::float8 from ob where slippage_buy_100 is not null
union all select t0, 'order_book.slippage_sell_100', slippage_sell_100::float8 from ob where slippage_sell_100 is not null
union all select t0, 'order_book.slippage_buy_1000', slippage_buy_1000::float8 from ob where slippage_buy_1000 is not null
union all select t0, 'order_book.slippage_sell_1000', slippage_sell_1000::float8 from ob where slippage_sell_1000 is not null
order by t0, feature_key
"""


def load_long_feature_rows(path: Path) -> list[tuple[str, str, float]]:
    rows: list[tuple[str, str, float]] = []
    with path.open() as f:
        r = csv.DictReader(f)
        for d in r:
            t0 = d["t0"]
            k = d["feature_key"]
            try:
                v = float(d["feature_value"])
            except Exception:
                continue
            if not math.isfinite(v):
                continue
            rows.append((t0, k, v))
    return rows


def evaluate_feature_thresholds(
    x: np.ndarray,
    y: np.ndarray,  # 1 accurate / 0 inaccurate
    feature_key: str,
) -> list[dict[str, Any]]:
    # threshold candidates: unique feature values
    uniq = np.unique(x)
    if uniq.size < 2:
        return []

    n = int(len(y))
    n_pos = int(y.sum())
    n_neg = n - n_pos
    out: list[dict[str, Any]] = []

    def score(cond: np.ndarray, op: str, thr: float) -> None:
        tp = int(np.sum(cond & (y == 1)))
        fp = int(np.sum(cond & (y == 0)))
        fn = int(np.sum((~cond) & (y == 1)))
        tn = int(np.sum((~cond) & (y == 0)))

        tpr = tp / n_pos if n_pos else float("nan")
        tnr = tn / n_neg if n_neg else float("nan")
        law_acc = (tp + tn) / n if n else float("nan")  # keep if cond, flip otherwise
        kept = tp + fp
        keep_acc = tp / kept if kept else float("nan")  # if we only take trades when cond
        keep_cov = kept / n if n else float("nan")
        baseline = n_pos / n if n else float("nan")
        delta_law = law_acc - baseline if law_acc == law_acc and baseline == baseline else float("nan")
        gmean = math.sqrt(max(tpr, 0.0) * max(tnr, 0.0)) if tpr == tpr and tnr == tnr else float("nan")

        out.append(
            {
                "feature_key": feature_key,
                "operator": op,
                "threshold": float(thr),
                "n_obs": n,
                "n_accurate": n_pos,
                "n_inaccurate": n_neg,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "tn": tn,
                "tpr_retain_accurate": tpr,
                "tnr_filter_inaccurate": tnr,
                "law_accuracy_keep_flip": law_acc,
                "baseline_accuracy": baseline,
                "delta_accuracy_keep_flip": delta_law,
                "keep_only_n": kept,
                "keep_only_coverage": keep_cov,
                "keep_only_accuracy": keep_acc,
                "gmean_tpr_tnr": gmean,
            }
        )

    # brute-force is cheap at this scale (<=205 points).
    for thr in uniq:
        score(x >= thr, ">=", float(thr))
        score(x <= thr, "<=", float(thr))
    return out


def fmt_pct(v: float) -> str:
    if v != v:
        return "nan"
    return f"{100.0 * v:.4f}%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--fired-events",
        default="/Users/vitolo/Desktop/projects/poly/scripts/output/window_edge_eth_nonrolling_lastN/20260211T105622Z/fired_events.csv",
        help="Path to ETH fired events CSV with columns: t0,prediction,correct,...",
    )
    ap.add_argument("--pair", default="ETH-USD")
    ap.add_argument("--min-obs", type=int, default=180, help="Minimum observations for a candidate feature.")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[2]
    db_url = load_db_url(root / ".env")

    fired_path = Path(args.fired_events)
    events = load_events(fired_path)
    correct_by_t0 = {e.t0: e.correct for e in events}

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = root / "scripts" / "output" / "window_edge_eth_law_mining" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    iv_csv = out_dir / "features_indicator_values.csv"
    oi_csv = out_dir / "features_oi_open_interest.csv"
    ob_csv = out_dir / "features_order_book.csv"
    psql_copy_to_csv(db_url, query_indicator_values_long(events, pair=args.pair), iv_csv)
    psql_copy_to_csv(db_url, query_oi_open_interest_long(events, pair=args.pair), oi_csv)
    psql_copy_to_csv(db_url, query_order_book_long(events, pair=args.pair), ob_csv)

    long_rows = []
    long_rows.extend(load_long_feature_rows(iv_csv))
    long_rows.extend(load_long_feature_rows(oi_csv))
    long_rows.extend(load_long_feature_rows(ob_csv))

    # Pivot to feature -> arrays of (value, y)
    by_feat: dict[str, list[tuple[float, int]]] = {}
    for t0, key, val in long_rows:
        y = correct_by_t0.get(t0)
        if y is None:
            continue
        by_feat.setdefault(key, []).append((val, y))

    all_rules: list[dict[str, Any]] = []
    for feat, pairs in by_feat.items():
        if len(pairs) < args.min_obs:
            continue
        x = np.array([p[0] for p in pairs], dtype=float)
        y = np.array([p[1] for p in pairs], dtype=int)
        rules = evaluate_feature_thresholds(x, y, feat)
        all_rules.extend(rules)

    if not all_rules:
        raise SystemExit("No rules produced. Try lowering --min-obs.")

    # Write full table
    all_rules.sort(
        key=lambda r: (
            -(r["law_accuracy_keep_flip"] if r["law_accuracy_keep_flip"] == r["law_accuracy_keep_flip"] else -1),
            -(r["gmean_tpr_tnr"] if r["gmean_tpr_tnr"] == r["gmean_tpr_tnr"] else -1),
            -(r["keep_only_accuracy"] if r["keep_only_accuracy"] == r["keep_only_accuracy"] else -1),
            -r["n_obs"],
        )
    )

    all_csv = out_dir / "rules_all.csv"
    cols = [
        "feature_key",
        "operator",
        "threshold",
        "n_obs",
        "n_accurate",
        "n_inaccurate",
        "tp",
        "fp",
        "fn",
        "tn",
        "tpr_retain_accurate",
        "tnr_filter_inaccurate",
        "law_accuracy_keep_flip",
        "baseline_accuracy",
        "delta_accuracy_keep_flip",
        "keep_only_n",
        "keep_only_coverage",
        "keep_only_accuracy",
        "gmean_tpr_tnr",
    ]
    with all_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in all_rules:
            w.writerow(r)

    # Strong candidates where both sides are high (the "law" shape user described).
    filtered = [
        r
        for r in all_rules
        if r["tpr_retain_accurate"] >= 0.80
        and r["tnr_filter_inaccurate"] >= 0.80
        and r["n_obs"] >= args.min_obs
    ]
    filtered.sort(key=lambda r: (-r["law_accuracy_keep_flip"], -r["gmean_tpr_tnr"], -r["keep_only_accuracy"]))

    filtered_csv = out_dir / "rules_filtered.csv"
    with filtered_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in filtered:
            w.writerow(r)

    best = all_rules[0]
    top10 = all_rules[:10]
    baseline = best["baseline_accuracy"]

    md: list[str] = []
    md.append("# ETH Indicator Law Mining (from fired events)")
    md.append("")
    md.append(f"Run: `{out_dir}`")
    md.append("")
    md.append("## Input")
    md.append("")
    md.append(f"- fired_events_csv: `{fired_path}`")
    md.append(f"- fired_event_count: `{len(events)}`")
    md.append(f"- min_obs: `{args.min_obs}`")
    md.append("")
    md.append("## Best Single Law (by keep/flip accuracy)")
    md.append("")
    md.append(f"- feature: `{best['feature_key']}`")
    md.append(f"- rule: `{best['feature_key']} {best['operator']} {best['threshold']}`")
    md.append(f"- n_obs: `{best['n_obs']}`")
    md.append(f"- retain_accurate (TPR): `{fmt_pct(best['tpr_retain_accurate'])}`")
    md.append(f"- filter_inaccurate (TNR): `{fmt_pct(best['tnr_filter_inaccurate'])}`")
    md.append(f"- keep_only_accuracy: `{fmt_pct(best['keep_only_accuracy'])}` at coverage `{fmt_pct(best['keep_only_coverage'])}`")
    md.append(f"- keep/flip accuracy: `{fmt_pct(best['law_accuracy_keep_flip'])}` vs baseline `{fmt_pct(baseline)}` (delta `{fmt_pct(best['delta_accuracy_keep_flip'])}`)")
    md.append("")
    md.append("## 80/80 Law Candidates")
    md.append("")
    if filtered:
        md.append(f"- count: `{len(filtered)}`")
        for r in filtered[:10]:
            md.append(
                f"- `{r['feature_key']} {r['operator']} {r['threshold']}` | "
                f"TPR {fmt_pct(r['tpr_retain_accurate'])}, TNR {fmt_pct(r['tnr_filter_inaccurate'])}, "
                f"keep_only_acc {fmt_pct(r['keep_only_accuracy'])}, keep/flip_acc {fmt_pct(r['law_accuracy_keep_flip'])}"
            )
    else:
        md.append("- none found with TPR>=80% and TNR>=80%")
    md.append("")
    md.append("## Top 10 Rules")
    md.append("")
    for r in top10:
        md.append(
            f"- `{r['feature_key']} {r['operator']} {r['threshold']}` | "
            f"TPR {fmt_pct(r['tpr_retain_accurate'])}, TNR {fmt_pct(r['tnr_filter_inaccurate'])}, "
            f"keep_only_acc {fmt_pct(r['keep_only_accuracy'])} (cov {fmt_pct(r['keep_only_coverage'])}), "
            f"keep/flip_acc {fmt_pct(r['law_accuracy_keep_flip'])}"
        )
    md.append("")
    md.append("Artifacts:")
    md.append(f"- `{all_csv}`")
    md.append(f"- `{filtered_csv}`")
    md.append(f"- `{iv_csv}`")
    md.append(f"- `{oi_csv}`")
    md.append(f"- `{ob_csv}`")
    (out_dir / "REPORT.md").write_text("\n".join(md) + "\n")

    print(str(out_dir))


if __name__ == "__main__":
    main()

