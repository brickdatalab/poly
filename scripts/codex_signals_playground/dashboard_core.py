from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

DECISION_MINUTES = (2, 17, 32, 47)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def next_decision_after(now_utc: datetime) -> datetime:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    now_utc = now_utc.astimezone(timezone.utc)

    hour_base = now_utc.replace(minute=0, second=0, microsecond=0)
    candidates = []
    for hour_shift in (0, 1, 2):
        h = hour_base + timedelta(hours=hour_shift)
        for minute in DECISION_MINUTES:
            candidates.append(h + timedelta(minutes=minute))

    for c in candidates:
        if c > now_utc:
            return c
    # Safety fallback, should never hit.
    return hour_base + timedelta(hours=1, minutes=DECISION_MINUTES[0])


def bucket_for_decision(decision_utc: datetime) -> datetime:
    if decision_utc.tzinfo is None:
        decision_utc = decision_utc.replace(tzinfo=timezone.utc)
    return decision_utc.astimezone(timezone.utc) - timedelta(minutes=2)


def summarize_pair_window(
    *,
    pair: str,
    bucket_time: datetime,
    rows: list[dict[str, Any]],
    sigma_std_by_config: dict[str, float],
    sigma_min: float = 0.25,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "pair": pair,
        "bucket_time": bucket_time.astimezone(timezone.utc).isoformat(),
        "signal_fired": bool(rows),
        "filter_pass": False,
        "prediction": "none",
        "rules_passed": len(rows),
        "sigma_from_threshold": None,
        "base_accuracy_ref": None,
        "top_rule_id": None,
        "detail": rows,
    }

    if not rows:
        return event

    # Weighted directional vote by sum(base_accuracy).
    score_by_side: dict[str, float] = defaultdict(float)
    rows_by_side: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        side = str(r.get("prediction", "none"))
        acc = float(r.get("base_accuracy") or 0.0)
        score_by_side[side] += acc
        rows_by_side[side].append(r)

    if not score_by_side:
        return event

    ordered = sorted(score_by_side.items(), key=lambda x: x[1], reverse=True)
    if len(ordered) >= 2 and abs(ordered[0][1] - ordered[1][1]) < 1e-12:
        chosen_side = "conflict"
        chosen_rows = rows
    else:
        chosen_side = ordered[0][0]
        chosen_rows = rows_by_side.get(chosen_side, rows)

    top_row = max(chosen_rows, key=lambda r: (float(r.get("base_accuracy") or 0.0), str(r.get("rule_id") or "")))

    cfg = str(top_row.get("config_id") or "")
    indicator_value = float(top_row.get("indicator_value") or 0.0)
    threshold = float(top_row.get("threshold") or 0.0)
    sd = sigma_std_by_config.get(cfg)
    sigma_val: float | None = None
    if sd is not None and sd > 0:
        sigma_val = (indicator_value - threshold) / sd

    event["prediction"] = chosen_side
    event["top_rule_id"] = top_row.get("rule_id")
    event["base_accuracy_ref"] = float(top_row.get("base_accuracy") or 0.0)
    event["sigma_from_threshold"] = round(sigma_val, 4) if sigma_val is not None else None
    event["filter_pass"] = bool(sigma_val is not None and abs(sigma_val) >= sigma_min and chosen_side in {"up", "down"})

    return event
