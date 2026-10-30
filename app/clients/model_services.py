"""模型推理服务客户端：embedding(:8001) / rerank(:8002) / LLM(Ollama :11434, OpenAI 兼容)。"""
from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import AsyncIterator

import app._platform_fix  # noqa: F401  Windows 下短路 WMI 平台查询，避免 openai/aiohttp 导入卡死

import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.clients.redis_client import cache_get_json, cache_set_json

logger = logging.getLogger(__name__)


# ---------- embedding ----------
async def embed_texts(texts: list[str], use_cache: bool = False) -> tuple[list[list[float]], list[dict]]:
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
# 资源不足（显存/内存）时 Ollama 加载模型会直接失败；OpenAI 兼容接口不透传 num_gpu/num_ctx，
# 因此降档走 Ollama 原生 /api/chat，并按档位逐级降低 GPU 层数与上下文后重试。
_OOM_MARKERS = ("out of memory", "cudamalloc", "failed to allocate", "unable to allocate")
_DEGRADE_LADDER: list[tuple[int, int]] = [(18, 4096), (8, 2048), (0, 2048)]
_native_profile: tuple[int, int] | None = None  # 已生效的降档档位；非 None 时后续直接走原生接口


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Message(content)


class _TextCompletion:
    """把原生接口结果包装成与 OpenAI 一致的结构（choices[0].message.content）。"""

    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


def get_llm_client() -> AsyncOpenAI:
    cfg = settings.models.llm
    return AsyncOpenAI(base_url=cfg.base_url, api_key="ollama", timeout=cfg.timeout)


def _is_oom_error(exc: Exception) -> bool:
    parts = [str(exc)]
    response = getattr(exc, "response", None)
    if response is not None:
        parts.append(getattr(response, "text", "") or "")
    text = " ".join(parts).casefold()
    return any(marker in text for marker in _OOM_MARKERS)


def _native_chat_url() -> str:
    base = settings.models.llm.base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return f"{base}/api/chat"


def _native_payload(messages: list[dict], profile: tuple[int, int], stream: bool) -> dict:
    cfg = settings.models.llm
    return {
        "model": cfg.model,
        "messages": messages,
        "stream": stream,
        "options": {
            "temperature": cfg.temperature,
            "num_predict": cfg.max_output_tokens,
            "num_gpu": profile[0],
            "num_ctx": profile[1],
        },
    }


async def _native_chat(messages: list[dict], profile: tuple[int, int]) -> str:
    async with httpx.AsyncClient(timeout=settings.models.llm.timeout) as client:
        resp = await client.post(_native_chat_url(), json=_native_payload(messages, profile, False))
        if resp.status_code >= 400:
            raise RuntimeError(f"Ollama {resp.status_code}: {resp.text[:500]}")
        body = resp.json()
    return (body.get("message") or {}).get("content") or ""


async def _native_chat_stream(messages: list[dict], profile: tuple[int, int]) -> AsyncIterator[str]:
    async with httpx.AsyncClient(timeout=settings.models.llm.timeout) as client:
        async with client.stream("POST", _native_chat_url(), json=_native_payload(messages, profile, True)) as resp:
            if resp.status_code >= 400:
                detail = (await resp.aread()).decode("utf-8", "ignore")
                raise RuntimeError(f"Ollama {resp.status_code}: {detail[:500]}")
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("error"):
                    raise RuntimeError(f"Ollama: {data['error']}")
                piece = (data.get("message") or {}).get("content") or ""
                if piece:
                    yield piece


def _ladder_start() -> int:
    if _native_profile is None:
        return 0
    return _DEGRADE_LADDER.index(_native_profile) + 1


def _remember_profile(profile: tuple[int, int]) -> None:
    global _native_profile
    if _native_profile != profile:
        _native_profile = profile
        logger.warning("LLM 资源不足, 已自动降档: num_gpu=%s num_ctx=%s", profile[0], profile[1])


async def _chat_with_degrade(messages: list[dict], first_exc: Exception) -> _TextCompletion:
    last_exc = first_exc
    for profile in _DEGRADE_LADDER[_ladder_start():]:
        try:
            text = await _native_chat(messages, profile)
        except Exception as native_exc:
            last_exc = native_exc
            if not _is_oom_error(native_exc):
                raise
            continue
        _remember_profile(profile)
        return _TextCompletion(text)
    raise last_exc


async def _stream_with_degrade(messages: list[dict]) -> AsyncIterator[str]:
    last_exc: Exception | None = None
    for profile in _DEGRADE_LADDER[_ladder_start():]:
        emitted = False
        try:
            async for piece in _native_chat_stream(messages, profile):
                emitted = True
                yield piece
        except Exception as native_exc:
            if emitted or not _is_oom_error(native_exc):
                raise
            last_exc = native_exc
            continue
        _remember_profile(profile)
        return
    raise last_exc or RuntimeError("LLM 降档重试已耗尽")


async def llm_chat(messages: list[dict], stream: bool = False, **kwargs) -> Any:
    cfg = settings.models.llm
    if _native_profile is not None and not stream:
        return _TextCompletion(await _native_chat(messages, _native_profile))
    client = get_llm_client()
    try:
        return await client.chat.completions.create(
            model=cfg.model,
            messages=messages,  # type: ignore[arg-type]
            temperature=cfg.temperature,
            max_tokens=cfg.max_output_tokens,
            stream=stream,
            **kwargs,
        )
    except Exception as exc:
        if stream or not _is_oom_error(exc):
            raise
        logger.warning("LLM 加载失败(资源不足), 开始自动降档重试: %s", str(exc)[:200])
        return await _chat_with_degrade(messages, exc)


async def llm_chat_stream(messages: list[dict]) -> AsyncIterator[str]:
    """流式返回增量文本；资源不足时自动降档后继续。"""
    if _native_profile is not None:
        async for piece in _native_chat_stream(messages, _native_profile):
            yield piece
        return
    try:
        stream = await llm_chat(messages, stream=True)
    except Exception as exc:
        if not _is_oom_error(exc):
            raise
        logger.warning("LLM 流式加载失败(资源不足), 开始自动降档重试: %s", str(exc)[:200])
        async for piece in _stream_with_degrade(messages):
            yield piece
        return
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
