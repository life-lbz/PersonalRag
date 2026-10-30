"""块级增强：auto_question（P0 核心项）——LLM 为每块生成 1-3 个"该块能回答的问题"。

问题随块入库建向量，检索时与正文双路召回后融合（架构文档 §2.3）。
走 Celery 闲时队列（low_priority）。
"""
from __future__ import annotations

import asyncio
import logging

from app.clients.model_services import llm_json
from app.config import settings

logger = logging.getLogger(__name__)

_PROMPT = (
    "你是检索索引构建助手。阅读下面的文本块，生成 {n} 个该块能直接回答的问题。\n"
    "要求：问题必须能独立理解（不出现'该块''上述'等指代）；覆盖块中不同知识点；每句一个。\n"
    "仅输出 JSON：{{\"questions\": [\"问题1\", \"问题2\"]}}\n\n文本块：\n{content}"
)


async def generate_questions(content: str) -> list[str]:
    n = settings.ingest.enhance.auto_question.questions_per_chunk
    try:
        result = await llm_json([{"role": "user", "content": _PROMPT.format(n=n, content=content[:2000])}])
        qs = [str(q).strip() for q in result.get("questions", []) if str(q).strip()]
        return qs[:n]
    except Exception as e:
        logger.warning("问题生成失败(跳过): %s", e)
        return []


async def generate_questions_batch(contents: list[str], concurrency: int = 4) -> list[list[str]]:
    """并发生成（M1）：信号量限制在途请求数，避免逐块串行带来的线性耗时。"""
    if not contents:
        return []
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(content: str) -> list[str]:
        async with sem:
            return await generate_questions(content)

    return list(await asyncio.gather(*(_one(c) for c in contents)))


def generate_questions_batch_sync(contents: list[str], concurrency: int = 4) -> list[list[str]]:
    """Celery 线程池内调用：单事件循环内并发跑完全部块。"""
    if not contents:
        return []
    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(generate_questions_batch(contents, concurrency))
        finally:
            loop.close()
    except Exception as e:  # 线程内无事件循环冲突时兜底
        logger.warning("问题批量生成同步执行异常: %s", e)
        return [[] for _ in contents]
