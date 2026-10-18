"""通用调度器：后台线程扫描 scheduled_jobs 表并分发到已注册的处理器。

各场景（定时转账 / 生日检测 / 续费提醒）通过 register_handler 注册自己的
处理函数 handler(db, job) -> None。处理完成后 job 会被标记为 done。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Callable

from sqlalchemy import select

from ..core.database import SessionLocal
from ..core.models import ScheduledJob
from ..core.timeutil import utcnow

logger = logging.getLogger(__name__)

_HANDLERS: dict[str, Callable] = {}
_lock = threading.Lock()
_started = False


def register_handler(job_type: str, handler: Callable) -> None:
    with _lock:
        _HANDLERS[job_type] = handler


def process_due_jobs() -> int:
    """处理所有到期的 pending 任务，返回处理数量。"""
    db = SessionLocal()
    try:
        now = utcnow()
        jobs = list(
            db.execute(
                select(ScheduledJob).where(
                    ScheduledJob.status == "pending",
                    ScheduledJob.run_at <= now,
                )
            ).scalars().all()
        )
        for job in jobs:
            handler = _HANDLERS.get(job.job_type)
            if handler is None:
                logger.warning("未注册的任务类型: %s", job.job_type)
                continue
            try:
                handler(db, job)
            except Exception as exc:  # noqa: BLE001
                logger.exception("任务 %s 执行失败: %s", job.id, exc)
            job.status = "done"
        db.commit()
        return len(jobs)
    finally:
        db.close()


def _loop(interval: float) -> None:
    while True:
        try:
            process_due_jobs()
        except Exception:  # noqa: BLE001
            logger.exception("调度循环异常")
        time.sleep(interval)


def start_scheduler(interval: float = 20.0) -> None:
    global _started
    if _started:
        return
    _started = True
    thread = threading.Thread(target=_loop, args=(interval,), daemon=True, name="job-scheduler")
    thread.start()
    logger.info("调度器已启动（间隔 %.0fs）", interval)
