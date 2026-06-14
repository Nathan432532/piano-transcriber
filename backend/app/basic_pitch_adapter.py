from __future__ import annotations

import importlib
import math
from collections.abc import Iterable, Mapping, Sequence
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Protocol

from .audio_validation import audio_duration_seconds


NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


class BasicPitchBinding(Protocol):
    def load_model(self, model_path: Path) -> None:
        ...

    def predict(self, audio_path: Path) -> Any:
        ...


class BasicPitchProductionBinding:
    def __init__(self) -> None:
        self._predict: Any = None
        self._model: Any = None

    def load_model(self, model_path: Path) -> None:
        try:
            inference = importlib.import_module("basic_pitch.inference")
        except Exception as exc:
            raise RuntimeError("Basic Pitch package could not be imported") from exc

        try:
            predict = getattr(inference, "predict")
            model = getattr(inference, "Model")(str(model_path))
        except Exception as exc:
            raise RuntimeError("Basic Pitch model could not be loaded") from exc

        self._predict = predict
        self._model = model

    def predict(self, audio_path: Path) -> Any:
        if self._predict is None or self._model is None:
            raise RuntimeError("Basic Pitch model is not loaded")
        return self._predict(str(audio_path), model_or_model_path=self._model)


class BasicPitchTranscriptionAdapter:
    def __init__(self, model_path: str | Path | None = None, binding: BasicPitchBinding | None = None) -> None:
        self._model_path = model_path
        self._binding = binding or BasicPitchProductionBinding()

    def load(self, context: Any) -> None:
        from .transcription_jobs import TranscriptionAdapterLoadError

        model_path = resolve_basic_pitch_model_path(self._model_path)

        try:
            self._binding.load_model(model_path)
        except Exception as exc:
            raise TranscriptionAdapterLoadError("Basic Pitch model could not be loaded") from exc

    def transcribe(self, context: Any, report_progress: Any) -> dict[str, Any]:
        from .transcription_jobs import TranscriptionAdapterInferenceError

        try:
            report_progress("inferencing", 85, "Detecting notes")
            output = self._binding.predict(context.upload_path)
            report_progress("postprocessing", 95, "Normalizing note events")
            notes = normalize_basic_pitch_notes(extract_note_events(output))
            duration = extract_duration_seconds(output)
            if duration is None:
                duration = round(audio_duration_seconds(context.upload_path, context.upload_path.suffix), 3)
            duration = normalize_duration_seconds(duration)
            report_progress("saving", 99, "Saving transcript metadata")
        except TranscriptionAdapterInferenceError:
            raise
        except Exception as exc:
            raise TranscriptionAdapterInferenceError("Basic Pitch inference failed") from exc

        return {
            "_transcript": {
                "version": "1.0",
                "source": {
                    "kind": "uploaded",
                    "filename": context.upload_path.name,
                    "duration": duration,
                },
                "notes": notes,
            },
            "transcriptUrl": None,
            "exports": {},
            "noteCount": len(notes),
            "durationSeconds": duration,
        }


def extract_note_events(output: Any) -> Any:
    if isinstance(output, Mapping):
        for key in ("notes", "noteEvents", "note_events"):
            if key in output:
                return output[key]
        raise_invalid_output("Basic Pitch output is missing note events")

    if isinstance(output, Sequence) and not isinstance(output, (str, bytes, bytearray)) and len(output) >= 3:
        return output[2]

    raise_invalid_output("Basic Pitch output shape is not supported")


def resolve_basic_pitch_model_path(configured_model_path: str | Path | None) -> Path:
    from .transcription_jobs import TranscriptionAdapterLoadError

    if configured_model_path is not None and str(configured_model_path).strip():
        model_path = Path(str(configured_model_path)).expanduser()
    else:
        try:
            basic_pitch = importlib.import_module("basic_pitch")
            model_path = Path(getattr(basic_pitch, "ICASSP_2022_MODEL_PATH")).expanduser()
        except Exception as exc:
            raise TranscriptionAdapterLoadError("Basic Pitch package default model could not be resolved") from exc

    if not is_basic_pitch_model_path_available(model_path):
        raise TranscriptionAdapterLoadError("Basic Pitch model file is not available")
    return model_path


def is_basic_pitch_model_path_available(model_path: Path) -> bool:
    return model_path.is_file() or (
        model_path.is_dir()
        and (model_path / "saved_model.pb").is_file()
        and (model_path / "variables").is_dir()
    )


def extract_duration_seconds(output: Any) -> Any:
    if isinstance(output, Mapping):
        for key in ("durationSeconds", "duration_seconds", "duration"):
            if key in output:
                return output[key]
    return None


def normalize_basic_pitch_notes(note_events: Any) -> list[dict[str, Any]]:
    events = materialize_note_events(note_events)
    notes = [normalize_basic_pitch_note(event) for event in events]
    return sorted(notes, key=lambda note: (note["startTime"], note["pitch"], note["endTime"]))


def materialize_note_events(note_events: Any) -> list[Any]:
    if isinstance(note_events, (str, bytes, bytearray)) or not isinstance(note_events, Iterable):
        raise_invalid_output("Basic Pitch note events must be iterable")
    try:
        return list(note_events)
    except TypeError:
        raise_invalid_output("Basic Pitch note events must be iterable")


def normalize_basic_pitch_note(note: Any) -> dict[str, Any]:
    if isinstance(note, Mapping):
        start_time = first_present(note, "startTime", "start_time", "start")
        end_time = first_present(note, "endTime", "end_time", "end")
        pitch = first_present(note, "pitch", "midiPitch", "midi_pitch")
        confidence = first_present(note, "confidence", "amplitude", "score")
        velocity = note.get("velocity")
    elif isinstance(note, Sequence) and not isinstance(note, (str, bytes, bytearray)) and len(note) >= 4:
        start_time, end_time, pitch, confidence = note[:4]
        velocity = None
    else:
        raise_invalid_output("Basic Pitch note shape is not supported")

    normalized_confidence = normalize_unit_float(confidence, "confidence")
    normalized_velocity = (
        normalize_velocity(velocity) if velocity is not None else int(round(normalized_confidence * 127))
    )
    normalized_pitch = normalize_pitch(pitch)
    normalized_start = normalize_time(start_time, "startTime")
    normalized_end = normalize_time(end_time, "endTime")
    if normalized_end <= normalized_start:
        raise_invalid_output("Basic Pitch note endTime must be after startTime")

    return {
        "pitch": normalized_pitch,
        "noteName": midi_note_name(normalized_pitch),
        "startTime": normalized_start,
        "endTime": normalized_end,
        "velocity": normalized_velocity,
        "confidence": normalized_confidence,
        "hand": "unknown",
    }


def first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    raise_invalid_output("Basic Pitch note is missing a required field")


def normalize_pitch(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise_invalid_output("Basic Pitch note pitch must be an integer")
    pitch = int(value)
    if not 0 <= pitch <= 127:
        raise_invalid_output("Basic Pitch note pitch is out of range")
    return pitch


def normalize_velocity(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise_invalid_output("Basic Pitch note velocity must be an integer")
    velocity = int(value)
    if not 0 <= velocity <= 127:
        raise_invalid_output("Basic Pitch note velocity is out of range")
    return velocity


def normalize_unit_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise_invalid_output(f"Basic Pitch note {field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0 <= normalized <= 1:
        raise_invalid_output(f"Basic Pitch note {field_name} is out of range")
    return normalized


def normalize_time(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise_invalid_output(f"Basic Pitch note {field_name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise_invalid_output(f"Basic Pitch note {field_name} must be finite and non-negative")
    return normalized


def normalize_duration_seconds(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise_invalid_output("Basic Pitch duration must be numeric")
    duration = float(value)
    if not math.isfinite(duration) or duration < 0:
        raise_invalid_output("Basic Pitch duration must be finite and non-negative")
    return duration


def midi_note_name(pitch: int) -> str:
    return f"{NOTE_NAMES[pitch % 12]}{pitch // 12 - 1}"


def raise_invalid_output(message: str) -> None:
    from .transcription_jobs import TranscriptionAdapterInferenceError

    raise TranscriptionAdapterInferenceError(message)
