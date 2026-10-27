"""Celery 应用：高低优先级队列分离（§7 部署设计）。"""
from __future__ import annotations

from celery import Celery

from app.config import settings

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
)
