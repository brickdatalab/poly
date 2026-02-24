from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .db import PsqlSettings
from .io_utils import RunPaths
from .logging_utils import Logger


@dataclass(frozen=True)
class Ctx:
    paths: RunPaths
    settings: PsqlSettings
    logger: Logger
    mode: str  # quick | standard | deep

