import argparse
import logging

from iceberg_search.base import setup_logging
from iceberg_search.agents import Navigator
from iceberg_search.config import Config
from iceberg_search.orchestrator import Orchestrator
from iceberg_search.display import stream_events

logger = logging.getLogger("iceberg_search.main")
display = logging.getLogger("iceberg_search.display")


def parse_args():
    parser = argparse.ArgumentParser(description="Iceberg Search: 自主多 Agent 研究系统")
    parser.add_argument("query", nargs="?", default=None, help="研究问题（不提供则交互输入）")
    parser.add_argument("--model", default=None, help="LLM 模型名称")
    parser.add_argument("--max-rounds", type=int, default=None, help="最大审查轮数")
    parser.add_argument("--max-steps", type=int, default=None, help="Diver 最大搜索步数")
    parser.add_argument("--timeout", type=int, default=None, help="LLM 调用超时(秒)")
    parser.add_argument("--data-dir", default=None, help="数据目录路径")
    return parser.parse_args()


def main():
    setup_logging()
    args = parse_args()
    config = Config()

    if args.model:
        config.llm.model = args.model
    if args.max_rounds:
        config.max_rounds = args.max_rounds
    if args.max_steps:
        config.max_steps = args.max_steps
    if args.timeout:
        config.llm.timeout = args.timeout
    if args.data_dir:
        config.data_dir = args.data_dir

    with Orchestrator(config) as orch:
        raw_query = args.query or input("请输入研究问题: ")
        navigator = Navigator(
            llm=orch.llm_client,
            context_builder=orch.context_builder,
            max_steps=orch.config.max_steps,
        )
        research_brief = navigator.run(raw_query)

        display.info("\n" + "=" * 60)
        display.info("开始研究: %s", research_brief)
        display.info("=" * 60)

        stream_events(orch.run_research(research_brief))

        llm = orch.llm_client
        total_tokens = llm.total_prompt_tokens + llm.total_completion_tokens
        logger.info("统计: %d 次调用, tokens=%d(in:%d+out:%d)", llm.total_calls, total_tokens, llm.total_prompt_tokens, llm.total_completion_tokens)
        display.info("\n--- 统计 ---")
        display.info("LLM 调用: %d 次", llm.total_calls)
        display.info("Token: %d (in:%d + out:%d)", total_tokens, llm.total_prompt_tokens, llm.total_completion_tokens)


if __name__ == "__main__":
    main()
