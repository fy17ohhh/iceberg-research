from __future__ import annotations

import logging
import os
import re
import shutil

from pydantic import BaseModel
import pymupdf
from ..tools.tool_paper import PaperReaderTool
from ..mcp import MCPTool


logger = logging.getLogger(__name__)


class ConvertMetadata(BaseModel):
    output_path: str
    source_type: str
    arxiv_id: str | None = None
    title: str


def convert_to_markdown(
    src: str,
    output_dir: str,
    paper_tool: PaperReaderTool | None,
    pdf_reader_tool: MCPTool | None,
    custom_title: str | None = None,
) -> ConvertMetadata:
    """Convert an arXiv ID or local document into a Markdown file."""

    is_arxiv_id = re.match(r"^\d{4}\.\d{4,5}", src)
    if is_arxiv_id:
        source_type = "arxiv"
        title = custom_title or f"arXiv:{src}"
    else:
        ext = os.path.splitext(src)[-1].lower()
        title = custom_title or os.path.splitext(os.path.basename(src))[0]

        ext_to_type = {".pdf": "pdf", ".md": "markdown", ".markdown": "markdown", ".txt": "text"}
        source_type = ext_to_type.get(ext)

        if not source_type:
            raise ValueError(f"不支持的文件类型: {ext}")

    dest = os.path.join(output_dir, f"{title}.md")

    if source_type == "arxiv":
        if paper_tool is None:
            raise RuntimeError("Paper Search MCP is unavailable; arXiv ingestion is disabled")
        text = paper_tool.run_tool({"paper_id": src})
        with open(dest, "w", encoding="utf-8") as f:
            f.write(text)
    elif source_type == "pdf":
        try:
            text = extract_pdf_text(src)
        except RuntimeError as local_error:
            if pdf_reader_tool is None:
                raise
            logger.info(
                "PyMuPDF could not extract %s; attempting optional PDF Reader MCP: %s",
                os.path.basename(src),
                local_error,
            )
            try:
                text = pdf_reader_tool.run_tool({"sources": [{"path": os.path.abspath(src)}]})
            except Exception as exc:
                raise RuntimeError(
                    f"PyMuPDF extraction failed ({local_error}); PDF Reader MCP fallback also failed: {exc}"
                ) from exc
            if not text or not text.strip():
                raise RuntimeError(
                    "Neither PyMuPDF nor PDF Reader MCP could extract readable text from this PDF. "
                    "It may be password-protected or require OCR."
                )
        with open(dest, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        shutil.copy(src, dest)

    return ConvertMetadata(
        output_path=dest,
        source_type=source_type,
        arxiv_id=src if source_type == "arxiv" else None,
        title=title,
    )


def extract_pdf_text(src: str) -> str:
    """Extract a PDF text layer locally with PyMuPDF, the stable default parser."""
    try:
        document = pymupdf.open(src)
        if document.needs_pass:
            if not document.authenticate(""):
                raise RuntimeError("The PDF is password-protected and cannot be read")
        sections = [
            f"## Page {page_number}\n\n{page.get_text('text').strip()}"
            for page_number, page in enumerate(document, 1)
            if page.get_text("text").strip()
        ]
        document.close()
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Local PDF extraction failed: {exc}") from exc

    if not sections:
        raise RuntimeError(
            "No text layer was found in this PDF. It may be a scanned document; "
            "enable PDF Reader MCP for OCR fallback or run OCR first."
        )
    return "\n\n".join(sections) + "\n"
