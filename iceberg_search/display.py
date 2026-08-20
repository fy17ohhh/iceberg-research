from __future__ import annotations

"""Human-readable stage output for graph execution."""

import logging
import time

from .agents.sonar_models import ReviewResult

logger = logging.getLogger("iceberg_search.display")


def _log(msg: str):
    logger.info(msg)


def format_sonar_verdict(note_review) -> str:
    failed = note_review.failed_criteria()
    if not failed:
        return f"verdict={note_review.verdict} (5/5 PASS)"
    lines = [f"verdict={note_review.verdict}"]
    for line in failed.split("\n"):
        lines.append(f"       {line}")
    return "\n".join(lines)


def print_stage_header(node_name: str, elapsed: float):
    _log(f"\n{'=' * 60}")
    _log(f"[{node_name}]  (elapsed {elapsed:.1f}s)")
    _log("=" * 60)


def print_plan(output):
    sub_questions = output.get("sub_questions", [])
    _log(f"  拆分出 {len(sub_questions)} 个子问题:")
    for i, sq in enumerate(sub_questions):
        _log(f"\n  [{i}] question: {sq.question}")
        _log(f"      rationale: {sq.rationale}")


def print_research(output):
    items = output.get("pending_sonar_items", [])
    for item in items:
        _log(f"  子问题: {item.sub_question}")
        _log(f"  研究笔记 ({len(item.research_note)} 字符):")
        _log("  " + "-" * 50)
        for line in item.research_note.split("\n"):
            _log(f"  {line}")
        _log("  " + "-" * 50)


def print_sonar(output):
    rr = output.get("sonar_result")
    if rr:
        if isinstance(rr, dict):
            rr = ReviewResult(**rr)
        for i, nr in enumerate(rr.note_reviews):
            _log(f"  [{i}] {format_sonar_verdict(nr)}")
        if rr.coverage_gaps:
            for gap in rr.coverage_gaps:
                _log(f"  coverage_gap: {gap.dimension} — {gap.reason}")
    _log(f"  approved_items 新增: {len(output.get('approved_items', []))} 条")
    retry = output.get("retry_items", [])
    if retry:
        _log(f"  retry_items: {len(retry)} 条")
        for item in retry:
            _log(f"    - {item['sub_question'][:80]}")
    _log(f"  refine_round: {output.get('refine_round')}")


def print_write(output):
    report = output.get("final_report", "")
    _log(f"  报告长度: {len(report)} 字符")
    _log(f"\n{'=' * 60}")
    _log("最终报告:")
    _log("=" * 60)
    _log(report)


def stream_events(events):
    printers = {
        "navigator_node": print_plan,
        "diver_node": print_research,
        "sonar_node": print_sonar,
        "synthesizer_node": print_write,
    }
    t_start = time.time()
    for event in events:
        for node_name, output in event.items():
            elapsed = time.time() - t_start
            print_stage_header(node_name, elapsed)
            printer = printers.get(node_name)
            if printer:
                printer(output)
            else:
                _log(f"  output keys: {list(output.keys())}")
    elapsed = time.time() - t_start
    _log(f"\n总耗时: {elapsed:.1f}s")
