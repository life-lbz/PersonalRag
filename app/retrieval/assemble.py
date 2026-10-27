"""token 预算组装 + 父子块合并（§5.4 算法 + §3.3 优化点）。"""
from __future__ import annotations

import asyncio
import logging
from collections import Counter

from sqlalchemy import select

from app.config import settings

from .retriever import ScoredChunk

logger = logging.getLogger(__name__)


def assemble_context(reranked: list[ScoredChunk], query: str, history: str = "") -> tuple[str, list[ScoredChunk]]:
    """返回 (context_text, 实际使用的 chunks)。
    预算 = 窗口 − max_output − query − history − prompt模板预留（§5.4）。
    末篇超预算: 保头尾截中间（keep_head_tail）。"""
    from app.ingest.tokenizer import count_tokens

    a = settings.assemble
    budget = a.context_window - a.max_output - count_tokens(query) - count_tokens(history) - a.prompt_overhead
    if budget <= 0:
        budget = a.context_window // 2

    chunks = _merge_siblings(reranked) if a.merge_sibling_chunks else list(reranked)

    parts: list[str] = []
    used: list[ScoredChunk] = []
    for c in chunks:
        t = c.token_count or len(c.content)
        if budget - t >= 0:
            parts.append(_render(c, len(used) + 1))
            used.append(c)
            budget -= t
        elif budget > 100:  # 末篇超预算: 截断后结束
            parts.append(_render_truncated(c, len(used) + 1, budget))
            used.append(c)
            break
        else:
            break
    return "\n\n".join(parts), used


def _merge_siblings(reranked: list[ScoredChunk]) -> list[ScoredChunk]:
    """同一父块的多个子块被命中时，合并返回父块（LlamaIndex AutoMerging, 配置级开关）。"""
    parent_counter = Counter(c.parent_id for c in reranked if c.parent_id)
    need_parents = {c.parent_id for c in reranked if c.parent_id and parent_counter[c.parent_id] >= 2}
    parent_map = _load_parents_sync(need_parents) if need_parents else {}

    out: list[ScoredChunk] = []
    for c in reranked:
        if c.parent_id and c.parent_id in parent_map:
            merged = parent_map[c.parent_id]
            if merged is None or any(x.chunk_id == merged.chunk_id for x in out):
                continue  # 父块缺失或已并入
            merged.rerank_score = c.rerank_score
            merged.cosine = max(merged.cosine, c.cosine)
            out.append(merged)
        else:
            out.append(c)
    return out


def _load_parents_sync(parent_ids: set[str]) -> dict[str, ScoredChunk | None]:
    from app.db.session import AsyncSessionLocal
    from app.models.entities import Chunk

    async def _q():
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(
                select(Chunk).where(Chunk.id.in_(list(parent_ids)))
            )).scalars().all()
            return rows

    try:
        loop = asyncio.new_event_loop()
        try:
            rows = loop.run_until_complete(_q())
        finally:
            loop.close()
    except Exception:
        logger.exception("父块加载失败")
        return {pid: None for pid in parent_ids}

    out: dict[str, ScoredChunk | None] = {pid: None for pid in parent_ids}
    for r in rows:
        out[r.id] = ScoredChunk(chunk_id=r.id, content=r.content, token_count=r.token_count,
                                doc_id=r.doc_id, metadata=r.meta or {},
                                page=(r.meta or {}).get("page"))
    return out


def _render(c: ScoredChunk, n: int) -> str:
    loc = f"（来源{n}: {c.doc_title}{' 第' + str(c.page) + '页' if c.page else ''}）"
    return f"[{n}] {c.content}\n{loc}"


def _render_truncated(c: ScoredChunk, n: int, budget: int) -> str:
    text = c.content
    if budget < len(text):
        half = budget // 2
        text = text[: budget - half] + "\n...(中间省略)...\n" + text[-half:]
    return f"[{n}] {text}\n（来源{n}: {c.doc_title}）"
