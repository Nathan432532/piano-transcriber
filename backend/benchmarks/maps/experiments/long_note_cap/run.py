"""Replay cap variants on verified MAPS heads, with unchanged app normalization."""
from __future__ import annotations

import argparse
import csv
import importlib.metadata
import inspect
import json
from pathlib import Path
import time

import numpy as np

from app.bytedance_adapter import normalize_bytedance_notes
from benchmarks.metrics import read_midi
from benchmarks.maps.dataset import MANIFEST, resolve_root, verify
from benchmarks.maps.evaluate import extended_aggregate, validated_cache
from benchmarks.maps.scoring import evaluate, match_rows, onset_window
from benchmarks.prepare import sha256
from .decoder import decode, events_for_matrices, tuples

TARGETED = ("01_isolated", "02_isolated", "04_isolated", "05_long", "06_long", "07_long",
            "08_long", "09_long", "10_repeated", "13_sustain", "16_chords")
VARIANTS = {"A_600": 600, "B_1200": 1200, "C_3000": 3000, "D_no_cap": None}


def seam_observations(cache):
    """Compare the same physical times in overlapping raw segments, no GT."""
    observations = []
    for case, pitch in (("07_long", 82), ("08_long", 62), ("09_long", 31)):
        with np.load(cache / "predictions/bytedance" / case / "raw-segment-heads.npz") as raw:
            for seconds in (6.5, 7.49, 7.5, 7.51, 8., 9.):
                i, j, column = round(seconds * 100), round((seconds - 5) * 100), pitch - 21
                row = {"case": case, "pitch": pitch, "globalTime": seconds,
                       "segment0LocalFrame": i, "segment1LocalFrame": j}
                for field, key in (("Frame", "frame_output"), ("Onset", "reg_onset_output"), ("Offset", "reg_offset_output")):
                    row["segment0" + field] = float(raw[key][0, i, column])
                    row["segment1" + field] = float(raw[key][1, j, column])
                observations.append(row)
    return observations


def dump(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def run(root, cache, output, stage):
    root = resolve_root(root)
    manifest = json.loads(MANIFEST.read_text())
    verify(root, manifest)
    assert importlib.metadata.version("piano-transcription-inference") == "0.0.6"
    from piano_transcription_inference import config, inference, models, piano_vad, utilities
    assert config.sample_rate == 16000 and config.frames_per_second == 100
    fps = config.frames_per_second
    if stage == "full":
        gate = json.loads((output / "targeted-summary.json").read_text())
        assert gate["manifestSha256"] == sha256(MANIFEST)
        assert gate["fullReplayPlausible"], "Targeted gate does not support a full replay"
    output.mkdir(parents=True, exist_ok=True)
    cases = [c for c in manifest["cases"] if stage == "full" or c["caseId"] in TARGETED]
    results, rows, changes, details, proofs = [], [], [], [], []
    start = time.perf_counter()
    previous = json.loads((cache / "maps-enstdkcl-summary.json").read_text())
    assert previous["manifestSha256"] == sha256(MANIFEST)
    for case in cases:
        transcript, meta, _ = validated_cache("bytedance", case, root, cache)
        assert meta["manifestSha256"] == sha256(MANIFEST)
        for module in (inference, models, piano_vad, utilities):
            path = Path(inspect.getfile(module))
            assert sha256(path) == meta["identity"]["adapterAndDecoderSha256"][path.name]
        directory = cache / "predictions/bytedance" / case["caseId"]
        with np.load(directory / "library-framewise-output.npz") as loaded:
            matrices = {k: loaded[k] for k in loaded.files}
        duration = transcript["source"]["duration"]
        events = json.loads((directory / "library-events.json").read_text())
        baseline_events, baseline_traces = events_for_matrices(matrices, 600, fps)
        # Exact baseline equivalence against real installed decoder, all 88 keys.
        for column in range(88):
            values = [matrices[k][:, column] for k in ("frame_output", "onset_output", "onset_shift_output",
                      "offset_output", "offset_shift_output", "velocity_output")]
            assert tuples(decode(*values, .1, 600)) == [list(map(float, row)) for row in
                piano_vad.note_detection_with_onset_offset_regress(*values, .1)]
        assert baseline_events == events["notes"]
        normalized = normalize_bytedance_notes({"est_note_events": baseline_events, "output_dict": matrices}, duration)
        assert normalized == transcript["notes"], "Offline A must equal frozen canonical output exactly"
        # Prove raw segment heads are available and exactly match deframed cache.
        with np.load(directory / "raw-segment-heads.npz") as raw:
            samples = round(duration * 16000)
            segment_count = raw["frame_output"].shape[0]
            for key in raw.files:
                assert np.array_equal(inference.PianoTranscription.deframe(None, raw[key].copy())[:samples], matrices[key])
        proofs.append({"case": case["caseId"], "baselineExact": True, "rawDeframeExact": True,
                       "segmentCount": segment_count, "outputFrames": len(matrices["frame_output"]),
                       "audioDuration": duration, "cacheProvenanceSha256": sha256(directory / "provenance.json")})
        window = case["evaluationOnsetWindowSeconds"]
        reference = onset_window(read_midi(root / case["midi"]), window)
        baseline = onset_window(normalized, window)
        baseline_by_identity = {(n["pitch"], n["startTime"]): n for n in baseline}
        assert len(baseline_by_identity) == len(baseline)
        metrics_a = evaluate(reference, baseline, duration)
        existing = next(r for r in previous["cases"] if r["case"] == case["caseId"] and r["engine"] == "bytedance")
        for key in ("TP", "FP", "FN", "F1", "onset_mae_ms", "offset_mae_ms", "sustain_offset_mae_ms"):
            assert metrics_a[key] == existing[key]
        for variant, cap in VARIANTS.items():
            decoded, traces = events_for_matrices(matrices, cap, fps)
            canonical = normalize_bytedance_notes({"est_note_events": decoded, "output_dict": matrices}, duration)
            predictions = onset_window(canonical, window)
            assert [(n["pitch"], n["startTime"], n["velocity"], n["confidence"]) for n in canonical] == [
                (n["pitch"], n["startTime"], n["velocity"], n["confidence"]) for n in normalized]
            score = evaluate(reference, predictions, duration)
            for key in ("TP", "FP", "FN", "precision", "recall", "F1", "onset_mae_ms"):
                assert score[key] == metrics_a[key]
            score.update(case=case["caseId"], category=case["category"], variant=variant,
                         capFrames=cap, changed_offsets=sum(n["endTime"] != a["endTime"] for n, a in zip(predictions, baseline)),
                         upstreamBeyondAudio=sum(e["onset_time"] < duration < e["offset_time"] for e in decoded),
                         canonicalBeyondAudio=sum(n["endTime"] > duration for n in canonical))
            results.append(score)
            trace_by_identity = {(e["midi_note"], e["onset_time"]): t for e, t in zip(decoded, traces)}
            matched_rows = match_rows(reference, predictions, score, duration)
            for row in matched_rows:
                row.update(case=case["caseId"], category=case["category"], variant=variant)
                rows.append(row)
                if row["predictionIndex"] is None:
                    continue
                note = predictions[row["predictionIndex"]]
                identity = (note["pitch"], note["startTime"])
                a = baseline_by_identity[identity]
                trace = trace_by_identity[identity]
                if variant != "A_600" and a["endTime"] != note["endTime"]:
                    changes.append({**row, "baselineEnd": a["endTime"],
                        "baselineKeyError": None if row["key_error"] is None else a["endTime"] - row["gt_key_release"],
                        "baselineEffectiveError": None if row["pedal_error"] is None else a["endTime"] - row["gt_pedal_release"],
                        "keyWorsenedOver50ms": row["key_error"] is not None and abs(row["key_error"]) > abs(a["endTime"] - row["gt_key_release"]) + .05,
                        "effectiveWorsenedOver50ms": row["pedal_error"] is not None and abs(row["pedal_error"]) > abs(a["endTime"] - row["gt_pedal_release"]) + .05,
                        "wasCorrectKeyNowWrong": row["key_error"] is not None and abs(a["endTime"] - row["gt_key_release"]) <= .05 < abs(row["key_error"]),
                        "decoder": trace["reason"]})
                # Labels are used only here, after global decoding and matching.
                if stage == "targeted" and row["match"] == "TP":
                    column = row["pitch"] - 21
                    begin = trace["beginFrame"]
                    key_frame = round(row["gt_key_release"] * fps)
                    observations = []
                    for name, index in (("onset", begin), ("sixSecondPoint", begin + 600),
                                        ("keyRelease", key_frame), ("decoderEnd", trace["endFrame"])):
                        if index < len(matrices["frame_output"]):
                            observations.append({"landmark": name, "frame": index,
                                "time": index / fps, "frameActivation": float(matrices["frame_output"][index, column]),
                                "offsetRegression": float(matrices["reg_offset_output"][index, column]),
                                "acceptedOffset": bool(matrices["offset_output"][index, column])})
                    after = matrices["frame_output"][begin+601:min(key_frame, len(matrices["frame_output"])), column]
                    peaks = [{"frame": int(i), "time": (int(i) + float(matrices["offset_shift_output"][i, column])) / fps,
                              "regression": float(matrices["reg_offset_output"][i, column])}
                             for i in np.flatnonzero(matrices["offset_output"][:, column]) if i > begin]
                    detail = {**row, "audioDuration": duration, "trueKeyDuration": row["gt_key_release"] - row["gt_onset"],
                              "decoder": trace, "rawOffset": (trace["endFrame"] + trace["offsetShift"]) / fps,
                              "canonicalEnd": note["endTime"], "clipped": (trace["endFrame"] + trace["offsetShift"]) / fps > duration,
                              "frameAfterCap": {"samples": len(after), "min": float(after.min()) if len(after) else None,
                                 "max": float(after.max()) if len(after) else None,
                                 "fractionAboveThreshold": float(np.mean(after > .1)) if len(after) else None},
                              "headLandmarks": observations, "acceptedOffsetPeaks": peaks,
                              "segmentJoinFrameCenters": [750 + 500*i for i in range(max(0, segment_count - 1))]}
                    details.append(detail)
            mae = score["offset_mae_ms"]
            print(stage, case["caseId"], variant, "key MAE", None if mae is None else round(mae, 3), flush=True)
    groups = {}
    for category in sorted({r["category"] for r in results}) + ["TOTAL"]:
        groups[category] = {}
        for variant in VARIANTS:
            selected = [r for r in results if r["variant"] == variant and (category == "TOTAL" or r["category"] == category)]
            total = extended_aggregate(selected, [])
            subset_changes = [r for r in changes if r["variant"] == variant and (category == "TOTAL" or r["category"] == category)]
            for flag in ("keyWorsenedOver50ms", "effectiveWorsenedOver50ms", "wasCorrectKeyNowWrong"):
                total[flag] = sum(r[flag] for r in subset_changes)
            total["upstreamBeyondAudio"] = sum(r["upstreamBeyondAudio"] for r in selected)
            total["canonicalBeyondAudio"] = sum(r["canonicalBeyondAudio"] for r in selected)
            groups[category][variant] = total
    plausible = any(groups["long"][v]["offset_mae_ms"] < groups["long"]["A_600"]["offset_mae_ms"] and
                    groups["TOTAL"][v]["canonicalBeyondAudio"] == 0 for v in VARIANTS if v != "A_600")
    summary = {"stage": stage, "manifestSha256": sha256(MANIFEST), "variants": VARIANTS,
               "caseIds": [c["caseId"] for c in cases], "decoderSha256": sha256(Path(__file__).with_name("decoder.py")),
               "cache": str(cache.resolve()), "groups": groups, "cases": results, "notes": rows,
               "changes": changes, "traces": details, "proofs": proofs,
               "fullReplayPlausible": plausible, "offlineReplaySeconds": time.perf_counter() - start}
    dump(output / (stage + "-summary.json"), summary)
    if stage == "targeted":
        dump(output / "segment-seam-observations.json", seam_observations(cache))
    for filename, records in (("results", results), ("notes", rows), ("changes", changes)):
        fields = [k for k in records[0] if k not in ("errors", "diagnostics")] if records else []
        with (output / f"{stage}-{filename}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)
    print("FULL_REPLAY_PLAUSIBLE", plausible, "runtime", summary["offlineReplaySeconds"], flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--stage", required=True, choices=("targeted", "full"))
    args = parser.parse_args()
    run(args.dataset_root, args.cache, args.output, args.stage)
