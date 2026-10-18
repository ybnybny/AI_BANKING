"""审计日志。"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..core.models import AuditLog


def log_audit(
    db: Session,
    user_id: int | None,
    action: str,
    payload: dict[str, Any] | None = None,
    risk: str = "low",
    status: str = "success",
) -> None:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        payload=json.dumps(payload or {}, ensure_ascii=False, default=str),
        risk=risk,
        status=status,
    )
    db.add(entry)
    db.commit()
