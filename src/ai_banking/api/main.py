"""FastAPI 应用入口：REST + WebSocket 通道。

启动时初始化数据库、注册场景工具并启动后台调度器；
提供 /health、/api/tools、/api/chat 与 /ws/chat 等接口。
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ai_banking.config import settings
from ai_banking.core.database import SessionLocal, init_db
from ai_banking.core.tooling import registry
from ai_banking.domain.scheduler import start_scheduler


class ChatRequest(BaseModel):
    user_id: int
    session_id: Optional[str] = None
    message: str


def _run_chat(user_id: int, session_id: Optional[str], message: str) -> dict:
    """执行一轮对话，返回完整响应结构（含 session_id）。"""
    from ai_banking.agent.graph import run_agent

    sid = session_id or str(uuid.uuid4())
    db = SessionLocal()
    try:
        result = run_agent(db, int(user_id), sid, message)
    finally:
        db.close()
    return {
        "session_id": sid,
        "response": result.get("response"),
        "intent": result.get("intent"),
        "tool_used": result.get("tool_used"),
        "data": result.get("data"),
        "requires_confirmation": result.get("requires_confirmation"),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    import ai_banking.agent.tools  # noqa: F401  触发各场景工具注册
    try:
        start_scheduler()
    except Exception:  # noqa: BLE001
        pass
    yield


app = FastAPI(title="AI Banking Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "tools": len(registry.names()),
        "llm_configured": settings.llm_configured,
    }


@app.get("/api/tools")
def list_tools() -> dict:
    return {"tools": registry.describe()}


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    return _run_chat(req.user_id, req.session_id, req.message)


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            payload = await ws.receive_json()
            req = ChatRequest(**payload)
            await ws.send_json(_run_chat(req.user_id, req.session_id, req.message))
    except WebSocketDisconnect:
        pass


# 静态文件挂载须在 API 路由之后，使已注册路由优先。
_web_dir = Path(__file__).resolve().parents[1] / "web"
_web_dir.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(_web_dir), html=True), name="web")
