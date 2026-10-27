"""FastAPI 入口。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, documents, kb, laws, search
from app.config import settings

logging.basicConfig(level=settings.logging.level,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.getLogger("app").info("PersonalRag api-server 启动 (env=%s)", settings.env)
    yield


app = FastAPI(title="PersonalRag", version="0.1.0", lifespan=lifespan)

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
