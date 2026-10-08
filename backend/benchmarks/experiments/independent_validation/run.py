"""Validate unchanged A/B/C on frozen holdout audio; offline replay after capture."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import csv
import inspect
import json
from pathlib import Path
import time

import numpy as np
import soundfile as sf

from benchmarks.metrics import score, aggregate, read_midi
from benchmarks.offset_helpers import decoder_trace
from benchmarks.prepare import ROOT, sha256
from benchmarks.experiments.offset_policy.policies import evaluate_event, terminal_silence_start
from .prepare import FIXTURES, POLICY, POLICY_SHA, verify
from .assessment import enhance_metrics, release_state, safety_findings

CACHE = ROOT / "backend/data/benchmarks/runs/independent-validation-heads"
REPORTS = ROOT / "backend/benchmarks/reports"
MODEL = ROOT / "backend/data/models/CRNN_note_F1=0.9677_pedal_F1=0.9186.pth"
MODEL_SHA = "c3fa9730725bf4a762f1c14bc80cd5986eacda01b026f5a4a2525cd607876141"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def capture(manifest, allow_inference):
    from piano_transcription_inference import inference, utilities, piano_vad
    source_hashes = {Path(inspect.getfile(m)).name: sha256(Path(inspect.getfile(m))) for m in (inference, utilities, piano_vad)}
    assert source_hashes == read_json(ROOT / "backend/data/benchmarks/runs/offset-diagnosis-20261006/trace.json")["upstreamSourceSha256"]
    assert sha256(MODEL) == MODEL_SHA
    assert sha256(POLICY) == POLICY_SHA
    binding = None
    try:
        for case in manifest["cases"]:
            dest = CACHE / case["name"]
            if dest.exists():
                meta = read_json(dest / "provenance.json")
                assert meta["audioSha256"] == case["audioSha256"] and meta["modelSha256"] == MODEL_SHA
                assert meta["upstreamSourceSha256"] == source_hashes
                for name, digest in meta["outputSha256"].items():
                    assert sha256(dest / name) == digest
                continue
            if not allow_inference:
                raise RuntimeError(f"Missing frozen heads: {case['name']}; use --capture once")
            from benchmarks.offset_diagnosis import ObservingBinding
            if binding is None:
                binding = ObservingBinding()
                binding.load_model(MODEL)
                assert (binding._model.onset_threshold, binding._model.offset_threshod,
                        binding._model.frame_threshold, binding._model.pedal_offset_threshold) == (.3, .3, .1, .2)
            binding.segment_inputs.clear()
            binding.segment_outputs.clear()
            start = time.perf_counter()
            print(f"Real unchanged ByteDance inference: {case['name']}", flush=True)
            library, duration = binding.predict(ROOT / case["audio"])
            raw = {key: np.concatenate([chunk[key] for chunk in binding.segment_outputs], axis=0)
                   for key in binding.segment_outputs[0]}
            for key, matrix in raw.items():
                expected = binding._model.deframe(matrix.copy())[:round(duration*16000)]
                assert np.array_equal(expected, library["output_dict"][key])
            from app.bytedance_adapter import normalize_bytedance_notes
            canonical = normalize_bytedance_notes(library, duration)
            dest.mkdir(parents=True)
            np.savez_compressed(dest / "raw-segment-heads.npz", **raw)
            np.savez_compressed(dest / "library-framewise-output.npz", **library["output_dict"])
            (dest / "library-events.json").write_text(json.dumps({"notes": library["est_note_events"], "pedal": library["est_pedal_events"]}, indent=2, default=float))
            (dest / "canonical-baseline.json").write_text(json.dumps(canonical, indent=2))
            meta = {"createdAt": datetime.now(timezone.utc).isoformat(), "audioSha256": case["audioSha256"],
                    "modelSha256": MODEL_SHA, "upstreamSourceSha256": source_hashes,
                    "duration": duration, "runtimeSeconds": time.perf_counter()-start,
                    "segments": len(raw["frame_output"]), "outputFrames": len(library["output_dict"]["frame_output"]),
                    "modelParameters": {"onset": .3, "offset": .3, "frame": .1, "pedal_offset": .2},
                    "outputSha256": {p.name: sha256(p) for p in dest.iterdir() if p.is_file()}}
            assert datetime.fromisoformat(meta["createdAt"]) > datetime.fromisoformat(manifest["frozenAt"])
            (dest / "provenance.json").write_text(json.dumps(meta, indent=2))
            print(f"Captured {len(canonical)} notes, {meta['segments']} segments, {meta['runtimeSeconds']:.3f}s", flush=True)
    finally:
        if binding is not None:
            binding.hook.remove()


def runtime_decisions(case):
    """No reference timing/MIDI is loaded or used here."""
    dest = CACHE / case["name"]
    meta, events = read_json(dest / "provenance.json"), read_json(dest / "library-events.json")
    with np.load(dest / "library-framewise-output.npz") as file:
        matrices = {key: file[key] for key in file.files}
    duration = meta["duration"]
    audio, rate = sf.read(ROOT / case["audio"], always_2d=True)
    silence = terminal_silence_start(audio, rate)
    canonical = read_json(dest / "canonical-baseline.json")
    sorted_events = sorted((e for e in events["notes"] if e["onset_time"] < duration),
                           key=lambda e: (e["onset_time"], e["midi_note"], min(e["offset_time"], duration)))
    assert len(canonical) == len(sorted_events)
    traced = {}
    from piano_transcription_inference.piano_vad import note_detection_with_onset_offset_regress
    for pitch in {e["midi_note"] for e in sorted_events}:
        column = pitch-21
        args = [matrices[key][:, column] for key in ("frame_output", "onset_output", "onset_shift_output", "offset_output", "offset_shift_output", "velocity_output")] + [.1]
        traces = decoder_trace(*args)
        upstream = note_detection_with_onset_offset_regress(*args)
        assert len(traces) == len(upstream)
        for trace, original in zip(traces, upstream):
            assert [trace[k] for k in ("beginFrame", "endFrame", "onsetShift", "offsetShift", "velocityRaw")] == [float(v) for v in original]
        traced[pitch] = traces
    rows = []
    for index, (event, note) in enumerate(zip(sorted_events, canonical)):
        assert event["midi_note"] == note["pitch"] and event["onset_time"] == note["startTime"]
        trace = min(traced[note["pitch"]], key=lambda t: abs(t["onsetSeconds"]-note["startTime"]))
        assert abs(trace["onsetSeconds"]-note["startTime"]) < 1e-6
        assert abs(trace["offsetSeconds"]-event["offset_time"]) < 1e-6
        following = [e["onset_time"] for e in sorted_events if e["midi_note"] == note["pitch"] and e["onset_time"] > note["startTime"]]
        result = evaluate_event(event, trace, matrices, duration, events["pedal"] or [], min(following, default=None), silence)
        assert result["A"] == note["endTime"]
        assert result["B"] <= result["A"] and result["C"] <= result["A"], "Policy unexpectedly extended an event"
        # Only A/B/C are evaluated; D is internal to frozen C, not an extra policy.
        column = note["pitch"]-21
        # Report also peaks after an upstream cap. They are not candidates in
        # frozen B's window, but are essential to diagnose a held note's release.
        upper = min(duration, min(following, default=float("inf")))
        peaks = [{"frame": int(i), "time": (int(i)+float(matrices["offset_shift_output"][i,column]))/100,
                  "score": float(matrices["reg_offset_output"][i,column]),
                  "insidePolicyWindow": (int(i)+float(matrices["offset_shift_output"][i,column]))/100 <= min(event["offset_time"],duration)+1e-6}
                 for i in np.flatnonzero(matrices["offset_output"][:,column])
                 if trace["beginFrame"] < i and (int(i)+float(matrices["offset_shift_output"][i,column]))/100 <= upper+1e-6]
        rows.append({"case": case["name"], "category": case["category"], "variant": case["variant"], "predictionIndex": index,
                     "pitch": note["pitch"], "onset": note["startTime"], "upstream_offset": event["offset_time"],
                     "audio_duration": duration, "terminal_silence_start": silence,
                     "decoder_reason": trace["reason"], "decoder": trace,
                     "raw_offset_peaks": peaks, "predicted_pedal_events": events["pedal"],
                     "next_same_pitch_onset": min(following, default=None),
                     "canonical_note": note, "raw_candidate_offset": result["raw_candidate_offset"],
                     "A": result["A"], "B": result["B"], "C": result["C"],
                     "reason_B": result["reason_B"], "reason_C": result["reason_C"],
                     "gt_onset": None, "gt_key_release": None, "gt_pedal_release": None})
    return rows, {"provenance": meta, "terminalSilenceStart": silence, "pedalEvents": events["pedal"],
                  "rawOutsideAudioEvents": len(events["notes"])-len(sorted_events)}


def run(allow_inference=False):
    manifest = read_json(FIXTURES / "manifest.json")
    verify(manifest)
    capture(manifest, allow_inference)
    # All runtime decisions completed before reading independent reference notes.
    runtime = {case["name"]: runtime_decisions(case) for case in manifest["cases"]}
    all_rows, case_metrics, missing = [], [], []
    scored = {}
    for case in manifest["cases"]:
        rows, metadata = runtime[case["name"]]
        if not case.get("midi"):
            for row in rows:
                row["match"] = "diagnostic_no_ground_truth"
            all_rows.extend(rows)
            continue
        refs = read_midi(ROOT / case["midi"])
        assert len(refs) == case["groundTruthNotes"]
        scores = {}
        for policy in "ABC":
            predicted = [{**row["canonical_note"], "endTime": row[policy]} for row in rows]
            assert [(n["pitch"], n["startTime"]) for n in predicted] == [(r["pitch"], r["onset"]) for r in rows]
            scores[policy] = score(refs, predicted)
        for policy in "BC":
            for key in ("TP", "FP", "FN", "F1", "onset_TP", "onset_FP", "onset_FN", "onset_F1", "onset_mae_ms"):
                assert scores[policy][key] == scores["A"][key], "RED FLAG: pitch/onset results changed"
        matches = {m["predictionIndex"]: m["reference"] for m in scores["A"]["diagnostics"]["correct"]}
        for row in rows:
            ref = matches.get(row["predictionIndex"])
            row["match"] = "pitch_onset_match" if ref else "unmatched_prediction"
            if ref:
                row.update(gt_onset=ref["startTime"], gt_key_release=ref["endTime"], gt_pedal_release=ref["sustainEndTime"])
                for policy in "ABC":
                    row[f"key_error_{policy}"] = row[policy]-ref["endTime"]
                    row[f"pedal_error_{policy}"] = row[policy]-ref["sustainEndTime"]
                    row[f"key_state_{policy}"] = release_state(row[policy], ref["endTime"])
                    row[f"pedal_state_{policy}"] = release_state(row[policy], ref["sustainEndTime"])
                    row[f"safety_{policy}"] = safety_findings(row, policy)
        for policy in "ABC":
            metrics = enhance_metrics(scores[policy], rows, policy)
            case_metrics.append({"case": case["name"], "category": case["category"], "variant": case["variant"], "policy": policy, **metrics})
        matched_refs = {m["referenceIndex"] for m in scores["A"]["diagnostics"]["correct"]}
        missing.extend({"case": case["name"], "referenceIndex": i, **ref} for i, ref in enumerate(refs) if i not in matched_refs)
        scored[case["name"]] = scores
        all_rows.extend(rows)
    groups = {}
    # Clean and noisy copies are separate: no double counting as independent notes.
    for variant in ("clean", "noise", "all"):
        cases = [c for c in manifest["cases"] if (variant == "all" or c["variant"] == variant) and c.get("midi")]
        categories = ["TOTAL"] if variant == "all" else sorted({c["category"] for c in cases}) + ["TOTAL"]
        for category in categories:
            selected = [c for c in cases if category == "TOTAL" or c["category"] == category]
            names = {c["name"] for c in selected}
            rows = [r for r in all_rows if r["case"] in names]
            groups[f"{variant}:{category}"] = {p: enhance_metrics(aggregate([scored[c["name"]][p] for c in selected]), rows, p) for p in "ABC"}
    regressions = []
    for row in all_rows:
        if row["gt_key_release"] is None:
            continue
        for policy in "BC":
            key_worse = abs(row[policy]-row["gt_key_release"]) > abs(row["A"]-row["gt_key_release"])+1e-7
            pedal_worse = abs(row[policy]-row["gt_pedal_release"]) > abs(row["A"]-row["gt_pedal_release"])+1e-7
            if key_worse or pedal_worse or row[f"safety_{policy}"]:
                regressions.append({"case": row["case"], "predictionIndex": row["predictionIndex"], "pitch": row["pitch"], "policy": policy,
                                    "keyWorsened": key_worse, "pedalWorsened": pedal_worse, "failures": row[f"safety_{policy}"],
                                    "A": row["A"], "candidate": row[policy], "keyRelease": row["gt_key_release"], "pedalRelease": row["gt_pedal_release"]})
    noise_pairs = []
    noise_events = []
    for case in manifest["cases"]:
        if case["variant"] != "noise":
            continue
        entry = {"clean": case["parent"], "noise": case["name"]}
        for label, name in (("clean", case["parent"]), ("noise", case["name"])):
            selected = [r for r in all_rows if r["case"] == name]
            metrics = {r["policy"]: r for r in case_metrics if r["case"] == name}
            entry[label+"GuardChangedNotes"] = sum(abs(r["C"]-r["B"])>1e-7 for r in selected)
            entry[label+"GuardKeyMaeGainMs"] = metrics["B"]["offset_mae_ms"]-metrics["C"]["offset_mae_ms"] if metrics["B"]["offset_mae_ms"] is not None else None
            entry[label+"GuardEffectiveMaeGainMs"] = metrics["B"]["sustain_offset_mae_ms"]-metrics["C"]["sustain_offset_mae_ms"] if metrics["B"]["sustain_offset_mae_ms"] is not None else None
        entry["guardGainLostWithNoise"] = bool(entry["cleanGuardEffectiveMaeGainMs"] is not None and entry["cleanGuardEffectiveMaeGainMs"]>0 and entry["noiseGuardChangedNotes"] == 0)
        noise_pairs.append(entry)
        clean_rows = {(r["pitch"],r["gt_onset"]): r for r in all_rows if r["case"] == case["parent"] and r["gt_key_release"] is not None}
        for row in [r for r in all_rows if r["case"] == case["name"] and r["gt_key_release"] is not None]:
            clean = clean_rows.get((row["pitch"], row["gt_onset"]))
            if clean is None:
                continue
            for policy in "BC":
                effective = row["gt_pedal_release"]
                noise_events.append({"cleanCase": case["parent"], "noiseCase": case["name"], "pitch": row["pitch"],
                                     "gtOnset": row["gt_onset"], "gtKeyRelease": row["gt_key_release"], "gtPedalRelease": effective,
                                     "policy": policy, "cleanEnd": clean[policy], "noiseEnd": row[policy],
                                     "cleanEffectiveErrorMs": (clean[policy]-effective)*1000,
                                     "noiseEffectiveErrorMs": (row[policy]-effective)*1000,
                                     "worsensUnderNoise": abs(row[policy]-effective)>abs(clean[policy]-effective)+1e-7})
    b_fails = any(r["policy"] == "B" and r["failures"] for r in regressions)
    c_fails = any(r["policy"] == "C" and r["failures"] for r in regressions)
    c_noise_fail = any(p["guardGainLostWithNoise"] for p in noise_pairs)
    summary = {"createdAt": datetime.now(timezone.utc).isoformat(), "manifestSha256": sha256(FIXTURES / "manifest.json"),
               "policySha256": sha256(POLICY), "manifest": manifest, "groups": groups, "caseMetrics": case_metrics,
               "notes": all_rows, "regressions": regressions, "unmatchedReferences": missing,
               "noisePairs": noise_pairs,
               "noiseEventComparisons": noise_events,
               "verdicts": {"B": "DO NOT SHIP" if b_fails else "MORE VALIDATION NEEDED",
                            "C": "DO NOT SHIP" if c_fails or c_noise_fail else "MORE VALIDATION NEEDED",
                            "cNoiseReliabilityFailure": c_noise_fail},
               "runtimeMetadata": {name: item[1] for name, item in runtime.items()}}
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "bytedance-offset-independent-validation.json").write_text(json.dumps(summary, indent=2))
    from .report import render
    render(summary, REPORTS / "bytedance-offset-independent-validation.md")
    fields = ["case", "category", "variant", "match", "pitch", "onset", "gt_onset", "gt_key_release", "gt_pedal_release",
              "upstream_offset", "raw_candidate_offset", "A", "B", "C", "key_error_A", "key_error_B", "key_error_C",
              "pedal_error_A", "pedal_error_B", "pedal_error_C", "key_state_A", "key_state_B", "key_state_C",
              "pedal_state_A", "pedal_state_B", "pedal_state_C", "safety_B", "safety_C", "decoder_reason",
              "audio_duration", "terminal_silence_start", "next_same_pitch_onset", "reason_B", "reason_C", "raw_offset_peaks", "predicted_pedal_events"]
    with (REPORTS / "bytedance-offset-independent-validation-notes.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fields, extrasaction="ignore")
        writer.writeheader()
        for row in all_rows:
            writer.writerow({key: json.dumps(row[key]) if isinstance(row.get(key), (list, dict)) else row.get(key) for key in fields})
    fields = list(case_metrics[0])
    with (REPORTS / "bytedance-offset-independent-validation-metrics.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fields)
        writer.writeheader()
        writer.writerows(case_metrics)
    verify(manifest)
    print(json.dumps({"groups": groups, "regressions": regressions, "missing": missing}, indent=2), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", action="store_true", help="Capture missing unchanged model outputs on frozen audio once")
    run(parser.parse_args().capture)
