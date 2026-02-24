from __future__ import annotations

import datetime as dt


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def utc_slug(ts: dt.datetime | None = None) -> str:
    t = ts or utc_now()
    return t.strftime("%Y%m%dT%H%M%SZ")

