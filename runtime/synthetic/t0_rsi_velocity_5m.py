#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone

from engine import evaluate_indicator, floor_15m, iso_z, print_payload


def main() -> int:
    bucket = floor_15m(datetime.now(timezone.utc))
    payload = evaluate_indicator("rsi_velocity_5m", ["BTC-USD", "ETH-USD"], iso_z(bucket))
    print_payload(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
