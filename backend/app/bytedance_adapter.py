from __future__ import annotations

import importlib
import logging
import math
from pathlib import Path
from typing import Any

from .basic_pitch_adapter import midi_note_name
from .transcription_jobs import TranscriptionAdapterInferenceError, TranscriptionAdapterLoadError

logger = logging.getLogger(__name__)


class ByteDanceProductionBinding:
    def load_model(self, model_path: Path) -> None:
        # Explicit local checkpoint avoids upstream's wget download on Windows.
        package = importlib.import_module("piano_transcription_inference")
        self._sample_rate = package.sample_rate
        self._model = package.PianoTranscription(device="cpu", checkpoint_path=str(model_path))

    def predict(self, audio_path: Path) -> tuple[dict[str, Any], float]:
        librosa = importlib.import_module("librosa")
        audio, _ = librosa.load(path=str(audio_path), sr=self._sample_rate, mono=True)
        duration = len(audio) / self._sample_rate
        # Only canonical JSON is published; existing backend produces both MIDIs.
        return self._model.transcribe(audio, None), duration


class ByteDanceTranscriptionAdapter:
    def __init__(self, model_path: str | Path | None, binding: Any = None) -> None:
        self._model_path = model_path
        self._binding = binding or ByteDanceProductionBinding()

    def load(self, context: Any) -> None:
        try:
            if not self._model_path:
                raise ValueError("Configure PIANO_TRANSCRIBER_BYTEDANCE_MODEL_PATH")
            model_path = Path(self._model_path).expanduser()
            if not model_path.is_file() or model_path.stat().st_size < 160_000_000:
                raise ValueError("ByteDance checkpoint is missing or incomplete")
            self._binding.load_model(model_path)
        except Exception as exc:
            logger.exception("ByteDance model load failed")
            raise TranscriptionAdapterLoadError("ByteDance model could not be loaded") from exc

    def transcribe(self, context: Any, report_progress: Any) -> dict[str, Any]:
        try:
            report_progress("inferencing", 85, "Detecting piano notes with ByteDance")
            output, duration = self._binding.predict(context.upload_path)
            report_progress("postprocessing", 95, "Normalizing note events")
            notes = normalize_bytedance_notes(output, duration)
            report_progress("saving", 99, "Saving transcript metadata")
            logger.info("ByteDance CPU inference produced %d notes", len(notes))
            return {
                "_transcript": {
                    "version": "1.0",
                    "source": {"kind": "uploaded", "filename": context.upload_path.name, "duration": duration},
                    "notes": notes,
                },
                "transcriptUrl": None, "exports": {},
                "noteCount": len(notes), "durationSeconds": duration,
            }
        except Exception as exc:
            logger.exception("ByteDance inference failed")
            raise TranscriptionAdapterInferenceError("ByteDance inference failed") from exc


def normalize_bytedance_notes(output: dict[str, Any], duration: float) -> list[dict[str, Any]]:
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Invalid audio duration")
    notes = []
    for event in output["est_note_events"]:
        pitch = event["midi_note"]
        velocity = event["velocity"]
        start, end = float(event["onset_time"]), float(event["offset_time"])
        if (isinstance(pitch, bool) or not isinstance(pitch, int) or not 21 <= pitch <= 108
                or isinstance(velocity, bool) or not isinstance(velocity, int) or not 1 <= velocity <= 127
                or not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start):
            raise ValueError("Invalid ByteDance note event")
        # Upstream pads to 10-second segments; exclude events outside real audio.
        if start >= duration:
            continue
        end = min(end, duration)
        # Upstream has no per-event confidence. Preserve the onset model score
        # at the nearest 100 Hz frame as an explicit, uncalibrated proxy.
        scores = output["output_dict"]["reg_onset_output"]
        frame = min(round(start * 100), len(scores) - 1)
        confidence = float(scores[frame, pitch - 21])
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("Invalid ByteDance onset score")
        notes.append({"pitch": pitch, "noteName": midi_note_name(pitch),
                      "startTime": start, "endTime": end, "velocity": velocity,
                      "confidence": confidence, "hand": "unknown"})
    return sorted(notes, key=lambda note: (note["startTime"], note["pitch"], note["endTime"]))
