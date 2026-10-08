"""Observe two frozen clips through the unchanged production ByteDance adapter.

Exports raw model heads, upstream events, decoder decisions and unchanged JSON.
No counterfactual decoding, threshold edits, corrections or app job writes.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import time
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from app.bytedance_adapter import ByteDanceProductionBinding, ByteDanceTranscriptionAdapter
from app.transcription_jobs import validate_transcript_payload
from benchmarks.metrics import read_midi
from benchmarks.prepare import ROOT, FIXTURES, sha256
from benchmarks.offset_helpers import decoder_trace, padding_info

BASELINE = ROOT / "backend/data/benchmarks/runs/20261006-baseline-01"
SELECTION = {"single_notes": [60, 67, 71], "long_notes_sustain": [55, 60, 64, 67]}


class ObservingBinding(ByteDanceProductionBinding):
    def load_model(self, path):
        super().load_model(path)
        self.segment_outputs = []
        self.segment_inputs = []
        def capture(_module, inputs, outputs):
            self.segment_inputs.append(inputs[0].detach().cpu().numpy().copy())
            self.segment_outputs.append({key: value.detach().cpu().numpy().copy() for key, value in outputs.items()})
        self.hook = self._model.model.register_forward_hook(capture)

    def predict(self, path):
        self.library_output, self.duration = super().predict(path)
        return self.library_output, self.duration


def audit(output: Path) -> dict:
    from piano_transcription_inference import piano_vad, inference, utilities
    manifest = json.loads((FIXTURES / "baseline-manifest.json").read_text())
    output.mkdir(parents=True, exist_ok=False)
    sources = [Path(inspect.getfile(module)) for module in [inference, utilities, piano_vad]]
    model = ROOT / "backend/data/models/CRNN_note_F1=0.9677_pedal_F1=0.9186.pth"
    report = {"createdAt": datetime.now(timezone.utc).isoformat(), "modelSha256": sha256(model),
              "upstreamSourceSha256": {path.name: sha256(path) for path in sources},
              "adapterSha256": sha256(ROOT / "backend/app/bytedance_adapter.py"),
              "scriptSha256": sha256(Path(__file__)), "clips": []}
    for name, pitches in SELECTION.items():
        fragment = next(item for item in manifest["fragments"] if item["name"] == name)
        audio_path, midi_path = ROOT / fragment["audio"], ROOT / fragment["midi"]
        assert sha256(audio_path) == fragment["audioSha256"] and sha256(midi_path) == fragment["midiSha256"]
        baseline = json.loads((BASELINE / "predictions/bytedance" / f"{name}.json").read_text())
        job = json.loads((BASELINE / "predictions/bytedance" / f"{name}.job.json").read_text())
        stored_path = ROOT / "backend/data/jobs/artifacts" / job["jobId"] / "transcript.json"
        stored = json.loads(stored_path.read_text())
        assert baseline == stored, "Baseline snapshot differs from originally stored job JSON"
        context = SimpleNamespace(upload_path=audio_path, job=job)
        binding = ObservingBinding()
        adapter = ByteDanceTranscriptionAdapter(model, binding)
        print(f"Observing {name}; unchanged production adapter", flush=True)
        start = time.perf_counter()
        adapter.load(context)
        try:
            result = adapter.transcribe(context, lambda *args: None)
        finally:
            binding.hook.remove()
        canonical = validate_transcript_payload(result["_transcript"])
        # Only source filename changes (fixture name versus uploaded UUID).
        assert canonical["notes"] == stored["notes"], "Reproduction differs from baseline; do not mix traces"
        assert json.loads(json.dumps(canonical))["notes"] == stored["notes"]
        library = binding.library_output
        matrices = library["output_dict"]
        assert len(binding.segment_outputs) == 1, "This diagnosis is explicitly for the two one-segment clips"
        for key, raw in binding.segment_outputs[0].items():
            assert np.array_equal(raw[0], matrices[key]), "Unexpected deframe change in single-segment output"
        sample_count = round(binding.duration * 16000)
        info = sf.info(audio_path)
        padding = padding_info(sample_count, info.frames, info.samplerate, len(matrices["frame_output"]))
        segments = binding.segment_inputs[0]
        assert segments.shape == (1, 160000)
        assert np.all(segments[0, sample_count:] == 0), "Expected explicit zero-padding"
        destination = output / name
        destination.mkdir()
        np.savez_compressed(destination / "raw-segment-model-heads.npz", **binding.segment_outputs[0])
        np.savez_compressed(destination / "library-framewise-output.npz", **matrices)
        np.savez_compressed(destination / "model-input-segments.npz", samples=segments)
        (destination / "library-events.json").write_text(json.dumps({"notes": library["est_note_events"],
                                                                      "pedal": library["est_pedal_events"]}, indent=2, default=float))
        (destination / "reproduced-canonical.json").write_text(json.dumps(canonical, indent=2))
        refs = read_midi(midi_path)
        clip = {"name": name, "audioSha256": fragment["audioSha256"], "midiSha256": fragment["midiSha256"],
                "storedJsonSha256": sha256(stored_path), "storedJobId": job["jobId"],
                "runtimeSeconds": time.perf_counter() - start, "padding": padding,
                "modelParameters": {"onset": binding._model.onset_threshold, "offset": binding._model.offset_threshod,
                                    "frame": binding._model.frame_threshold, "pedal_offset": binding._model.pedal_offset_threshold},
                "pedalEvents": library["est_pedal_events"], "notes": []}
        for pitch in pitches:
            column = pitch - 21
            frame = matrices["frame_output"][:, column]
            onset = matrices["onset_output"][:, column]
            offset = matrices["offset_output"][:, column]
            onset_shift = matrices["onset_shift_output"][:, column]
            offset_shift = matrices["offset_shift_output"][:, column]
            velocity = matrices["velocity_output"][:, column]
            traces = decoder_trace(frame, onset, onset_shift, offset, offset_shift, velocity, binding._model.frame_threshold)
            upstream = piano_vad.note_detection_with_onset_offset_regress(frame, onset, onset_shift, offset, offset_shift, velocity, binding._model.frame_threshold)
            assert len(traces) == len(upstream)
            for trace, original in zip(traces, upstream):
                assert [trace["beginFrame"], trace["endFrame"], trace["onsetShift"], trace["offsetShift"], trace["velocityRaw"]] == [float(value) for value in original]
            ref = next(note for note in refs if note["pitch"] == pitch)
            event = min((e for e in library["est_note_events"] if e["midi_note"] == pitch), key=lambda e: abs(e["onset_time"] - ref["startTime"]))
            trace = min(traces, key=lambda t: abs(t["onsetSeconds"] - event["onset_time"]))
            assert abs(trace["offsetSeconds"] - event["offset_time"]) < 1e-6
            converted = min((n for n in canonical["notes"] if n["pitch"] == pitch), key=lambda n: abs(n["startTime"] - ref["startTime"]))
            saved = min((n for n in stored["notes"] if n["pitch"] == pitch), key=lambda n: abs(n["startTime"] - ref["startTime"]))
            peaks = [{"frame": int(index), "time": (index + float(offset_shift[index])) / 100,
                      "score": float(matrices["reg_offset_output"][index, column])}
                     for index in np.flatnonzero(offset)[np.flatnonzero(offset) > trace["beginFrame"]]]
            gt_frame = round(ref["endTime"] * 100)
            samples = sorted(set([trace["beginFrame"], gt_frame, round(ref["sustainEndTime"] * 100),
                                  trace["endFrame"], padding["lastCenterInsideAudio"], padding["lastOutputFrame"]]
                                 + [n for n in [trace["firstOffsetFrame"], trace["firstFrameDisappear"]] if n is not None]))
            note = {"pitch": pitch, "groundTruth": ref, "rawModelOnsetScalar": None, "rawModelOffsetScalar": None,
                    "scalarExplanation": "Model returns framewise heads, not note timestamps; peaks below are decoded regression cues, not a standalone model note end",
                    "onsetHeadPeak": {"frame": trace["beginFrame"], "time": trace["onsetSeconds"],
                                      "score": float(matrices["reg_onset_output"][trace["beginFrame"], column])},
                    "offsetHeadPeaks": peaks, "frameAtGroundTruthKeyRelease": float(frame[gt_frame]),
                    "decoder": trace, "libraryOnset": float(event["onset_time"]), "libraryOffset": float(event["offset_time"]),
                    "adapterOnset": converted["startTime"], "adapterOffset": converted["endTime"],
                    "canonicalOffset": canonical["notes"][canonical["notes"].index(converted)]["endTime"],
                    "finalStoredOffset": saved["endTime"], "clippingApplied": float(event["offset_time"]) > binding.duration,
                    "clippingReason": "Existing adapter min(library offset, resampled audio duration)" if float(event["offset_time"]) > binding.duration else "No clipping; upstream end lies inside actual audio",
                    "selectedFrames": [{"frame": index, "time": index / 100, "frameActivation": float(frame[index]),
                                        "offsetScore": float(matrices["reg_offset_output"][index, column]),
                                        "offsetPeak": bool(offset[index])} for index in samples]}
            clip["notes"].append(note)
            with (destination / f"pitch-{pitch}-frames.csv").open("w", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(["frame", "seconds", "onset_score", "onset_peak", "offset_score", "offset_peak", "frame_activation", "inside_audio"])
                for index in range(len(frame)):
                    writer.writerow([index, index / 100, float(matrices["reg_onset_output"][index, column]), int(onset[index]),
                                     float(matrices["reg_offset_output"][index, column]), int(offset[index]), float(frame[index]), index <= padding["lastCenterInsideAudio"]])
        report["clips"].append(clip)
        (output / "trace.json").write_text(json.dumps(report, indent=2, default=float))
        print([(note["pitch"], note["libraryOffset"], note["adapterOffset"], note["decoder"]["reason"]) for note in clip["notes"]], flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "backend/data/benchmarks/runs/offset-diagnosis-20261006")
    args = parser.parse_args()
    audit(args.output)
