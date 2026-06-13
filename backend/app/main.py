from __future__ import annotations

from pathlib import Path

from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import config
from .audio_validation import ALLOWED_EXTENSIONS, ensure_child_path, store_validated_audio
from .transcription_jobs import (
    TranscriptionApiError,
    cancel_transcription_job,
    create_transcription_job,
    creation_response,
    ensure_job_dirs,
    load_job,
    public_job,
    run_demo_transcription_job,
)
from .transcript import DEMO_TRANSCRIPT


app = FastAPI(title="Piano Audio Transcriber API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


class TranscriptionCreateRequest(BaseModel):
    uploadId: str
    engine: str = "basic-pitch"
    options: dict[str, Any] = Field(default_factory=dict)


@app.exception_handler(TranscriptionApiError)
def transcription_api_error_handler(_: object, exc: TranscriptionApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.to_detail()})


@app.on_event("startup")
def ensure_data_dirs() -> None:
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    config.SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    ensure_job_dirs()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/transcripts/demo")
def demo_transcript() -> dict:
    return DEMO_TRANSCRIPT


@app.get("/api/samples/demo")
def demo_sample() -> FileResponse:
    sample = ensure_child_path(config.SAMPLE_DIR, config.SAMPLE_DIR / "demo.wav")
    if not sample.exists():
        raise HTTPException(status_code=404, detail="Demo sample has not been generated")
    return FileResponse(sample, media_type="audio/wav", filename="demo.wav")


@app.post("/api/uploads")
async def upload_audio(file: UploadFile) -> dict:
    stored = await store_validated_audio(file)
    transcript = {
        **DEMO_TRANSCRIPT,
        "source": {
            "kind": "uploaded",
            "filename": stored.original_filename,
            "duration": round(stored.duration, 3),
        },
    }
    return {
        "uploadId": stored.upload_id,
        "originalFilename": stored.original_filename,
        "duration": round(stored.duration, 3),
        "size": stored.size,
        "audioUrl": f"/api/uploads/{stored.upload_id}",
        "transcript": transcript,
    }


@app.get("/api/uploads/{upload_id}")
def uploaded_audio(upload_id: str) -> FileResponse:
    if not upload_id.isalnum() or len(upload_id) > 64:
        raise HTTPException(status_code=404, detail="Upload not found")

    matches: list[Path] = []
    for extension in ALLOWED_EXTENSIONS:
        candidate = ensure_child_path(config.UPLOAD_DIR, config.UPLOAD_DIR / f"{upload_id}{extension}")
        if candidate.exists():
            matches.append(candidate)

    if not matches:
        raise HTTPException(status_code=404, detail="Upload not found")

    path = matches[0]
    media_type = "audio/mpeg" if path.suffix == ".mp3" else "audio/wav"
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.post("/api/transcriptions")
def create_transcription(
    payload: TranscriptionCreateRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    job = create_transcription_job(payload.model_dump(), idempotency_key)
    if config.TRANSCRIPTION_AUTO_RUN and job.get("_created") and job["state"] == "queued":
        background_tasks.add_task(run_demo_transcription_job, job["jobId"])
    return JSONResponse(status_code=202, content=creation_response(job))


@app.get("/api/transcriptions/{job_id}")
def get_transcription(job_id: str) -> dict[str, Any]:
    return public_job(load_job(job_id))


@app.delete("/api/transcriptions/{job_id}")
def delete_transcription(job_id: str) -> dict[str, Any]:
    return public_job(cancel_transcription_job(job_id))
