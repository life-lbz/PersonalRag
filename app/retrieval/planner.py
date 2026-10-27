"""多跳 Planner：拆解子问题（≤ planner_max_steps）→ 并行 hybrid → 汇总去重。"""
from __future__ import annotations

import asyncio
import logging

from app.clients.model_services import llm_json
from app.config import settings

from .retriever import ScoredChunk, hybrid_search

logger = logging.getLogger(__name__)

_PLAN_PROMPT = (
    "把下面的复杂问题拆解为不超过 {n} 个可以独立检索的子问题，按依赖顺序排列。\n"
    "注意：每个子问题必须自包含（补全主语和背景，如把'它的职责'改为'测试管理部门的职责'），"
    "否则单独检索会失义。\n"
    '仅输出 JSON：{{"sub_queries": ["子问题1", "子问题2"]}}\n\n问题：{query}'
)


async def plan_and_search(query: str, kb_id: str) -> tuple[list[ScoredChunk], list[str]]:
    n = settings.router.planner_max_steps
    result = await llm_json([{"role": "user", "content": _PLAN_PROMPT.format(n=n, query=query)}])
    sub_queries = [str(q).strip() for q in result.get("sub_queries", []) if str(q).strip()][:n]
    if not sub_queries:
        sub_queries = [query]

    tasks = [hybrid_search(sq, kb_id) for sq in sub_queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    seen: set[str] = set()
    merged: list[ScoredChunk] = []
    for r in results:
        if isinstance(r, Exception) or not r:
            continue
        for c in r:
            if c.chunk_id not in seen:
                seen.add(c.chunk_id)
                merged.append(c)
    merged.sort(key=lambda x: -(x.rerank_score or x.score))
    return merged, sub_queries
