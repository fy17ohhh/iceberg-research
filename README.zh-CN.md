# Iceberg Research

> 穿透水面，深入研究。

[English](README.md) | [简体中文](README.zh-CN.md)

![home_page](assets/home_page_zh.png)

Iceberg Research 是一个多智能体深度研究项目，能够将模糊的问题转化为有据可查、带引用的研究报告。它会澄清研究需求、规划调查步骤、搜索网页与论文、检查证据质量，并综合生成带有来源追溯能力的 Markdown 报告。核心设计遵循一套“水下研究工作流”：最终报告浮于水面，而规划、检索、证据验证与综合推理发生在水下。

## 🤖 智能体工作流

```text
Navigator   # 确定研究方向
  ↓
Diver       # 在网页、论文、记忆和 RAG 中下潜检索
  ↓
Sonar       # 验证证据，发现缺口与冗余
  ↓
Synthesizer # 撰写基于证据的最终报告
```

## 📌 主要技术栈

- FastAPI · SSE · MCP · 多智能体编排
- RAG · BM25 + 向量检索 + Reciprocal Rank Fusion (RRF) ranking · Qdrant
- 多轮搜索 · 网页抓取 · arXiv 检索 · 证据审查 · 引用溯源
- Next.js · React · TypeScript · Tailwind CSS · Docker · uv

## ⭐ 功能特性

- 在执行前通过澄清步骤对齐研究需求的多智能体研究闭环，将问题拆分为子问题，并依据 Agent反馈迭代重规划
- Brave 与 Tavily 双搜索源及回退策略；通过 arXiv、论文检索工具和 MCP 集成发现学术资料
- 可导入 PDF、Markdown、文本和已保存研究报告的本地文档库；基于已导入文档和缓存搜索的本地 RAG 知识检索
- 面向用户偏好和研究事实的长期记忆管理
- 独立审查阶段（Sonar）用于检查证据质量、缺失维度和内容冗余；Synthesizer 负责引用规范化、来源清理与最终 Markdown 报告生成
- FastAPI 后端通过 SSE 向前端流式推送研究进度；Next.js 前端，提供研究流程、报告渲染、记忆和文档库体验
- 通过 OpenAI 兼容客户端和模型前缀自动识别，灵活支持多种模型提供商

## 🚀 快速开始

Iceberg Research 对外只提供一个启动命令。启动器会管理 uv 环境、前端依赖、可选 MCP 检查、服务健康检查和进程清理。

```bash
git clone https://github.com/fy17ohhh/iceberg-research.git
cd iceberg-research
cp .env.example .env
# 在 .env 中填写你的 API Key

chmod +x ./setup.sh
./setup.sh
```

启动器随后会询问要启动的界面：

- **Web command deck [1]（默认）** — 启动后端及浏览器界面，访问 http://localhost:3000
- **Terminal search [2]** — 启动后端及当前终端中的交互式研究控制台
- 停止所有服务：按 `Ctrl+C`

也可以跳过模式选择，直接使用 `./setup.sh web` 或 `./setup.sh terminal`。

终端默认使用英文；可切换为中文：

```bash
ICEBERG_LANGUAGE=zh-CN ./setup.sh terminal
# 或者在后端已启动时：
uv run iceberg-terminal --lang zh-CN
```

## 📄 CLI 用法

### 运行研究问题

```bash
uv run iceberg-research "What are the trade-offs between RAG and agentic search for enterprise knowledge work?"
```

可选参数：

```bash
uv run iceberg-research "..." --model deepseek-v3 --max-rounds 3 --max-steps 4 --timeout 180
```

添加本地 PDF 或 arXiv 论文：

```bash
uv run iceberg-library add 2401.12345 --title "My Paper"
uv run iceberg-library add ./data/originals/my_paper.pdf
```

删除文档：

```bash
uv run iceberg-library delete "My Paper"
```

## 🌐 API 提供商

项目通过 OpenAI 兼容 API 及模型前缀自动识别支持多种 LLM 提供商。配置模板见 `.env.example`。

### LLM / 模型提供商

- DeepSeek — https://platform.deepseek.com
- 智谱 GLM — https://open.bigmodel.cn
- Google Gemini — https://aistudio.google.com/apikey
- OpenAI — https://platform.openai.com
- Anthropic Claude — https://console.anthropic.com
- 阿里云 Qwen — https://dashscope.console.aliyun.com
- 离线 Ollama — https://ollama.com

### 搜索提供商

- Brave Search API — https://brave.com/search/api/
- Tavily Search API — https://tavily.com/

### 可选支持服务

- Qdrant Cloud — https://cloud.qdrant.io/
- GitHub MCP / 基于 GitHub Token 的集成 — https://github.com
  - ⚠️ 请确认 Docker 🐳 已安装并在后台运行。
- Unpaywall / 论文元数据 API — https://unpaywall.org/
- Core API（论文相关元数据）— https://core.ac.uk/

## 环境配置

`.env` 示例变量：

```env
LLM_MODEL_ID="deepseek-v4-flash"
DEEPSEEK_API_KEY="your-deepseek-api-key"
DEEPSEEK_BASE_URL="https://api.deepseek.com"

# 离线 Ollama 示例：
# LLM_PROVIDER="ollama"
# LLM_MODEL_ID="llama3.2:latest"
# OLLAMA_BASE_URL="http://localhost:11434/v1"
# OLLAMA_API_KEY="ollama"
# OLLAMA_DISABLE_TOOLS=true

BRAVE_API_KEY="your-brave-api-key"
TAVILY_API_KEY="your-tavily-api-key"

EMBEDDING_MODEL_ID="embedding-3"
EMBEDDING_BASE_URL="https://open.bigmodel.cn/api/paas/v4/"

QDRANT_URL=
QDRANT_API_KEY=
QDRANT_COLLECTION=iceberg_research
```

说明：

- 正常研究流程至少需要一个 LLM 提供商和一个搜索提供商。
- Embedding 可用于本地 RAG 与混合检索。
- Qdrant 是可选项，但推荐用于持久化向量索引。

## ⚖️ 许可证

本项目代码基于 [MIT License](LICENSE) 发布。
