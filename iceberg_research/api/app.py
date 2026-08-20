from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from iceberg_research.agents import Navigator
from iceberg_research.base import LLMClient, setup_logging
from iceberg_research.config import Config
from iceberg_research.library.library_manager import LibraryManager
from iceberg_research.orchestrator import Orchestrator
from .schemas import (
    NavigationRequest,
    NavigationResult,
    NavigationRefineRequest,
    NavigationRefineResult,
    ResearchRequest,
    SaveReportRequest,
    IngestRequest,
    IngestResult,
    PreferencesRequest,
)

logger = logging.getLogger(__name__)

PREVIEW_LENGTH = 150
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
SUPPORTED_UPLOAD_SUFFIXES = {".pdf", ".md", ".txt"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(enable_display=False)
    orchestrator = Orchestrator(Config())
    app.state.orchestrator = orchestrator
    app.state.navigator = Navigator(
        llm=orchestrator.llm_client,
        context_builder=orchestrator.context_builder,
        max_steps=orchestrator.config.max_steps,
        creative_temperature=orchestrator.config.llm.diver_temperature,
    )
    app.state.library_manager = orchestrator.create_library_manager()
    yield
    orchestrator.close()


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.post("/api/navigator/analyze")
def analyze_navigation(body: NavigationRequest, request: Request) -> NavigationResult:
    navigator: Navigator = request.app.state.navigator
    result = navigator.analyze(body.query)
    return result


@app.post("/api/navigator/refine")
def refine_navigation(
    body: NavigationRefineRequest, request: Request
) -> NavigationRefineResult:
    navigator: Navigator = request.app.state.navigator
    result = navigator.refine(raw_query=body.query, user_response=body.response)
    return NavigationRefineResult(brief=result)


@app.post("/api/research")
def research(body: ResearchRequest, request: Request):
    orchestrator: Orchestrator = request.app.state.orchestrator
    events = orchestrator.run_research(body.brief, session_id=body.session_id)

    return StreamingResponse(
        format_sse_events(events=events, llm_client=orchestrator.llm_client),
        media_type="text/event-stream",
    )


@app.get("/api/memory/preferences")
def get_memory_preferences(request: Request):
    orchestrator: Orchestrator = request.app.state.orchestrator
    return orchestrator.memory_manager.get_preferences()


@app.put("/api/memory/preferences")
def update_memory_preferences(body: PreferencesRequest, request: Request):
    orchestrator: Orchestrator = request.app.state.orchestrator
    return orchestrator.memory_manager.save_preferences(
        body.preferences, session_id=body.session_id
    )


@app.get("/api/memory")
def list_memories(request: Request, memory_type: str | None = None):
    orchestrator: Orchestrator = request.app.state.orchestrator
    return orchestrator.memory_manager.list_items(memory_type)


@app.delete("/api/memory/{memory_id}")
def delete_memory(memory_id: str, request: Request):
    orchestrator: Orchestrator = request.app.state.orchestrator
    deleted = orchestrator.memory_manager.delete(memory_id)
    return {"deleted": deleted, "id": memory_id}


@app.get("/api/library")
def list_docs(request: Request):
    library_manager: LibraryManager = request.app.state.library_manager
    result = library_manager.list_docs()
    return result


@app.post("/api/library/save-report")
def save_report(body: SaveReportRequest, request: Request) -> IngestResult:
    library_manager: LibraryManager = request.app.state.library_manager
    safe_name = body.title.replace("/", "_").replace("\\", "_")
    tmp_dir = tempfile.mkdtemp(dir=library_manager.data_dir)
    src = os.path.join(tmp_dir, f"{safe_name}.md")
    try:
        with open(src, "w", encoding="utf-8") as f:
            f.write(body.content)
        result = library_manager.ingest(
            src=src, custom_title=body.title, overwrite=True,
            save_original=False,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return result


@app.post("/api/library/upload")
async def upload_file(file: UploadFile, request: Request) -> IngestResult:
    library_manager: LibraryManager = request.app.state.library_manager
    filename = file.filename or "upload.pdf"
    safe_name = filename.replace("/", "_").replace("\\", "_")
    suffix = os.path.splitext(safe_name)[1].lower()
    if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail="Unsupported file type. Upload a PDF, Markdown, or text file.",
        )
    tmp_dir = tempfile.mkdtemp(dir=library_manager.data_dir)
    src = os.path.join(tmp_dir, safe_name)
    try:
        total_bytes = 0
        with open(src, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="File is larger than the 25 MB upload limit.",
                    )
                f.write(chunk)
        try:
            result = library_manager.ingest(src=src, overwrite=True)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Library upload failed for %s", safe_name)
            raise HTTPException(
                status_code=422,
                detail=f"The document could not be processed: {exc}",
            ) from exc
    finally:
        await file.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return result


@app.post("/api/library/ingest")
def ingest(body: IngestRequest, request: Request) -> IngestResult:
    library_manager: LibraryManager = request.app.state.library_manager
    result = library_manager.ingest(
        src=body.src,
        custom_title=body.custom_title,
        overwrite=body.overwrite,
    )
    return result


@app.get("/api/library/{title}/preview")
def preview_doc(title: str, request: Request):
    library_manager: LibraryManager = request.app.state.library_manager
    try:
        return library_manager.get_doc_preview(title)
    except (KeyError, FileNotFoundError) as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/library/{title}")
def delete_doc(title: str, request: Request):
    library_manager: LibraryManager = request.app.state.library_manager
    library_manager.delete_doc(title)
    return {"message": f"deleted: {title}"}


def format_sse_events(events, llm_client: LLMClient):
    try:
        for event in events:
            for node_name, output in event.items():
                if node_name == "navigator_node":
                    event_type = "navigator"
                    data = {
                        "sub_questions": [
                            {"label": sq.label, "question": sq.question}
                            for sq in output["sub_questions"]
                        ]
                    }

                elif node_name == "diver_node":
                    event_type = "diver"
                    item = output["pending_sonar_items"][0]
                    data = {
                        "question": item.sub_question,
                        "preview": item.research_note[:PREVIEW_LENGTH] + "...",
                        "tool_call_counts": output.get("tool_call_counts", {}),
                    }

                elif node_name == "sonar_node":
                    event_type = "sonar"
                    data = {
                        "round": output["refine_round"],
                        "sonar_summary": [
                            {
                                "question": r["question"],
                                "verdict": r["verdict"],
                                "failed": r["failed"],
                                "evidence": r.get("evidence", {}),
                            }
                            for r in output["sonar_summary"]
                        ],
                        "missing_dimensions": output.get("missing_dimensions", ""),
                    }

                elif node_name == "synthesizer_node":
                    event_type = "synthesizer"
                    data = {"report": output["final_report"]}

                else:
                    continue

                yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        stats_data = {
            "total_calls": llm_client.total_calls,
            "prompt_tokens": llm_client.total_prompt_tokens,
            "completion_tokens": llm_client.total_completion_tokens,
            "total_tokens": llm_client.total_prompt_tokens
            + llm_client.total_completion_tokens,
        }
        yield f"event: stats\ndata: {json.dumps(stats_data, ensure_ascii=False)}\n\n"

    except Exception as e:
        # error event
        yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
