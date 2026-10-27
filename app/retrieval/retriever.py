"""三段式检索：宽召回 top100（向量+稀疏+过滤）→ 版本过滤(searchable) → 融合 → rerank(0.2 硬过滤, Top5)。

依据《RAG系统方案设计文档.md》§3.2.2/§5.2、《基本配置文档》§3.1。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select

from app.clients import milvus_client
from app.clients.model_services import embed_query, rerank as rerank_api
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ScoredChunk:
    chunk_id: str
    doc_id: str | None = None
    score: float = 0.0          # 融合分
    cosine: float = 0.0
    fulltext: float = 0.0
    rerank_score: float | None = None
    content: str = ""
    token_count: int = 0
    doc_title: str = ""
    page: int | None = None
    parent_id: str | None = None
    metadata: dict = field(default_factory=dict)


async def hybrid_search(query: str, kb_id: str, top_k: int | None = None) -> list[ScoredChunk]:
    """三路召回 → question/dense 同 chunk 取 max → 融合 → searchable 过滤 → rerank。"""
    cfg = settings.retrieve
    k = top_k or cfg.per_channel_top_k

    dense_vec, sparse_vec = await embed_query(query)
    dense_hits = milvus_client.search_dense(kb_id, dense_vec, k)
    question_hits = milvus_client.search_question(kb_id, dense_vec, k)
    sparse_hits = milvus_client.search_sparse(kb_id, sparse_vec, k)

    # question 召回与 dense 召回对同一 chunk 取分数最大值，视为同一路 cosine（§3.1）
    cosine_map: dict[str, float] = {}
    for h in dense_hits:
        cosine_map[h["chunk_id"]] = max(cosine_map.get(h["chunk_id"], 0.0), h["score"])
    for h in question_hits:
        cosine_map[h["chunk_id"]] = max(cosine_map.get(h["chunk_id"], 0.0), h["score"])

    # sparse 分数归一化到 0-1（IP 内积除以最大值）
    sparse_map: dict[str, float] = {h["chunk_id"]: h["score"] for h in sparse_hits}
    max_sparse = max(sparse_map.values()) if sparse_map else 0.0
    if max_sparse > 0:
        sparse_map = {cid: s / max_sparse for cid, s in sparse_map.items()}

    # 融合（weighted | rrf）
    all_ids = set(cosine_map) | set(sparse_map)
    scored: dict[str, ScoredChunk] = {}
    if cfg.fusion.mode == "rrf":
        rrf_k = 60
        rank_dense = {h["chunk_id"]: i for i, h in enumerate(
            sorted(dense_hits + question_hits, key=lambda x: -x["score"]))}
        rank_sparse = {h["chunk_id"]: i for i, h in enumerate(sparse_hits)}
        for cid in all_ids:
            s = 0.0
            if cid in rank_dense:
                s += 1.0 / (rrf_k + rank_dense[cid])
            if cid in rank_sparse:
                s += 1.0 / (rrf_k + rank_sparse[cid])
            scored[cid] = ScoredChunk(chunk_id=cid, score=s)
    else:
        w = cfg.fusion.vector_weight
        for cid in all_ids:
            cos = cosine_map.get(cid, 0.0)
            full = sparse_map.get(cid, 0.0)
            scored[cid] = ScoredChunk(chunk_id=cid, score=w * cos + (1 - w) * full,
                                      cosine=cos, fulltext=full)

    # kb 静态加权：kb_boost 默认空；启用时在 _filter_searchable 回填 kb_id 后按库加分（预留）

    # 版本过滤：回 PG 过滤 searchable=true（§5.3 检索一致性）
    candidates = sorted(scored.values(), key=lambda x: -x.score)[: cfg.rerank.candidate_pool_max]
    candidates = await _filter_searchable(candidates, kb_id)

    # rerank 硬过滤 + TopN
    if not candidates:
        return []
    texts = await _load_contents(candidates)
    scores = await rerank_api(query, texts)
    for c, s in zip(candidates, scores):
        c.rerank_score = float(s)
    passed = [c for c in candidates if c.rerank_score >= cfg.rerank.score_threshold]
    passed.sort(key=lambda x: -(x.rerank_score or 0))
    result = passed[: cfg.rerank.top_n]
    logger.info("检索 %s: 候选%d → searchable后%d → rerank通过%d → 取%d",
                query[:20], len(scored), len(candidates), len(passed), len(result))
    return result


async def _filter_searchable(candidates: list[ScoredChunk], kb_id: str) -> list[ScoredChunk]:
    """Milvus 宽召回后、入 rerank 池前，按 chunk 的 version 回 PG 过滤 searchable=true。"""
    from app.db.session import AsyncSessionLocal
    from app.models.entities import Chunk, Document

    ids = [c.chunk_id for c in candidates]
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Chunk.id, Chunk.doc_id, Chunk.parent_id, Chunk.meta)
            .where(Chunk.id.in_(ids), Chunk.searchable.is_(True))
        )).all()
        docs = (await session.execute(
            select(Document.id, Document.title).where(Document.kb_id == kb_id)
        )).all()
    title_map = {d.id: d.title for d in docs}
    valid = {r.id: r for r in rows}
    out = []
    for c in candidates:
        if c.chunk_id not in valid:
            continue
        r = valid[c.chunk_id]
        c.doc_id = r.doc_id
        c.parent_id = r.parent_id
        c.metadata = r.meta or {}
        c.doc_title = title_map.get(r.doc_id, "")
        c.page = (r.meta or {}).get("page")
        out.append(c)
    return out


async def _load_contents(candidates: list[ScoredChunk]) -> list[str]:
    from app.db.session import AsyncSessionLocal
    from app.models.entities import Chunk

    ids = [c.chunk_id for c in candidates]
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(Chunk.id, Chunk.content).where(Chunk.id.in_(ids))
        )).all()
    content_map = {r.id: r.content for r in rows}
    for c in candidates:  # 回填内容, 供组装与展示使用
        if c.chunk_id in content_map:
            c.content = content_map[c.chunk_id]
    return [c.content for c in candidates]
