import json
import types

from iceberg_search.memory import MemoryManager, ResearchPreferences
from iceberg_search.memory.models import (
    Evidence,
    MemoryItem,
    MemoryLifecycle,
    MemoryOrigin,
)


class FakeEmbedding:
    def invoke(self, text):
        texts = [text] if isinstance(text, str) else text
        vectors = []
        for value in texts:
            normalized = value.lower()
            vectors.append([
                float("rag" in normalized or "检索" in normalized),
                float("source" in normalized or "来源" in normalized),
                float("agent" in normalized),
            ])
        return (vectors[0] if isinstance(text, str) else vectors, 0)


def _fact(now="2026-07-30T18:30:00+08:00"):
    return MemoryItem(
        id="mem_fact_self_rag",
        type="research_fact",
        subject="Self-RAG 检索机制",
        content="Self-RAG 使用反思 token 决定是否检索并评价证据。",
        topics=["RAG", "Self-RAG"],
        entities=["Self-RAG"],
        keywords=["检索", "反思 token"],
        importance=0.9,
        confidence=0.95,
        evidence=[
            Evidence(
                title="Self-RAG paper",
                url="https://arxiv.org/abs/2310.11511",
                source_type="paper",
                accessed_at=now,
            )
        ],
        origin=MemoryOrigin(
            kind="research_session",
            research_question="如何减少 RAG 幻觉？",
            created_by="synthesizer",
        ),
        lifecycle=MemoryLifecycle(
            created_at=now,
            updated_at=now,
            last_verified_at=now,
        ),
    )


def test_each_memory_is_an_atomic_json_file_and_can_be_reloaded(tmp_path):
    manager = MemoryManager(str(tmp_path), embedding=FakeEmbedding())
    manager.save(_fact())
    manager.close()

    path = tmp_path / "items" / "research_fact" / "mem_fact_self_rag.json"
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1

    reopened = MemoryManager(str(tmp_path), embedding=FakeEmbedding())
    assert reopened.list_items("research_fact")[0].content.startswith("Self-RAG")
    reopened.close()


def test_retrieval_returns_related_memory_but_not_unrelated_query(tmp_path):
    manager = MemoryManager(str(tmp_path), embedding=FakeEmbedding())
    manager.save(_fact())

    related = manager.retrieve("RAG 如何决定什么时候进行检索？")
    unrelated = manager.retrieve("法国菜的历史")

    assert related[0].memory.id == "mem_fact_self_rag"
    assert unrelated == []
    manager.close()


def test_preferences_are_individual_files_and_round_trip(tmp_path):
    manager = MemoryManager(str(tmp_path), embedding=None)
    preferences = ResearchPreferences(
        report_language="zh-CN",
        report_depth="deep",
        include_code_repositories=True,
        research_context="我正在研究 Iceberg Search Agent 的评测和可靠性。",
    )

    manager.save_preferences(preferences, session_id="session-test")
    restored = manager.get_preferences()

    assert restored == preferences
    assert len(list((tmp_path / "items" / "user_preference").glob("*.json"))) == 7
    assert (
        tmp_path
        / "items"
        / "research_context"
        / "context_user_research_background.json"
    ).exists()
    prompt = manager.format_for_prompt("研究 Agent 的评测方法")
    assert "用户偏好使用中文撰写研究报告" in prompt
    assert "研究相关时，应寻找并列出有价值的官方代码仓库" in prompt
    manager.close()


def test_research_extraction_rejects_facts_without_http_evidence(tmp_path):
    manager = MemoryManager(str(tmp_path), embedding=None)
    payload = {
        "facts": [
            {
                "subject": "Valid",
                "content": "A reusable supported fact.",
                "topics": ["Agent"],
                "entities": [],
                "keywords": ["Agent"],
                "importance": 0.8,
                "confidence": 0.9,
                "evidence": [
                    {
                        "title": "Paper",
                        "url": "https://example.com/paper",
                        "source_type": "paper",
                        "published_at": None,
                        "excerpt": None,
                    }
                ],
            },
            {
                "subject": "Unsupported",
                "content": "A fact with no valid source.",
                "topics": [],
                "entities": [],
                "keywords": [],
                "importance": 0.5,
                "confidence": 0.5,
                "evidence": [
                    {
                        "title": "Missing URL",
                        "url": "not-a-url",
                        "source_type": "webpage",
                    }
                ],
            },
        ]
    }
    response = types.SimpleNamespace(
        tool_calls=[
            types.SimpleNamespace(
                function=types.SimpleNamespace(arguments=json.dumps(payload))
            )
        ]
    )
    llm = types.SimpleNamespace(invoke=lambda **kwargs: response)

    saved = manager.remember_research(
        llm=llm,
        research_question="Agent memory",
        report="report source: https://example.com/paper",
    )

    assert len(saved) == 1
    assert saved[0].subject == "Valid"
    manager.close()
