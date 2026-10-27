"""检索问答 API（SSE 流式，§6 接口契约）：

SSE 事件：
  {"delta": "..."}                                    增量文本
  {"citations": [{n, chunk_id, doc_title, page}]}      引用
  {"route": "...", "latency_ms": N, "done": true}      结束
  {"error": {code, message}, "done": true}             异常终止
"""
from __future__ import annotations

import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_async_session
from app.models.entities import QueryLog
from app.retrieval.generator import generate_stream
from app.retrieval.workflow import run_retrieval

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatRequest(BaseModel):
    kb_id: str
    query: str
    session_id: str | None = None
    mode: str = "auto"  # auto|direct|rule|hybrid|multi_hop


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat/completions")
async def chat_completions(body: ChatRequest, session: AsyncSession = Depends(get_async_session)):
    from app.models.entities import KnowledgeBase
    from app.config import settings

    # C5: KB 存在性校验（快速失败，不入流）
    if not body.kb_id:
        raise HTTPException(400, "缺少 kb_id")
    if body.query and len(body.query.strip()) > 2000:
        raise HTTPException(400, "query 过长（上限 2000 字）")
    if body.mode not in ("auto", "direct", "rule", "hybrid", "multi_hop"):
        raise HTTPException(400, f"无效 mode: {body.mode}")
    if await session.get(KnowledgeBase, body.kb_id) is None:
        raise HTTPException(404, "知识库不存在或已删除")

    session_id = body.session_id or str(uuid.uuid4())
    log_id = str(uuid.uuid4())

    async def event_stream():
        t0 = time.time()
        answer_parts: list[str] = []
        try:
            state = await run_retrieval(body.query, body.kb_id, session_id, body.mode)
            yield _sse({"route": state.route, "session_id": session_id, "log_id": log_id})

            if state.error_code == "REFUSE":
                yield _sse({"delta": "根据现有知识库内容无法回答该问题。"})
                yield _sse({"error": {"code": "REFUSE", "message": "反思重试超限, 已拒答"}, "done": True})
                await _save_log(log_id, session_id, body, state, "（拒答）", session)
                return

            if state.route == "direct_answer":
                # 直答：无检索上下文
                async for delta in generate_stream("", body.query):
                    answer_parts.append(delta)
                    yield _sse({"delta": delta})
            else:
                if not state.used_chunks:
                    yield _sse({"delta": "知识库中暂未检索到相关内容。"})
                    yield _sse({"error": {"code": "RETRIEVAL_EMPTY", "message": "检索为空"}, "done": True})
                    await _save_log(log_id, session_id, body, state, "", session)
                    return
                if state.route == "rule_search":
                    # 规则通道精确命中：直出条文原文（§5.2 ②），不经 LLM 改写
                    for i, c in enumerate(state.used_chunks, 1):
                        loc = f"（来源: {c.doc_title}{' 第' + str(c.page) + '页' if c.page else ''}）"
                        piece = f"[{i}] {c.content}\n{loc}\n\n"
                        answer_parts.append(piece)
                        yield _sse({"delta": piece})
                else:
                    async for delta in generate_stream(state.context, body.query):
                        answer_parts.append(delta)
                        yield _sse({"delta": delta})

            answer = "".join(answer_parts)
            from app.retrieval.generator import extract_citations

            # H1: rule_search 通道下 answer 是条文原文而非 LLM 输出，跳过 citation 正则提取
            if state.route == "rule_search":
                citations = [{"n": i + 1, "chunk_id": c.chunk_id, "doc_title": c.doc_title}
                             for i, c in enumerate(state.used_chunks)]
            else:
                citations = extract_citations(answer, state.used_chunks)
            yield _sse({"citations": citations})
            yield _sse({"route": state.route, "latency_ms": int((time.time() - t0) * 1000), "done": True})
            await _save_log(log_id, session_id, body, state, answer, session, citations)
        except Exception as e:
            logger.exception("chat 异常")
            # C4: 生产环境不暴露堆栈给前端，只给通用错误
            if settings.debug:
                msg = str(e)[:500]
            else:
                msg = "服务器内部错误, 请稍后重试"
            yield _sse({"error": {"code": "INTERNAL", "message": msg}, "done": True})

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _save_log(log_id, session_id, body: ChatRequest, state, answer: str,
                    session: AsyncSession, citations: list | None = None):
    if not settings.logging.query_log_enabled:
        return
    try:
        session.add(QueryLog(
            id=log_id,
            session_id=session_id,
            query=body.query,
            route=state.route,
            plan={"sub_queries": state.sub_queries, "retry_count": state.retry_count},
            retrieved_ids=[c.chunk_id for c in state.used_chunks],
            rerank_scores=[c.rerank_score for c in state.used_chunks if c.rerank_score is not None],
            answer=answer,
            latency_ms=state.latency_ms,
        ))
        await session.commit()
    except Exception:
        logger.exception("query_log 落库失败")
