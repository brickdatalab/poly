#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

# Allow `python3 scripts/.../run_all.py` to work without installation.
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(THIS_DIR.parent))

from training_schema_review.context import Ctx
from training_schema_review.db import PsqlSettings
from training_schema_review.io_utils import ensure_dirs, write_md
from training_schema_review.logging_utils import Logger
from training_schema_review.time_utils import utc_slug

from training_schema_review.sections import (
    alignment_with_indicators,
    ambiguities,
    candles,
    indicators,
    inventory,
)


def _build_report(run_dir: Path) -> str:
    md_dir = run_dir / "md"
    parts = [
        ("training_inventory.md", "Training Inventory"),
        ("candles_profile.md", "Candles"),
        ("indicator_coverage.md", "Indicators"),
        ("alignment_with_indicators.md", "Alignment"),
        ("ambiguities.md", "Ambiguities"),
    ]

    lines: list[str] = []
    lines.append("# Training Schema Review Report")
    lines.append("")
    lines.append(f"Run directory: `{run_dir}`")
    lines.append("")

    for filename, title in parts:
        p = md_dir / filename
        lines.append(f"## {title}")
        lines.append("")
        if p.exists():
            lines.append(p.read_text(encoding="utf-8").rstrip())
        else:
            lines.append(f"_Missing section output: {filename}_")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", default=str(THIS_DIR / "runs"))
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--mode", choices=["quick", "standard", "deep"], default="standard")
    ap.add_argument("--statement-timeout-s", type=int, default=600)
    ap.add_argument("--work-mem-mb", type=int, default=256)
    ap.add_argument("--parallel-workers", type=int, default=4, help="max_parallel_workers_per_gather")
    ap.add_argument("--dry-run", action="store_true", help="Create run dir, do not query the DB.")
    ap.add_argument(
        "--only",
        default="",
        help="Comma-separated subset of sections to run: inventory,candles,indicators,alignment,ambiguities",
    )
    args = ap.parse_args()

    out_root = Path(args.out_root).resolve()
    run_dir = out_root / utc_slug()
    paths = ensure_dirs(run_dir)
    logger = Logger(paths.logs_dir / "run_all.log")

    settings = PsqlSettings(
        statement_timeout_s=args.statement_timeout_s,
        work_mem_mb=args.work_mem_mb,
        max_parallel_workers_per_gather=args.parallel_workers,
    )
    ctx = Ctx(paths=paths, settings=settings, logger=logger, mode=args.mode)

    logger.log(f"run_all: mode={args.mode} jobs={args.jobs} out={run_dir}")

    if args.dry_run:
        write_md(paths.md_dir / "REPORT.md", _build_report(run_dir))
        logger.log("run_all: dry-run complete")
        return 0

    heavy_sem = threading.Semaphore(2)  # keep DB from thrashing on parallel heavy scans

    TaskFn = Callable[[Ctx], dict]
    tasks: list[tuple[str, TaskFn, bool]] = [
        ("inventory", inventory.run, False),
        ("candles", candles.run, True),
        ("indicators", indicators.run, True),
        ("alignment", alignment_with_indicators.run, False),
        ("ambiguities", ambiguities.run, False),
    ]
    if args.only.strip():
        allowed = {s.strip() for s in args.only.split(",") if s.strip()}
        tasks = [t for t in tasks if t[0] in allowed]

    def _wrap(name: str, fn: TaskFn, heavy: bool) -> tuple[str, dict]:
        if heavy:
            with heavy_sem:
                logger.log(f"{name}: start (heavy)")
                r = fn(ctx)
                logger.log(f"{name}: done")
                return name, r
        logger.log(f"{name}: start")
        r = fn(ctx)
        logger.log(f"{name}: done")
        return name, r

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
        futs = [ex.submit(_wrap, name, fn, heavy) for name, fn, heavy in tasks]
        for fut in as_completed(futs):
            name, r = fut.result()
            results[name] = r

    report = _build_report(run_dir)
    write_md(paths.md_dir / "REPORT.md", report)
    write_md(paths.run_dir / "REPORT.md", report)
    logger.log("run_all: wrote REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
