"""模型推理服务客户端：embedding(:8001) / rerank(:8002) / LLM(vLLM :8000, OpenAI 兼容)。"""
from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from typing import Any

import app._platform_fix  # noqa: F401  Windows 下短路 WMI 平台查询，避免 openai/aiohttp 导入卡死

import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.clients.redis_client import cache_get_json, cache_set_json


# ---------- embedding ----------
async def embed_texts(texts: list[str]) -> tuple[list[list[float]], list[dict]]:
    """返回 (dense_vecs, sparse_vecs)。sparse 为 {token_id_str: weight} dict。"""
    cfg = settings.models.embedding
    async with httpx.AsyncClient(timeout=cfg.timeout) as client:
        resp = await client.post(
            f"{cfg.base_url}/v1/embeddings", json={"texts": texts}, headers={"X-Model": cfg.model}
        )
        resp.raise_for_status()
        data = resp.json()
    return data["dense"], data["sparse"]


async def embed_query(query: str) -> tuple[list[float], dict[int, float]]:
    """查询向量，带 Redis 缓存（TTL query_embedding_ttl）。"""
    key = f"query:emb:{hashlib.md5(query.encode()).hexdigest()}"
    cached = await cache_get_json(key)
    if cached:
        return cached["dense"], {int(k): v for k, v in cached["sparse"].items()}
    dense_list, sparse_list = await embed_texts([query])
    dense, sparse = dense_list[0], sparse_list[0]
    await cache_set_json(key, {"dense": dense, "sparse": sparse}, ttl=settings.retrieve.cache.query_embedding_ttl)
    return dense, {int(k): v for k, v in sparse.items()}


# ---------- rerank ----------
async def rerank(query: str, documents: list[str]) -> list[float]:
    cfg = settings.models.rerank
    scores: list[float] = []
    batch = cfg.batch_size
    async with httpx.AsyncClient(timeout=cfg.timeout) as client:
        for i in range(0, len(documents), batch):
            resp = await client.post(
                f"{cfg.base_url}/v1/rerank",
                json={"query": query, "documents": documents[i : i + batch]},
            )
            resp.raise_for_status()
            scores.extend(resp.json()["scores"])
    return scores


# ---------- LLM ----------
def get_llm_client() -> AsyncOpenAI:
    cfg = settings.models.llm
    # vLLM 未启用 --api-key 时不校验该值, 此处仅为 OpenAI SDK 的必填占位
    return AsyncOpenAI(base_url=cfg.base_url, api_key="EMPTY", timeout=cfg.timeout)


async def llm_chat(messages: list[dict], stream: bool = False, **kwargs) -> Any:
    cfg = settings.models.llm
    client = get_llm_client()
    return await client.chat.completions.create(
        model=cfg.model,
        messages=messages,  # type: ignore[arg-type]
        temperature=cfg.temperature,
        max_tokens=cfg.max_output_tokens,
        stream=stream,
        **kwargs,
    )


async def llm_chat_stream(messages: list[dict]) -> AsyncIterator[str]:
    """流式返回增量文本。"""
    stream = await llm_chat(messages, stream=True)
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


async def llm_json(messages: list[dict]) -> dict:
    """非流式调用并解析 JSON 输出（router/planner 用）。"""
    text = ""
    try:
        resp = await llm_chat(messages, stream=False)
        text = resp.choices[0].message.content or ""
    except Exception:
        return {}
    # 宽容解析：截取首个 { 到末个 }
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
