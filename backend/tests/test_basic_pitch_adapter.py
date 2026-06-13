from __future__ import annotations

import importlib
import math
import sys
from types import ModuleType
import wave
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import config
from app.basic_pitch_adapter import BasicPitchProductionBinding, BasicPitchTranscriptionAdapter, normalize_basic_pitch_notes
from app.main import app
from app.transcription_jobs import (
    DemoTranscriptionAdapter,
    TranscriptionAdapterContext,
    cancel_transcription_job,
    create_transcription_adapter,
    load_job,
    run_transcription_job,
    update_running_progress,
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


def create_job(upload_id: str, key: str = "basic-pitch-key") -> dict[str, Any]:
    response = client.post(
        "/api/transcriptions",
        headers={"Idempotency-Key": key},
        json={"uploadId": upload_id, "engine": "basic-pitch", "options": {"minPitch": 21}},
    )
    assert response.status_code == 202
    return response.json()


DEFAULT_OUTPUT = object()


class FakeBinding:
    def __init__(
        self,
        output: Any = DEFAULT_OUTPUT,
        *,
        load_error: Exception | None = None,
        predict_error: Exception | None = None,
    ):
        self.output = {"notes": [], "durationSeconds": 0.25} if output is DEFAULT_OUTPUT else output
        self.load_error = load_error
        self.predict_error = predict_error
        self.loaded_path: Path | None = None
        self.predict_calls = 0

    def load_model(self, model_path: Path) -> None:
        if self.load_error is not None:
            raise self.load_error
        self.loaded_path = model_path

    def predict(self, audio_path: Path) -> Any:
        self.predict_calls += 1
        if self.predict_error is not None:
            raise self.predict_error
        return self.output


def model_file(tmp_path: Path) -> Path:
    path = tmp_path / "basic_pitch_model.pb"
    path.write_bytes(b"placeholder")
    return path


def install_fake_basic_pitch_module(monkeypatch: pytest.MonkeyPatch, inference: ModuleType) -> None:
    package = ModuleType("basic_pitch")
    package.__path__ = []
    package.inference = inference
    monkeypatch.setitem(sys.modules, "basic_pitch", package)
    monkeypatch.setitem(sys.modules, "basic_pitch.inference", inference)


def test_basic_pitch_adapter_module_does_not_import_basic_pitch_package() -> None:
    sys.modules.pop("basic_pitch", None)
    sys.modules.pop("basic_pitch.inference", None)

    importlib.import_module("app.basic_pitch_adapter")

    assert "basic_pitch" not in sys.modules
    assert "basic_pitch.inference" not in sys.modules


def test_adapter_factory_selects_demo_or_basic_pitch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "TRANSCRIPTION_RUNNER_MODE", "demo")
    assert isinstance(create_transcription_adapter(), DemoTranscriptionAdapter)

    monkeypatch.setattr(config, "TRANSCRIPTION_RUNNER_MODE", "basic-pitch")
    monkeypatch.setattr(config, "BASIC_PITCH_MODEL_PATH", str(model_file(tmp_path)))
    assert isinstance(create_transcription_adapter(), BasicPitchTranscriptionAdapter)


def test_unknown_runner_mode_fails_job_without_demo_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="unknown-mode-key")
    monkeypatch.setattr(config, "TRANSCRIPTION_RUNNER_MODE", "surprise")

    result = run_transcription_job(created["jobId"])

    assert result["state"] == "failed"
    assert result["error"]["code"] == "MODEL_LOAD_FAILED"
    assert result["error"]["details"] == {"engine": "basic-pitch"}
    assert load_job(created["jobId"])["result"] is None


@pytest.mark.parametrize("configured_path", [None, "", "   ", "/missing/basic-pitch-model.pb"])
def test_basic_pitch_missing_model_path_or_file_maps_to_model_load_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    configured_path: str | None,
) -> None:
    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key=f"missing-model-{configured_path!r}")
    monkeypatch.setattr(config, "TRANSCRIPTION_RUNNER_MODE", "basic-pitch")
    monkeypatch.setattr(config, "BASIC_PITCH_MODEL_PATH", configured_path)

    result = run_transcription_job(created["jobId"])

    assert result["state"] == "failed"
    assert result["error"]["code"] == "MODEL_LOAD_FAILED"
    assert result["error"]["details"] == {"engine": "basic-pitch"}
    assert "missing" not in str(result["error"])


def test_basic_pitch_package_import_error_maps_to_model_load_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="import-failure-key")
    monkeypatch.setattr(config, "TRANSCRIPTION_RUNNER_MODE", "basic-pitch")
    monkeypatch.setattr(config, "BASIC_PITCH_MODEL_PATH", str(model_file(tmp_path)))

    original_import_module = importlib.import_module

    def fake_import_module(name: str, package: str | None = None):
        if name == "basic_pitch.inference":
            raise ImportError("no basic pitch")
        return original_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    result = run_transcription_job(created["jobId"])

    assert result["state"] == "failed"
    assert result["error"]["code"] == "MODEL_LOAD_FAILED"
    assert result["error"]["details"] == {"engine": "basic-pitch"}


def test_basic_pitch_production_model_init_error_maps_to_persisted_model_load_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="production-model-init-failure-key")
    monkeypatch.setattr(config, "TRANSCRIPTION_RUNNER_MODE", "basic-pitch")
    monkeypatch.setattr(config, "BASIC_PITCH_MODEL_PATH", str(model_file(tmp_path)))

    inference = ModuleType("basic_pitch.inference")

    class FailingModel:
        def __init__(self, model_path: str) -> None:
            raise RuntimeError(f"bad model at {model_path}")

    def predict(audio_path: str, *, model_or_model_path: Any) -> Any:
        raise AssertionError("predict should not run when model initialization fails")

    inference.Model = FailingModel
    inference.predict = predict
    install_fake_basic_pitch_module(monkeypatch, inference)

    result = run_transcription_job(created["jobId"])
    persisted = load_job(created["jobId"])

    assert result["state"] == "failed"
    assert result["error"] == {
        "code": "MODEL_LOAD_FAILED",
        "message": "The transcription engine could not be started.",
        "retryable": True,
        "details": {"engine": "basic-pitch"},
    }
    assert result["progress"]["phase"] == "failed"
    assert result["progress"]["percent"] == 25
    assert persisted["state"] == "failed"
    assert persisted["error"] == result["error"]
    assert persisted["result"] is None
    assert str(tmp_path) not in str(result["error"])
    assert "Traceback" not in str(result["error"])


def test_basic_pitch_production_predict_receives_loaded_model_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = model_file(tmp_path)
    audio_path = tmp_path / "audio.wav"
    make_wav(audio_path)
    loaded_models: list[Any] = []
    received_models: list[Any] = []
    received_audio_paths: list[str] = []
    inference = ModuleType("basic_pitch.inference")

    class FakeModel:
        def __init__(self, model_path_arg: str) -> None:
            self.model_path_arg = model_path_arg
            loaded_models.append(self)

    def predict(audio_path_arg: str, *, model_or_model_path: Any) -> Any:
        received_audio_paths.append(audio_path_arg)
        received_models.append(model_or_model_path)
        return {"notes": [], "durationSeconds": 0.25}

    inference.Model = FakeModel
    inference.predict = predict
    install_fake_basic_pitch_module(monkeypatch, inference)

    binding = BasicPitchProductionBinding()
    binding.load_model(model_path)
    output = binding.predict(audio_path)

    assert output == {"notes": [], "durationSeconds": 0.25}
    assert len(loaded_models) == 1
    assert loaded_models[0].model_path_arg == str(model_path)
    assert received_audio_paths == [str(audio_path)]
    assert received_models == [loaded_models[0]]
    assert received_models[0] != str(model_path)


def test_basic_pitch_binding_load_error_maps_to_model_load_failed(tmp_path: Path) -> None:
    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="binding-load-failure-key")
    adapter = BasicPitchTranscriptionAdapter(
        model_file(tmp_path),
        binding=FakeBinding(load_error=RuntimeError("bad model")),
    )

    result = run_transcription_job(created["jobId"], adapter)

    assert result["state"] == "failed"
    assert result["error"]["code"] == "MODEL_LOAD_FAILED"


def test_basic_pitch_success_returns_public_result_only_and_uses_binding_duration(tmp_path: Path) -> None:
    output = {
        "durationSeconds": 3.5,
        "notes": [
            {"pitch": 64, "startTime": 0.5, "endTime": 1.0, "confidence": 0.75, "velocity": 90},
            (0.1, 0.3, 60, 0.5),
        ],
    }
    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="basic-success-key")

    result = run_transcription_job(
        created["jobId"],
        BasicPitchTranscriptionAdapter(model_file(tmp_path), binding=FakeBinding(output)),
    )

    assert result["state"] == "succeeded"
    assert result["result"] == {
        "transcriptUrl": None,
        "exports": {},
        "noteCount": 2,
        "durationSeconds": 3.5,
    }
    assert "notes" not in result["result"]


def test_basic_pitch_uses_audio_duration_when_binding_duration_is_absent(tmp_path: Path) -> None:
    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="fallback-duration-key")

    result = run_transcription_job(
        created["jobId"],
        BasicPitchTranscriptionAdapter(model_file(tmp_path), binding=FakeBinding({"notes": []})),
    )

    assert result["state"] == "succeeded"
    assert result["result"]["durationSeconds"] == 0.25


def test_basic_pitch_note_normalization_is_deterministic_and_internal() -> None:
    notes = normalize_basic_pitch_notes(
        [
            {"pitch": 62, "startTime": 0.5, "endTime": 0.7, "confidence": 0.5},
            (0.1, 0.4, 64, 0.75),
            {"pitch": 60, "startTime": 0.1, "endTime": 0.3, "confidence": 1.0, "velocity": 127},
        ]
    )

    assert notes == [
        {
            "pitch": 60,
            "noteName": "C4",
            "startTime": 0.1,
            "endTime": 0.3,
            "velocity": 127,
            "confidence": 1.0,
            "hand": "unknown",
        },
        {
            "pitch": 64,
            "noteName": "E4",
            "startTime": 0.1,
            "endTime": 0.4,
            "velocity": 95,
            "confidence": 0.75,
            "hand": "unknown",
        },
        {
            "pitch": 62,
            "noteName": "D4",
            "startTime": 0.5,
            "endTime": 0.7,
            "velocity": 64,
            "confidence": 0.5,
            "hand": "unknown",
        },
    ]


@pytest.mark.parametrize(
    "output",
    [
        None,
        {},
        {"notes": [{"pitch": 60, "startTime": 0, "endTime": 1, "confidence": 2}]},
        {"notes": [{"pitch": 60, "startTime": -0.1, "endTime": 1, "confidence": 0.5}]},
        {"notes": [{"pitch": 60, "startTime": 1, "endTime": 1, "confidence": 0.5}]},
        {"notes": [{"pitch": 60.5, "startTime": 0, "endTime": 1, "confidence": 0.5}]},
        {"notes": [{"pitch": 60, "startTime": 0, "endTime": 1, "confidence": 0.5, "velocity": 128}]},
        {"notes": [], "durationSeconds": math.inf},
    ],
)
def test_invalid_basic_pitch_output_or_notes_maps_to_model_inference_failed(tmp_path: Path, output: Any) -> None:
    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key=f"invalid-output-{len(str(output))}")

    result = run_transcription_job(
        created["jobId"],
        BasicPitchTranscriptionAdapter(model_file(tmp_path), binding=FakeBinding(output)),
    )

    assert result["state"] == "failed"
    assert result["error"]["code"] == "MODEL_INFERENCE_FAILED"
    assert result["error"]["details"] == {"engine": "basic-pitch"}
    assert load_job(created["jobId"])["result"] is None


def test_basic_pitch_predict_error_maps_to_model_inference_failed(tmp_path: Path) -> None:
    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="predict-failure-key")

    result = run_transcription_job(
        created["jobId"],
        BasicPitchTranscriptionAdapter(
            model_file(tmp_path),
            binding=FakeBinding(predict_error=RuntimeError("predict failed")),
        ),
    )

    assert result["state"] == "failed"
    assert result["error"]["code"] == "MODEL_INFERENCE_FAILED"


def test_cancellation_before_adapter_selection_skips_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import transcription_jobs

    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="cancel-before-factory-key")
    factory_calls = 0

    def fake_factory():
        nonlocal factory_calls
        factory_calls += 1
        return DemoTranscriptionAdapter()

    def cancelling_progress(job_id: str, phase: str, percent: int, message: str) -> dict[str, Any]:
        result = update_running_progress(job_id, phase, percent, message)
        if phase == "preprocessing":
            cancel_transcription_job(job_id)
        return result

    monkeypatch.setattr(transcription_jobs, "create_transcription_adapter", fake_factory)
    monkeypatch.setattr(transcription_jobs, "update_running_progress", cancelling_progress)

    result = run_transcription_job(created["jobId"])

    assert result["state"] == "cancelled"
    assert factory_calls == 0


def test_cancellation_after_basic_pitch_load_skips_inference(tmp_path: Path) -> None:
    class CancellingAfterLoadAdapter(BasicPitchTranscriptionAdapter):
        def load(self, context: TranscriptionAdapterContext) -> None:
            super().load(context)
            cancel_transcription_job(context.job["jobId"])

    binding = FakeBinding({"notes": [(0, 0.1, 60, 0.5)]})
    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="cancel-after-load-key")

    result = run_transcription_job(
        created["jobId"],
        CancellingAfterLoadAdapter(model_file(tmp_path), binding=binding),
    )

    assert result["state"] == "cancelled"
    assert binding.predict_calls == 0


def test_cancellation_before_succeeded_publication_wins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import transcription_jobs

    upload_id = create_upload(tmp_path)
    created = create_job(upload_id, key="cancel-before-success-key")
    original_validate = transcription_jobs.validate_adapter_result

    def cancelling_validate(result: Any) -> dict[str, Any]:
        validated = original_validate(result)
        cancel_transcription_job(created["jobId"])
        return validated

    monkeypatch.setattr(transcription_jobs, "validate_adapter_result", cancelling_validate)

    result = run_transcription_job(
        created["jobId"],
        BasicPitchTranscriptionAdapter(model_file(tmp_path), binding=FakeBinding({"notes": [], "durationSeconds": 1})),
    )

    assert result["state"] == "cancelled"
    assert load_job(created["jobId"])["result"] is None
