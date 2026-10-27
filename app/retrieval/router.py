"""四通道路由：直答/规则检索/模型检索(混合)/多跳。路由依据=通道自然语言描述（注册制）。

依据《RAG系统方案设计文档.md》§3.2.1、《架构文档》§3.4。
"""
from __future__ import annotations

import logging

from app.clients.model_services import llm_json
from app.config import settings

logger = logging.getLogger(__name__)

# 通道描述注册制：新增通道只需注册描述
CHANNEL_DESCRIPTIONS: dict[str, str] = {
    "direct_answer": "闲聊、常识问答、创作、翻译、总结等无需知识库即可回答的请求",
    "rule_search": "要求精确查找某条具体条文/规则/条目的请求，通常出现'《XX》第X条''第X条规定'等格式化引用",
    "hybrid_search": "需要依据知识库内容回答的业务问题（默认通道，语义+关键词混合检索）",
    "multi_hop": "需要跨多篇文档/多个知识点串联推理的复杂问题，如'A和B的关系是什么''为什么A会导致B'",
}

_ROUTE_PROMPT = (
    "你是检索路由器。根据通道描述判断用户请求应走哪条通道。\n{channels}\n\n"
    "用户请求：{query}\n\n"
    '仅输出 JSON：{{"route": "direct_answer|rule_search|hybrid_search|multi_hop", "confidence": 0.0-1.0}}'
)


async def classify(query: str) -> tuple[str, float]:
    """LLM 分类。强制 mode（router.mode != auto）时直接返回。低置信降级 hybrid。"""
    r = settings.router
    if r.mode != "auto":
        return r.mode, 1.0
    channels = "\n".join(f"- {k}: {v}" for k, v in CHANNEL_DESCRIPTIONS.items())
    result = await llm_json([{"role": "user", "content": _ROUTE_PROMPT.format(channels=channels, query=query)}])
    route = result.get("route", "hybrid_search")
    confidence = float(result.get("confidence", 0.5))
    if route not in CHANNEL_DESCRIPTIONS or confidence < r.confidence_threshold:
        route = "hybrid_search"  # 置信度不足降级 hybrid, 保证兜底
    return route, confidence
