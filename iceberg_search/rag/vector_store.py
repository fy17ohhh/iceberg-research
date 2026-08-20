from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import uuid
import jieba
from dotenv import load_dotenv

try:
    from qdrant_client import QdrantClient, models
except ImportError:
    QdrantClient = None
    models = None

from .document import Chunk


logger = logging.getLogger(__name__)
load_dotenv()


class VectorStore:
    """Persistent hybrid store: Qdrant dense vectors + SQLite FTS5/BM25."""

    COLLECTION_NAME = "iceberg_search_chunks"
    _POINT_NAMESPACE = uuid.UUID("d619b128-f924-41d8-943e-9e4c40e04054")

    def __init__(
        self,
        data_dir: str,
        *,
        collection_name: str | None = None,
        qdrant_client: QdrantClient | None = None,
    ) -> None:
        self.data_dir = os.path.abspath(data_dir)
        self.collection_name = collection_name or os.getenv(
            "QDRANT_COLLECTION", self.COLLECTION_NAME
        )
        os.makedirs(self.data_dir, exist_ok=True)

        self.sqlite_path = os.path.join(self.data_dir, "sparse_store.db")
        self._db = sqlite3.connect(self.sqlite_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db_lock = threading.RLock()
        self._configure_sqlite()
        self._create_sparse_schema()

        if qdrant_client is not None:
            self.qdrant = qdrant_client
        else:
            if QdrantClient is None:
                self._db.close()
                raise ImportError(
                    "RAG 持久化需要 qdrant-client。请运行 ./setup.sh，"
                    "或执行 uv add 'qdrant-client>=1.15'。"
                )
            qdrant_url = os.getenv("QDRANT_URL", "").strip()
            qdrant_api_key = os.getenv("QDRANT_API_KEY", "").strip()
            if not qdrant_url or not qdrant_api_key:
                missing = [
                    name
                    for name, value in (
                        ("QDRANT_URL", qdrant_url),
                        ("QDRANT_API_KEY", qdrant_api_key),
                    )
                    if not value
                ]
                self._db.close()
                raise ValueError(
                    "Qdrant Cloud 配置不完整，缺少环境变量: "
                    + ", ".join(missing)
                )
            self.qdrant = QdrantClient(
                url=qdrant_url,
                api_key=qdrant_api_key,
                timeout=float(os.getenv("QDRANT_TIMEOUT", "10")),
                check_compatibility=os.getenv(
                    "QDRANT_CHECK_COMPATIBILITY", "false"
                ).strip().lower() in {"1", "true", "yes", "on"},
            )
            logger.info("[RAG] Qdrant Cloud: %s", qdrant_url)

    def _configure_sqlite(self) -> None:
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute("PRAGMA foreign_keys=ON")

    def _create_sparse_schema(self) -> None:
        try:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    point_id TEXT NOT NULL UNIQUE,
                    file_path TEXT NOT NULL,
                    file_path_key TEXT NOT NULL,
                    chunk_idx INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    tokens TEXT NOT NULL,
                    UNIQUE(file_path_key, chunk_idx)
                );

                CREATE INDEX IF NOT EXISTS idx_chunks_file_path_key
                    ON chunks(file_path_key);

                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    tokens,
                    content='chunks',
                    content_rowid='id',
                    tokenize='unicode61'
                );

                CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                    INSERT INTO chunks_fts(rowid, tokens)
                    VALUES (new.id, new.tokens);
                END;

                CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                    INSERT INTO chunks_fts(chunks_fts, rowid, tokens)
                    VALUES ('delete', old.id, old.tokens);
                END;

                CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
                    INSERT INTO chunks_fts(chunks_fts, rowid, tokens)
                    VALUES ('delete', old.id, old.tokens);
                    INSERT INTO chunks_fts(rowid, tokens)
                    VALUES (new.id, new.tokens);
                END;
                """
            )
            self._db.commit()
        except sqlite3.OperationalError as exc:
            raise RuntimeError(
                "当前 Python SQLite 未启用 FTS5，无法创建持久化 BM25 索引"
            ) from exc

    @staticmethod
    def _normalize_path(file_path: str) -> str:
        return os.path.normcase(os.path.abspath(file_path))

    @classmethod
    def _point_id(cls, file_path: str, chunk_idx: int) -> str:
        key = f"{cls._normalize_path(file_path)}:{chunk_idx}"
        return str(uuid.uuid5(cls._POINT_NAMESPACE, key))

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [token.strip().lower() for token in jieba.lcut(text) if token.strip()]

    def _collection_exists(self) -> bool:
        return self.qdrant.collection_exists(self.collection_name)

    def _ensure_collection(self, vector_size: int) -> None:
        if self._collection_exists():
            collection = self.qdrant.get_collection(self.collection_name)
            vectors = collection.config.params.vectors
            existing_size = getattr(vectors, "size", None)
            if existing_size is not None and existing_size != vector_size:
                raise ValueError(
                    f"Qdrant collection 向量维度为 {existing_size}，"
                    f"但当前 embedding 返回 {vector_size}。"
                    "请使用新的 QDRANT_COLLECTION 或重建索引。"
                )
            return

        self.qdrant.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
                on_disk=True,
            ),
        )
        logger.info(
            "[RAG] created Qdrant collection: %s (dim=%d)",
            self.collection_name,
            vector_size,
        )

    def add_chunks(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        if any(chunk.embedding is None for chunk in chunks):
            raise ValueError("写入 Qdrant 前所有 chunk 都必须包含 embedding")

        vector_size = len(chunks[0].embedding)
        if any(len(chunk.embedding) != vector_size for chunk in chunks):
            raise ValueError("同一批次的 embedding 维度不一致")
        self._ensure_collection(vector_size)

        points = []
        sparse_rows = []
        for chunk in chunks:
            tokens = chunk.tokens or self._tokenize(chunk.content)
            chunk.tokens = tokens
            point_id = self._point_id(chunk.file_path, chunk.chunk_idx)
            file_path_key = self._normalize_path(chunk.file_path)
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=chunk.embedding,
                    payload={
                        "file_path": chunk.file_path,
                        "file_path_key": file_path_key,
                        "chunk_idx": chunk.chunk_idx,
                        "content": chunk.content,
                    },
                )
            )
            sparse_rows.append(
                (
                    point_id,
                    chunk.file_path,
                    file_path_key,
                    chunk.chunk_idx,
                    chunk.content,
                    " ".join(tokens),
                )
            )

        with self._db_lock:
            try:
                with self._db:
                    self._db.executemany(
                        """
                        INSERT INTO chunks(
                            point_id, file_path, file_path_key,
                            chunk_idx, content, tokens
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(point_id) DO UPDATE SET
                            file_path=excluded.file_path,
                            file_path_key=excluded.file_path_key,
                            chunk_idx=excluded.chunk_idx,
                            content=excluded.content,
                            tokens=excluded.tokens
                        """,
                        sparse_rows,
                    )
                    # Keep the SQLite transaction open until Qdrant confirms the
                    # write. A cloud failure then rolls the sparse mutation back.
                    self.qdrant.upsert(
                        collection_name=self.collection_name,
                        points=points,
                        wait=True,
                    )
            except Exception:
                logger.exception("[RAG] hybrid persistence failed; SQLite rolled back")
                raise

    @staticmethod
    def _chunk_from_payload(payload: dict) -> Chunk:
        return Chunk(
            chunk_idx=int(payload["chunk_idx"]),
            content=str(payload["content"]),
            file_path=str(payload["file_path"]),
        )

    def dense_search(
        self, query_embedding: list[float], top_k: int
    ) -> list[tuple[Chunk, float]]:
        if top_k <= 0 or not self._collection_exists():
            return []
        points = self.qdrant.query_points(
            collection_name=self.collection_name,
            query=query_embedding,
            limit=top_k,
            with_payload=True,
        ).points
        return [
            (self._chunk_from_payload(point.payload or {}), float(point.score))
            for point in points
        ]

    @staticmethod
    def _fts_query(tokens: list[str]) -> str:
        safe_tokens = [token.replace('"', '""') for token in tokens if token]
        return " OR ".join(f'"{token}"' for token in safe_tokens)

    def bm25_search(self, query: str, top_k: int) -> list[tuple[Chunk, float]]:
        tokens = self._tokenize(query)
        match_query = self._fts_query(tokens)
        if top_k <= 0 or not match_query:
            return []

        with self._db_lock:
            rows = self._db.execute(
                """
                SELECT c.chunk_idx, c.content, c.file_path,
                       bm25(chunks_fts) AS bm25_rank
                FROM chunks_fts
                JOIN chunks AS c ON c.id = chunks_fts.rowid
                WHERE chunks_fts MATCH ?
                ORDER BY bm25_rank
                LIMIT ?
                """,
                (match_query, top_k),
            ).fetchall()
        return [
            (
                Chunk(
                    chunk_idx=row["chunk_idx"],
                    content=row["content"],
                    file_path=row["file_path"],
                ),
                -float(row["bm25_rank"]),
            )
            for row in rows
        ]

    def hybrid_search(
        self, query: str, query_embedding: list[float], top_k: int, k: int = 60
    ) -> list[tuple[Chunk, float]]:
        if self.count() == 0:
            return []

        sparse_results = self.bm25_search(query=query, top_k=top_k * 2)
        dense_results = self.dense_search(
            query_embedding=query_embedding, top_k=top_k * 2
        )
        fused: dict[tuple[str, int], tuple[Chunk, float]] = {}

        for rank, (chunk, _) in enumerate(sparse_results, start=1):
            key = (self._normalize_path(chunk.file_path), chunk.chunk_idx)
            fused[key] = (chunk, 1 / (k + rank))
        for rank, (chunk, _) in enumerate(dense_results, start=1):
            key = (self._normalize_path(chunk.file_path), chunk.chunk_idx)
            previous = fused.get(key)
            score = 1 / (k + rank)
            fused[key] = (
                chunk,
                score + (previous[1] if previous else 0),
            )

        return sorted(fused.values(), key=lambda item: item[1], reverse=True)[:top_k]

    def count(self) -> int:
        with self._db_lock:
            return int(self._db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

    def remove_by_filepath(self, file_path: str) -> int:
        file_path_key = self._normalize_path(file_path)
        with self._db_lock:
            rows = self._db.execute(
                "SELECT point_id FROM chunks WHERE file_path_key = ?",
                (file_path_key,),
            ).fetchall()
        if not rows:
            return 0

        point_ids = [row["point_id"] for row in rows]
        if self._collection_exists():
            self.qdrant.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=point_ids),
                wait=True,
            )
        with self._db_lock:
            with self._db:
                self._db.execute(
                    "DELETE FROM chunks WHERE file_path_key = ?",
                    (file_path_key,),
                )
        return len(point_ids)

    def save_to_json(self, file_path: str) -> None:
        """Backward-compatible no-op: both new stores persist on every mutation."""
        logger.debug("[RAG] persistent stores already flushed; skip JSON save: %s", file_path)

    def migrate_json(self, file_path: str) -> int:
        if not os.path.exists(file_path):
            return 0
        with open(file_path, "r", encoding="utf-8") as file:
            chunks = [Chunk(**item) for item in json.load(file)]
        if not chunks:
            return 0
        self.add_chunks(chunks)
        logger.info("[RAG] migrated %d chunks from %s", len(chunks), file_path)
        return len(chunks)

    def close(self) -> None:
        with self._db_lock:
            self._db.close()
        close = getattr(self.qdrant, "close", None)
        if close:
            close()
