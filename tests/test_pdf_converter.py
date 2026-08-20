import pytest

from iceberg_search.library import converter


class FakePage:
    def __init__(self, text: str):
        self.text = text

    def get_text(self, mode: str) -> str:
        assert mode == "text"
        return self.text


class FakeDocument:
    needs_pass = False

    def __init__(self, pages: list[FakePage]):
        self.pages = pages
        self.closed = False

    def __iter__(self):
        return iter(self.pages)

    def close(self):
        self.closed = True


def test_pdf_conversion_uses_pymupdf_by_default(tmp_path, monkeypatch):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf for mocked reader")
    output_dir = tmp_path / "converted"
    output_dir.mkdir()

    fake_document = FakeDocument([FakePage("First page"), FakePage("Second page")])
    monkeypatch.setattr(converter.pymupdf, "open", lambda _: fake_document)

    metadata = converter.convert_to_markdown(
        src=str(source),
        output_dir=str(output_dir),
        paper_tool=None,
        pdf_reader_tool=None,
    )

    content = (output_dir / "paper.md").read_text(encoding="utf-8")
    assert metadata.source_type == "pdf"
    assert "## Page 1\n\nFirst page" in content
    assert "## Page 2\n\nSecond page" in content


def test_local_pdf_extraction_explains_scanned_documents(monkeypatch):
    monkeypatch.setattr(converter.pymupdf, "open", lambda _: FakeDocument([FakePage("")]))

    with pytest.raises(RuntimeError, match="No text layer"):
        converter.extract_pdf_text("scan.pdf")


def test_pdf_reader_mcp_is_only_used_after_pymupdf_fails(tmp_path, monkeypatch):
    source = tmp_path / "scan.pdf"
    source.write_bytes(b"fake pdf")
    output_dir = tmp_path / "converted"
    output_dir.mkdir()

    monkeypatch.setattr(converter.pymupdf, "open", lambda _: FakeDocument([FakePage("")]))

    class FakePdfReaderTool:
        def __init__(self):
            self.arguments = None

        def run_tool(self, arguments):
            self.arguments = arguments
            return "# OCR result\n\nReadable content"

    pdf_reader_tool = FakePdfReaderTool()
    converter.convert_to_markdown(
        src=str(source),
        output_dir=str(output_dir),
        paper_tool=None,
        pdf_reader_tool=pdf_reader_tool,
    )

    assert pdf_reader_tool.arguments == {"sources": [{"path": str(source)}]}
    assert "Readable content" in (output_dir / "scan.md").read_text(encoding="utf-8")
