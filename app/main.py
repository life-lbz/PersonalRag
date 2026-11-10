"""FastAPI 入口。"""
from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.types import ASGIApp

from app.api import chat, documents, kb, laws, search
from app.config import settings
from app.observability import (
    bind_request_id,
    get_request_id,
    reset_request_id,
    setup_logging,
)

setup_logging(settings.logging.level, log_name="api")

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
        path = scope.get("path", "")
        if scope["type"] != "http" or not settings.auth.enabled \
                or scope.get("method") == "OPTIONS" \
                or path in _PUBLIC_PATHS \
                or not path.startswith("/api/"):
            # 仅保护 /api/** 业务接口；前端静态资源与 SPA 页面公开（不含数据）
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
            # trust_env=False：模型服务走本机回环/SSH 隧道，不能被系统代理劫持
            async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
                resp = await client.get(url)
            checks[name] = "ok" if resp.status_code == 200 else f"fail: http {resp.status_code}"
        except Exception as e:
            checks[name] = f"fail: {e}"

    ok = all(v == "ok" for v in checks.values())
    return {"status": "ok" if ok else "degraded", "checks": checks}


# ---------- 前端生产托管：FastAPI 直接服务 frontend/dist（同源部署，免 CORS） ----------
from app.config import PROJECT_ROOT  # noqa: E402

_DIST = PROJECT_ROOT / "frontend" / "dist"


def _no_cache_html(path):  # index.html 不缓存，assets 走内容 hash 长缓存
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


if _DIST.is_dir():

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        """SPA 托管：已存在的静态文件直接返回，其余路径回退 index.html（前端路由）。"""
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        if full_path:
            file = _DIST / full_path
            if file.is_file():
                # vite 产物 assets/ 文件名带内容 hash，可长缓存
                headers = {"Cache-Control": "public, max-age=31536000, immutable"} \
                    if full_path.startswith("assets/") else {}
                return FileResponse(file, headers=headers)
        return _no_cache_html(_DIST / "index.html")
else:
    logging.getLogger("app").warning("frontend/dist 不存在，API 以纯接口模式运行（先执行 npm run build）")
