import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from starlette.requests import Request

from iceberg_search.api.app import upload_file
from iceberg_search.api.schemas import IngestResult


class FakeLibraryManager:
    def __init__(self, data_dir):
        self.data_dir = str(data_dir)
        self.received = b""

    def ingest(self, src, overwrite):
        with open(src, "rb") as handle:
            self.received = handle.read()
        return IngestResult(title="uploaded", status="created")


def make_request(manager):
    app = SimpleNamespace(state=SimpleNamespace(library_manager=manager))
    return Request({"type": "http", "app": app})


def test_upload_file_streams_supported_document(tmp_path):
    manager = FakeLibraryManager(tmp_path)
    upload = UploadFile(filename="notes.md", file=BytesIO(b"# Research notes"))

    result = asyncio.run(upload_file(upload, make_request(manager)))

    assert result.title == "uploaded"
    assert manager.received == b"# Research notes"


def test_upload_file_rejects_unsupported_extension(tmp_path):
    manager = FakeLibraryManager(tmp_path)
    upload = UploadFile(filename="archive.zip", file=BytesIO(b"zip"))

    with pytest.raises(HTTPException) as error:
        asyncio.run(upload_file(upload, make_request(manager)))

    assert error.value.status_code == 415
