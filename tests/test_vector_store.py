import types
import sys
from dataclasses import dataclass

import pytest


try:
    from qdrant_client import models
except ImportError:
    class _PointStruct:
        def __init__(self, id, vector, payload):
            self.id = id
            self.vector = vector
            self.payload = payload

    class _VectorParams:
        def __init__(self, size, distance, on_disk):
            self.size = size
            self.distance = distance
            self.on_disk = on_disk

    class _PointIdsList:
        def __init__(self, points):
            self.points = points

    class _Distance:
        COSINE = "Cosine"

    models = types.SimpleNamespace(
        PointStruct=_PointStruct,
        VectorParams=_VectorParams,
        PointIdsList=_PointIdsList,
        Distance=_Distance,
    )
    qdrant_module = types.ModuleType("qdrant_client")
    qdrant_module.QdrantClient = object
    qdrant_module.models = models
    sys.modules["qdrant_client"] = qdrant_module

from iceberg_search.rag.document import Chunk
import iceberg_search.rag.vector_store as vector_store_module
from iceberg_search.rag.vector_store import VectorStore

vector_store_module.models = models


@dataclass
class _CollectionVectors:
    size: int


class _FakeQdrant:
    """Small in-process stand-in for testing Qdrant/SQLite coordination."""

    def __init__(self):
        self.vector_size = None
        self.points = {}

    def collection_exists(self, collection_name):
        return self.vector_size is not None

    def create_collection(self, collection_name, vectors_config):
        self.vector_size = vectors_config.size

    def get_collection(self, collection_name):
        return types.SimpleNamespace(
            config=types.SimpleNamespace(
                params=types.SimpleNamespace(
                    vectors=_CollectionVectors(size=self.vector_size)
                )
            )
        )

    def upsert(self, collection_name, points, wait):
        for point in points:
            self.points[str(point.id)] = point

    def query_points(self, collection_name, query, limit, with_payload):
        def cosine(vector):
            dot = sum(a * b for a, b in zip(query, vector))
            q_norm = sum(value * value for value in query) ** 0.5
            v_norm = sum(value * value for value in vector) ** 0.5
            return dot / (q_norm * v_norm)

        scored = [
            types.SimpleNamespace(
                payload=point.payload,
                score=cosine(point.vector),
            )
            for point in self.points.values()
        ]
        scored.sort(key=lambda point: point.score, reverse=True)
        return types.SimpleNamespace(points=scored[:limit])

    def delete(self, collection_name, points_selector, wait):
        for point_id in points_selector.points:
            self.points.pop(str(point_id), None)


@pytest.fixture
def store(tmp_path):
    value = VectorStore(
        data_dir=str(tmp_path),
        qdrant_client=_FakeQdrant(),
    )
    yield value
    value.close()


def _chunks():
    return [
        Chunk(
            chunk_idx=0,
            file_path="docs/ppo.md",
            content="PPO 使用裁剪目标函数限制策略更新幅度",
            embedding=[1.0, 0.0, 0.0],
        ),
        Chunk(
            chunk_idx=1,
            file_path="docs/dpo.md",
            content="DPO 直接使用偏好数据训练语言模型",
            embedding=[0.0, 1.0, 0.0],
        ),
    ]


def test_persists_sparse_rows_and_queries_bm25(store):
    store.add_chunks(_chunks())

    results = store.bm25_search("PPO 裁剪", top_k=5)

    assert store.count() == 2
    assert results
    assert results[0][0].file_path == "docs/ppo.md"


def test_hybrid_search_fuses_dense_and_sparse_results(store):
    store.add_chunks(_chunks())

    results = store.hybrid_search(
        query="PPO 策略更新",
        query_embedding=[1.0, 0.0, 0.0],
        top_k=2,
    )

    assert results[0][0].file_path == "docs/ppo.md"
    assert results[0][1] > 0


def test_remove_deletes_qdrant_and_sqlite_entries(store):
    store.add_chunks(_chunks())

    removed = store.remove_by_filepath("docs/ppo.md")

    assert removed == 1
    assert store.count() == 1
    assert not store.bm25_search("PPO", top_k=5)
    assert len(store.qdrant.points) == 1


def test_rejects_embedding_dimension_change(store):
    store.add_chunks(_chunks())

    with pytest.raises(ValueError, match="向量维度"):
        store.add_chunks([
            Chunk(
                chunk_idx=0,
                file_path="docs/new.md",
                content="new",
                embedding=[1.0, 0.0],
            )
        ])
