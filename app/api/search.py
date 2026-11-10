"""纯检索（调试/评估）与反馈 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.models.entities import QueryLog

router = APIRouter(prefix="/api/v1", tags=["search"])


class SearchRequest(BaseModel):
    kb_id: str
    query: str
    top_k: int | None = None


@router.post("/search")
async def search(body: SearchRequest, session: AsyncSession = Depends(get_async_session)):
    from app.retrieval.retriever import hybrid_search

    chunks = await hybrid_search(body.query, [body.kb_id], top_k=body.top_k)
    return [{
        "chunk_id": c.chunk_id, "doc_id": c.doc_id, "doc_title": c.doc_title,
        "score": round(c.score, 4), "cosine": round(c.cosine, 4),
        "rerank_score": round(c.rerank_score, 4) if c.rerank_score is not None else None,
        "page": c.page, "content": c.content[:500],
    } for c in chunks]


class FeedbackRequest(BaseModel):
    log_id: str
    feedback: int  # 1 | -1


@router.post("/feedback")
async def feedback(body: FeedbackRequest, session: AsyncSession = Depends(get_async_session)):
    """同一 log_id 重复提交以最后一次为准。"""
    log = await session.get(QueryLog, body.log_id)
    if log is None:
        return {"status": "not_found"}
    log.feedback = body.feedback
    await session.commit()
    return {"status": "ok"}
