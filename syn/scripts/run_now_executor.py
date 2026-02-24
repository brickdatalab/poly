#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import engine

DEFAULT_PAIRS = ["BTC-USD", "ETH-USD"]

# Keep indicator formulas untouched; this maps config IDs to evaluators that compute v1.
CONFIG_TO_INDICATOR: dict[str, str] = {
    "syn_mtf_signed_efficiency_ratio_5m12_15m8": "mtf_signed_efficiency_ratio",
    "syn_rsi_velocity_5m_3bar_z20": "rsi_velocity_5m",
    "syn_early_momentum_divergence_tplus1": "early_momentum_divergence_score",
    "syn_cvd_price_divergence_velocity_15m5_tplus2": "cvd_price_divergence_velocity",
    "syn_early_impulse_liq_align_tplus2": "early_impulse_liquidity_alignment_2m",
    "syn_multitimeframe_trend_confluence_tplus2": "multitimeframe_trend_confluence",
    "syn_oi_funding_impulse_tplus2": "oi_funding_impulse_confirmation_2m",
}

# Minimum elapsed seconds from bucket start before rule is eligible.
CONFIG_MIN_SECONDS: dict[str, int] = {
    "syn_mtf_signed_efficiency_ratio_5m12_15m8": 74,  # user requested t+1m14s
    "syn_rsi_velocity_5m_3bar_z20": 74,  # user requested t+1m14s
    "syn_early_momentum_divergence_tplus1": 74,  # user requested t+1m14s
    "syn_cvd_price_divergence_velocity_15m5_tplus2": 120,
    "syn_early_impulse_liq_align_tplus2": 120,
    "syn_multitimeframe_trend_confluence_tplus2": 120,
    "syn_oi_funding_impulse_tplus2": 120,
}

# Source of truth:
# - syn/sythnthetic_active.md
# - syn/synthetic_indicators_spec.md
# - syn/synthetic_indicators.txt
# Window-edge is intentionally excluded.
HARDCODED_RULES: list[dict[str, Any]] = [
    # BTC-USD
    {
        "rule_id": "btc_syn_rsi_velocity_5m_3bar_z20_up_ge_1p489539",
        "pair": "BTC-USD",
        "config_id": "syn_rsi_velocity_5m_3bar_z20",
        "operator": ">=",
        "threshold": 1.489539,
        "prediction": "up",
        "base_accuracy": 0.6562,
    },
    {
        "rule_id": "btc_syn_rsi_velocity_5m_3bar_z20_down_le_n1p432481",
        "pair": "BTC-USD",
        "config_id": "syn_rsi_velocity_5m_3bar_z20",
        "operator": "<=",
        "threshold": -1.432481,
        "prediction": "down",
        "base_accuracy": 0.6552,
    },
    {
        "rule_id": "btc_syn_early_impulse_liq_align_tplus2_down_ge_1p205976",
        "pair": "BTC-USD",
        "config_id": "syn_early_impulse_liq_align_tplus2",
        "operator": ">=",
        "threshold": 1.205976,
        "prediction": "down",
        "base_accuracy": 0.6933,
    },
    {
        "rule_id": "btc_syn_oi_funding_impulse_tplus2_down_ge_1p331442",
        "pair": "BTC-USD",
        "config_id": "syn_oi_funding_impulse_tplus2",
        "operator": ">=",
        "threshold": 1.331442,
        "prediction": "down",
        "base_accuracy": 0.6538,
    },
    {
        "rule_id": "btc_syn_early_momentum_divergence_tplus1_up_le_n0p189361",
        "pair": "BTC-USD",
        "config_id": "syn_early_momentum_divergence_tplus1",
        "operator": "<=",
        "threshold": -0.189361,
        "prediction": "up",
        "base_accuracy": 0.6400,
    },
    {
        "rule_id": "btc_syn_early_momentum_divergence_tplus1_down_ge_0p094863",
        "pair": "BTC-USD",
        "config_id": "syn_early_momentum_divergence_tplus1",
        "operator": ">=",
        "threshold": 0.094863,
        "prediction": "down",
        "base_accuracy": 0.6441,
    },
    # ETH-USD
    {
        "rule_id": "eth_syn_mtf_signed_efficiency_ratio_down_ge_0p335248",
        "pair": "ETH-USD",
        "config_id": "syn_mtf_signed_efficiency_ratio_5m12_15m8",
        "operator": ">=",
        "threshold": 0.335248,
        "prediction": "down",
        "base_accuracy": 0.6250,
    },
    {
        "rule_id": "eth_syn_rsi_velocity_5m_3bar_z20_up_ge_1p514696",
        "pair": "ETH-USD",
        "config_id": "syn_rsi_velocity_5m_3bar_z20",
        "operator": ">=",
        "threshold": 1.514696,
        "prediction": "up",
        "base_accuracy": 0.6373,
    },
    {
        "rule_id": "eth_syn_rsi_velocity_5m_3bar_z20_down_le_n1p625252",
        "pair": "ETH-USD",
        "config_id": "syn_rsi_velocity_5m_3bar_z20",
        "operator": "<=",
        "threshold": -1.625252,
        "prediction": "down",
        "base_accuracy": 0.6941,
    },
    {
        "rule_id": "eth_syn_early_impulse_liq_align_tplus2_down_ge_1p289645",
        "pair": "ETH-USD",
        "config_id": "syn_early_impulse_liq_align_tplus2",
        "operator": ">=",
        "threshold": 1.289645,
        "prediction": "down",
        "base_accuracy": 0.6234,
    },
    {
        "rule_id": "eth_syn_oi_funding_impulse_tplus2_up_le_n1p100426",
        "pair": "ETH-USD",
        "config_id": "syn_oi_funding_impulse_tplus2",
        "operator": "<=",
        "threshold": -1.100426,
        "prediction": "up",
        "base_accuracy": 0.6310,
    },
    {
        "rule_id": "eth_syn_early_momentum_divergence_tplus1_up_le_n0p177442",
        "pair": "ETH-USD",
        "config_id": "syn_early_momentum_divergence_tplus1",
        "operator": "<=",
        "threshold": -0.177442,
        "prediction": "up",
        "base_accuracy": 0.6573,
    },
    {
        "rule_id": "eth_syn_early_momentum_divergence_tplus1_down_ge_0p366086",
        "pair": "ETH-USD",
        "config_id": "syn_early_momentum_divergence_tplus1",
        "operator": ">=",
        "threshold": 0.366086,
        "prediction": "down",
        "base_accuracy": 0.6608,
    },
]

PHASE_MAX_SECONDS = {
    "t0": 0,
    "t_plus_1": 74,
    "t_plus_2": 120,
}


def parse_pairs(text: str) -> list[str]:
    pairs = [p.strip() for p in text.split(",") if p.strip()]
    return pairs if pairs else list(DEFAULT_PAIRS)


def infer_uniform_bucket(now_utc: datetime) -> datetime:
    bucket = now_utc.replace(minute=(now_utc.minute // 15) * 15, second=0, microsecond=0)
    if now_utc < bucket + timedelta(minutes=2):
        bucket -= timedelta(minutes=15)
    return bucket


def fetch_active_rules(
    pairs: list[str],
) -> list[dict[str, Any]]:
    pair_set = set(pairs)
    return [r for r in HARDCODED_RULES if r["pair"] in pair_set]


def filter_rules_for_phase(
    rules: list[dict[str, Any]],
    max_phase: str,
) -> list[dict[str, Any]]:
    max_seconds = PHASE_MAX_SECONDS[max_phase]
    out: list[dict[str, Any]] = []
    for r in rules:
        cfg = r["config_id"]
        min_sec = CONFIG_MIN_SECONDS.get(cfg, 120)
        if min_sec <= max_seconds:
            out.append(r)
    return out


def apply_indicator_values_to_rules(
    rules: list[dict[str, Any]],
    values: dict[tuple[str, str], float],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for r in rules:
        key = (r["pair"], r["config_id"])
        v1 = values.get(key)
        op = r["operator"]
        thr = float(r["threshold"])
        passes = False
        if v1 is not None:
            if op == ">=":
                passes = v1 >= thr
            elif op == "<=":
                passes = v1 <= thr
            elif op == ">":
                passes = v1 > thr
            elif op == "<":
                passes = v1 < thr
            elif op == "=":
                passes = v1 == thr
        enriched.append({**r, "value_v1": v1, "passes": passes})
    return enriched


def compute_values_from_evaluators(
    rules: list[dict[str, Any]],
    pairs: list[str],
    bucket: datetime,
) -> tuple[
    dict[tuple[str, str], float],
    list[dict[str, Any]],
    dict[tuple[str, str], dict[str, Any]],
]:
    needed_configs = sorted({r["config_id"] for r in rules})
    config_to_indicator = {
        cfg: CONFIG_TO_INDICATOR[cfg]
        for cfg in needed_configs
        if cfg in CONFIG_TO_INDICATOR
    }
    needed_indicators = sorted(set(config_to_indicator.values()))

    values: dict[tuple[str, str], float] = {}
    missing: list[dict[str, Any]] = []
    audits: dict[tuple[str, str], dict[str, Any]] = {}

    if not needed_indicators:
        return values, missing, audits

    # Faster path: evaluate pair+indicator jobs directly, skipping payload file writes in engine.evaluate_indicator.
    db_url = engine.build_db_url(engine.load_env(Path(__file__).resolve().parents[2]))
    jobs: list[tuple[str, str]] = [(pair, ind) for pair in pairs for ind in needed_indicators]
    results_by_pair_indicator: dict[tuple[str, str], dict[str, Any]] = {}

    def _run_job(pair: str, ind: str) -> tuple[tuple[str, str], dict[str, Any]]:
        spec = engine.EVALUATORS[ind]
        decision_time = bucket + timedelta(minutes=spec.decision_phase_minutes)
        row = spec.evaluator(db_url, pair, bucket, decision_time)
        return (pair, ind), row

    with ThreadPoolExecutor(max_workers=min(16, max(1, len(jobs)))) as ex:
        futs = [ex.submit(_run_job, pair, ind) for pair, ind in jobs]
        for f in as_completed(futs):
            key, row = f.result()
            results_by_pair_indicator[key] = row

    for cfg, ind in config_to_indicator.items():
        for pair in pairs:
            row = results_by_pair_indicator.get((pair, ind))
            audits[(pair, cfg)] = {
                "pair": pair,
                "config_id": cfg,
                "indicator": ind,
                "status": (row or {}).get("status"),
                "required_count": (row or {}).get("required_count"),
                "present_count": (row or {}).get("present_count"),
                "missing_count": (row or {}).get("missing_count"),
                "missing_inputs": (row or {}).get("missing_inputs", []),
                "calc": (row or {}).get("calc", {}),
            }
            if row and row.get("status") == "ready":
                v1 = row.get("calc", {}).get("v1")
                if v1 is not None:
                    values[(pair, cfg)] = float(v1)
                    continue
            missing.append(
                {
                    "pair": pair,
                    "config_id": cfg,
                    "indicator": ind,
                    "status": (row or {}).get("status"),
                    "missing_inputs": (row or {}).get("missing_inputs", []),
                }
            )

    return values, missing, audits


def recommend_from_triggered(
    triggered: list[dict[str, Any]],
    pairs: list[str],
    pair_not_ready: dict[str, bool] | None = None,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for p in pairs:
        if pair_not_ready and pair_not_ready.get(p, False):
            out[p] = {
                "up_signals": 0,
                "down_signals": 0,
                "recommended": "not_ready",
                "triggered_rule_ids": [],
            }
            continue

        ups = [t for t in triggered if t["pair"] == p and t["prediction"] == "up"]
        downs = [t for t in triggered if t["pair"] == p and t["prediction"] == "down"]
        if not ups and not downs:
            pick = "no_play"
        elif len(ups) > len(downs):
            pick = "up"
        elif len(downs) > len(ups):
            pick = "down"
        else:
            best_up = max([float(u["base_accuracy"]) for u in ups], default=-1.0)
            best_dn = max([float(d["base_accuracy"]) for d in downs], default=-1.0)
            if best_up > best_dn:
                pick = "up"
            elif best_dn > best_up:
                pick = "down"
            else:
                pick = "no_play"

        out[p] = {
            "up_signals": len(ups),
            "down_signals": len(downs),
            "recommended": pick,
            "triggered_rule_ids": [t["rule_id"] for t in triggered if t["pair"] == p],
        }
    return out


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run now: direct evaluator-based codex play evaluation.")
    ap.add_argument("--pairs", default=",".join(DEFAULT_PAIRS), help="Comma-separated pairs")
    ap.add_argument("--bucket-time", default=None, help="Optional explicit bucket_time UTC")
    ap.add_argument("--max-phase", choices=["t0", "t_plus_1", "t_plus_2"], default="t_plus_2")
    ap.add_argument("--pretty", action="store_true", help="Pretty print")
    ap.add_argument("--audit", action="store_true", help="Print full rule + formula/input audit tables")
    return ap.parse_args()


def run_once(
    *,
    pairs: list[str],
    bucket: datetime,
    max_phase: str,
) -> dict[str, Any]:
    t_start = time.perf_counter()
    active_rules = fetch_active_rules(pairs)
    phase_rules = filter_rules_for_phase(active_rules, max_phase)

    values, eval_missing, eval_audits = compute_values_from_evaluators(phase_rules, pairs, bucket)
    enriched = apply_indicator_values_to_rules(phase_rules, values)
    for r in enriched:
        a = eval_audits.get((r["pair"], r["config_id"]), {})
        r["indicator"] = a.get("indicator")
        r["eval_status"] = a.get("status")
        r["eval_missing_inputs"] = a.get("missing_inputs", [])
    rule_missing = [r for r in enriched if r.get("value_v1") is None]

    pair_not_ready = {p: False for p in pairs}
    for r in rule_missing:
        pair_not_ready[r["pair"]] = True

    triggered = [r for r in enriched if bool(r.get("passes"))]
    recommendation = recommend_from_triggered(triggered, pairs, pair_not_ready)

    status = "ok" if not rule_missing else "not_ready"
    payload = {
        "status": status,
        "now_utc": engine.iso_z(datetime.now(timezone.utc)),
        "bucket_time_utc": engine.iso_z(bucket),
        "pairs": pairs,
        "max_phase": max_phase,
        "rows_total": len(enriched),
        "evaluated_rows": enriched,
        "audit_rows": sorted(
            list(eval_audits.values()),
            key=lambda x: (str(x.get("pair")), str(x.get("config_id"))),
        ),
        "missing_rows_total": len(rule_missing),
        "missing_rows": rule_missing,
        "missing_eval_rows": eval_missing,
        "triggered_rows": triggered,
        "recommendation_by_pair": recommendation,
        "timing_seconds": round(time.perf_counter() - t_start, 4),
    }
    return payload


def main() -> int:
    args = parse_args()
    pairs = parse_pairs(args.pairs)
    now = datetime.now(timezone.utc)
    bucket = engine.parse_dt(args.bucket_time) if args.bucket_time else infer_uniform_bucket(now)

    payload = run_once(
        pairs=pairs,
        bucket=bucket,
        max_phase=args.max_phase,
    )

    out_dir = Path(__file__).resolve().parents[1] / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"run_now_executor_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps(payload, indent=2))

    if args.pretty:
        print(f"status={payload['status']}")
        print(f"now_utc={payload['now_utc']}")
        print(f"bucket_time_utc={payload['bucket_time_utc']}")
        print(f"max_phase={payload['max_phase']}")
        print(f"timing_seconds={payload['timing_seconds']}")
        print(f"output={out_path}")
        print()
        print("TRIGGERED")
        if payload["triggered_rows"]:
            for r in payload["triggered_rows"]:
                print(
                    f"{r['pair']} | {r['rule_id']} | v1={float(r['value_v1']):.12f} {r['operator']} {float(r['threshold']):.12f} -> {r['prediction']} | base_acc={float(r['base_accuracy']):.4f}"
                )
        else:
            print("none")
        print("\nRECOMMENDATION")
        for p in pairs:
            rec = payload["recommendation_by_pair"][p]
            print(f"{p} | up={rec['up_signals']} down={rec['down_signals']} -> {rec['recommended']}")
        print("\nMISSING_ROWS")
        if payload["missing_rows"]:
            for r in payload["missing_rows"]:
                print(f"{r['pair']} | {r['rule_id']} | config_id={r['config_id']}")
        else:
            print("none")

        if args.audit:
            print("\nALL_RULES_EVALUATED")
            for r in sorted(payload["evaluated_rows"], key=lambda x: (x["pair"], x["rule_id"])):
                v1 = r.get("value_v1")
                v1s = "null" if v1 is None else f"{float(v1):.12f}"
                print(
                    f"{r['pair']} | {r['rule_id']} | {r['config_id']} | {r['operator']} {float(r['threshold']):.12f} | v1={v1s} | passes={str(bool(r.get('passes'))).lower()} | eval_status={r.get('eval_status')}"
                )

            print("\nINDICATOR_AUDIT")
            for a in payload["audit_rows"]:
                calc = a.get("calc") or {}
                v1 = calc.get("v1")
                calc_view = {k: v for k, v in calc.items() if k in ("v1", "z_r", "liq_align", "oi_support", "crowding", "price_roc", "indicator_mom", "er_5m", "er_15m", "raw", "mu", "sd_used")}
                print(
                    f"{a['pair']} | {a['config_id']} | {a['indicator']} | status={a.get('status')} | present={a.get('present_count')}/{a.get('required_count')} | missing={a.get('missing_count')} | v1={('null' if v1 is None else f'{float(v1):.12f}')}"
                )
                if calc_view:
                    print(f"  calc={json.dumps(calc_view, sort_keys=True)}")
                if a.get("missing_inputs"):
                    print(f"  missing_inputs={json.dumps(a.get('missing_inputs'))}")

    return 0 if payload["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
