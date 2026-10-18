"""会话记忆：消息历史持久化 + 待确认操作存储。"""
from __future__ import annotations

import threading
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.models import Conversation
from ..schemas.common import AgentMessage

_lock = threading.Lock()
# session_id -> 待确认操作 {tool, args, prompt, risk}
_pending: dict[str, dict[str, Any]] = {}


def save_message(db: Session, user_id: int, session_id: str, role: str, content: str) -> None:
    db.add(Conversation(user_id=user_id, session_id=session_id, role=role, content=content))
    db.commit()


def get_history(db: Session, user_id: int, session_id: str, limit: int = 20) -> list[AgentMessage]:
    rows = db.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.session_id == session_id)
        .order_by(Conversation.id.desc())
        .limit(limit)
    ).scalars().all()
    rows = list(reversed(rows))
    return [AgentMessage(role=r.role, content=r.content) for r in rows]


def set_pending(session_id: str, payload: dict[str, Any]) -> None:
    with _lock:
        _pending[session_id] = payload


def get_pending(session_id: str) -> dict[str, Any] | None:
    with _lock:
        return _pending.get(session_id)


def clear_pending(session_id: str) -> None:
    with _lock:
        _pending.pop(session_id, None)
