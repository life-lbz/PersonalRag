"""LangGraph 在线检索状态机（§3.2.1）：编排"路由→检索→组装"段。

生成段由 API 层流式执行（SSE 增量直通前端）；本图负责：
query → router → direct(标记) / rule(精确命中) / hybrid / planner(multi_hop)
反思：检索为空 → 改写重试 ≤ max_retry → 仍失败 REFUSE。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from app.config import settings

logger = logging.getLogger(__name__)

# 请求 mode 值域 → 内部 route 值域（router.classify 输出 direct_answer/rule_search/hybrid_search/multi_hop）
_MODE2ROUTE = {
    "direct": "direct_answer",
    "rule": "rule_search",
    "hybrid": "hybrid_search",
    "multi_hop": "multi_hop",
}


@dataclass
class ChatState:
    query: str
    kb_id: str
    session_id: str | None = None
    mode: str = "auto"                     # auto|direct|rule|hybrid|multi_hop
    route: str = ""
    confidence: float = 0.0
    used_chunks: list = field(default_factory=list)
    context: str = ""
    sub_queries: list[str] = field(default_factory=list)
    retry_count: int = 0
    error_code: str | None = None          # RETRIEVAL_EMPTY / REFUSE
    latency_ms: int = 0


def build_graph():
    from langgraph.graph import END, StateGraph

    from app.retrieval import planner, router, rule_search
    from app.retrieval.assemble import assemble_context
    from app.retrieval.retriever import hybrid_search

    g = StateGraph(dict)

    async def node_router(state: dict) -> dict:
        s: ChatState = state["s"]
        if s.mode != "auto":
            s.route, s.confidence = _MODE2ROUTE.get(s.mode, "hybrid_search"), 1.0
        else:
            s.route, s.confidence = await router.classify(s.query)
        return {"s": s}

    async def node_rule(state: dict) -> dict:
        s: ChatState = state["s"]
        hits, _law = await rule_search.rule_lookup(s.query, s.kb_id)
        if hits:
            s.used_chunks = hits
            s.context, s.used_chunks = assemble_context(hits, s.query)
        else:
            s.route = "hybrid_search"  # 未命中降级（§5.2 ②）
        return {"s": s}

    async def node_hybrid(state: dict) -> dict:
        s: ChatState = state["s"]
        t0 = time.time()
        chunks = await hybrid_search(s.query, s.kb_id)
        s.used_chunks = chunks
        if chunks:
            s.context, s.used_chunks = assemble_context(chunks, s.query)
        logger.info("hybrid %dms, 命中 %d 块", int((time.time() - t0) * 1000), len(chunks))
        return {"s": s}

    async def node_planner(state: dict) -> dict:
        s: ChatState = state["s"]
        chunks, sub_queries = await planner.plan_and_search(s.query, s.kb_id)
        s.sub_queries = sub_queries
        s.used_chunks = chunks
        if chunks:
            s.context, s.used_chunks = assemble_context(chunks, s.query)
        return {"s": s}

    async def node_retry_or_refuse(state: dict) -> dict:
        s: ChatState = state["s"]
        if s.retry_count < settings.router.max_retry:
            from app.clients.model_services import llm_json

            s.retry_count += 1
            rewrite = await llm_json([{
                "role": "user",
                "content": f"原查询检索无结果。改写为更适合语义检索的查询（同义扩展、去口语化）。\n"
                           f'仅输出 JSON：{{"rewritten": "..."}}\n原查询：{s.query}',
            }])
            if rewrite.get("rewritten"):
                s.query = str(rewrite["rewritten"])
            s.route = "hybrid_search"
            return {"s": s}
        s.error_code = "REFUSE"
        return {"s": s}

    def route_after_router(state: dict) -> str:
        s: ChatState = state["s"]
        return {
            "direct_answer": "direct_done",
            "rule_search": "rule",
            "hybrid_search": "hybrid",
            "multi_hop": "planner",
        }.get(s.route, "hybrid")

    def after_retrieve(state: dict) -> str:
        s: ChatState = state["s"]
        return "END_OK" if s.used_chunks else "retry"

    def after_retry(state: dict) -> str:
        s: ChatState = state["s"]
        return "END_OK" if s.error_code else "hybrid"

    g.add_node("router", node_router)
    g.add_node("direct_done", lambda state: {"s": state["s"]})
    g.add_node("rule", node_rule)
    g.add_node("hybrid", node_hybrid)
    g.add_node("planner", node_planner)
    g.add_node("retry_or_refuse", node_retry_or_refuse)

    g.set_entry_point("router")
    g.add_conditional_edges("router", route_after_router,
                            {"direct_done": END, "rule": "rule", "hybrid": "hybrid", "planner": "planner"})
    g.add_edge("rule", "assemble_or_retry")
    g.add_edge("hybrid", "assemble_or_retry")
    g.add_edge("planner", "assemble_or_retry")
    g.add_node("assemble_or_retry", lambda state: {"s": state["s"]})
    g.add_conditional_edges("assemble_or_retry", after_retrieve, {"END_OK": END, "retry": "retry_or_refuse"})
    g.add_conditional_edges("retry_or_refuse", after_retry, {"END_OK": END, "hybrid": "hybrid"})
    return g.compile()


_compiled = None


async def run_retrieval(query: str, kb_id: str, session_id: str | None,
                        mode: str = "auto") -> ChatState:
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    state = ChatState(query=query, kb_id=kb_id, session_id=session_id, mode=mode)
    t0 = time.time()
    result = await _compiled.ainvoke({"s": state})
    s: ChatState = result["s"]
    s.latency_ms = int((time.time() - t0) * 1000)
    return s
