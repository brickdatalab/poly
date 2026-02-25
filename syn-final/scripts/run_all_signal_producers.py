#!/usr/bin/env python3
"""Compatibility wrapper for canonical runtime synthetic runner.

Canonical source:
  /Users/vitolo/Desktop/projects/poly/runtime/synthetic/run_all_signal_producers.py
"""
from __future__ import annotations

import importlib.util
import runpy
from pathlib import Path
from types import ModuleType

_RUNTIME_RUNNER = Path(__file__).resolve().parents[2] / "runtime" / "synthetic" / "run_all_signal_producers.py"


def _load_runtime_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("runtime_synthetic_runner", _RUNTIME_RUNNER)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load runtime runner at {_RUNTIME_RUNNER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_runtime = _load_runtime_module()

for _name in dir(_runtime):
    if _name.startswith("_"):
        continue
    globals()[_name] = getattr(_runtime, _name)


def __getattr__(name: str):
    return getattr(_runtime, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_runtime)))


if __name__ == "__main__":
    runpy.run_path(str(_RUNTIME_RUNNER), run_name="__main__")
