# 模型文件说明

本目录存放 PersonalRag 运行所需的本地模型权重。**模型文件不随仓库分发**（总计约 4.6GB，超出 GitHub 单文件 100MB 限制，且 LFS 免费额度不足），二次开发时请按本文档自行下载。

## 一、模型清单

| 模型 | 用途 | 大小 | 来源 |
|---|---|---|---|
| BAAI/bge-m3 | 文本向量化（稠密 + 稀疏向量） | ~2.3GB | ModelScope / HuggingFace |
| BAAI/bge-reranker-base | 检索结果重排（交叉编码器） | ~1.1GB | ModelScope / HuggingFace |
| qwen2.5:3b-instruct-q4_K_M | LLM 生成（Ollama 托管） | ~2GB | Ollama 模型库 |

## 二、一键下载（推荐）

项目内置下载脚本，使用 ModelScope 国内镜像加速，只下载必需文件（排除 onnx、示例图等冗余）：

```bash
pip install modelscope
python scripts/download_models.py
```

下载完成后目录结构：

```
models/
├── bge-m3/
│   ├── pytorch_model.bin        # 主权重
│   ├── colbert_linear.pt        # ColBERT 稀疏向量头
│   ├── sparse_linear.pt         # 稀疏向量头
│   ├── config.json / tokenizer.json / ...
└── bge-reranker-base/
    ├── pytorch_model.bin
    ├── config.json / tokenizer.json / ...
```

## 三、手动下载

如果脚本不可用，可手动下载后放入对应目录：

- bge-m3：
  - ModelScope：https://modelscope.cn/models/BAAI/bge-m3
  - HuggingFace：https://huggingface.co/BAAI/bge-m3
- bge-reranker-base：
  - ModelScope：https://modelscope.cn/models/BAAI/bge-reranker-base
  - HuggingFace：https://huggingface.co/BAAI/bge-reranker-base

必需文件见 `scripts/download_models.py` 中的 `allow_patterns` 清单。

## 四、自定义模型路径（可选）

默认从项目根 `models/` 目录加载。如需放在其他位置，用环境变量覆盖：

```powershell
# Windows PowerShell
$env:BGE_M3_DIR = "D:\your\path\bge-m3"
$env:BGE_RERANKER_DIR = "D:\your\path\bge-reranker-base"
```

对应代码位置：
- `model_services/serve_embedding.py` → 读取 `BGE_M3_DIR`
- `model_services/serve_rerank.py` → 读取 `BGE_RERANKER_DIR`

## 五、LLM 模型

LLM 不在本目录，由推理引擎托管，两种方式任选：

### 方式 A：Ollama（本机默认）

```bash
ollama pull qwen2.5:3b-instruct-q4_K_M
```

对应 `config.yaml`：

```yaml
models:
  llm:
    base_url: http://localhost:11434/v1
    model: qwen2.5:3b-instruct-q4_K_M
```

### 方式 B：vLLM（GPU 服务器 / AutoDL 推荐）

```bash
pip install vllm
vllm serve Qwen/Qwen2.5-3B-Instruct --port 8000 --dtype half --max-model-len 8192
```

对应 `config.yaml`（注意模型名不同）：

```yaml
models:
  llm:
    base_url: http://<服务器地址>:8000/v1
    model: Qwen/Qwen2.5-3B-Instruct
```

vLLM 首次启动会自动从 HuggingFace 下载模型（约 6GB）；国内服务器可设置 `HF_ENDPOINT=https://hf-mirror.com` 走镜像。

显存 < 16GB 时改用 AWQ 量化版：`--quantization awq --model Qwen/Qwen2.5-3B-Instruct-AWQ`。

## 六、验证

模型就位后，启动服务并检查健康端点（服务启动即预热加载模型，`/health` 返回 ok 即模型可用）：

```bash
curl http://localhost:8001/health   # embedding
curl http://localhost:8002/health   # rerank
curl http://localhost:11434/v1/models  # LLM (Ollama)
```

## 七、配置对应关系

`config.yaml` 中的模型配置与本目录的对应关系：

```yaml
models:
  embedding:
    base_url: http://localhost:8001   # ← serve_embedding.py 加载 models/bge-m3
    model: bge-m3
  rerank:
    base_url: http://localhost:8002   # ← serve_rerank.py 加载 models/bge-reranker-base
    model: bge-reranker-base
  llm:
    base_url: http://localhost:11434/v1  # ← Ollama / vLLM
    model: qwen2.5:3b-instruct-q4_K_M
```
