# aegis/utils/time.py
from __future__ import annotations

from datetime import date as dt_date, datetime, time as dt_time, timezone
from time import perf_counter

__all__ = ["dt_date", "dt_time", "datetime", "timezone", "utcnow", "perf_counter"]

def utcnow() -> datetime:
    return datetime.now(timezone.utc)