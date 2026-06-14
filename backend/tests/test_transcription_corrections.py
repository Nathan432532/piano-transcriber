from __future__ import annotations

import json
import math
import wave
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.transcription_jobs import (
    TranscriptionAdapterContext,
    job_artifacts_dir,
    load_job,
    make_error,
    make_progress,
    run_transcription_job,
    transition_job,
)


client = TestClient(app)
non_raising_client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def isolated_runtime_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "JOB_DIR", tmp_path / "jobs")
    monkeypatch.setattr(config, "TRANSCRIPTION_AUTO_RUN", False)
    monkeypatch.setattr(config, "TRANSCRIPTION_RUNNER_MODE", "demo")
    monkeypatch.setattr(config, "BASIC_PITCH_MODEL_PATH", None)


def make_wav(path: Path, seconds: float = 1.0, rate: int = 8000) -> None:
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        for index in range(frames):
            sample = int(12000 * math.sin(2 * math.pi * 440 * index / rate))
            wav.writeframesraw(sample.to_bytes(2, "little", signed=True))


def create_upload(tmp_path: Path, seconds: float = 1.0) -> str:
    wav_path = tmp_path / "valid.wav"
    make_wav(wav_path, seconds=seconds)
    with wav_path.open("rb") as file:
        response = client.post("/api/uploads", files={"file": ("valid.wav", file, "audio/wav")})
    assert response.status_code == 200
    return response.json()["uploadId"]


def create_job(upload_id: str, key: str) -> dict[str, Any]:
    response = client.post(
        "/api/transcriptions",
        headers={"Idempotency-Key": key},
        json={"uploadId": upload_id, "engine": "basic-pitch", "options": {}},
    )
    assert response.status_code == 202
    return response.json()


class ArtifactAdapter:
    def __init__(self, duration: float = 1.0) -> None:
        self.duration = duration

    def load(self, context: TranscriptionAdapterContext) -> None:
        return None

    def transcribe(self, context: TranscriptionAdapterContext, report_progress) -> dict[str, Any]:
        return {
            "_transcript": {
                "version": "1.0",
                "source": {"kind": "uploaded", "filename": "valid.wav", "duration": self.duration},
                "notes": [
                    {
                        "pitch": 60,
                        "noteName": "C4",
                        "startTime": 0.0,
                        "endTime": 0.25,
                        "velocity": 80,
                        "confidence": 0.9,
                        "hand": "unknown",
                    }
                ],
            },
            "transcriptUrl": None,
            "exports": {},
            "noteCount": 1,
            "durationSeconds": self.duration,
        }


def create_succeeded_job_with_artifacts(tmp_path: Path, key: str = "correction-key", duration: float = 1.0) -> dict[str, Any]:
    upload_id = create_upload(tmp_path, seconds=duration)
    created = create_job(upload_id, key=key)
    result = run_transcription_job(created["jobId"], ArtifactAdapter(duration))
    assert result["state"] == "succeeded"
    return result


def valid_note(**overrides: Any) -> dict[str, Any]:
    note = {
        "pitch": 60,
        "noteName": "C4",
        "startTime": 0.1,
        "endTime": 0.5,
        "velocity": 90,
        "confidence": 0.95,
        "hand": "unknown",
    }
    note.update(overrides)
    return note


def put_correction(job_id: str, base_revision: int = 0, notes: list[dict[str, Any]] | None = None):
    body = {"baseRevision": base_revision, "notes": notes if notes is not None else [valid_note()]}
    return client.put(f"/api/transcriptions/{job_id}/corrections", json=body)


def put_correction_raw_json(job_id: str, body: str):
    return client.put(
        f"/api/transcriptions/{job_id}/corrections",
        content=body,
        headers={"content-type": "application/json"},
    )


def error_code(response) -> str:
    return response.json()["detail"]["code"]


def test_successful_correction_writes_corrected_artifacts_and_preserves_originals(tmp_path: Path) -> None:
    job = create_succeeded_job_with_artifacts(tmp_path)
    artifact_dir = job_artifacts_dir(job["jobId"])
    original_transcript = (artifact_dir / "transcript.json").read_bytes()
    original_midi = (artifact_dir / "transcription.mid").read_bytes()

    response = put_correction(job["jobId"])

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "revision": 1,
        "exports": {
            "transcript": f"/api/transcriptions/{job['jobId']}/artifacts/corrected-transcript.json",
            "midi": f"/api/transcriptions/{job['jobId']}/artifacts/corrected-transcription.mid",
        },
    }
    corrected_json = json.loads((artifact_dir / "corrected-transcript.json").read_text())
    assert corrected_json["notes"][0]["pitch"] == 60
    assert corrected_json["notes"][0]["noteName"] == "C4"
    assert (artifact_dir / "corrected-transcription.mid").read_bytes().startswith(b"MThd")
    assert (artifact_dir / "transcript.json").read_bytes() == original_transcript
    assert (artifact_dir / "transcription.mid").read_bytes() == original_midi

    persisted = load_job(job["jobId"])
    assert persisted["result"]["correction"]["revision"] == 1
    assert persisted["result"]["transcriptUrl"] == f"/api/transcriptions/{job['jobId']}/artifacts/transcript.json"
    assert persisted["result"]["exports"]["midi"] == f"/api/transcriptions/{job['jobId']}/artifacts/transcription.mid"


def test_second_valid_correction_replaces_only_corrected_artifacts_and_increments_revision(tmp_path: Path) -> None:
    job = create_succeeded_job_with_artifacts(tmp_path)
    artifact_dir = job_artifacts_dir(job["jobId"])
    original_transcript = (artifact_dir / "transcript.json").read_bytes()
    original_midi = (artifact_dir / "transcription.mid").read_bytes()

    first = put_correction(job["jobId"])
    first_json = (artifact_dir / "corrected-transcript.json").read_bytes()
    second = put_correction(job["jobId"], base_revision=1, notes=[valid_note(pitch=64, noteName="E4")])

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["revision"] == 2
    assert (artifact_dir / "transcript.json").read_bytes() == original_transcript
    assert (artifact_dir / "transcription.mid").read_bytes() == original_midi
    assert (artifact_dir / "corrected-transcript.json").read_bytes() != first_json
    assert json.loads((artifact_dir / "corrected-transcript.json").read_text())["notes"][0]["noteName"] == "E4"
    assert load_job(job["jobId"])["result"]["correction"]["revision"] == 2


def test_stale_revision_returns_409(tmp_path: Path) -> None:
    job = create_succeeded_job_with_artifacts(tmp_path)
    assert put_correction(job["jobId"]).status_code == 200

    stale = put_correction(job["jobId"], base_revision=0)

    assert stale.status_code == 409
    assert error_code(stale) == "CORRECTION_REVISION_CONFLICT"


@pytest.mark.parametrize("state", ["queued", "running", "failed", "cancelled"])
def test_non_succeeded_jobs_return_409(tmp_path: Path, state: str) -> None:
    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key=f"state-{state}")
    if state == "running":
        transition_job(created["jobId"], "running", progress=make_progress("validating", 5, "Validating upload"))
    if state == "failed":
        transition_job(
            created["jobId"],
            "failed",
            progress=make_progress("failed", 0, "Transcription failed"),
            error=make_error("UNKNOWN_ERROR"),
        )
    if state == "cancelled":
        transition_job(
            created["jobId"],
            "cancelled",
            progress=make_progress("cancelled", 0, "Transcription cancelled"),
            error=make_error("CANCELLED"),
        )

    response = put_correction(created["jobId"])

    assert response.status_code == 409
    assert error_code(response) == "JOB_NOT_SUCCEEDED"


@pytest.mark.parametrize(
    "note",
    [
        valid_note(pitch=20, noteName="G#0"),
        valid_note(velocity=0),
        valid_note(startTime=-0.1),
        valid_note(startTime=math.inf),
        valid_note(startTime=0.5, endTime=0.5),
        valid_note(endTime=1.1),
    ],
)
def test_invalid_notes_return_422(tmp_path: Path, note: dict[str, Any]) -> None:
    job = create_succeeded_job_with_artifacts(tmp_path, duration=1.0)

    if note["startTime"] == math.inf:
        response = put_correction_raw_json(
            job["jobId"],
            '{"baseRevision":0,"notes":[{"pitch":60,"noteName":"C4","startTime":Infinity,'
            '"endTime":0.5,"velocity":90,"confidence":0.95,"hand":"unknown"}]}',
        )
    else:
        response = put_correction(job["jobId"], notes=[note])

    assert response.status_code == 422
    assert error_code(response) == "INVALID_CORRECTION"


def test_unknown_job_returns_404() -> None:
    response = put_correction("00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert error_code(response) == "JOB_NOT_FOUND"


def test_corrected_artifact_downloads_are_safe_and_link_gated(tmp_path: Path) -> None:
    job = create_succeeded_job_with_artifacts(tmp_path)
    artifact_dir = job_artifacts_dir(job["jobId"])
    (artifact_dir / "corrected-transcript.json").write_text("{}\n")

    unlinked = client.get(f"/api/transcriptions/{job['jobId']}/artifacts/corrected-transcript.json")
    traversal = client.get(f"/api/transcriptions/{job['jobId']}/artifacts/../records/{job['jobId']}.json")

    assert unlinked.status_code == 404
    assert traversal.status_code == 404

    correction = put_correction(job["jobId"])
    assert correction.status_code == 200
    linked = client.get(correction.json()["exports"]["transcript"])
    assert linked.status_code == 200
    assert linked.json()["notes"][0]["pitch"] == 60


def test_write_failure_preserves_previous_revision_and_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = create_succeeded_job_with_artifacts(tmp_path)
    artifact_dir = job_artifacts_dir(job["jobId"])
    first = put_correction(job["jobId"])
    assert first.status_code == 200
    previous_json = (artifact_dir / "corrected-transcript.json").read_bytes()
    previous_midi = (artifact_dir / "corrected-transcription.mid").read_bytes()

    from app import transcription_jobs

    def failing_build_midi_file(notes: list[dict[str, Any]]) -> bytes:
        raise OSError("disk full")

    monkeypatch.setattr(transcription_jobs, "build_midi_file", failing_build_midi_file)

    response = non_raising_client.put(
        f"/api/transcriptions/{job['jobId']}/corrections",
        json={"baseRevision": 1, "notes": [valid_note(pitch=64, noteName="E4")]},
    )

    assert response.status_code == 500
    assert load_job(job["jobId"])["result"]["correction"]["revision"] == 1
    assert (artifact_dir / "corrected-transcript.json").read_bytes() == previous_json
    assert (artifact_dir / "corrected-transcription.mid").read_bytes() == previous_midi


def test_save_failure_after_prepare_preserves_previous_correction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    job = create_succeeded_job_with_artifacts(tmp_path)
    artifact_dir = job_artifacts_dir(job["jobId"])
    first = put_correction(job["jobId"])
    assert first.status_code == 200
    previous_job = load_job(job["jobId"])
    previous_correction = deepcopy(previous_job["result"]["correction"])
    previous_json = (artifact_dir / "corrected-transcript.json").read_bytes()
    previous_midi = (artifact_dir / "corrected-transcription.mid").read_bytes()

    from app import transcription_jobs

    original_save_job = transcription_jobs.save_job

    def failing_save_job(next_job: dict[str, Any]) -> dict[str, Any]:
        correction = ((next_job.get("result") or {}).get("correction") or {})
        if correction.get("revision") == 2:
            raise OSError("job store unavailable")
        return original_save_job(next_job)

    monkeypatch.setattr(transcription_jobs, "save_job", failing_save_job)

    response = non_raising_client.put(
        f"/api/transcriptions/{job['jobId']}/corrections",
        json={"baseRevision": 1, "notes": [valid_note(pitch=64, noteName="E4")]},
    )

    assert response.status_code == 500
    persisted = load_job(job["jobId"])
    assert persisted["result"]["correction"] == previous_correction
    assert persisted["result"]["correction"]["revision"] == 1
    assert (artifact_dir / "corrected-transcript.json").read_bytes() == previous_json
    assert (artifact_dir / "corrected-transcription.mid").read_bytes() == previous_midi
    assert not list(artifact_dir.glob("corrected-*.tmp"))
    assert not list(artifact_dir.glob("corrected-*.bak"))


def test_save_failure_after_prepare_leaves_no_first_corrected_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = create_succeeded_job_with_artifacts(tmp_path)
    artifact_dir = job_artifacts_dir(job["jobId"])
    previous_job = load_job(job["jobId"])

    from app import transcription_jobs

    original_save_job = transcription_jobs.save_job

    def failing_save_job(next_job: dict[str, Any]) -> dict[str, Any]:
        correction = ((next_job.get("result") or {}).get("correction") or {})
        if correction.get("revision") == 1:
            raise OSError("job store unavailable")
        return original_save_job(next_job)

    monkeypatch.setattr(transcription_jobs, "save_job", failing_save_job)

    response = non_raising_client.put(
        f"/api/transcriptions/{job['jobId']}/corrections",
        json={"baseRevision": 0, "notes": [valid_note(pitch=64, noteName="E4")]},
    )

    assert response.status_code == 500
    persisted = load_job(job["jobId"])
    assert persisted["result"] == previous_job["result"]
    assert "correction" not in persisted["result"]
    assert not (artifact_dir / "corrected-transcript.json").exists()
    assert not (artifact_dir / "corrected-transcription.mid").exists()
    assert not list(artifact_dir.glob("corrected-*.tmp"))
    assert not list(artifact_dir.glob("corrected-*.bak"))
