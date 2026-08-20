import pytest


qdrant_client = pytest.importorskip("qdrant_client")

from qdrant_client import QdrantClient

from iceberg_search.rag.document import Chunk
from iceberg_search.rag.vector_store import VectorStore


def make_store(tmp_path):
    return VectorStore(
        data_dir=str(tmp_path),
        collection_name="test_chunks",
        qdrant_client=QdrantClient(":memory:"),
    )


def test_persistent_sparse_and_dense_hybrid_search(tmp_path):
    store = make_store(tmp_path)
    chunks = [
        Chunk(
            chunk_idx=0,
            file_path=str(tmp_path / "ppo.md"),
            content="PPO 使用 clipped objective 限制策略更新幅度",
            embedding=[1.0, 0.0, 0.0],
        ),
        Chunk(
            chunk_idx=0,
            file_path=str(tmp_path / "rag.md"),
            content="RAG 使用向量数据库检索外部知识",
            embedding=[0.0, 1.0, 0.0],
        ),
    ]
    store.add_chunks(chunks)

    sparse = store.bm25_search("PPO 策略", top_k=2)
    dense = store.dense_search([1.0, 0.0, 0.0], top_k=2)
    hybrid = store.hybrid_search(
        query="PPO 策略",
        query_embedding=[1.0, 0.0, 0.0],
        top_k=2,
    )

    assert sparse[0][0].file_path.endswith("ppo.md")
    assert dense[0][0].file_path.endswith("ppo.md")
    assert hybrid[0][0].file_path.endswith("ppo.md")
    assert store.count() == 2
    store.close()


def test_remove_deletes_dense_and_sparse_records(tmp_path):
    store = make_store(tmp_path)
    file_path = str(tmp_path / "paper.md")
    store.add_chunks(
        [
            Chunk(
                chunk_idx=0,
                file_path=file_path,
                content="first chunk",
                embedding=[1.0, 0.0],
            ),
            Chunk(
                chunk_idx=1,
                file_path=file_path,
                content="second chunk",
                embedding=[0.9, 0.1],
            ),
        ]
    )

    assert store.remove_by_filepath(file_path) == 2
    assert store.count() == 0
    assert store.bm25_search("chunk", top_k=5) == []
    assert store.dense_search([1.0, 0.0], top_k=5) == []
    store.close()
