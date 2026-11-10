"""生成器：prompt 模板 + 引用映射 + 反思重试。

引用策略（v2）：
- LLM 正常回答，**不在正文里插 [n]**；引用溯源统一在答案结尾由前端展示
- citations 直接取自 used_chunks（assemble 阶段就知道喂了哪些块），
  不再靠正则从 LLM 输出里抠 [n]（LLM 常漏标/错标/乱标）
"""
from __future__ import annotations

import logging

from app.clients.model_services import llm_chat_stream
from app.config import settings

from .retriever import ScoredChunk

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = (
    "你是严谨的企业知识助手。仅依据下面的参考资料回答用户问题。\n"
    "要求：\n"
    "1. 只使用参考资料中的信息，不得编造；资料不足以回答时，直接说明'根据现有知识库内容无法回答该问题'。\n"
    "2. 回答保持简洁、结构清晰，可使用短列表。\n"
    "3. 【禁止】在正文里加 [n]、(n) 之类的引用编号，正常写答案即可，引用来源会在答案结尾统一列出。\n\n"
    "参考资料：\n{context}\n\n"
    "{history}用户问题：{query}\n\n回答："
)

# 直答通道：无检索上下文
PROMPT_DIRECT = (
    "你是乐于助人的企业知识助手。当前问题无需知识库资料，请直接、简洁地回答。\n\n"
    "{history}用户问题：{query}\n\n回答："
)


def build_messages(context: str, query: str, history: str = "") -> list[dict]:
    if context and context.strip():
        user = PROMPT_TEMPLATE.format(context=context, query=query, history=history)
    else:
        user = PROMPT_DIRECT.format(query=query, history=history)
    return [{"role": "user", "content": user}]


def extract_citations(answer: str, used: list[ScoredChunk]) -> list[dict]:
    """引用映射：直接用 used_chunks（assemble 阶段就确定喂了哪些块），
    并按 (doc_id, page) 去重——同文档同页只留第一条，n 重新编号。

    不依赖答案里的 [n]——LLM 常漏标/错标/乱标，而且 prompt 已经要求不要内联引用。
    返回的 citations 给前端在答案结尾统一展示，干净不重复。
    """
    seen: set[tuple[str, int | None]] = set()
    deduped: list[ScoredChunk] = []
    for c in used:
        key = (c.doc_id or c.doc_title or "", c.page)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)

    return [
        {
            "n": i + 1,
            "chunk_id": c.chunk_id,
            "doc_id": c.doc_id,
            "doc_title": c.doc_title,
            "page": c.page,
            "rerank_score": c.rerank_score,
            # 摘要片段：前端引用卡片展示，避免再发一次请求取原文
            "snippet": (c.content or "")[:140].replace("\n", " ").strip(),
        }
        for i, c in enumerate(deduped)
    ]


def quality_ok(answer: str, used: list[ScoredChunk]) -> bool:
    """反思判据：有块 + 有实质内容（不只是拒答语）。"""
    if not used or not answer.strip():
        return False
    refuse_phrases = ("根据现有知识库内容无法回答", "无法回答", "不清楚")
    return not any(p in answer for p in refuse_phrases)


async def generate_stream(context: str, query: str, history: str = ""):
    """流式生成，返回 async iterator of delta text。"""
    messages = build_messages(context, query, history)
    async for delta in llm_chat_stream(messages):
        yield delta
