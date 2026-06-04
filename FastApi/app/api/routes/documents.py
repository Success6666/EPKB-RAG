import asyncio
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile

from app.core.config import get_settings
from app.schemas.documents import DocumentIngestJob, DocumentIngestResponse
from app.services.factory import get_ingestion_service

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/ingest", response_model=DocumentIngestResponse)
async def ingest_document(job: DocumentIngestJob) -> DocumentIngestResponse:
    if not job.file_path and not job.content:
        raise HTTPException(status_code=400, detail="Either filePath or content is required.")

    try:
        return await get_ingestion_service().ingest(job)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/internal", response_model=DocumentIngestResponse)
async def delete_document(
    job: DocumentIngestJob,
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> DocumentIngestResponse:
    settings = get_settings()
    if not settings.java_callback_token or x_internal_token != settings.java_callback_token:
        raise HTTPException(status_code=403, detail="Invalid internal token.")
    try:
        return await get_ingestion_service().delete_document(job)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/upload", response_model=DocumentIngestResponse)
async def upload_and_ingest(
    tenant_id: str = Form(..., alias="tenantId"),
    kb_id: str = Form(..., alias="kbId"),
    file: UploadFile = File(...),
    doc_id: str | None = Form(default=None, alias="docId"),
) -> DocumentIngestResponse:
    settings = get_settings()
    upload_dir = Path(settings.upload_dir) / tenant_id / kb_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = Path(file.filename or "uploaded.txt").name
    target = upload_dir / f"{uuid4().hex}_{safe_name}"
    with target.open("wb") as buffer:
        await asyncio.to_thread(shutil.copyfileobj, file.file, buffer)

    job = DocumentIngestJob(
        tenantId=tenant_id,
        kbId=kb_id,
        docId=doc_id,
        filePath=str(target),
        fileName=safe_name,
        sourceUri=str(target),
    )
    try:
        return await get_ingestion_service().ingest(job)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
