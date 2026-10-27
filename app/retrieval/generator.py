"""生成器：prompt 模板（强制 [n] 引用）+ 引用映射 + 反思重试。"""
from __future__ import annotations

import logging
import re

from app.clients.model_services import llm_chat_stream
from app.config import settings

from .retriever import ScoredChunk

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = (
    "你是严谨的企业知识助手。仅依据下面的参考资料回答用户问题，答案中引用到的每条资料必须在句末标注编号，格式为 [n]。\n"
    "要求：\n"
    "1. 只使用参考资料中的信息，不得编造；资料不足以回答时，直接说明'根据现有知识库内容无法回答该问题'。\n"
    "2. 回答保持简洁、结构清晰，可使用短列表。\n"
    "3. 每个引用编号 [n] 对应参考资料中标注的来源序号。\n\n"
    "参考资料：\n{context}\n\n"
    "{history}用户问题：{query}\n\n回答："
)

# 直答通道：无检索上下文，禁止输出引用标注
PROMPT_DIRECT = (
    "你是乐于助人的企业知识助手。当前问题无需知识库资料，请直接、简洁地回答，"
    "不要输出 [n] 之类的引用标注。\n\n"
    "{history}用户问题：{query}\n\n回答："
)

_REF_RE = re.compile(r"\[(\d{1,2})\]")


def build_messages(context: str, query: str, history: str = "") -> list[dict]:
    if context and context.strip():
        user = PROMPT_TEMPLATE.format(context=context, query=query, history=history)
    else:
        user = PROMPT_DIRECT.format(query=query, history=history)
    return [{"role": "user", "content": user}]


def extract_citations(answer: str, used: list[ScoredChunk]) -> list[dict]:
    """引用映射：chunk_id → 文档定位（§5.2 ④）。"""
    nums = sorted({int(m) for m in _REF_RE.findall(answer)})
    out = []
    for n in nums:
        if 1 <= n <= len(used):
            c = used[n - 1]
            out.append({
                "n": n,
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                "doc_title": c.doc_title,
                "page": c.page,
                "rerank_score": c.rerank_score,
            })
    return out


def quality_ok(answer: str, used: list[ScoredChunk]) -> bool:
    """反思判据：有内容使用且答案带引用（rerank 分不达标/无引用视为低质）。"""
    if not used or not answer.strip():
        return False
    return bool(_REF_RE.search(answer))


async def generate_stream(context: str, query: str, history: str = ""):
    """流式生成，返回 async iterator of delta text。"""
    messages = build_messages(context, query, history)
    async for delta in llm_chat_stream(messages):
        yield delta
