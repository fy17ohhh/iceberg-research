# Iceberg Research

> Research beyond the surface.

[English](README.md) | [简体中文](README.zh-CN.md)

![home_page](assets/home_page.png)

Iceberg Research is multi-agent deep research project that turns a vague question into a grounded, cited research report. It clarifies the user brief, plans investigation steps, searches across web and papers, checks evidence quality, and synthesizes a final markdown report with citations and source traceability. The central design follows an **"underwater research workflow"**: the visible result is the final report, while the deeper work happens in planning, retrieval, evidence verification, and synthesis.

## 🤖 Agent Workflow

```text
Navigator  # decide where to investigate
  ↓
Diver      # search below the surface across web, papers, memory, and RAG
  ↓
Sonar      # verify evidence, detect gaps and redundancy
  ↓
Synthesizer # write the final grounded report
```

## Main Tech Stack

- FastAPI · SSE · MCP · Multi-Agent Orchestration
- RAG · BM25 + Vector Retrieval + Reciprocal Rank Fusion (RRF) ranking · Qdrant
- Iterative Search · Web Fetching · arXiv Retrieval · Evidence Review · Citation Traceability
- Next.js · React · TypeScript · Tailwind CSS · Docker · uv

## Features

- Multi-agent research loop with a clarification step before execution, research planning with sub-question decomposition and iterative re-planning based on Sonar feedback
- Web search with Brave and Tavily fallback; Paper and academic discovery via arXiv / search tools / MCP integrations
- Local library for ingesting PDFs, markdown, text, and saved research reports; RAG-based local knowledge retrieval over ingested documents and cached searches
- Long-term memory management for user preferences and research facts
- Independent reviewing stage (Sonar) for evidence quality, missing dimensions, and redundancy checks; Final markdown report generation through Synthesizer with citation normalization and source cleanup
- FastAPI backend with SSE streaming events for frontend progress updates; Next.js frontend for research workflows, report rendering, and memory/library UX
- Model-provider flexibility via OpenAI-compatible clients and provider auto-detection by model prefix

## 🚀 Quick start

Iceberg Research exposes one startup command. The launcher manages the uv environment, frontend dependencies, optional MCP checks, service health checks, and process cleanup.

```bash
git clone https://github.com/fy17ohhh/iceberg-research.git
cd iceberg-research
cp .env.example .env
# Add your API keys to .env

chmod +x ./setup.sh
./setup.sh
```

The launcher will then asks which interface to start:

- **Web command deck [1] (default)** — backend plus the browser UI at http://localhost:3000
- **Terminal search [2]** — backend plus an interactive research console in the current terminal
- Stop all services: press `Ctrl+C`

You can also skip the mode selection and enters directly by `./setup.sh web` and `./setup.sh terminal`.

## 📄 CLI usage

### Run a research query

```bash
uv run iceberg-research "What are the trade-offs between RAG and agentic search for enterprise knowledge work?"
```

Optional flags:

```bash
uv run iceberg-research "..." --model deepseek-v3 --max-rounds 3 --max-steps 4 --timeout 180
```

Add a local PDF or arXiv paper:

```bash
uv run iceberg-library add 2401.12345 --title "My Paper"
uv run iceberg-library add ./data/originals/my_paper.pdf
```

Delete a document:

```bash
uv run iceberg-library delete "My Paper"
```

## API providers

The project supports multiple LLM providers via OpenAI-compatible APIs and provider auto-detection by model prefix. The config template is defined in `.env.example`.

### LLM / model providers

- DeepSeek — https://platform.deepseek.com
- Zhipu GLM — https://open.bigmodel.cn
- Google Gemini — https://aistudio.google.com/apikey
- OpenAI — https://platform.openai.com
- Anthropic Claude — https://console.anthropic.com
- Alibaba Qwen — https://dashscope.console.aliyun.com
- Offline Ollama — https://ollama.com

### Search providers

- Brave Search API — https://brave.com/search/api/
- Tavily Search API — https://tavily.com/

### Optional supporting services

- Qdrant Cloud — https://cloud.qdrant.io/
- GitHub MCP / GitHub token-based integrations — https://github.com
  - ⚠️ make sure you have Docker🐳 Installed and running at background
- Unpaywall / paper metadata API — https://unpaywall.org/
- Core API (paper-related metadata) — https://core.ac.uk/

## Environment configuration

Example variables in `.env`:

```env
LLM_MODEL_ID="deepseek-v4-flash"
DEEPSEEK_API_KEY="your-deepseek-api-key"
DEEPSEEK_BASE_URL="https://api.deepseek.com"

# Offline Ollama example:
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

Notes:

- At least one LLM provider and one search provider are required for a normal research flow.
- Embeddings can be used for local RAG and hybrid retrieval.
- Qdrant is optional but strongly recommended for a more durable vector index.

## License

Code of this project is released under the [MIT License](LICENSE).
