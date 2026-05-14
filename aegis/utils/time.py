# aegis/utils/time.py
from __future__ import annotations

from datetime import date, datetime, time as dt_time, timezone
from time import perf_counter

__all__ = ["dt_time", "date", "datetime", "timezone", "utcnow", "perf_counter"]

def utcnow() -> datetime:
    return datetime.now(timezone.utc)