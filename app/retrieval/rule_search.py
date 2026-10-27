"""规则检索通道：元数据精确命中（如"《法名》第X条"）→ 命中即直出原文；未命中降级 hybrid。"""
from __future__ import annotations

import logging
import re

from sqlalchemy import select

from app.models.entities import Chunk, Document, LawArticle

logger = logging.getLogger(__name__)

_RULE_PATTERN_STRONG = re.compile(r"《(?P<law>[^》]{2,60})》\s*(?:的\s*)?第(?P<art>[一二三四五六七八九十百千零\d]+)条")


async def rule_lookup(query: str, kb_id: str):
    """强模式精确命中：返回 (chunks, law_name)；chunks=None 表示未命中需降级 hybrid。"""
    from app.db.session import AsyncSessionLocal
    from app.retrieval.retriever import ScoredChunk

    m = _RULE_PATTERN_STRONG.search(query)
    if not m:
        return None, None
    law_name, article_no = m.group("law"), f"第{m.group('art')}条"

    async with AsyncSessionLocal() as session:
        q = (
            select(LawArticle, Chunk, Document.title)
            .join(Document, Document.id == LawArticle.doc_id)
            .join(Chunk, Chunk.doc_id == LawArticle.doc_id)
            .where(
                Document.kb_id == kb_id,
                LawArticle.law_name == law_name,
                LawArticle.article_no == article_no,
                Chunk.meta["article_no"].astext == article_no,
                Chunk.searchable.is_(True),
            )
        )
        rows = (await session.execute(q.limit(10))).all()

    if not rows:
        return None, law_name

    out = [
        ScoredChunk(
            chunk_id=chunk.id, doc_id=chunk.doc_id, score=1.0, rerank_score=1.0,
            content=chunk.content, doc_title=title, parent_id=chunk.parent_id,
            page=(chunk.meta or {}).get("page"), metadata=chunk.meta or {},
        )
        for la, chunk, title in rows
    ]
    return out, law_name
