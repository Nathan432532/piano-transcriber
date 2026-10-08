"""Collect missing frozen heads once, then score four offline offset policies.

Run from backend: ..\.venv\Scripts\python.exe -m benchmarks.experiments.offset_policy.run --collect-missing
Subsequent runs omit --collect-missing and do not load a model.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import inspect
from pathlib import Path
import shutil
import statistics

import numpy as np
import soundfile as sf

from benchmarks.metrics import aggregate, read_midi, score
from benchmarks.offset_helpers import decoder_trace
from benchmarks.prepare import ROOT, FIXTURES, sha256
from .policies import evaluate_event, terminal_silence_start

BASELINE = ROOT / "backend/data/benchmarks/runs/20261006-baseline-01"
DIAGNOSIS = ROOT / "backend/data/benchmarks/runs/offset-diagnosis-20261006"
CACHE = ROOT / "backend/data/benchmarks/runs/offset-policy-frozen-heads"
REPORTS = ROOT / "backend/benchmarks/reports"
MODEL = ROOT / "backend/data/models/CRNN_note_F1=0.9677_pedal_F1=0.9186.pth"
MODEL_SHA = "c3fa9730725bf4a762f1c14bc80cd5986eacda01b026f5a4a2525cd607876141"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def collect(manifest: dict, allow_inference: bool):
    """No MIDI contents enter inference; hash checks establish frozen identity."""
    binding = None
    prior = load_json(DIAGNOSIS / "trace.json")
    assert prior["modelSha256"] == MODEL_SHA == sha256(MODEL)
    from piano_transcription_inference import inference, utilities, piano_vad
    for module in (inference, utilities, piano_vad):
        path = Path(inspect.getfile(module))
        assert sha256(path) == prior["upstreamSourceSha256"][path.name], "Upstream differs from frozen diagnosis"
    for fragment in manifest["fragments"]:
        name = fragment["name"]
        for key in ("audio", "midi"):
            assert sha256(ROOT / fragment[key]) == fragment[key + "Sha256"]
        dest = CACHE / name
        if dest.exists():
            meta = load_json(dest / "provenance.json")
            assert meta["audioSha256"] == fragment["audioSha256"] and meta["modelSha256"] == MODEL_SHA
            for filename, digest in meta["outputSha256"].items():
                assert sha256(dest / filename) == digest
            continue
        source = DIAGNOSIS / name
        dest.mkdir(parents=True)
        if source.exists():
            print(f"Reusing frozen model outputs: {name}", flush=True)
            clip = next(c for c in prior["clips"] if c["name"] == name)
            assert clip["audioSha256"] == fragment["audioSha256"]
            for filename in ("library-framewise-output.npz", "raw-segment-model-heads.npz", "library-events.json"):
                shutil.copyfile(source / filename, dest / filename)
            duration = clip["padding"]["preprocessedDuration"]
            origin = str(source)
        else:
            if not allow_inference:
                dest.rmdir()
                raise RuntimeError(f"Missing heads for {name}; rerun with --collect-missing on the same frozen WAV")
            from benchmarks.offset_diagnosis import ObservingBinding
            if binding is None:
                binding = ObservingBinding()
                binding.load_model(MODEL)
                assert (binding._model.onset_threshold, binding._model.offset_threshod,
                        binding._model.frame_threshold, binding._model.pedal_offset_threshold) == (.3, .3, .1, .2)
            binding.segment_outputs.clear()
            binding.segment_inputs.clear()
            print(f"Collecting unchanged model heads for frozen clip: {name}", flush=True)
            library, duration = binding.predict(ROOT / fragment["audio"])
            assert len(binding.segment_outputs) == 1
            for key, raw in binding.segment_outputs[0].items():
                assert np.array_equal(raw[0], library["output_dict"][key])
            np.savez_compressed(dest / "library-framewise-output.npz", **library["output_dict"])
            np.savez_compressed(dest / "raw-segment-model-heads.npz", **binding.segment_outputs[0])
            (dest / "library-events.json").write_text(json.dumps({"notes": library["est_note_events"],
                                                                 "pedal": library["est_pedal_events"]}, default=float, indent=2))
            origin = "Unchanged production binding on identical frozen audio; missing historical raw heads only"
        meta = {"audioSha256": fragment["audioSha256"], "modelSha256": MODEL_SHA,
                "duration": duration, "origin": origin, "createdAt": datetime.now(timezone.utc).isoformat(),
                "outputSha256": {p.name: sha256(p) for p in dest.iterdir() if p.is_file()}}
        (dest / "provenance.json").write_text(json.dumps(meta, indent=2))
    if binding is not None:
        binding.hook.remove()


def runtime_notes(fragment: dict) -> tuple[list[dict], dict]:
    """Construct all candidates without opening reference MIDI or reference JSON."""
    name = fragment["name"]
    dest = CACHE / name
    events = load_json(dest / "library-events.json")
    meta = load_json(dest / "provenance.json")
    duration = meta["duration"]
    with np.load(dest / "library-framewise-output.npz") as data:
        matrices = {key: data[key] for key in data.files}
    audio, rate = sf.read(ROOT / fragment["audio"], always_2d=True)
    silence = terminal_silence_start(audio, rate)
    baseline = load_json(BASELINE / "predictions/bytedance" / f"{name}.json")["notes"]
    # Existing normalization is invoked solely as an equality/provenance check.
    from app.bytedance_adapter import normalize_bytedance_notes
    assert normalize_bytedance_notes({"est_note_events": events["notes"], "output_dict": matrices}, duration) == baseline
    notes = sorted((e for e in events["notes"] if e["onset_time"] < duration),
                   key=lambda e: (e["onset_time"], e["midi_note"], min(e["offset_time"], duration)))
    assert len(notes) == len(baseline)
    traced = {}
    # This observer is checked against the installed unchanged upstream function.
    from piano_transcription_inference.piano_vad import note_detection_with_onset_offset_regress
    for pitch in {e["midi_note"] for e in notes}:
        c = pitch - 21
        args = [matrices[key][:, c] for key in ("frame_output", "onset_output", "onset_shift_output", "offset_output", "offset_shift_output", "velocity_output")] + [.1]
        traces = decoder_trace(*args)
        upstream = note_detection_with_onset_offset_regress(*args)
        assert len(traces) == len(upstream)
        for trace, original in zip(traces, upstream):
            assert [trace[k] for k in ("beginFrame", "endFrame", "onsetShift", "offsetShift", "velocityRaw")] == [float(v) for v in original]
        traced[pitch] = traces
    rows = []
    for event, canonical in zip(notes, baseline):
        traces = traced[event["midi_note"]]
        trace = min(traces, key=lambda t: abs(t["onsetSeconds"] - event["onset_time"]))
        assert abs(trace["onsetSeconds"] - event["onset_time"]) < 1e-6
        assert abs(trace["offsetSeconds"] - event["offset_time"]) < 1e-6
        subsequent = [e["onset_time"] for e in notes if e["midi_note"] == event["midi_note"] and e["onset_time"] > event["onset_time"]]
        outputs = evaluate_event(event, trace, matrices, duration, events["pedal"] or [], min(subsequent, default=None), silence)
        assert outputs["A"] == canonical["endTime"]
        column = event["midi_note"] - 21
        accepted = [{"frame": int(i), "time": (int(i) + float(matrices["offset_shift_output"][i, column])) / 100,
                     "score": float(matrices["reg_offset_output"][i, column])}
                    for i in np.flatnonzero(matrices["offset_output"][:, column]) if i > trace["beginFrame"]]
        rows.append({"clip": name, "pitch": canonical["pitch"], "onset": canonical["startTime"],
                     "upstream_offset": float(event["offset_time"]), "audio_duration": duration,
                     "segment_end": (len(matrices["frame_output"]) - 1) / 100,
                     "terminal_silence_start": silence, "decoder_reason": trace["reason"],
                     "decoder_begin_frame": trace["beginFrame"], "decoder_end_frame": trace["endFrame"],
                     "accepted_peaks": accepted, "predicted_pedal_events": events["pedal"],
                     "canonical_note": canonical, **outputs})
    return rows, {"audioDuration": duration, "terminalSilenceStart": silence,
                  "pedalEvents": events["pedal"], "provenance": meta}


def summarize(rows, totals):
    result = {}
    for policy in "ABCD":
        errors = [abs(r[policy] - r["gt_key_release"]) for r in rows]
        sustain = [r for r in rows if r["gt_pedal_release"] > r["gt_key_release"] + 1e-9]
        boundary = [r for r in rows if r["decoder_boundary"]]
        def mae(selection, key):
            return statistics.mean(abs(r[policy] - r[key]) for r in selection) * 1000 if selection else None
        result[policy] = {**totals[policy], "max_offset_error_ms": max(errors) * 1000,
                          "changed_offsets": sum(abs(r[policy] - r["A"]) > 1e-7 for r in rows),
                          "improved_notes": sum(abs(r[policy]-r["gt_key_release"]) < abs(r["A"]-r["gt_key_release"])-1e-7 for r in rows),
                          "worsened_notes": sum(abs(r[policy]-r["gt_key_release"]) > abs(r["A"]-r["gt_key_release"])+1e-7 for r in rows),
                          "audio_boundary_notes": sum(r[policy] == r["audio_duration"] for r in rows),
                          "segment_boundary_notes": sum(r[policy] == r["segment_end"] for r in rows),
                          "decoder_boundary_cases": len(boundary),
                          "runaway_key_mae_ms": mae(boundary, "gt_key_release"),
                          "sustain_notes": len(sustain), "sustain_key_mae_ms": mae(sustain, "gt_key_release"),
                          "sustain_pedal_mae_ms": mae(sustain, "gt_pedal_release"),
                          "sustain_pedal_worsened": sum(abs(r[policy]-r["gt_pedal_release"]) > abs(r["A"]-r["gt_pedal_release"])+1e-7 for r in sustain)}
    return result


def run(allow_inference=False):
    manifest = load_json(FIXTURES / "baseline-manifest.json")
    collect(manifest, allow_inference)
    # Compute every runtime decision BEFORE loading any reference MIDI.
    runtime = {f["name"]: runtime_notes(f) for f in manifest["fragments"]}
    scored_rows, scores = [], {p: [] for p in "ABCD"}
    for fragment in manifest["fragments"]:
        rows, _ = runtime[fragment["name"]]
        refs = read_midi(ROOT / fragment["midi"])
        for policy in "ABCD":
            predictions = [{**r["canonical_note"], "endTime": r[policy]} for r in rows]
            assert [(n["pitch"], n["startTime"]) for n in predictions] == [(r["pitch"], r["onset"]) for r in rows]
            metrics = score(refs, predictions)
            scores[policy].append(metrics)
            assert metrics["TP"] == len(rows) == len(refs) and metrics["FP"] == metrics["FN"] == 0
        matches = scores["A"][-1]["diagnostics"]["correct"]
        assert len(matches) == len(rows)
        for match in matches:
            row = dict(rows[match["predictionIndex"]])
            ref = match["reference"]
            row.update(gt_onset=ref["startTime"], gt_key_release=ref["endTime"], gt_pedal_release=ref["sustainEndTime"])
            for p in "ABCD":
                row[f"error_{p}"] = row[p] - ref["endTime"]
                row[f"pedal_error_{p}"] = row[p] - ref["sustainEndTime"]
            scored_rows.append(row)
    totals = summarize(scored_rows, {p: aggregate(scores[p]) for p in "ABCD"})
    assert len(scored_rows) == 23
    REPORTS.mkdir(parents=True, exist_ok=True)
    fields = ["clip", "pitch", "gt_onset", "gt_key_release", "gt_pedal_release", "onset", "upstream_offset",
              "raw_candidate_offset", *"ABCD", "error_A", "error_B", "error_C", "error_D",
              "pedal_error_A", "pedal_error_B", "pedal_error_C", "pedal_error_D", "decoder_reason", "decoder_boundary",
              "decoder_begin_frame", "decoder_end_frame", "audio_duration", "segment_end", "terminal_silence_start",
              "reason_B", "reason_C", "reason_D", "accepted_peaks", "predicted_pedal_events"]
    with (REPORTS / "bytedance-offset-policy-notes.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fields, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(scored_rows, key=lambda r: (r["clip"], r["gt_onset"], r["pitch"])):
            writer.writerow({**row, "accepted_peaks": json.dumps(row["accepted_peaks"]), "predicted_pedal_events": json.dumps(row["predicted_pedal_events"])})
    summary = {"createdAt": datetime.now(timezone.utc).isoformat(), "policySourceSha256": sha256(Path(__file__).with_name("policies.py")),
               "upstreamSourceSha256": load_json(DIAGNOSIS / "trace.json")["upstreamSourceSha256"],
               "totals": totals, "notes": scored_rows, "clips": {name: item[1] for name, item in runtime.items()}}
    (REPORTS / "bytedance-offset-policy-results.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({p: {k: v for k, v in values.items() if k not in {"errors", "diagnostics"}} for p, values in totals.items()}, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collect-missing", action="store_true", help="Same frozen WAVs only; no new examples, jobs or model settings")
    run(parser.parse_args().collect_missing)
