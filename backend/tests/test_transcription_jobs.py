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
    TranscriptionAdapterContext,
    TranscriptionAdapterInferenceError,
    TranscriptionAdapterLoadError,
    InvalidStateTransition,
    cancel_transcription_job,
    fail_transcription_job,
    idempotency_path,
    load_job,
    make_error,
    make_progress,
    run_demo_transcription_job,
    run_transcription_job,
    save_job,
    transition_job,
)


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_runtime_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "JOB_DIR", tmp_path / "jobs")
    monkeypatch.setattr(config, "TRANSCRIPTION_AUTO_RUN", False)
    monkeypatch.setattr(config, "TRANSCRIPTION_RUNNER_MODE", "demo")
    monkeypatch.setattr(config, "BASIC_PITCH_MODEL_PATH", None)


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


def test_demo_adapter_preserves_existing_happy_path_result(tmp_path: Path) -> None:
    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="demo-adapter-key")

    result = run_transcription_job(created["jobId"])
    response = client.get(f"/api/transcriptions/{created['jobId']}")

    assert result["state"] == "succeeded"
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "succeeded"
    assert payload["result"] == {
        "transcriptUrl": None,
        "exports": {},
        "noteCount": 8,
        "durationSeconds": 0.25,
    }


def test_injected_adapter_can_publish_success_result(tmp_path: Path) -> None:
    class FakeAdapter:
        def load(self, context: TranscriptionAdapterContext) -> None:
            assert context.upload_path.exists()
            assert context.job["uploadId"] == upload_id

        def transcribe(self, context: TranscriptionAdapterContext, report_progress) -> dict:
            report_progress("inferencing", 80, "Fake inference")
            return {
                "transcriptUrl": None,
                "exports": {},
                "noteCount": 1,
                "durationSeconds": 0.123,
                "ignoredFutureField": "not public",
            }

    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="fake-success-key")

    run_transcription_job(created["jobId"], FakeAdapter())

    job = load_job(created["jobId"])
    assert job["state"] == "succeeded"
    assert job["progress"]["phase"] == "complete"
    assert job["result"] == {"transcriptUrl": None, "exports": {}, "noteCount": 1, "durationSeconds": 0.123}


@pytest.mark.parametrize(
    ("adapter_result", "key"),
    [
        (None, "invalid-none"),
        (["not", "a", "dict"], "invalid-list"),
        ({}, "invalid-empty"),
        ({"transcriptUrl": None, "exports": {}, "noteCount": 1}, "invalid-missing-duration"),
        ({"transcriptUrl": 123, "exports": {}, "noteCount": 1, "durationSeconds": 0.25}, "invalid-url-type"),
        ({"transcriptUrl": None, "exports": [], "noteCount": 1, "durationSeconds": 0.25}, "invalid-exports-type"),
        ({"transcriptUrl": None, "exports": {}, "noteCount": "1", "durationSeconds": 0.25}, "invalid-count-type"),
        ({"transcriptUrl": None, "exports": {}, "noteCount": -1, "durationSeconds": 0.25}, "invalid-negative-count"),
        ({"transcriptUrl": None, "exports": {}, "noteCount": 1, "durationSeconds": "0.25"}, "invalid-duration-type"),
        ({"transcriptUrl": None, "exports": {}, "noteCount": 1, "durationSeconds": -0.25}, "invalid-negative-duration"),
        ({"transcriptUrl": None, "exports": {}, "noteCount": 1, "durationSeconds": math.nan}, "invalid-nan-duration"),
        ({"transcriptUrl": None, "exports": {}, "noteCount": 1, "durationSeconds": math.inf}, "invalid-inf-duration"),
    ],
)
def test_invalid_adapter_result_fails_without_publishing_result(tmp_path: Path, adapter_result, key: str) -> None:
    class InvalidResultAdapter:
        def load(self, context: TranscriptionAdapterContext) -> None:
            return None

        def transcribe(self, context: TranscriptionAdapterContext, report_progress):
            report_progress("inferencing", 80, "Fake inference")
            return adapter_result

    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key=key)

    result = run_transcription_job(created["jobId"], InvalidResultAdapter())
    job = load_job(created["jobId"])

    assert result["state"] == "failed"
    assert result["error"]["code"] == "MODEL_INFERENCE_FAILED"
    assert job["state"] == "failed"
    assert job["error"]["code"] == "MODEL_INFERENCE_FAILED"
    assert job["result"] is None


def test_adapter_load_error_maps_to_model_load_failed(tmp_path: Path) -> None:
    class LoadFailingAdapter:
        def load(self, context: TranscriptionAdapterContext) -> None:
            raise TranscriptionAdapterLoadError("load failed")

        def transcribe(self, context: TranscriptionAdapterContext, report_progress) -> dict:
            raise AssertionError("transcribe should not run")

    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="load-failure-key")

    result = run_transcription_job(created["jobId"], LoadFailingAdapter())

    assert result["state"] == "failed"
    assert result["error"]["code"] == "MODEL_LOAD_FAILED"
    assert result["progress"]["phase"] == "failed"
    assert result["progress"]["percent"] == 25


def test_adapter_inference_error_maps_to_model_inference_failed(tmp_path: Path) -> None:
    class InferenceFailingAdapter:
        def load(self, context: TranscriptionAdapterContext) -> None:
            return None

        def transcribe(self, context: TranscriptionAdapterContext, report_progress) -> dict:
            report_progress("inferencing", 55, "Fake inference")
            raise TranscriptionAdapterInferenceError("inference failed")

    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="inference-failure-key")

    result = run_transcription_job(created["jobId"], InferenceFailingAdapter())

    assert result["state"] == "failed"
    assert result["error"]["code"] == "MODEL_INFERENCE_FAILED"
    assert result["progress"]["phase"] == "failed"
    assert result["progress"]["percent"] == 55


def test_unexpected_adapter_error_maps_to_unknown_error(tmp_path: Path) -> None:
    class UnexpectedFailingAdapter:
        def load(self, context: TranscriptionAdapterContext) -> None:
            return None

        def transcribe(self, context: TranscriptionAdapterContext, report_progress) -> dict:
            raise RuntimeError("unexpected failure")

    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="unknown-failure-key")

    result = run_transcription_job(created["jobId"], UnexpectedFailingAdapter())

    assert result["state"] == "failed"
    assert result["error"]["code"] == "UNKNOWN_ERROR"


def test_cancellation_before_adapter_call_prevents_execution_and_publication(tmp_path: Path) -> None:
    class RecordingAdapter:
        calls = 0

        def load(self, context: TranscriptionAdapterContext) -> None:
            self.calls += 1

        def transcribe(self, context: TranscriptionAdapterContext, report_progress) -> dict:
            self.calls += 1
            return {"transcriptUrl": None, "exports": {}, "noteCount": 99, "durationSeconds": 1.0}

    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="cancel-before-key")
    adapter = RecordingAdapter()

    cancel_transcription_job(created["jobId"])
    result = run_transcription_job(created["jobId"], adapter)

    assert result["state"] == "cancelled"
    assert adapter.calls == 0
    assert load_job(created["jobId"])["result"] is None


def test_cancellation_after_adapter_execution_prevents_succeeded_publication(tmp_path: Path) -> None:
    class CancellingAdapter:
        def load(self, context: TranscriptionAdapterContext) -> None:
            return None

        def transcribe(self, context: TranscriptionAdapterContext, report_progress) -> dict:
            report_progress("inferencing", 85, "Fake inference")
            cancel_transcription_job(context.job["jobId"])
            return {"transcriptUrl": None, "exports": {}, "noteCount": 99, "durationSeconds": 1.0}

    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="cancel-after-key")

    result = run_transcription_job(created["jobId"], CancellingAdapter())

    assert result["state"] == "cancelled"
    job = load_job(created["jobId"])
    assert job["state"] == "cancelled"
    assert job["result"] is None


def test_invalid_adapter_result_after_cancellation_publishes_no_succeeded_result(tmp_path: Path) -> None:
    class CancellingInvalidAdapter:
        def load(self, context: TranscriptionAdapterContext) -> None:
            return None

        def transcribe(self, context: TranscriptionAdapterContext, report_progress) -> dict:
            report_progress("inferencing", 85, "Fake inference")
            cancel_transcription_job(context.job["jobId"])
            return {}

    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="cancel-invalid-after-key")

    result = run_transcription_job(created["jobId"], CancellingInvalidAdapter())
    job = load_job(created["jobId"])

    assert result["state"] == "cancelled"
    assert job["state"] == "cancelled"
    assert job["error"]["code"] == "CANCELLED"
    assert job["result"] is None


def test_create_endpoint_schedules_default_demo_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "TRANSCRIPTION_AUTO_RUN", True)
    upload_id = create_upload(tmp_path)

    created = create_job(upload_id, key="auto-run-key")
    response = client.get(f"/api/transcriptions/{created['jobId']}")

    assert created["state"] == "queued"
    assert response.status_code == 200
    assert response.json()["state"] == "succeeded"


def test_idempotent_reuse_of_queued_job_does_not_schedule_second_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main as main_module

    monkeypatch.setattr(config, "TRANSCRIPTION_AUTO_RUN", True)
    upload_id = create_upload(tmp_path)
    calls: list[str] = []

    def fake_runner(job_id: str) -> dict:
        calls.append(job_id)
        return load_job(job_id)

    monkeypatch.setattr(main_module, "run_transcription_job", fake_runner)
    headers = {"Idempotency-Key": "queued-reuse-key"}
    body = {"uploadId": upload_id, "engine": "basic-pitch", "options": {"minPitch": 21}}

    first = client.post("/api/transcriptions", headers=headers, json=body)
    second = client.post("/api/transcriptions", headers=headers, json=body)

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json() == first.json()
    assert calls == [first.json()["jobId"]]
    assert load_job(first.json()["jobId"])["state"] == "queued"


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


def test_concurrent_runners_for_same_job_only_start_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import transcription_jobs

    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="runner-race-key")
    progress_updates: list[str] = []
    original_update = transcription_jobs.update_running_progress

    def slow_update(job_id: str, phase: str, percent: int, message: str) -> dict:
        progress_updates.append(phase)
        time.sleep(0.01)
        return original_update(job_id, phase, percent, message)

    monkeypatch.setattr(transcription_jobs, "update_running_progress", slow_update)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run_demo_transcription_job(created["jobId"]), range(2)))

    assert len([job for job in results if job["state"] == "succeeded"]) == 1
    assert len(progress_updates) == 5
    assert load_job(created["jobId"])["state"] == "succeeded"


def test_concurrent_adapter_runners_for_same_job_only_execute_once(tmp_path: Path) -> None:
    class SlowAdapter:
        def load(self, context: TranscriptionAdapterContext) -> None:
            return None

        def transcribe(self, context: TranscriptionAdapterContext, report_progress) -> dict:
            calls.append(context.job["jobId"])
            time.sleep(0.02)
            report_progress("inferencing", 75, "Fake inference")
            return {"transcriptUrl": None, "exports": {}, "noteCount": 2, "durationSeconds": 0.25}

    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="adapter-runner-race-key")
    calls: list[str] = []

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run_transcription_job(created["jobId"], SlowAdapter()), range(2)))

    assert calls == [created["jobId"]]
    assert len([job for job in results if job["state"] == "succeeded"]) == 1
    assert load_job(created["jobId"])["state"] == "succeeded"


def test_runner_stops_safely_for_non_queued_jobs(tmp_path: Path) -> None:
    upload_id = create_upload(tmp_path)

    cancelled = create_job(upload_id, key="runner-cancelled-key")
    transition_job(
        cancelled["jobId"],
        "cancelled",
        progress=make_progress("cancelled", 0, "Transcription cancelled"),
        error=make_error("CANCELLED"),
    )

    failed = create_job(upload_id, key="runner-failed-key")
    transition_job(
        failed["jobId"],
        "failed",
        progress=make_progress("failed", 0, "Transcription failed"),
        error=make_error("UNKNOWN_ERROR"),
    )

    succeeded = create_job(upload_id, key="runner-succeeded-key")
    transition_job(succeeded["jobId"], "running", progress=make_progress("validating", 5, "Validating upload"))
    transition_job(
        succeeded["jobId"],
        "succeeded",
        progress=make_progress("complete", 100, "Transcription ready"),
        result={"noteCount": 0},
    )

    assert run_demo_transcription_job(cancelled["jobId"])["state"] == "cancelled"
    assert run_demo_transcription_job(failed["jobId"])["state"] == "failed"
    assert run_demo_transcription_job(succeeded["jobId"])["state"] == "succeeded"


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
