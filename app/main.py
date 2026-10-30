"""FastAPI 入口。"""
from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp

from app.api import chat, documents, kb, laws, search
from app.config import settings
from app.observability import (
    bind_request_id,
    get_request_id,
    reset_request_id,
    setup_logging,
)

setup_logging(settings.logging.level)

# 免鉴权路径（容器探活/负载均衡健康检查）
_PUBLIC_PATHS = {"/health"}


def _scope_header(scope: dict, name: str) -> str:
    for key, value in scope.get("headers", []):
        if key.decode("latin-1").lower() == name:
            return value.decode("latin-1")
    return ""


class ApiAuthMiddleware:
    """L5: Bearer token / X-API-Key 鉴权（默认关闭，prod 在 config 中开启）。

    用纯 ASGI 实现而非 BaseHTTPMiddleware：后者会包装响应体迭代器，
    对 SSE 流式响应可能造成分块结束不完整（浏览器表现为 ERR_ABORTED）。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not settings.auth.enabled \
                or scope.get("method") == "OPTIONS" \
                or scope.get("path") in _PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        api_key = _scope_header(scope, "x-api-key").strip()
        auth = _scope_header(scope, "authorization")
        token = api_key or (auth[7:].strip() if auth.lower().startswith("bearer ") else "")
        if not token or not any(hmac.compare_digest(token, t) for t in settings.auth.tokens):
            await JSONResponse({"detail": "unauthorized"}, status_code=401)(scope, receive, send)
            return
        await self.app(scope, receive, send)


class RequestContextMiddleware:
    """L4: 为每个请求建立 request_id 上下文并回写响应头，日志自动带上它。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = bind_request_id(_scope_header(scope, "x-request-id") or None)
        rid = get_request_id()

        async def send_with_header(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", rid.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            reset_request_id(token)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log = logging.getLogger("app")
    log.info("PersonalRag api-server 启动 (env=%s)", settings.env)
    if settings.auth.enabled and not settings.auth.tokens:
        log.warning("auth.enabled=true 但 tokens 为空，所有业务接口都会被拒绝")
    yield


app = FastAPI(title="PersonalRag", version="0.1.0", lifespan=lifespan)

# 注册顺序 = 内层 → 外层（后注册的包住先注册的）
app.add_middleware(ApiAuthMiddleware)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(kb.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(search.router)
app.include_router(laws.router)


@app.get("/health")
async def health():
    """全链路健康探测：PG / Redis / Milvus / MinIO / 模型服务。"""
    checks: dict[str, str] = {}
    # PG
    try:
        from sqlalchemy import text

        from app.db.session import async_engine
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"fail: {e}"
    # Redis
    try:
        from app.clients.redis_client import get_async_redis

        await get_async_redis().ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"fail: {e}"
    # Milvus（连通性测试即可，database/collection 由 _ensure_kb_db 懒创建）
    try:
        from pymilvus import MilvusClient
        MilvusClient(uri=settings.milvus.uri, db_name="default").list_collections()
        checks["milvus"] = "ok"
    except Exception as e:
        checks["milvus"] = f"fail: {e}"
    # 模型服务
    import httpx

    for name, url in [("embedding", f"{settings.models.embedding.base_url}/health"),
                      ("rerank", f"{settings.models.rerank.base_url}/health"),
                      ("llm", f"{settings.models.llm.base_url}/models")]:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(url)
            checks[name] = "ok" if resp.status_code == 200 else f"fail: http {resp.status_code}"
        except Exception as e:
            checks[name] = f"fail: {e}"

    ok = all(v == "ok" for v in checks.values())
    return {"status": "ok" if ok else "degraded", "checks": checks}
