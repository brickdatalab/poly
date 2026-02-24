from __future__ import annotations

from datetime import datetime, timedelta, timezone

DECISION_MINUTES = (2, 17, 32, 47)
PHASE_TO_SECONDS = {"t0": 0, "t_plus_1": 74, "t_plus_2": 120}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def next_decision_after(now_utc: datetime) -> datetime:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    now_utc = now_utc.astimezone(timezone.utc)

    hour_base = now_utc.replace(minute=0, second=0, microsecond=0)
    candidates: list[datetime] = []
    for hour_shift in (0, 1, 2):
        h = hour_base + timedelta(hours=hour_shift)
        for minute in DECISION_MINUTES:
            candidates.append(h + timedelta(minutes=minute))

    for c in candidates:
        if c > now_utc:
            return c
    return hour_base + timedelta(hours=1, minutes=DECISION_MINUTES[0])


def bucket_for_decision(decision_utc: datetime) -> datetime:
    if decision_utc.tzinfo is None:
        decision_utc = decision_utc.replace(tzinfo=timezone.utc)
    return decision_utc.astimezone(timezone.utc) - timedelta(minutes=2)


def is_indicator_due(decision_phase_minutes: int, max_phase: str) -> bool:
    allowed = PHASE_TO_SECONDS[max_phase]
    required = 74 if decision_phase_minutes == 1 else 120
    return required <= allowed
