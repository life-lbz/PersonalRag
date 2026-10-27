"""创建 Milvus Collection（kb_chunks，字段见方案设计文档 §4.2）。

运行: python scripts/init_milvus.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.clients.milvus_client import create_text_collection, collection_stats  # noqa: E402
from app.config import settings  # noqa: E402


def main() -> None:
    create_text_collection(dim=settings.models.embedding.dim)
    print(f"collection {settings.milvus.text_collection} 就绪")
    try:
        print("stats:", collection_stats())
    except Exception as e:
        print("stats 暂不可用(空集合):", e)


if __name__ == "__main__":
    main()
