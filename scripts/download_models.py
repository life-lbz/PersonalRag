"""模型权重下载（ModelScope 国内加速，仅必需文件）。

运行: python scripts/download_models.py
"""
from __future__ import annotations

# allow_patterns 排除 onnx/colbert 示例图等非必需大文件
COMMON_PATTERNS = [
    "*.json", "*.md", "*.txt", "sentencepiece.bpe.model",
]
MODELS = [
    ("BAAI/bge-m3", "C:/Users/20832/.cache/models/bge-m3",
     COMMON_PATTERNS + ["pytorch_model.bin", "colbert_linear.pt", "sparse_linear.pt"]),
    ("BAAI/bge-reranker-base", "C:/Users/20832/.cache/models/bge-reranker-base",
     COMMON_PATTERNS + ["pytorch_model.bin"]),
]


def main() -> None:
    from modelscope import snapshot_download

    for model_id, local_dir, patterns in MODELS:
        print(f"下载 {model_id} -> {local_dir}", flush=True)
        snapshot_download(model_id, local_dir=local_dir, allow_patterns=patterns)
        print(f"{model_id} 完成", flush=True)
    print("全部模型下载完成")


if __name__ == "__main__":
    main()
