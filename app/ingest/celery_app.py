"""Celery 应用：高低优先级队列分离（§7 部署设计）。"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging as celery_setup_logging

from app.config import settings
from app.observability import setup_logging

celery_app = Celery(
    "personal_rag",
    broker=settings.celery.broker_url,
    backend=settings.celery.result_backend,
    include=["app.ingest.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_default_queue="high_priority",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    # Windows: 由启动参数指定 --pool=threads / solo
    timezone="Asia/Shanghai",
    enable_utc=False,
    # 定时任务：每日 03:00 清理已过 purge_after 窗口的 archived 版本
    beat_schedule={
        "purge-archived-versions": {
            "task": "ingest.purge_archived",
            "schedule": crontab(hour=3, minute=0),
            "options": {"queue": "high_priority"},
        },
    },
)


@celery_setup_logging.connect
def _configure_worker_logging(**_kwargs) -> None:
    """L4: worker 日志与 API 使用同一格式（含 request_id）。"""
    setup_logging(settings.logging.level)
