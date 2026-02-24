#!/usr/bin/env python3
"""Run adversarial signal-integrity checks on canonical synthetic dataset.

Checks:
1) Timestamp leakage invariants (source_time <= decision_deadline)
2) Future-peek probe (shift feature by -1 event)
3) Placebo probe (shuffle outcomes within pair/config)
"""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
import sys

if str(THIS_DIR) not in sys.path:
    sys.path.append(str(THIS_DIR))

from metrics import RuleSweepResult, best_rules_for_both_sides


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run leakage/adversarial tests")
    ap.add_argument("--dataset", required=True, help="Path to dataset.csv.gz from canonical builder")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--min-support-n", type=int, default=40)
    ap.add_argument("--min-support-pct", type=float, default=0.02)
    ap.add_argument("--placebo-runs", type=int, default=120)
    ap.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 8) - 1))
    return ap.parse_args()


@dataclass(frozen=True)
class SideProbe:
    precision: float
    support_n: int
    operator: str
    threshold: float


@dataclass(frozen=True)
class GroupProbe:
    pair: str
    config_id: str
    n_total: int
    up_baseline: SideProbe | None
    down_baseline: SideProbe | None
    up_future: SideProbe | None
    down_future: SideProbe | None
    up_placebo_mean: float
    up_placebo_p95: float
    down_placebo_mean: float
    down_placebo_p95: float


def _rule_to_probe(rule: RuleSweepResult | None) -> SideProbe | None:
    if rule is None:
        return None
    return SideProbe(
        precision=float(rule.precision),
        support_n=int(rule.support_n),
        operator=rule.operator,
        threshold=float(rule.threshold),
    )


def _best_prec_for_side(values: np.ndarray, y: np.ndarray, side: str, min_n: int, min_pct: float) -> float:
    rr = best_rules_for_both_sides(values, y, min_n, min_pct)[side]
    return float(rr.precision) if rr is not None else 0.0


def _placebo_worker(task: tuple[np.ndarray, np.ndarray, int, int, float, int]) -> dict[str, float]:
    values, y, seed, runs, min_n, min_pct = task
    rng = np.random.default_rng(seed)
    up_scores = np.zeros(runs, dtype=np.float64)
    down_scores = np.zeros(runs, dtype=np.float64)

    for i in range(runs):
        y_perm = y.copy()
        rng.shuffle(y_perm)
        best = best_rules_for_both_sides(values, y_perm, int(min_n), float(min_pct))
        up_scores[i] = best["up"].precision if best["up"] is not None else 0.0
        down_scores[i] = best["down"].precision if best["down"] is not None else 0.0

    return {
        "up_mean": float(up_scores.mean()),
        "up_p95": float(np.quantile(up_scores, 0.95)),
        "down_mean": float(down_scores.mean()),
        "down_p95": float(np.quantile(down_scores, 0.95)),
    }


def _group_probe(
    g: pd.DataFrame,
    min_support_n: int,
    min_support_pct: float,
    placebo_runs: int,
    workers: int,
) -> GroupProbe:
    g = g.sort_values("bucket_time").reset_index(drop=True)
    x = g["value"].to_numpy(dtype=np.float64)
    y_up = g["is_up"].to_numpy(dtype=bool)

    baseline = best_rules_for_both_sides(x, y_up, min_support_n, min_support_pct)

    x_future = np.roll(x, -1)
    valid = np.ones(len(x), dtype=bool)
    valid[-1] = False
    future = best_rules_for_both_sides(x_future[valid], y_up[valid], min_support_n, min_support_pct)

    # Split placebo runs across processes.
    chunks = min(workers, max(1, placebo_runs // 10))
    per_chunk = placebo_runs // chunks
    rem = placebo_runs % chunks
    tasks: list[tuple[np.ndarray, np.ndarray, int, int, float, int]] = []
    for i in range(chunks):
        n = per_chunk + (1 if i < rem else 0)
        tasks.append((x, y_up.copy(), 1337 + i, n, min_support_n, min_support_pct))

    up_means = []
    up_p95s = []
    down_means = []
    down_p95s = []
    with ProcessPoolExecutor(max_workers=chunks) as ex:
        for res in ex.map(_placebo_worker, tasks):
            up_means.append(res["up_mean"])
            up_p95s.append(res["up_p95"])
            down_means.append(res["down_mean"])
            down_p95s.append(res["down_p95"])

    return GroupProbe(
        pair=str(g.iloc[0]["pair"]),
        config_id=str(g.iloc[0]["config_id"]),
        n_total=int(len(g)),
        up_baseline=_rule_to_probe(baseline["up"]),
        down_baseline=_rule_to_probe(baseline["down"]),
        up_future=_rule_to_probe(future["up"]),
        down_future=_rule_to_probe(future["down"]),
        up_placebo_mean=float(np.mean(up_means)),
        up_placebo_p95=float(np.max(up_p95s)),
        down_placebo_mean=float(np.mean(down_means)),
        down_placebo_p95=float(np.max(down_p95s)),
    )


def main() -> None:
    args = parse_args()
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise SystemExit(f"Dataset not found: {dataset_path}")

    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = dataset_path.parent / f"leakage_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(dataset_path, compression="gzip")
    if df.empty:
        raise SystemExit("Dataset is empty")

    df["bucket_time"] = pd.to_datetime(df["bucket_time"], utc=True, errors="coerce")
    df["source_time"] = pd.to_datetime(df.get("source_time"), utc=True, errors="coerce")
    df["decision_deadline"] = pd.to_datetime(df.get("decision_deadline"), utc=True, errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["is_up"] = df["outcome"].eq("up")

    invalid_source_rows = df.loc[
        df["source_time"].notna() & df["decision_deadline"].notna() & (df["source_time"] > df["decision_deadline"])
    ]

    probes: list[GroupProbe] = []
    for (_, _), g in df.groupby(["pair", "config_id"], sort=True):
        probes.append(
            _group_probe(
                g,
                min_support_n=args.min_support_n,
                min_support_pct=args.min_support_pct,
                placebo_runs=args.placebo_runs,
                workers=max(1, args.workers // 2),
            )
        )

    records = [asdict(p) for p in probes]
    probe_df = pd.json_normalize(records)

    def _uplift(side: str) -> pd.Series:
        return probe_df[f"{side}_future.precision"].fillna(0.0) - probe_df[f"{side}_baseline.precision"].fillna(0.0)

    probe_df["up_future_uplift"] = _uplift("up")
    probe_df["down_future_uplift"] = _uplift("down")
    probe_df["up_vs_placebo_margin"] = probe_df["up_baseline.precision"].fillna(0.0) - probe_df["up_placebo_p95"].fillna(0.0)
    probe_df["down_vs_placebo_margin"] = probe_df["down_baseline.precision"].fillna(0.0) - probe_df["down_placebo_p95"].fillna(0.0)

    summary = {
        "rows": int(len(df)),
        "pair_config_groups": int(probe_df.shape[0]),
        "invalid_source_rows": int(len(invalid_source_rows)),
        "invalid_source_rate": float(len(invalid_source_rows) / max(1, len(df))),
        "mean_up_future_uplift": float(probe_df["up_future_uplift"].mean()),
        "mean_down_future_uplift": float(probe_df["down_future_uplift"].mean()),
        "mean_up_placebo_margin": float(probe_df["up_vs_placebo_margin"].mean()),
        "mean_down_placebo_margin": float(probe_df["down_vs_placebo_margin"].mean()),
    }

    probe_csv = out_dir / "group_probe_results.csv"
    summary_json = out_dir / "summary.json"
    report_md = out_dir / "REPORT.md"

    probe_df.to_csv(probe_csv, index=False)
    summary_json.write_text(json.dumps(summary, indent=2))

    lines = [
        "# Leakage / Adversarial Integrity Tests",
        "",
        f"Dataset: `{dataset_path}`",
        f"Rows: `{summary['rows']}`",
        f"Groups: `{summary['pair_config_groups']}`",
        f"Invalid source-time rows: `{summary['invalid_source_rows']}` ({summary['invalid_source_rate']*100:.4f}%)",
        "",
        "## Probe Aggregates",
        "",
        f"- Mean UP future uplift: `{summary['mean_up_future_uplift']:.4f}`",
        f"- Mean DOWN future uplift: `{summary['mean_down_future_uplift']:.4f}`",
        f"- Mean UP placebo margin: `{summary['mean_up_placebo_margin']:.4f}`",
        f"- Mean DOWN placebo margin: `{summary['mean_down_placebo_margin']:.4f}`",
        "",
        "## Artifacts",
        "",
        f"- `{probe_csv}`",
        f"- `{summary_json}`",
    ]
    report_md.write_text("\n".join(lines) + "\n")
    print(str(out_dir))


if __name__ == "__main__":
    main()
