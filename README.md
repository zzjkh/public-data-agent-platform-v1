# 公共数据 Agent 平台 V1

面向政务政策与开放数据分析场景的可追踪 AI Agent 平台。系统同时处理非结构化政策文档和结构化统计数据，支持政策问答、数据问答、混合问答、引用溯源、SQL 安全控制、执行 Trace 与离线评测。

本仓库是 V1 的开源代码快照，不包含项目开发日志、个人环境配置或采集的原始政务资料。运行前请自行准备具备合法使用权限的数据。

## 核心能力

- HTML、文本 PDF 与扫描 PDF 的解析、OCR、元素抽取和版本管理。
- 基于 pgvector、关键词和全文检索的 Policy Hybrid RAG。
- 面向数据集、字段、指标和 SQL 示例的 Semantic Metadata RAG。
- 通过只读 reporting 视图、SQL AST Guard 和独立只读连接实现受控 Text-to-SQL。
- 支持 POLICY_QA、DATA_QA、HYBRID_QA 三类问答链路。
- 记录路由、检索、SQL、模型调用和图表生成等 Trace span。
- 提供文件、文档、数据集、指标、任务、Trace 和评测管理页面。
- 提供可独立部署的 OpenAI-Compatible Embedding Server。

## 系统结构

```text
React + Ant Design
        |
FastAPI API / JWT / RBAC
        |
QA Orchestrator
  |-- Policy Hybrid RAG
  |-- Semantic Metadata RAG
  |-- Guarded Text-to-SQL
  |-- Trace / Eval
        |
PostgreSQL + pgvector + reporting views
```

```text
backend/                  FastAPI 后端、迁移与测试
frontend/                 React 管理与问答界面
infra/                    PostgreSQL + pgvector 开发环境
services/embedding_server 独立 Embedding 服务
```

## 技术栈

- Python 3.12+、FastAPI、SQLAlchemy 2、Alembic、Pydantic
- PostgreSQL 16、pgvector、sqlglot
- DeepSeek JSON Output、自托管 Qwen3-Embedding-4B
- React、TypeScript、Vite、Ant Design、ECharts
- pytest、Vitest、Ruff、GitHub Actions

V1 使用项目内的显式 `QAOrchestrator` 编排问答链路，没有依赖 LangChain 或 LangGraph。V2 将在保留现有业务模块的基础上引入 LangGraph 状态图。

## 快速启动

1. 启动 PostgreSQL：

```powershell
docker compose -f infra/docker-compose.yml up -d
```

2. 配置环境：

```powershell
Copy-Item .env.example .env
```

填写 `DEEPSEEK_API_KEY`、`JWT_SECRET_KEY`，并按部署方式配置 Embedding 服务。

3. 初始化并启动后端：

```powershell
cd backend
uv sync --dev
uv run alembic upgrade head
uv run python -m app.scripts.seed_users
uv run uvicorn app.main:app --reload
```

4. 启动前端：

```powershell
cd frontend
npm install
npm run dev
```

系统不附带业务数据。请登录后通过文件、数据集和指标导入接口写入你有权使用的资料，再运行解析、切块和 Embedding 任务。

## 安全边界

- LLM 只能生成结构化输出，所有响应经过 Pydantic 校验。
- Text-to-SQL 只能访问白名单中的 `reporting` 只读视图。
- SQL 经过 sqlglot AST 校验、函数白名单、行数限制和超时控制。
- 数据库执行使用独立只读账号和固定 `search_path`。
- 问答入口包含问题安全检查，执行过程写入 Trace。
- `.env`、上传文件、模型权重、缓存和运行日志不会进入 Git。

这些措施不能替代真实部署中的数据分级、权限治理、网络隔离和安全审计。

## 验证

```powershell
cd backend
uv run pytest
uvx ruff check .

cd ../frontend
npm test -- --run
npm run build

cd ../services/embedding_server
uv run pytest
uvx ruff check .
```

## 数据与许可

仓库不分发政策文件、统计年鉴、开放数据网页快照或其他采集资料。使用者应从合法来源自行获取数据，并遵守来源网站、数据许可和适用法律。

代码采用 [MIT License](LICENSE)。
