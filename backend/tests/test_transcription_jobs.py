from __future__ import annotations

import json
import math
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.transcription_jobs import (
    ALLOWED_TRANSITIONS,
    InvalidStateTransition,
    fail_transcription_job,
    idempotency_path,
    load_job,
    make_error,
    make_progress,
    run_demo_transcription_job,
    save_job,
    transition_job,
)


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_runtime_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "JOB_DIR", tmp_path / "jobs")
    monkeypatch.setattr(config, "TRANSCRIPTION_AUTO_RUN", False)


def make_wav(path: Path, seconds: float = 0.25, rate: int = 8000) -> None:
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        for index in range(frames):
            sample = int(12000 * math.sin(2 * math.pi * 440 * index / rate))
            wav.writeframesraw(sample.to_bytes(2, "little", signed=True))


def create_upload(tmp_path: Path) -> str:
    wav_path = tmp_path / "valid.wav"
    make_wav(wav_path)
    with wav_path.open("rb") as file:
        response = client.post("/api/uploads", files={"file": ("valid.wav", file, "audio/wav")})
    assert response.status_code == 200
    return response.json()["uploadId"]


def create_job(upload_id: str, key: str = "transcription-key") -> dict:
    response = client.post(
        "/api/transcriptions",
        headers={"Idempotency-Key": key},
        json={"uploadId": upload_id, "engine": "basic-pitch", "options": {"minPitch": 21, "maxPitch": 108}},
    )
    assert response.status_code == 202
    return response.json()


def error_code(response) -> str:
    return response.json()["detail"]["code"]


def test_create_and_run_deterministic_transcription_job(tmp_path: Path) -> None:
    upload_id = create_upload(tmp_path)
    created = create_job(upload_id)

    assert created["state"] == "queued"
    assert created["progress"]["phase"] == "queued"
    assert created["links"]["self"] == f"/api/transcriptions/{created['jobId']}"
    assert (config.JOB_DIR / "records" / f"{created['jobId']}.json").exists()

    run_demo_transcription_job(created["jobId"])
    response = client.get(f"/api/transcriptions/{created['jobId']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "succeeded"
    assert payload["progress"]["phase"] == "complete"
    assert payload["progress"]["percent"] == 100
    assert payload["error"] is None
    assert payload["result"]["transcriptUrl"] is None
    assert payload["result"]["exports"] == {}
    assert payload["result"]["noteCount"] == 8
    assert payload["result"]["durationSeconds"] == 0.25


def test_create_endpoint_schedules_default_demo_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "TRANSCRIPTION_AUTO_RUN", True)
    upload_id = create_upload(tmp_path)

    created = create_job(upload_id, key="auto-run-key")
    response = client.get(f"/api/transcriptions/{created['jobId']}")

    assert created["state"] == "queued"
    assert response.status_code == 200
    assert response.json()["state"] == "succeeded"


def test_idempotency_key_reuses_same_body_and_rejects_different_body(tmp_path: Path) -> None:
    upload_id = create_upload(tmp_path)
    body = {"uploadId": upload_id, "engine": "basic-pitch", "options": {"minPitch": 21}}
    headers = {"Idempotency-Key": "same-key"}

    first = client.post("/api/transcriptions", headers=headers, json=body)
    second = client.post("/api/transcriptions", headers=headers, json=body)
    conflict = client.post(
        "/api/transcriptions",
        headers=headers,
        json={"uploadId": upload_id, "engine": "basic-pitch", "options": {"minPitch": 22}},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["jobId"] == first.json()["jobId"]
    assert conflict.status_code == 409
    assert error_code(conflict) == "IDEMPOTENCY_CONFLICT"


def test_concurrent_idempotent_creates_return_one_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    upload_id = create_upload(tmp_path)
    body = {"uploadId": upload_id, "engine": "basic-pitch", "options": {"minPitch": 21}}
    headers = {"Idempotency-Key": "concurrent-key"}

    from app import transcription_jobs

    original_save_job = transcription_jobs.save_job

    def slow_save_job(job: dict) -> dict:
        time.sleep(0.02)
        return original_save_job(job)

    monkeypatch.setattr(transcription_jobs, "save_job", slow_save_job)

    def post_create() -> tuple[int, dict]:
        with TestClient(app) as thread_client:
            response = thread_client.post("/api/transcriptions", headers=headers, json=body)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: post_create(), range(8)))

    assert {status for status, _ in responses} == {202}
    job_ids = {payload["jobId"] for _, payload in responses}
    assert len(job_ids) == 1
    assert len(list((config.JOB_DIR / "records").glob("*.json"))) == 1


def test_idempotency_recovers_missing_or_incomplete_record(tmp_path: Path) -> None:
    upload_id = create_upload(tmp_path)
    body = {"uploadId": upload_id, "engine": "basic-pitch", "options": {"minPitch": 21}}
    headers = {"Idempotency-Key": "recovery-key"}

    first = client.post("/api/transcriptions", headers=headers, json=body)
    assert first.status_code == 202
    job_id = first.json()["jobId"]

    idem_path = idempotency_path("recovery-key")
    idem_path.unlink()

    missing_record = client.post("/api/transcriptions", headers=headers, json=body)
    assert missing_record.status_code == 202
    assert missing_record.json()["jobId"] == job_id
    assert json.loads(idem_path.read_text())["jobId"] == job_id

    idem_path.write_text(json.dumps({"idempotencyKey": "recovery-key"}) + "\n")
    incomplete_record = client.post("/api/transcriptions", headers=headers, json=body)
    conflict = client.post(
        "/api/transcriptions",
        headers=headers,
        json={"uploadId": upload_id, "engine": "basic-pitch", "options": {"minPitch": 22}},
    )

    assert incomplete_record.status_code == 202
    assert incomplete_record.json()["jobId"] == job_id
    assert conflict.status_code == 409
    assert error_code(conflict) == "IDEMPOTENCY_CONFLICT"


def test_invalid_upload_engine_options_and_job_errors(tmp_path: Path) -> None:
    upload_id = create_upload(tmp_path)

    missing_key = client.post(
        "/api/transcriptions",
        json={"uploadId": upload_id, "engine": "basic-pitch", "options": {}},
    )
    unsupported = client.post(
        "/api/transcriptions",
        headers={"Idempotency-Key": "unsupported"},
        json={"uploadId": upload_id, "engine": "other-engine", "options": {}},
    )
    invalid_options = client.post(
        "/api/transcriptions",
        headers={"Idempotency-Key": "invalid-options"},
        json={"uploadId": upload_id, "engine": "basic-pitch", "options": {"minPitch": 109}},
    )
    missing_upload = client.post(
        "/api/transcriptions",
        headers={"Idempotency-Key": "missing-upload"},
        json={"uploadId": "missinguploadid", "engine": "basic-pitch", "options": {}},
    )
    unknown_job = client.get("/api/transcriptions/00000000-0000-0000-0000-000000000000")

    assert missing_key.status_code == 400
    assert error_code(missing_key) == "INVALID_OPTIONS"
    assert unsupported.status_code == 400
    assert error_code(unsupported) == "UNSUPPORTED_ENGINE"
    assert invalid_options.status_code == 400
    assert error_code(invalid_options) == "INVALID_OPTIONS"
    assert missing_upload.status_code == 404
    assert error_code(missing_upload) == "UPLOAD_NOT_FOUND"
    assert unknown_job.status_code == 404
    assert error_code(unknown_job) == "JOB_NOT_FOUND"


def test_expired_job_returns_410(tmp_path: Path) -> None:
    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="expired-key")
    job = load_job(created["jobId"], check_expiry=False)
    job["expiresAt"] = "2000-01-01T00:00:00Z"
    save_job(job)

    response = client.get(f"/api/transcriptions/{created['jobId']}")

    assert response.status_code == 410
    assert error_code(response) == "JOB_EXPIRED"


def test_state_transition_contract_is_exact(tmp_path: Path) -> None:
    assert ALLOWED_TRANSITIONS == {
        "queued": {"running", "cancelled", "failed"},
        "running": {"succeeded", "failed", "cancelled"},
        "succeeded": set(),
        "failed": set(),
        "cancelled": set(),
    }

    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="transition-key")
    running = transition_job(created["jobId"], "running", progress=make_progress("validating", 5, "Validating upload"))
    succeeded = transition_job(
        created["jobId"],
        "succeeded",
        progress=make_progress("complete", 100, "Transcription ready"),
        result={"noteCount": 0},
    )

    assert running["state"] == "running"
    assert succeeded["state"] == "succeeded"
    with pytest.raises(InvalidStateTransition):
        transition_job(created["jobId"], "running")

    failed_job = create_job(upload_id, key="queued-failed-key")
    failed = transition_job(
        failed_job["jobId"],
        "failed",
        progress=make_progress("failed", 0, "Transcription failed"),
        error=make_error("UNKNOWN_ERROR"),
    )
    assert failed["state"] == "failed"


def test_failure_persists_terminal_error_contract(tmp_path: Path) -> None:
    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="failure-key")

    failed = fail_transcription_job(
        created["jobId"],
        "MODEL_LOAD_FAILED",
        percent=25,
        details={"engine": "basic-pitch"},
    )
    response = client.get(f"/api/transcriptions/{created['jobId']}")

    assert failed["state"] == "failed"
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "failed"
    assert payload["progress"]["phase"] == "failed"
    assert payload["progress"]["percent"] == 25
    assert payload["error"] == {
        "code": "MODEL_LOAD_FAILED",
        "message": "The transcription engine could not be started.",
        "retryable": True,
        "details": {"engine": "basic-pitch"},
    }
    assert payload["result"] is None


def test_cancels_non_terminal_job_and_rejects_terminal_delete(tmp_path: Path) -> None:
    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="cancel-key")

    cancelled = client.delete(f"/api/transcriptions/{created['jobId']}")
    second_delete = client.delete(f"/api/transcriptions/{created['jobId']}")

    assert cancelled.status_code == 200
    payload = cancelled.json()
    assert payload["state"] == "cancelled"
    assert payload["progress"]["phase"] == "cancelled"
    assert payload["error"]["code"] == "CANCELLED"

    assert second_delete.status_code == 409
    detail = second_delete.json()["detail"]
    assert detail["code"] == "JOB_TERMINAL"
    assert detail["details"]["job"]["state"] == "cancelled"


def test_job_record_is_json_runtime_artifact(tmp_path: Path) -> None:
    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="json-key")

    record = json.loads((config.JOB_DIR / "records" / f"{created['jobId']}.json").read_text())

    assert record["jobId"] == created["jobId"]
    assert record["state"] == "queued"
