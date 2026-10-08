import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import config
from app.basic_pitch_adapter import BasicPitchTranscriptionAdapter
from app.bytedance_adapter import ByteDanceTranscriptionAdapter, normalize_bytedance_notes
from app.main import app
from app.transcription_jobs import (
    TranscriptionAdapterLoadError, TranscriptionAdapterInferenceError,
    DemoTranscriptionAdapter, create_transcription_adapter, run_transcription_job,
)


def output(event=None):
    return {"est_note_events": [event or {"midi_note": 60, "onset_time": 0.1, "offset_time": 0.8, "velocity": 83}],
            "output_dict": {"reg_onset_output": np.full((100, 88), 0.75)}}


def test_normalizes_model_velocity_score_and_padding():
    result = output()
    result["est_note_events"].append({"midi_note": 62, "onset_time": 1.1, "offset_time": 1.5, "velocity": 70})
    notes = normalize_bytedance_notes(result, 0.5)
    assert notes == [{"pitch": 60, "noteName": "C4", "startTime": 0.1, "endTime": 0.5,
                      "velocity": 83, "confidence": 0.75, "hand": "unknown"}]


@pytest.mark.parametrize("field,value", [("midi_note", 20), ("midi_note", True), ("velocity", 0),
                                         ("onset_time", -0.1), ("offset_time", math.nan), ("offset_time", 0.05)])
def test_rejects_malformed_events(field, value):
    result = output()
    result["est_note_events"][0][field] = value
    with pytest.raises(ValueError):
        normalize_bytedance_notes(result, 1)


def test_empty_model_output_is_valid():
    result = output()
    result["est_note_events"] = []
    assert normalize_bytedance_notes(result, 1) == []


def test_engine_selection_uses_job_engine(monkeypatch):
    monkeypatch.setattr(config, "TRANSCRIPTION_RUNNER_MODE", "bytedance")
    assert isinstance(create_transcription_adapter(), ByteDanceTranscriptionAdapter)
    assert isinstance(create_transcription_adapter("basic-pitch"), BasicPitchTranscriptionAdapter)
    monkeypatch.setattr(config, "TRANSCRIPTION_RUNNER_MODE", "basic-pitch")
    assert isinstance(create_transcription_adapter("bytedance"), ByteDanceTranscriptionAdapter)
    monkeypatch.setattr(config, "TRANSCRIPTION_RUNNER_MODE", "demo")
    assert isinstance(create_transcription_adapter("basic-pitch"), DemoTranscriptionAdapter)
    assert isinstance(create_transcription_adapter("bytedance"), ByteDanceTranscriptionAdapter)


def test_missing_checkpoint_reports_model_load_error(tmp_path):
    with pytest.raises(TranscriptionAdapterLoadError):
        ByteDanceTranscriptionAdapter(tmp_path / "missing.pth").load(None)


def test_inference_exception_is_translated():
    class BrokenBinding:
        def predict(self, path):
            raise RuntimeError("decoder failure")
    with pytest.raises(TranscriptionAdapterInferenceError):
        ByteDanceTranscriptionAdapter(None, BrokenBinding()).transcribe(
            SimpleNamespace(upload_path=Path("audio.wav")), lambda *args: None)


def test_bytedance_reuses_artifacts_and_revision_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "JOB_DIR", tmp_path / "jobs")
    monkeypatch.setattr(config, "TRANSCRIPTION_AUTO_RUN", False)
    class Binding:
        def predict(self, path):
            return output(), 1.0
    class Adapter(ByteDanceTranscriptionAdapter):
        def load(self, context):
            pass
    with TestClient(app) as client:
        audio = Path(__file__).resolve().parents[1] / "data/samples/demo.wav"
        with audio.open("rb") as file:
            upload = client.post("/api/uploads", files={"file": ("piano.wav", file, "audio/wav")})
        assert upload.status_code == 200
        created = client.post("/api/transcriptions", headers={"Idempotency-Key": "bytedance"},
                              json={"uploadId": upload.json()["uploadId"], "engine": "bytedance", "options": {}})
        assert created.status_code == 202
        job_id = created.json()["jobId"]
        job = run_transcription_job(job_id, Adapter(None, Binding()))
        assert job["state"] == "succeeded" and job["engine"] == "bytedance"
        original = client.get(job["result"]["transcriptUrl"]).json()
        assert client.get(job["result"]["exports"]["midi"]).content.startswith(b"MThd")
        notes = original["notes"]
        notes[0]["pitch"] = 61
        for note in notes:
            note.pop("noteName")
        saved = client.put(f"/api/transcriptions/{job_id}/corrections", json={"baseRevision": 0, "notes": notes})
        assert saved.status_code == 200
        recovered = client.get(f"/api/transcriptions/{job_id}").json()
        correction = recovered["result"]["correction"]
        assert correction["revision"] == 1
        assert client.get(correction["exports"]["transcript"]).json()["notes"][0]["pitch"] == 61
        assert client.get(correction["exports"]["midi"]).content.startswith(b"MThd")
