"""Terminal client for the Iceberg Search HTTP/SSE API."""

from __future__ import annotations

import json
import os
import sys
import argparse
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from typing import Any


API_BASE = os.getenv("ICEBERG_API_BASE", "http://127.0.0.1:8000").rstrip("/")
LANGUAGE = os.getenv("ICEBERG_LANGUAGE", "en")
RESET = "\033[0m"
ICE = "\033[1;96m"
CYAN = "\033[0;36m"
DIM = "\033[2m"
GREEN = "\033[0;32m"
RED = "\033[0;31m"

TEXT = {
    "en": {
        "api_unreachable": "Cannot reach Iceberg API at {base}: {reason}",
        "api_error": "API returned HTTP {code}: {detail}",
        "scope_fallback": "Please narrow the research scope.",
        "scope": "Scope",
        "default_scope": "Please use the most relevant suggested direction.",
        "routes_mapped": "{count} routes mapped",
        "researching": "Researching",
        "review_round": "Round {round} · {approved}/{total} approved",
        "report_surfaced": "Report surfaced",
        "unknown_error": "Unknown research error",
        "stream_disconnected": "Research stream disconnected: {reason}",
        "research_failed": "Research request failed with HTTP {code}: {detail}",
        "query": "Research query",
        "save": "Save to library? [y/N]",
        "title": "Report title",
        "saved": "Saved to the research library.",
        "banner_subtitle": "navigate · dive · verify · synthesize",
        "quit_hint": "Type :quit to leave the console.",
        "closed": "Surfacing. Research console closed.",
        "terminal_failed": "Terminal search failed:",
    },
    "zh-CN": {
        "api_unreachable": "无法连接 Iceberg API（{base}）：{reason}",
        "api_error": "API 返回 HTTP {code}：{detail}",
        "scope_fallback": "请进一步缩小研究范围。",
        "scope": "研究范围",
        "default_scope": "请使用最相关的建议方向。",
        "routes_mapped": "已规划 {count} 条研究路径",
        "researching": "正在研究",
        "review_round": "第 {round} 轮审查 · {approved}/{total} 通过",
        "report_surfaced": "研究报告已生成",
        "unknown_error": "未知研究错误",
        "stream_disconnected": "研究连接已中断：{reason}",
        "research_failed": "研究请求失败，HTTP {code}：{detail}",
        "query": "研究问题",
        "save": "保存到文档库？[y/N]",
        "title": "报告标题",
        "saved": "已保存到研究文档库。",
        "banner_subtitle": "导航 · 下潜 · 验证 · 综合",
        "quit_hint": "输入 :quit 退出终端。",
        "closed": "浮出水面，研究终端已关闭。",
        "terminal_failed": "终端搜索失败：",
    },
}


def tr(key: str, **variables: object) -> str:
    return TEXT.get(LANGUAGE, TEXT["en"])[key].format(**variables)


def api_json(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(tr("api_error", code=exc.code, detail=detail)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(tr("api_unreachable", base=API_BASE, reason=exc.reason)) from exc


def navigate_query(query: str) -> str:
    result = api_json("/api/navigator/analyze", {"query": query})
    if result.get("is_clear"):
        return str(result.get("brief") or query)

    print(f"\n{CYAN}NAVIGATOR{RESET}  {result.get('message', tr('scope_fallback'))}")
    directions = result.get("directions") or []
    for index, direction in enumerate(directions, 1):
        print(f"  {index}. {direction}")
    answer = input(f"\n{ICE}{tr('scope')} › {RESET}").strip()
    if not answer:
        answer = tr("default_scope")
    refined = api_json("/api/navigator/refine", {"query": query, "response": answer})
    return str(refined.get("brief") or query)


def iter_sse(response: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    event_type = "message"
    data_lines: list[str] = []
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
        if not line:
            if data_lines:
                yield event_type, json.loads("\n".join(data_lines))
            event_type, data_lines = "message", []
        elif line.startswith("event:"):
            event_type = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield event_type, json.loads("\n".join(data_lines))


def render_event(event_type: str, data: dict[str, Any]) -> None:
    if event_type == "navigator":
        print(f"{CYAN}NAVIGATOR{RESET}  {tr('routes_mapped', count=len(data.get('sub_questions', [])))}")
    elif event_type == "diver":
        question = str(data.get("question", tr("researching")))
        print(f"{CYAN}DIVER{RESET}      {question[:88]}")
    elif event_type == "sonar":
        reviews = data.get("sonar_summary", [])
        approved = sum(item.get("verdict") == "approved" for item in reviews)
        print(f"{CYAN}SONAR{RESET}      {tr('review_round', round=data.get('round', '?'), approved=approved, total=len(reviews))}")
    elif event_type == "synthesizer":
        print(f"{GREEN}SYNTHESIZER{RESET}  {tr('report_surfaced')}")
    elif event_type == "stats":
        print(f"{DIM}TOKENS      {data.get('total_tokens', 0):,}{RESET}")
    elif event_type == "error":
        print(f"{RED}ERROR{RESET}      {data.get('message', tr('unknown_error'))}")


def stream_research(brief: str, session_id: str) -> str | None:
    payload = json.dumps({"brief": brief, "session_id": session_id}).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}/api/research",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    report: str | None = None
    try:
        with urllib.request.urlopen(request) as response:
            for event_type, data in iter_sse(response):
                render_event(event_type, data)
                if event_type == "synthesizer":
                    report = data.get("report")
                elif event_type == "error":
                    return None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(tr("research_failed", code=exc.code, detail=detail)) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(tr("stream_disconnected", reason=exc.reason)) from exc
    return report


def save_report(title: str, report: str) -> None:
    api_json("/api/library/save-report", {"title": title, "content": report})


def run_search_session(session_id: str) -> bool:
    query = input(f"\n{ICE}{tr('query')} › {RESET}").strip()
    if query.lower() in {":q", ":quit", "quit", "exit"}:
        return False
    if not query:
        return True
    brief = navigate_query(query)
    print(f"\n{DIM}{brief}{RESET}\n")
    report = stream_research(brief, session_id)
    if report:
        print(f"\n{'─' * 72}\n{report}\n{'─' * 72}")
        if input(f"\n{ICE}{tr('save')} › {RESET}").strip().lower() in {"y", "yes"}:
            title = input(f"{ICE}{tr('title')} › {RESET}").strip() or query[:80]
            save_report(title, report)
            print(f"{GREEN}{tr('saved')}{RESET}")
    return True


def main() -> int:
    global LANGUAGE
    parser = argparse.ArgumentParser(description="Iceberg Search terminal interface")
    parser.add_argument("--lang", choices=("en", "zh-CN"), default=LANGUAGE, help="Display language (default: en)")
    args = parser.parse_args()
    LANGUAGE = args.lang
    print(f"{ICE}╭──────────────────────────────────────────╮")
    print("│        ICEBERG SEARCH // TERMINAL        │")
    print(f"│  {tr('banner_subtitle'):^40}│")
    print(f"╰──────────────────────────────────────────╯{RESET}")
    print(f"{DIM}{tr('quit_hint')}{RESET}")
    session_id = f"terminal_{uuid.uuid4().hex}"
    try:
        while run_search_session(session_id):
            pass
    except (EOFError, KeyboardInterrupt):
        print(f"\n{DIM}{tr('closed')}{RESET}")
        return 130
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"\n{RED}{tr('terminal_failed')}{RESET} {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
