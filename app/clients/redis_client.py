"""Redis 客户端（幂等缓存/查询缓存/结果缓存）。"""
from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aredis
import redis as sync_redis

from app.config import settings

_async_client: aredis.Redis | None = None
_sync_client: sync_redis.Redis | None = None


def get_async_redis() -> aredis.Redis:
    global _async_client
    if _async_client is None:
        _async_client = aredis.from_url(settings.redis.url, decode_responses=True)
    return _async_client


def get_sync_redis() -> sync_redis.Redis:
    """Celery 任务内使用。"""
    global _sync_client
    if _sync_client is None:
        _sync_client = sync_redis.from_url(settings.redis.url, decode_responses=True)
    return _sync_client


async def cache_get_json(key: str) -> Any | None:
    r = get_async_redis()
    val = await r.get(key)
    return json.loads(val) if val else None


async def cache_set_json(key: str, value: Any, ttl: int | None = None) -> None:
    r = get_async_redis()
    await r.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)


def cache_get_json_sync(key: str) -> Any | None:
    r = get_sync_redis()
    val = r.get(key)
    return json.loads(val) if val else None


def cache_set_json_sync(key: str, value: Any, ttl: int | None = None) -> None:
    r = get_sync_redis()
    r.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
