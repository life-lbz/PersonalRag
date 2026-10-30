"""serve_embedding.py —— BGE-M3，同时输出稠密+稀疏向量（CPU, 方案E）。

启动: python model_services/serve_embedding.py   (:8001)
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import app._platform_fix  # noqa: E402  Windows 下短路 WMI 平台查询, 避免首次加载模型时卡死

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

_DEFAULT_MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "bge-m3"
MODEL_DIR = os.environ.get("BGE_M3_DIR", str(_DEFAULT_MODEL_DIR))
USE_FP16 = os.environ.get("BGE_USE_FP16", "0") == "1"  # 本机显存留给LLM, 默认CPU fp32
PORT = int(os.environ.get("EMBED_PORT", "8001"))

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """启动即加载模型：health 就绪即代表模型可用，避免首个业务请求冷加载超时。"""
    get_model()
    yield


app = FastAPI(title="bge-m3 embedding service", lifespan=_lifespan)
_model = None


def get_model():
    global _model
    if _model is None:
        from FlagEmbedding import BGEM3FlagModel

        _model = BGEM3FlagModel(MODEL_DIR, use_fp16=USE_FP16)
    return _model


class EmbedReq(BaseModel):
    texts: list[str]
    max_length: int = 8192
    batch_size: int = 8   # CPU 模式 batch 降为 8, 防内存峰值过高


@app.post("/v1/embeddings")
def embed(req: EmbedReq):
    model = get_model()
    out = model.encode(req.texts, return_dense=True, return_sparse=True,
                       max_length=req.max_length, batch_size=req.batch_size)
    return {"dense": out["dense_vecs"].tolist(),
            "sparse": [{str(k): float(v) for k, v in lw.items()} for lw in out["lexical_weights"]]}


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
