"""app.ingest 包入口：`celery -A app.ingest worker ...` 引导。"""
from .celery_app import celery_app

__all__ = ["celery_app"]
