"""切分配置桥接（从全局 settings 读取，避免循环导入）。"""
from __future__ import annotations

from app.config import settings


def get_splitter_general_config() -> dict:
    g = settings.ingest.splitter.general
    return {
        "child_tokens": g.child_tokens,
        "parent_tokens": g.parent_tokens,
        "overlap_ratio": g.overlap_ratio,
        "table_context_window": g.table_context_window,
    }


def get_splitter_map() -> dict[str, str]:
    return settings.ingest.splitter.map


def get_default_splitter() -> str:
    return settings.ingest.splitter.default
