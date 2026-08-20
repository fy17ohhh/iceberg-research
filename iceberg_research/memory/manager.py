from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import jieba

from .models import (
    Evidence,
    MemoryItem,
    MemoryLifecycle,
    MemoryOrigin,
    ResearchPreferences,
    RetrievedMemory,
)

if TYPE_CHECKING:
    from ..base import LLMClient
    from ..rag.embedding import Embedding


logger = logging.getLogger(__name__)

PREFERENCE_DEFINITIONS = {
    "report_language": {
        "subject": "研究报告语言偏好",
        "values": {
            "auto": "研究报告语言应跟随用户当前问题的语言。",
            "zh-CN": "用户偏好使用中文撰写研究报告。",
            "en": "用户偏好使用英文撰写研究报告。",
        },
        "keywords": ["报告语言", "中文", "英文", "language"],
    },
    "report_depth": {
        "subject": "研究报告深度偏好",
        "values": {
            "concise": "用户偏好简洁的研究报告，突出核心结论和关键证据。",
            "balanced": "用户偏好在结论、分析深度和篇幅之间保持平衡。",
            "deep": "用户偏好深入的研究报告，包含机制、对比、限制和充分证据。",
        },
        "keywords": ["报告深度", "篇幅", "详细分析"],
    },
    "prefer_primary_sources": {
        "subject": "一手来源偏好",
        "true": "Iceberg Research 应优先使用官方文档、原始报告、数据集和其他一手来源。",
        "false": "用户不要求 Iceberg Research 优先使用一手来源。",
        "keywords": ["一手来源", "官方文档", "原始数据"],
    },
    "prefer_academic_sources": {
        "subject": "学术来源偏好",
        "true": "Iceberg Research 应优先使用论文和学术资料。",
        "false": "用户不要求 Iceberg Research 优先使用学术资料。",
        "keywords": ["论文", "学术来源", "paper"],
    },
    "include_methodology": {
        "subject": "方法细节偏好",
        "true": "研究报告应包含关键方法、机制和实验设计细节。",
        "false": "研究报告不必主动展开方法和实验设计细节。",
        "keywords": ["方法", "机制", "实验设计"],
    },
    "include_quantitative_evidence": {
        "subject": "量化证据偏好",
        "true": "研究报告应尽量提供数据、指标、日期和量化结果。",
        "false": "研究报告不强制要求量化指标。",
        "keywords": ["数据", "指标", "量化证据"],
    },
    "include_code_repositories": {
        "subject": "代码仓库偏好",
        "true": "研究相关时，应寻找并列出有价值的官方代码仓库或实现。",
        "false": "研究报告不必主动寻找代码仓库。",
        "keywords": ["代码仓库", "GitHub", "implementation"],
    },
}


MEMORY_EXTRACTION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "save_research_memories",
        "description": "Extract a small set of durable, atomic, evidence-backed facts.",
        "parameters": {
            "type": "object",
            "properties": {
                "facts": {
                    "type": "array",
                    "maxItems": 8,
                    "items": {
                        "type": "object",
                        "properties": {
                            "subject": {"type": "string"},
                            "content": {"type": "string"},
                            "topics": {"type": "array", "items": {"type": "string"}},
                            "entities": {"type": "array", "items": {"type": "string"}},
                            "keywords": {"type": "array", "items": {"type": "string"}},
                            "importance": {"type": "number", "minimum": 0, "maximum": 1},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "evidence": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "url": {"type": "string"},
                                        "source_type": {
                                            "type": "string",
                                            "enum": [
                                                "paper", "official_documentation",
                                                "official_report", "dataset",
                                                "webpage", "book", "news"
                                            ],
                                        },
                                        "published_at": {"type": ["string", "null"]},
                                        "excerpt": {"type": ["string", "null"]},
                                    },
                                    "required": ["title", "url", "source_type"],
                                },
                            },
                        },
                        "required": [
                            "subject", "content", "topics", "entities", "keywords",
                            "importance", "confidence", "evidence"
                        ],
                    },
                }
            },
            "required": ["facts"],
        },
    },
}


class MemoryManager:
    """File-first long-term memory with a rebuildable local hybrid index."""

    def __init__(
        self,
        data_dir: str,
        embedding: Embedding | None = None,
        max_results: int = 8,
        max_prompt_chars: int = 6000,
    ) -> None:
        self.root = Path(data_dir)
        self.items_dir = self.root / "items"
        self.archive_dir = self.root / "archive"
        self.index_dir = self.root / "index"
        for memory_type in ("user_preference", "research_context", "research_fact"):
            (self.items_dir / memory_type).mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)

        self.embedding = embedding
        self.max_results = max_results
        self.max_prompt_chars = max_prompt_chars
        self._lock = threading.RLock()
        self._db = sqlite3.connect(
            self.index_dir / "memory_index.db", check_same_thread=False
        )
        self._db.row_factory = sqlite3.Row
        self._configure_database()
        self._sync_files()

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [
            token.strip().lower()
            for token in jieba.lcut(text)
            if token.strip() and not token.isspace()
        ]

    @staticmethod
    def _search_text(item: MemoryItem) -> str:
        return " ".join(
            [
                item.subject,
                item.content,
                *item.topics,
                *item.entities,
                *item.keywords,
            ]
        )

    def _configure_database(self) -> None:
        with self._db:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL UNIQUE,
                    file_mtime REAL NOT NULL,
                    memory_type TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    content TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    item_json TEXT NOT NULL,
                    embedding_json TEXT
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    id UNINDEXED,
                    search_text,
                    tokenize='unicode61'
                );
                """
            )

    def _embed(self, text: str) -> list[float] | None:
        if self.embedding is None:
            return None
        try:
            vector, _ = self.embedding.invoke(text)
            return vector
        except Exception as exc:
            logger.warning("[Memory] embedding unavailable, sparse fallback: %s", exc)
            return None

    def _index_item(self, item: MemoryItem, path: Path, mtime: float) -> None:
        search_text = self._search_text(item)
        tokens = " ".join(self._tokenize(search_text))
        existing = self._db.execute(
            "SELECT file_mtime, embedding_json FROM memory_records WHERE id = ?",
            (item.id,),
        ).fetchone()
        if existing and float(existing["file_mtime"]) == mtime:
            return
        embedding = self._embed(search_text)
        embedding_json = (
            json.dumps(embedding) if embedding is not None
            else (existing["embedding_json"] if existing else None)
        )
        with self._db:
            self._db.execute("DELETE FROM memory_fts WHERE id = ?", (item.id,))
            self._db.execute(
                """
                INSERT INTO memory_records(
                    id, file_path, file_mtime, memory_type, subject,
                    content, search_text, item_json, embedding_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    file_path=excluded.file_path,
                    file_mtime=excluded.file_mtime,
                    memory_type=excluded.memory_type,
                    subject=excluded.subject,
                    content=excluded.content,
                    search_text=excluded.search_text,
                    item_json=excluded.item_json,
                    embedding_json=excluded.embedding_json
                """,
                (
                    item.id,
                    str(path),
                    mtime,
                    item.type,
                    item.subject,
                    item.content,
                    search_text,
                    item.model_dump_json(),
                    embedding_json,
                ),
            )
            self._db.execute(
                "INSERT INTO memory_fts(id, search_text) VALUES (?, ?)",
                (item.id, tokens),
            )

    def _sync_files(self) -> None:
        with self._lock:
            paths = list(self.items_dir.glob("*/*.json"))
            live_paths = {str(path) for path in paths}
            for path in paths:
                try:
                    item = MemoryItem.model_validate_json(
                        path.read_text(encoding="utf-8")
                    )
                    self._index_item(item, path, path.stat().st_mtime)
                except Exception as exc:
                    logger.error("[Memory] skip invalid file %s: %s", path, exc)

            indexed = self._db.execute(
                "SELECT id, file_path FROM memory_records"
            ).fetchall()
            stale_ids = [row["id"] for row in indexed if row["file_path"] not in live_paths]
            if stale_ids:
                with self._db:
                    self._db.executemany(
                        "DELETE FROM memory_fts WHERE id = ?",
                        [(memory_id,) for memory_id in stale_ids],
                    )
                    self._db.executemany(
                        "DELETE FROM memory_records WHERE id = ?",
                        [(memory_id,) for memory_id in stale_ids],
                    )

    def save(self, item: MemoryItem) -> MemoryItem:
        if item.type == "research_fact" and not item.evidence:
            raise ValueError("research_fact 必须至少包含一个 evidence")
        destination = self.items_dir / item.type / f"{item.id}.json"
        payload = item.model_dump_json(indent=2)
        with self._lock:
            fd, tmp_path = tempfile.mkstemp(
                prefix=f".{item.id}.", suffix=".tmp", dir=destination.parent
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    file.write(payload)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(tmp_path, destination)
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            self._index_item(item, destination, destination.stat().st_mtime)
        logger.info("[Memory] saved %s: %s", item.type, item.subject)
        return item

    def list_items(self, memory_type: str | None = None) -> list[MemoryItem]:
        self._sync_files()
        sql = "SELECT item_json FROM memory_records"
        params: tuple = ()
        if memory_type:
            sql += " WHERE memory_type = ?"
            params = (memory_type,)
        rows = self._db.execute(sql, params).fetchall()
        items = [MemoryItem.model_validate_json(row["item_json"]) for row in rows]
        return sorted(
            items, key=lambda item: item.lifecycle.updated_at, reverse=True
        )

    def delete(self, memory_id: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT file_path FROM memory_records WHERE id = ?",
                (memory_id,),
            ).fetchone()
            if not row:
                return False
            source = Path(row["file_path"])
            if source.exists():
                destination = self.archive_dir / source.name
                if destination.exists():
                    destination = self.archive_dir / (
                        f"{source.stem}_{uuid.uuid4().hex[:8]}.json"
                    )
                shutil.move(str(source), str(destination))
            with self._db:
                self._db.execute("DELETE FROM memory_fts WHERE id = ?", (memory_id,))
                self._db.execute(
                    "DELETE FROM memory_records WHERE id = ?", (memory_id,)
                )
        return True

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left:
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)

    def retrieve(self, query: str, top_k: int | None = None) -> list[RetrievedMemory]:
        if not query.strip():
            return []
        self._sync_files()
        limit = top_k or self.max_results
        query_tokens = self._tokenize(query)
        fts_query = " OR ".join(
            f'"{token.replace(chr(34), chr(34) * 2)}"' for token in query_tokens
        )
        sparse_ranks: dict[str, int] = {}
        if fts_query:
            try:
                rows = self._db.execute(
                    """
                    SELECT id FROM memory_fts
                    WHERE memory_fts MATCH ?
                    ORDER BY bm25(memory_fts)
                    LIMIT ?
                    """,
                    (fts_query, max(limit * 4, 20)),
                ).fetchall()
                sparse_ranks = {
                    row["id"]: rank for rank, row in enumerate(rows, start=1)
                }
            except sqlite3.OperationalError as exc:
                logger.warning("[Memory] sparse query failed: %s", exc)

        query_embedding = self._embed(query)
        query_terms = set(query_tokens)
        rows = self._db.execute(
            "SELECT id, item_json, search_text, embedding_json FROM memory_records"
        ).fetchall()
        results: list[RetrievedMemory] = []
        now = self._now()
        for row in rows:
            item = MemoryItem.model_validate_json(row["item_json"])
            if item.lifecycle.status != "active":
                continue
            if item.lifecycle.expires_at and item.lifecycle.expires_at < now:
                continue

            sparse_score = (
                1 / (60 + sparse_ranks[item.id]) if item.id in sparse_ranks else 0
            )
            item_terms = set(self._tokenize(row["search_text"]))
            overlap = len(query_terms & item_terms) / max(1, len(query_terms))
            dense_score = 0.0
            if query_embedding and row["embedding_json"]:
                dense_score = max(
                    0.0,
                    self._cosine(query_embedding, json.loads(row["embedding_json"])),
                )
            preference_bonus = 0.05 if item.type == "user_preference" else 0.0
            score = (
                dense_score * 0.45
                + min(1.0, sparse_score * 61) * 0.20
                + overlap * 0.15
                + item.importance * 0.10
                + item.confidence * 0.10
                + preference_bonus
            )
            lexical_match = item.id in sparse_ranks or overlap > 0
            if score >= 0.36 and (lexical_match or dense_score >= 0.45):
                results.append(RetrievedMemory(memory=item, score=score))

        results.sort(key=lambda result: result.score, reverse=True)
        return results[:limit]

    def format_for_prompt(self, query: str) -> str:
        retrieved = self.retrieve(query)
        preferences = [
            item
            for item in self.list_items("user_preference")
            if item.lifecycle.status == "active"
        ]
        if not retrieved and not preferences:
            return ""
        groups = {
            "user_preference": preferences,
            "research_context": [],
            "research_fact": [],
        }
        type_limits = {
            "user_preference": len(preferences),
            "research_context": 3,
            "research_fact": 5,
        }
        for result in retrieved:
            if result.memory.type == "user_preference":
                continue
            group = groups[result.memory.type]
            if len(group) < type_limits[result.memory.type]:
                group.append(result.memory)

        sections = [
            "The following memories are contextual preferences and previously "
            "verified facts. Apply them only when relevant. Research facts may "
            "be outdated and never override newer evidence."
        ]
        headings = {
            "user_preference": "User research preferences",
            "research_context": "Relevant research context",
            "research_fact": "Previously verified research facts",
        }
        for memory_type, items in groups.items():
            if not items:
                continue
            sections.append(f"### {headings[memory_type]}")
            for item in items:
                line = f"- {item.content}"
                if memory_type == "research_fact":
                    verified = item.lifecycle.last_verified_at or "unknown"
                    source = item.evidence[0].title if item.evidence else "unknown"
                    line += f" (Source: {source}; verified: {verified})"
                sections.append(line)
        return "\n".join(sections)[: self.max_prompt_chars]

    def get_preferences(self) -> ResearchPreferences:
        values = ResearchPreferences().model_dump()
        for item in self.list_items("user_preference"):
            key = item.id.removeprefix("pref_")
            if key not in values:
                continue
            raw_value = item.origin.excerpt
            if isinstance(values[key], bool):
                values[key] = raw_value == "true"
            else:
                values[key] = raw_value or values[key]
        contexts = self.list_items("research_context")
        if contexts:
            values["research_context"] = contexts[0].content
        return ResearchPreferences(**values)

    def save_preferences(
        self, preferences: ResearchPreferences, session_id: str | None = None
    ) -> ResearchPreferences:
        now = self._now()
        for key, definition in PREFERENCE_DEFINITIONS.items():
            value = getattr(preferences, key)
            if "values" in definition:
                content = definition["values"][value]
            else:
                content = definition["true" if value else "false"]
            item = MemoryItem(
                id=f"pref_{key}",
                type="user_preference",
                subject=definition["subject"],
                content=content,
                topics=["Iceberg Research", "research preferences"],
                keywords=definition["keywords"],
                importance=0.9,
                confidence=1.0,
                origin=MemoryOrigin(
                    kind="user_message",
                    session_id=session_id,
                    excerpt=str(value).lower() if isinstance(value, bool) else str(value),
                    created_by="user",
                ),
                lifecycle=MemoryLifecycle(
                    created_at=now,
                    updated_at=now,
                ),
            )
            self.save(item)

        if preferences.research_context.strip():
            context = MemoryItem(
                id="context_user_research_background",
                type="research_context",
                subject="用户长期研究背景",
                content=preferences.research_context.strip(),
                topics=["Iceberg Research", "user research background"],
                keywords=self._tokenize(preferences.research_context)[:20],
                importance=0.95,
                confidence=1.0,
                origin=MemoryOrigin(
                    kind="user_message",
                    session_id=session_id,
                    excerpt=preferences.research_context.strip()[:300],
                    created_by="user",
                ),
                lifecycle=MemoryLifecycle(created_at=now, updated_at=now),
            )
            self.save(context)
        else:
            self.delete("context_user_research_background")
        return preferences

    def remember_research(
        self,
        llm: LLMClient,
        research_question: str,
        report: str,
        session_id: str | None = None,
    ) -> list[MemoryItem]:
        prompt = (
            "Extract at most 8 durable, reusable, atomic facts from this Deep "
            "Research report. Every fact must be directly supported by at least "
            "one source URL present in the report. Do not save opinions, report "
            "structure, temporary instructions, credentials, or facts without "
            "evidence. Keep each content field independently understandable.\n\n"
            f"<research_question>{research_question}</research_question>\n"
            f"<report>{report}</report>"
        )
        response = llm.invoke(
            messages=[{"role": "user", "content": prompt}],
            tools=[MEMORY_EXTRACTION_SCHEMA],
            tool_choice={
                "type": "function",
                "function": {"name": "save_research_memories"},
            },
            temperature=0,
            tag="memory:extract",
        )
        if not response.tool_calls:
            logger.warning("[Memory] extraction returned no tool call")
            return []
        try:
            facts = json.loads(response.tool_calls[0].function.arguments).get(
                "facts", []
            )
        except (json.JSONDecodeError, AttributeError):
            logger.exception("[Memory] invalid extraction response")
            return []

        now = self._now()
        saved: list[MemoryItem] = []
        for fact in facts[:8]:
            evidence_data = fact.get("evidence") or []
            evidence = []
            for source in evidence_data:
                url = str(source.get("url", "")).strip()
                if not re.match(r"^https?://", url) or url not in report:
                    continue
                evidence.append(
                    Evidence(
                        **{
                            **source,
                            "url": url,
                            "accessed_at": now,
                        }
                    )
                )
            if not evidence:
                continue
            content = str(fact.get("content", "")).strip()
            if not content:
                continue
            digest = hashlib.sha256(content.casefold().encode("utf-8")).hexdigest()[:20]
            item = MemoryItem(
                id=f"mem_fact_{digest}",
                type="research_fact",
                subject=str(fact.get("subject", "")).strip() or content[:80],
                content=content,
                topics=fact.get("topics", [])[:10],
                entities=fact.get("entities", [])[:10],
                keywords=fact.get("keywords", [])[:15],
                importance=max(0.0, min(1.0, float(fact.get("importance", 0.7)))),
                confidence=max(0.0, min(1.0, float(fact.get("confidence", 0.8)))),
                evidence=evidence,
                origin=MemoryOrigin(
                    kind="research_session",
                    session_id=session_id,
                    research_question=research_question,
                    created_by="synthesizer",
                ),
                lifecycle=MemoryLifecycle(
                    created_at=now,
                    updated_at=now,
                    last_verified_at=now,
                ),
            )
            saved.append(self.save(item))
        return saved

    def close(self) -> None:
        with self._lock:
            self._db.close()
