# Embedding Server

该目录提供独立的 OpenAI-Compatible Embedding 服务，供公共数据 Agent 平台通过 HTTP 调用。

服务端只负责：

```text
文本批次 -> Qwen3-Embedding-4B 推理 -> last-token pooling -> MRL 1024 维 -> 归一化向量
```

文档解析、切块、版本管理、重试和 pgvector 写入仍由主系统负责。

本地测试：

```powershell
cd services/embedding_server
uv sync --dev
uv run pytest
uvx ruff check .
```

服务运行环境需要预装：

```text
Python 3.10+
aiohttp
torch
transformers
```

启动：

```bash
set -a
source /path/to/embedding-server.env
set +a
python -m embedding_server
```

生产部署时建议使用独立的低权限服务账号、环境变量文件和进程管理器，并限制服务监听地址与调用来源。
