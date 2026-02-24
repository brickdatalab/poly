from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Logger:
    path: Path

    def log(self, msg: str) -> None:
        ts = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = f"[{ts}] {msg}\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line)
        # Keep stdout minimal but useful.
        print(line.rstrip())
