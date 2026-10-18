"""时间工具：无时区的 UTC 当前时间（保持与 datetime.utcnow 相同的朴素语义）。"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
