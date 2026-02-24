#!/usr/bin/env python3
"""Run full synthetic signal integrity pipeline.

Stages:
1) canonical dataset build
2) leakage/adversarial probes
3) regime decomposition
4) support decay diagnostics
5) walk-forward evaluation
6) optional rule activation updates in indicators.codex_signal_rules
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
RESEARCH_DIR = REPO_ROOT / "scripts" / "synthetic_indicators" / "research"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run signal integrity pipeline")
    ap.add_argument("--start", default="2026-01-22T00:00:00Z")
    ap.add_argument("--end", default="now")
    ap.add_argument("--pairs", default="BTC-USD,ETH-USD")
    ap.add_argument("--apply-updates", action="store_true")
    ap.add_argument(
        "--confirm-live-updates",
        default="",
        help="Required with --apply-updates. Must equal: I_UNDERSTAND_THIS_WRITES_LIVE_RULES",
    )
    ap.add_argument("--output-root", default="scripts/output/signal_integrity")
    return ap.parse_args()


def _run(cmd: list[str]) -> str:
    out = subprocess.check_output(cmd, text=True, cwd=REPO_ROOT).strip()
    return out.splitlines()[-1].strip()


def _exec_sql(sql: str) -> None:
    env = {}
    for line in (REPO_ROOT / ".env").read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    db_url = env.get("SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("SUPABASE_DB_URL missing")
    subprocess.check_call([
        "psql",
        db_url,
        "-v",
        "ON_ERROR_STOP=1",
        "-P",
        "pager=off",
        "-c",
        sql,
    ])


def _write_discovery_docs(
    out_dir: Path,
    final_df: pd.DataFrame,
    regime_overall: pd.DataFrame,
    stability: pd.DataFrame,
) -> None:
    disc_dir = REPO_ROOT / "docs" / "discoveries"
    disc_dir.mkdir(parents=True, exist_ok=True)

    regime_doc = disc_dir / "signal_integrity_regimes.md"
    decay_doc = disc_dir / "signal_support_decay.md"

    top = final_df.sort_values(["recommended_active", "rule_accuracy"], ascending=[False, False]).head(20)

    regime_lines = [
        "# Signal Integrity Regimes",
        "",
        "This report summarizes regime-aware integrity gating for BTC/ETH codex rules.",
        "",
        "## Top Rules by Recommendation",
        "",
        "| rule_id | pair | config_id | recommended_active | rule_accuracy | regime_gate | walkforward_gate |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for r in top.to_dict(orient="records"):
        regime_lines.append(
            f"| {r['rule_id']} | {r['pair']} | {r['config_id']} | {bool(r['recommended_active'])} | {r['rule_accuracy']:.4f} | {bool(r['regime_gate'])} | {bool(r['walkforward_gate'])} |"
        )

    regime_lines += [
        "",
        "## Aggregate",
        "",
        f"- Rules evaluated: `{len(final_df)}`",
        f"- Recommended active: `{int(final_df['recommended_active'].sum())}`",
        f"- Recommended inactive: `{int((~final_df['recommended_active']).sum())}`",
        "",
        f"Source run: `{out_dir}`",
    ]

    decay_lines = [
        "# Signal Support Decay",
        "",
        "Stability diagnostics across support, choppy regime behavior, and decay slope.",
        "",
        "| rule_id | support_n | accuracy | ci_low | choppy_accuracy | weekly_acc_slope | max_loss_streak |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in stability.sort_values("accuracy", ascending=False).head(25).to_dict(orient="records"):
        decay_lines.append(
            f"| {r['rule_id']} | {int(r['support_n'])} | {float(r['accuracy']):.4f} | {float(r['ci_low']):.4f} | {float(r['choppy_accuracy']):.4f} | {float(r['weekly_acc_slope']):.5f} | {int(r['max_loss_streak'])} |"
        )

    decay_lines += [
        "",
        f"Source run: `{out_dir}`",
    ]

    regime_doc.write_text("\n".join(regime_lines) + "\n")
    decay_doc.write_text("\n".join(decay_lines) + "\n")


def main() -> None:
    args = parse_args()
    if args.apply_updates and args.confirm_live_updates != "I_UNDERSTAND_THIS_WRITES_LIVE_RULES":
        raise SystemExit(
            "Refusing live updates. Re-run with --confirm-live-updates I_UNDERSTAND_THIS_WRITES_LIVE_RULES"
        )

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = REPO_ROOT / args.output_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    dataset_dir = Path(
        _run(
            [
                "python",
                str(RESEARCH_DIR / "build_canonical_signal_dataset.py"),
                "--start",
                args.start,
                "--end",
                args.end,
                "--pairs",
                args.pairs,
                "--output-root",
                str(Path(args.output_root)),
            ]
        )
    )
    dataset = dataset_dir / "dataset.csv.gz"

    leakage_dir = Path(
        _run(
            [
                "python",
                str(RESEARCH_DIR / "leakage_tests.py"),
                "--dataset",
                str(dataset),
                "--out-dir",
                str(out_dir / "leakage"),
            ]
        )
    )

    regime_dir = Path(
        _run(
            [
                "python",
                str(RESEARCH_DIR / "regime_decomposition.py"),
                "--dataset",
                str(dataset),
                "--pairs",
                args.pairs,
                "--out-dir",
                str(out_dir / "regimes"),
            ]
        )
    )

    decay_dir = Path(
        _run(
            [
                "python",
                str(RESEARCH_DIR / "support_decay.py"),
                "--dataset",
                str(dataset),
                "--pairs",
                args.pairs,
                "--out-dir",
                str(out_dir / "decay"),
            ]
        )
    )

    wf_dir = Path(
        _run(
            [
                "python",
                str(RESEARCH_DIR / "rolling_walkforward.py"),
                "--dataset",
                str(dataset),
                "--pairs",
                args.pairs,
                "--out-dir",
                str(out_dir / "walkforward"),
            ]
        )
    )

    regime_overall = pd.read_csv(regime_dir / "rule_overall_metrics.csv")
    stability = pd.read_csv(decay_dir / "rule_stability_metrics.csv")
    wf = pd.read_csv(wf_dir / "walkforward_rule_summary.csv")

    merged = regime_overall.merge(
        stability[
            [
                "rule_id",
                "support_n",
                "accuracy",
                "ci_low",
                "choppy_accuracy",
                "choppy_support_n",
                "weekly_acc_slope",
                "max_loss_streak",
                "recommended_active",
            ]
        ].rename(
            columns={
                "support_n": "stability_support_n",
                "accuracy": "rule_accuracy",
                "ci_low": "rule_ci_low",
            }
        ),
        on="rule_id",
        how="left",
    ).merge(
        wf[["rule_id", "mean_accuracy", "min_accuracy", "avg_support"]],
        on="rule_id",
        how="left",
    )

    merged["regime_gate"] = merged["passes_overall_gate"].fillna(False)
    merged["walkforward_gate"] = merged["mean_accuracy"].fillna(0.0) >= 0.60
    merged["recommended_active"] = (
        merged["recommended_active"].fillna(False)
        & merged["regime_gate"].fillna(False)
        & merged["walkforward_gate"].fillna(False)
    )

    final_csv = out_dir / "final_rule_recommendations.csv"
    merged.sort_values(["pair", "config_id", "rule_id"]).to_csv(final_csv, index=False)

    applied_updates = []
    if args.apply_updates:
        # Update only requested pairs.
        pair_set = {p.strip() for p in args.pairs.split(",") if p.strip()}
        for r in merged.to_dict(orient="records"):
            if r.get("pair") not in pair_set:
                continue
            rule_id = str(r["rule_id"]).replace("'", "''")
            is_active = "true" if bool(r["recommended_active"]) else "false"
            base_acc = float(r.get("rule_accuracy") or 0.0)
            support_n = int(r.get("stability_support_n") or 0)
            set_parts = [f"is_active = {is_active}"]
            if base_acc > 0:
                set_parts.append(f"base_accuracy = {base_acc:.12f}")
            if support_n > 0:
                set_parts.append(f"support_n = {support_n}")
            sql = (
                "update indicators.codex_signal_rules "
                f"set {', '.join(set_parts)} "
                f"where rule_id = '{rule_id}';"
            )
            _exec_sql(sql)
            applied_updates.append({"rule_id": rule_id, "is_active": is_active, "base_accuracy": base_acc, "support_n": support_n})

    summary = {
        "run_id": run_id,
        "dataset_dir": str(dataset_dir),
        "leakage_dir": str(leakage_dir),
        "regime_dir": str(regime_dir),
        "decay_dir": str(decay_dir),
        "walkforward_dir": str(wf_dir),
        "final_recommendations_csv": str(final_csv),
        "rules_total": int(len(merged)),
        "rules_recommended_active": int(merged["recommended_active"].sum()),
        "rules_recommended_inactive": int((~merged["recommended_active"]).sum()),
        "applied_updates": applied_updates,
    }

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    _write_discovery_docs(out_dir, merged, regime_overall, stability)

    report_lines = [
        "# Signal Integrity Pipeline",
        "",
        f"Run ID: `{run_id}`",
        f"Rules evaluated: `{summary['rules_total']}`",
        f"Recommended active: `{summary['rules_recommended_active']}`",
        f"Recommended inactive: `{summary['rules_recommended_inactive']}`",
        f"Applied updates: `{len(applied_updates)}`",
        "",
        "## Artifacts",
        "",
        f"- `{dataset_dir}`",
        f"- `{leakage_dir}`",
        f"- `{regime_dir}`",
        f"- `{decay_dir}`",
        f"- `{wf_dir}`",
        f"- `{final_csv}`",
        f"- `{out_dir / 'summary.json'}`",
        "",
        "## Discovery Docs Updated",
        "",
        "- `docs/discoveries/signal_integrity_regimes.md`",
        "- `docs/discoveries/signal_support_decay.md`",
    ]
    (out_dir / "REPORT.md").write_text("\n".join(report_lines) + "\n")

    print(str(out_dir))


if __name__ == "__main__":
    main()
