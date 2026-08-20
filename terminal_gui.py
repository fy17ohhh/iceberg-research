"""Terminal client for the Iceberg Research HTTP/SSE API."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from collections.abc import Iterator
from typing import Any


API_BASE = os.getenv("ICEBERG_API_BASE", "http://127.0.0.1:8000").rstrip("/")
RESET = "\033[0m"
ICE = "\033[1;96m"
CYAN = "\033[0;36m"
DIM = "\033[2m"
GREEN = "\033[0;32m"
RED = "\033[0;31m"


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
        raise RuntimeError(f"API returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach Iceberg API at {API_BASE}: {exc.reason}") from exc


def navigate_query(query: str) -> str:
    result = api_json("/api/navigator/analyze", {"query": query})
    if result.get("is_clear"):
        return str(result.get("brief") or query)

    print(f"\n{CYAN}NAVIGATOR{RESET}  {result.get('message', 'Please narrow the research scope.')}")
    directions = result.get("directions") or []
    for index, direction in enumerate(directions, 1):
        print(f"  {index}. {direction}")
    answer = input(f"\n{ICE}Scope › {RESET}").strip()
    if not answer:
        answer = "Please use the most relevant suggested direction."
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
        print(f"{CYAN}NAVIGATOR{RESET}  {len(data.get('sub_questions', []))} routes mapped")
    elif event_type == "diver":
        question = str(data.get("question", "Researching"))
        print(f"{CYAN}DIVER{RESET}      {question[:88]}")
    elif event_type == "sonar":
        reviews = data.get("sonar_summary", [])
        approved = sum(item.get("verdict") == "approved" for item in reviews)
        print(f"{CYAN}SONAR{RESET}      Round {data.get('round', '?')} · {approved}/{len(reviews)} approved")
    elif event_type == "synthesizer":
        print(f"{GREEN}SYNTHESIZER{RESET}  Report surfaced")
    elif event_type == "stats":
        print(f"{DIM}TOKENS      {data.get('total_tokens', 0):,}{RESET}")
    elif event_type == "error":
        print(f"{RED}ERROR{RESET}      {data.get('message', 'Unknown research error')}")


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
        raise RuntimeError(f"Research request failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Research stream disconnected: {exc.reason}") from exc
    return report


def save_report(title: str, report: str) -> None:
    api_json("/api/library/save-report", {"title": title, "content": report})


def run_search_session(session_id: str) -> bool:
    query = input(f"\n{ICE}Research query › {RESET}").strip()
    if query.lower() in {":q", ":quit", "quit", "exit"}:
        return False
    if not query:
        return True
    brief = navigate_query(query)
    print(f"\n{DIM}{brief}{RESET}\n")
    report = stream_research(brief, session_id)
    if report:
        print(f"\n{'─' * 72}\n{report}\n{'─' * 72}")
        if input(f"\n{ICE}Save to library? [y/N] › {RESET}").strip().lower() in {"y", "yes"}:
            title = input(f"{ICE}Report title › {RESET}").strip() or query[:80]
            save_report(title, report)
            print(f"{GREEN}Saved to the research library.{RESET}")
    return True


def main() -> int:
    print(f"{ICE}╭──────────────────────────────────────────╮")
    print("│       ICEBERG RESEARCH // TERMINAL       │")
    print(f"│     navigate · dive · verify · synthesize │")
    print(f"╰──────────────────────────────────────────╯{RESET}")
    print(f"{DIM}Type :quit to leave the console.{RESET}")
    session_id = f"terminal_{uuid.uuid4().hex}"
    try:
        while run_search_session(session_id):
            pass
    except (EOFError, KeyboardInterrupt):
        print(f"\n{DIM}Surfacing. Research console closed.{RESET}")
        return 130
    except (RuntimeError, json.JSONDecodeError) as exc:
        print(f"\n{RED}Terminal search failed:{RESET} {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
