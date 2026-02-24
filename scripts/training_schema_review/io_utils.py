from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunPaths:
    run_dir: Path
    md_dir: Path
    json_dir: Path
    logs_dir: Path


def ensure_dirs(run_dir: Path) -> RunPaths:
    md_dir = run_dir / "md"
    json_dir = run_dir / "json"
    logs_dir = run_dir / "logs"
    md_dir.mkdir(parents=True, exist_ok=True)
    json_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    return RunPaths(run_dir=run_dir, md_dir=md_dir, json_dir=json_dir, logs_dir=logs_dir)


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def write_json(path: Path, obj: Any) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, sort_keys=True) + "\n")


def write_md(path: Path, content: str) -> None:
    atomic_write_text(path, content.rstrip() + "\n")

