"""四通道路由：直答/规则检索/模型检索(混合)/多跳。路由依据=通道自然语言描述（注册制）。

依据《RAG系统方案设计文档.md》§3.2.1、《架构文档》§3.4。

v2 路由策略（通用化，不局限于简历/特定知识库）：
  1. 明显闲聊（寒暄、过短）→ 直接 direct_answer，跳过 LLM
  2. LLM 正常分类四通道
  3. hard_fallback 只做"纠偏"——当 LLM 给出 direct_answer 时，检查是否包含事实性问句标记，
     如果有则降级为 hybrid（防止 LLM 小模型把事实问句误判为闲聊）
  4. 置信度不足 / 通道非法 → 兜底 hybrid_search
"""
from __future__ import annotations

import logging

from app.clients.model_services import llm_json
from app.config import settings

logger = logging.getLogger(__name__)

# 通道描述注册制：新增通道只需注册描述
# direct_answer 严格收窄到纯闲聊/纯创作/纯翻译，其他一律 hybrid_search
CHANNEL_DESCRIPTIONS: dict[str, str] = {
    "direct_answer": (
        "仅限纯闲聊（打招呼、情绪发泄）、纯创作（写首诗、写个故事、写封邮件）、"
        "纯翻译、纯总结（'帮我总结一下上面的对话'）。"
        "只要问题可能涉及知识库中的任何实体、事实、人物、公司、制度、项目、产品，"
        "一律走 hybrid_search，不得选 direct_answer。"
    ),
    "rule_search": "要求精确查找某条具体条文/规则/条目的请求，通常出现'《XX》第X条''第X条规定'等格式化引用",
    "hybrid_search": "需要依据知识库内容回答的业务问题（默认通道，语义+关键词混合检索）",
    "multi_hop": "需要跨多篇文档/多个知识点串联推理的复杂问题，如'A和B的关系是什么''为什么A会导致B'",
}

# 通用事实性问句标记词（不局限于任何特定领域）
_FACTUAL_MARKERS = ("谁", "什么", "哪里", "何时", "为什么", "怎么", "如何",
                    "有哪些", "哪些", "是不是", "有没有")

# 寒暄前缀（明显闲聊，直接 direct）
_GREETING_PREFIXES = ("你好", "您好", "hi", "hello", "在吗", "谢谢", "再见",
                      "拜拜", "ok", "好的", "嗯", "哈", "呵", "嘿")

_ROUTE_PROMPT = (
    "你是检索路由器。根据通道描述判断用户请求应走哪条通道。\n{channels}\n\n"
    "用户请求：{query}\n\n"
    "再次提醒：只要问题可能与知识库内容相关（人物、公司、项目、制度、产品、技术），"
    "必须选 hybrid_search；direct_answer 只限纯闲聊、纯创作、纯翻译。\n\n"
    '仅输出 JSON：{{"route": "direct_answer|rule_search|hybrid_search|multi_hop", "confidence": 0.0-1.0}}'
)


def _greeting_detect(query: str) -> bool:
    """判断是否是明显的寒暄/闲聊，这些直接走 direct_answer，不需要 LLM。"""
    q = query.strip()
    if not q or len(q) < 2:
        return True
    low = q.lower()
    if low.startswith(_GREETING_PREFIXES):
        return True
    # 单字/双字的短问候
    if len(q) <= 4 and not any(m in q for m in _FACTUAL_MARKERS) and "？" not in q and "?" not in q:
        return True
    return False


def _is_factual_question(query: str) -> bool:
    """判断是否是事实性问句（应走知识库检索，而不是 direct_answer）。

    通用策略：检查是否包含疑问代词或问号结尾（排除寒暄前缀）。
    """
    q = query.strip()
    if not q:
        return False
    if _greeting_detect(q):
        return False
    # 包含通用疑问代词 → 事实性
    if any(m in q for m in _FACTUAL_MARKERS):
        return True
    # 问号结尾（排除寒暄）→ 可能是事实性
    if ("？" in q or "?" in q) and not q.lower().startswith(_GREETING_PREFIXES):
        return True
    return False


async def classify(query: str) -> tuple[str, float]:
    """LLM 分类 + 纠偏。强制 mode 时直接返回。"""
    r = settings.router
    if r.mode != "auto":
        return r.mode, 1.0

    # 快速通道：明显闲聊 → 跳过 LLM，直接 direct_answer
    if _greeting_detect(query):
        logger.info("[router] greeting_detect → direct_answer query=%s", query[:30])
        return "direct_answer", 0.95

    # LLM 正常四通道分类
    channels = "\n".join(f"- {k}: {v}" for k, v in CHANNEL_DESCRIPTIONS.items())
    try:
        result = await llm_json([{"role": "user", "content": _ROUTE_PROMPT.format(channels=channels, query=query)}])
        route = result.get("route", "hybrid_search")
        confidence = float(result.get("confidence", 0.5))
    except Exception:
        logger.warning("[router] LLM 分类异常，兜底 hybrid")
        route = "hybrid_search"
        confidence = 0.5

    # ===== hard_fallback 纠偏区 =====
    # 核心原则：只要有任何理由怀疑 LLM 误判了 direct_answer，就降级到 hybrid_search
    if route == "direct_answer":
        downgrade = False
        if confidence < 0.9:
            # 低置信度 → 降级
            logger.info("[router] downgrade direct→hybrid (conf=%.2f < 0.9)", confidence)
            downgrade = True
        elif _is_factual_question(query):
            # LLM 说 direct_answer，但查询里有事实性问句标记 → LLM 可能漏看了，降级
            logger.info("[router] downgrade direct→hybrid (factual markers detected) query=%s", query[:30])
            downgrade = True
        if downgrade:
            route = "hybrid_search"
            confidence = max(confidence, 0.8)  # 提升置信度，避免后续被再降级

    # 置信度/通道合法性兜底
    if route not in CHANNEL_DESCRIPTIONS or confidence < r.confidence_threshold:
        logger.info("[router] fallback→hybrid (route=%s conf=%.2f)", route, confidence)
        route = "hybrid_search"

    logger.info("[router] query=%s → %s (conf=%.2f)", query[:30], route, confidence)
    return route, confidence
