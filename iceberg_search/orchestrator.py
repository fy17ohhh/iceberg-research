from __future__ import annotations

import os, json, logging

from iceberg_search.agents import Sonar, Navigator, Diver, Synthesizer
from iceberg_search.base import LLMClient
from iceberg_search.config import Config
from iceberg_search.context import HistoryCompactor, TokenCounter, ContextBuilder
from iceberg_search.graph import build_graph
from iceberg_search.library import LibraryManager
from iceberg_search.memory import MemoryManager
from iceberg_search.mcp import create_mcp_clients, register_mcp_tools
from iceberg_search.rag import Pipeline
from iceberg_search.search import SearchTool
from iceberg_search.tools import ToolRegistry, RAGTool
from iceberg_search.tools.tool_paper import PaperReaderTool

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, config: Config):
        self.config = config
        self.llm_client = LLMClient(model=config.llm.model, timeout=config.llm.timeout)
        self.rag_pipeline = Pipeline(data_dir=config.data_dir, llm_client=self.llm_client)
        self.memory_manager = MemoryManager(
            data_dir=os.path.join(config.data_dir, "memory"),
            embedding=self.rag_pipeline.embedding,
        )
        token_counter = TokenCounter()
        history_compactor = HistoryCompactor(llm_client=self.llm_client, token_counter=token_counter)
        self.context_builder = ContextBuilder(
            history_compactor=history_compactor,
            token_counter=token_counter,
            reserve_ratio=config.context.reserve_ratio,
            max_tokens=config.context.max_tokens,
            memory_manager=self.memory_manager,
        )
        self.mcp_clients = create_mcp_clients(
            os.path.join(self.config.config_dir, "mcp_servers.json")
        )
        tool_registry = ToolRegistry()
        register_mcp_tools(registry=tool_registry, clients=self.mcp_clients)

        brave_tool = tool_registry.tools.get("mcp__brave-search__brave_web_search")
        tavily_tool = tool_registry.tools.get("mcp__tavily__tavily_search")
        search_tool = SearchTool(brave_tool=brave_tool, tavily_tool=tavily_tool)

        download_tool = tool_registry.tools.get("mcp__paper-search__download_arxiv")
        read_tool = tool_registry.tools.get("mcp__paper-search__read_arxiv_paper")
        self.paper_reader = None
        if download_tool and read_tool:
            self.paper_reader = PaperReaderTool(
                download_tool=download_tool,
                read_tool=read_tool,
            )
            tool_registry.register_tool(self.paper_reader)
        else:
            logger.warning("Paper Search MCP tools are unavailable; arXiv full-text reading is disabled")

        self.pdf_reader_tool = tool_registry.tools.get("mcp__pdf-reader__read_pdf")
        if self.pdf_reader_tool is None:
            logger.info("PDF Reader MCP is unavailable; PyMuPDF remains the default PDF parser")

        rag_tool = RAGTool(pipeline=self.rag_pipeline)
        tool_registry.register_tool(search_tool)
        tool_registry.register_tool(rag_tool)

        with open(os.path.join(self.config.config_dir, "agents.json")) as f:
            agent_configs = json.load(f)

        whitelist = agent_configs["diver"]["allowed_tools"]
        missing_tools = [name for name in whitelist if name not in tool_registry.tools]
        missing_github_tools = [
            name for name in missing_tools if name.startswith("mcp__github__")
        ]
        if missing_github_tools:
            logger.info(
                "GitHub research tools are disabled; configure GITHUB_TOKEN and start "
                "the GitHub MCP server to enable repository analysis"
            )
        missing_tools = [name for name in missing_tools if name not in missing_github_tools]
        if missing_tools:
            logger.warning("Skipping unavailable optional tools: %s", ", ".join(missing_tools))
        available_tools = [name for name in whitelist if name in tool_registry.tools]
        self.diver_tools = tool_registry.get_tools(available_tools)
        
    def run_research(self, brief: str, session_id: str | None = None):
        sonar_override_llm = LLMClient(model=self.config.llm.sonar_model, timeout=self.config.llm.timeout) if self.config.llm.sonar_model else None
        sonar_llm = sonar_override_llm or self.llm_client
        sonar_token_counter = TokenCounter()
        sonar_context_builder = ContextBuilder(
            history_compactor=HistoryCompactor(
                llm_client=sonar_llm,
                token_counter=sonar_token_counter,
            ),
            token_counter=sonar_token_counter,
            reserve_ratio=self.config.context.reserve_ratio,
            max_tokens=self.config.context.max_tokens,
            memory_manager=None,
        )
        navigator = Navigator(
            llm=self.llm_client,
            context_builder=self.context_builder,
            max_steps=self.config.max_steps,
        )
        sonar = Sonar(
            llm=sonar_llm,
            context_builder=sonar_context_builder,
            batch_size=self.config.sonar.batch_size,
            max_attempts=self.config.sonar.max_attempts,
        )
        synthesizer = Synthesizer(llm=self.llm_client, context_builder=self.context_builder, temperature=self.config.llm.synthesizer_temperature)

        # make sure that every diver's history is independent
        def create_diver(diver_id: str = "D-?"):
            return Diver(
                name=diver_id,
                llm=self.llm_client,
                context_builder=self.context_builder,
                tool_list=self.diver_tools,
                max_steps=self.config.max_steps,
                temperature=self.config.llm.diver_temperature,
            )

        graph = build_graph(
            navigator,
            sonar,
            create_diver,
            synthesizer,
            self.rag_pipeline,
            self.config.max_rounds,
            memory_manager=self.memory_manager,
            llm_client=self.llm_client,
        )
        graph_generator = graph.stream(
            {"research_brief": brief, "session_id": session_id}
        )
        for event in graph_generator:
            yield event

    def create_library_manager(self) -> LibraryManager:
        manager = LibraryManager(
            data_dir=self.config.data_dir,
            paper_tool=self.paper_reader,
            pdf_reader_tool=self.pdf_reader_tool,
            pipeline=self.rag_pipeline,
        )
        return manager

    def close(self):
        if self.paper_reader is not None:
            self.paper_reader.cleanup()
        self.memory_manager.close()
        self.rag_pipeline.close()
        for client in self.mcp_clients:
            client.disconnect()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
