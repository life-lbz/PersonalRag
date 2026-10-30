"""法规条文精确查询 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.models.entities import Chunk, Document, LawArticle

router = APIRouter(prefix="/api/v1/laws", tags=["laws"])


@router.get("/{law_name}/articles/{article_no}")
async def get_article(law_name: str, article_no: str, session: AsyncSession = Depends(get_async_session)):
    """法规条文精确查询：/api/v1/laws/{name}/articles/第X条 或 第X（自动补"第..条"）。"""
    if not article_no.startswith("第"):
        article_no = f"第{article_no}条"
    rows = (await session.execute(
        select(LawArticle, Chunk)
        .join(Document, Document.id == LawArticle.doc_id)
        .join(Chunk, (Chunk.doc_id == LawArticle.doc_id)
              & (Chunk.meta["article_no"].astext == LawArticle.article_no))
        .where(
            LawArticle.law_name == law_name,
            LawArticle.article_no == article_no,
            # 只返回当前生效版本，历史版本法条不参与精确查询
            LawArticle.version == cast(Document.current_version, String),
        )
        .limit(5)
    )).all()
    if not rows:
        raise HTTPException(404, f"未找到 {law_name} {article_no}")
    return [{
        "law_name": la.law_name, "article_no": la.article_no,
        "status": la.status, "effective_date": str(la.effective_date) if la.effective_date else None,
        "content": chunk.content, "chunk_id": chunk.id,
    } for la, chunk in rows]
