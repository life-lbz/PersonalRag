"""向量化客户端（Celery worker 内同步调用 embedding 服务）。"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def embed_texts_sync(texts: list[str]) -> tuple[list[list[float]], list[dict]]:
    cfg = settings.models.embedding
    out_dense: list[list[float]] = []
    out_sparse: list[dict] = []
    batch = max(1, cfg.batch_size)
    with httpx.Client(timeout=cfg.timeout) as client:
        for i in range(0, len(texts), batch):
            resp = client.post(f"{cfg.base_url}/v1/embeddings",
                               json={"texts": texts[i : i + batch]})
            resp.raise_for_status()
            data = resp.json()
            out_dense.extend(data["dense"])
            out_sparse.extend(data["sparse"])
    return out_dense, out_sparse
