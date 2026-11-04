"""链路追踪与日志（L4）：request_id 贯穿 API → 日志 → Celery 任务。

用法：
  - FastAPI 中间件为每个请求分配 request_id（默认 uuid 前 12 位，也接受客户端 X-Request-ID）
  - 日志格式自动带上 request_id
  - Celery 任务通过 headers 透传，任务内部 bind_request_id 后可继续关联同一条请求
"""
from __future__ import annotations

import contextvars
import logging
import uuid

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def get_request_id() -> str:
    return _request_id.get()


def bind_request_id(rid: str | None = None) -> contextvars.Token:
    """绑定 request_id（空则新建），返回用于恢复的 token。"""
    return _request_id.set(rid or new_request_id())


def reset_request_id(token: contextvars.Token) -> None:
    _request_id.reset(token)


class RequestIdFilter(logging.Filter):
    """把当前上下文的 request_id 注入每条日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = _request_id.get()
        return True


def setup_logging(level: str = "INFO", log_name: str = "app") -> None:
    """统一日志（含 request_id）：控制台 + 文件双写。API 与 Celery worker 共用。

    文件：logs/{log_name}-{pid}.log，按天轮转（TimedRotatingFileHandler），
    保留 logging.file_max_days 天；带 pid 是避免多进程（uvicorn workers）轮转时抢文件锁。
    """
    fmt = logging.Formatter("%(asctime)s [%(request_id)s] %(name)s %(levelname)s %(message)s")

    console = logging.StreamHandler()
    console.addFilter(RequestIdFilter())
    console.setFormatter(fmt)

    handlers: list[logging.Handler] = [console]

    from app.config import PROJECT_ROOT, settings

    if settings.logging.file_enabled:
        log_dir = PROJECT_ROOT / settings.logging.dir
        log_dir.mkdir(parents=True, exist_ok=True)
        import os
        from logging.handlers import TimedRotatingFileHandler

        file_handler = TimedRotatingFileHandler(
            log_dir / f"{log_name}-{os.getpid()}.log",
            when="midnight",
            backupCount=settings.logging.file_max_days,
            encoding="utf-8",
        )
        file_handler.addFilter(RequestIdFilter())
        file_handler.setFormatter(fmt)
        handlers.append(file_handler)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = handlers
