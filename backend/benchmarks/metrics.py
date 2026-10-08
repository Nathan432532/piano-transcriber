from __future__ import annotations

from collections import Counter, defaultdict
import math
from pathlib import Path
import statistics

import mido
import mir_eval
import numpy as np

ONSET_TOLERANCE = 0.05
OFFSET_RATIO = 0.2
OFFSET_MIN_TOLERANCE = 0.05


def read_midi(path: Path) -> list[dict]:
    """Read key releases and CC64-effective releases in seconds, with tempo changes."""
    active = {}
    pending = defaultdict(list)
    pedal = defaultdict(bool)
    notes = []
    seconds = 0.0
    midi = mido.MidiFile(path)
    if midi.type == 2:
        raise ValueError("Asynchronous MIDI type 2 is not supported")
    for message in midi:
        seconds += message.time
        if message.type == "control_change" and message.control == 64:
            channel = message.channel
            pedal[channel] = message.value >= 64
            if not pedal[channel]:
                for note in pending.pop(channel, []):
                    note["sustainEndTime"] = seconds
        elif message.type == "note_on" and message.velocity > 0:
            key = message.channel, message.note
            if key in active:
                raise ValueError("Overlapping same-channel/same-pitch MIDI is ambiguous")
            # A same-pitch reattack ends the preceding pedal-held logical note.
            for note in list(pending[message.channel]):
                if note["pitch"] == message.note:
                    note["sustainEndTime"] = seconds
                    pending[message.channel].remove(note)
            active[key] = {"pitch": message.note, "startTime": seconds, "velocity": message.velocity}
        elif message.type == "note_off" or (message.type == "note_on" and message.velocity == 0):
            key = message.channel, message.note
            if key not in active:
                raise ValueError("Unmatched MIDI note-off")
            note = active.pop(key)
            if seconds <= note["startTime"]:
                raise ValueError("MIDI note must have positive duration")
            note.update(endTime=seconds, sustainEndTime=seconds)
            notes.append(note)
            if pedal[message.channel]:
                pending[message.channel].append(note)
    if active:
        raise ValueError("Unclosed MIDI notes")
    if any(pending.values()):
        raise ValueError("Pedal-held reference notes need an explicit CC64 release")
    return sorted(notes, key=lambda note: (note["startTime"], note["pitch"], note["endTime"]))


def prf(tp: int, predicted: int, reference: int) -> dict:
    precision = tp / predicted if predicted else 0.0
    recall = tp / reference if reference else 0.0
    return {"TP": tp, "FP": predicted - tp, "FN": reference - tp,
            "precision": precision, "recall": recall,
            "F1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}


def arrays(notes: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    for note in notes:
        if not isinstance(note["pitch"], int) or not 0 <= note["pitch"] <= 127:
            raise ValueError("Invalid integer MIDI pitch")
        if (not math.isfinite(note["startTime"]) or not math.isfinite(note["endTime"])
                or note["startTime"] < 0 or note["endTime"] <= note["startTime"]):
            raise ValueError("Invalid note interval")
    intervals = np.array([[note["startTime"], note["endTime"]] for note in notes], dtype=float).reshape(-1, 2)
    frequencies = np.array([440 * 2 ** ((note["pitch"] - 69) / 12) for note in notes])
    return intervals, frequencies


def score(reference: list[dict], predicted: list[dict], *, velocity_reliable=False) -> dict:
    ref_intervals, ref_pitches = arrays(reference)
    est_intervals, est_pitches = arrays(predicted)
    matches = mir_eval.transcription.match_notes(
        ref_intervals, ref_pitches, est_intervals, est_pitches,
        onset_tolerance=ONSET_TOLERANCE, pitch_tolerance=1.0,
        offset_ratio=None, strict=False,
    )
    onset_matches = mir_eval.transcription.match_note_onsets(
        ref_intervals, est_intervals, onset_tolerance=ONSET_TOLERANCE, strict=False)
    offset_matches = mir_eval.transcription.match_notes(
        ref_intervals, ref_pitches, est_intervals, est_pitches,
        onset_tolerance=ONSET_TOLERANCE, pitch_tolerance=1.0,
        offset_ratio=OFFSET_RATIO, offset_min_tolerance=OFFSET_MIN_TOLERANCE, strict=False)
    ref_count, est_count = len(reference), len(predicted)
    result = {"ground_truth_notes": ref_count, "predicted_notes": est_count,
              **prf(len(matches), est_count, ref_count)}
    # A pitch-only bag-of-events score intentionally ignores all timing.
    pitch_tp = sum((Counter(n["pitch"] for n in reference) & Counter(n["pitch"] for n in predicted)).values())
    for prefix, count in (("pitch", pitch_tp), ("onset", len(onset_matches)), ("offset", len(offset_matches))):
        result.update({f"{prefix}_{key}": value for key, value in prf(count, est_count, ref_count).items()})
    onset_errors = [predicted[j]["startTime"] - reference[i]["startTime"] for i, j in matches]
    offset_errors = [predicted[j]["endTime"] - reference[i]["endTime"] for i, j in matches]
    sustain_errors = [predicted[j]["endTime"] - reference[i].get("sustainEndTime", reference[i]["endTime"])
                      for i, j in matches]
    velocity_errors = [abs(predicted[j]["velocity"] - reference[i]["velocity"]) for i, j in matches] if velocity_reliable else []
    result["errors"] = {"onset": onset_errors, "offset": offset_errors,
                        "sustain_offset": sustain_errors, "velocity": velocity_errors}
    add_error_summaries(result)
    unmatched_ref = set(range(ref_count)) - {i for i, _ in matches}
    unmatched_est = set(range(est_count)) - {j for _, j in matches}
    diagnostics = {"correct": [], "right_pitch_wrong_timing": [], "wrong_pitch": [], "missed": [], "extra": []}
    for i, j in matches:
        diagnostics["correct"].append({"referenceIndex": int(i), "predictionIndex": int(j),
                                       "reference": reference[i], "prediction": predicted[j]})
    # Diagnostic pairing does not change scores: closest same-pitch residuals
    # first, then closest residual onsets within 50 ms, then missed/extra.
    candidates = sorted((abs(predicted[j]["startTime"] - reference[i]["startTime"]), i, j)
                        for i in unmatched_ref for j in unmatched_est if reference[i]["pitch"] == predicted[j]["pitch"])
    for _, i, j in candidates:
        if i in unmatched_ref and j in unmatched_est:
            diagnostics["right_pitch_wrong_timing"].append({"reference": reference[i], "prediction": predicted[j]})
            unmatched_ref.remove(i)
            unmatched_est.remove(j)
    candidates = sorted((abs(predicted[j]["startTime"] - reference[i]["startTime"]), i, j)
                        for i in unmatched_ref for j in unmatched_est
                        if round(abs(predicted[j]["startTime"] - reference[i]["startTime"]), 4) <= ONSET_TOLERANCE)
    for _, i, j in candidates:
        if i in unmatched_ref and j in unmatched_est:
            diagnostics["wrong_pitch"].append({"reference": reference[i], "prediction": predicted[j]})
            unmatched_ref.remove(i)
            unmatched_est.remove(j)
    diagnostics["missed"] = [reference[i] for i in sorted(unmatched_ref)]
    diagnostics["extra"] = [predicted[j] for j in sorted(unmatched_est)]
    result["diagnostics"] = diagnostics
    return result


def add_error_summaries(result: dict) -> None:
    for key, values in result["errors"].items():
        scale = 1 if key == "velocity" else 1000
        result[f"{key}_mae" + ("" if key == "velocity" else "_ms")] = statistics.mean(abs(v) for v in values) * scale if values else None
        result[f"{key}_median_abs" + ("" if key == "velocity" else "_ms")] = statistics.median(abs(v) for v in values) * scale if values else None
        if key != "velocity":
            result[f"{key}_bias_ms"] = statistics.mean(values) * scale if values else None


def aggregate(results: list[dict]) -> dict:
    reference = sum(row["ground_truth_notes"] for row in results)
    predicted = sum(row["predicted_notes"] for row in results)
    total = {"ground_truth_notes": reference, "predicted_notes": predicted,
             **prf(sum(row["TP"] for row in results), predicted, reference)}
    for prefix in ("pitch", "onset", "offset"):
        total.update({f"{prefix}_{key}": value for key, value in prf(sum(row[f"{prefix}_TP"] for row in results), predicted, reference).items()})
    total["errors"] = {key: [value for row in results for value in row["errors"][key]]
                       for key in ("onset", "offset", "sustain_offset", "velocity")}
    add_error_summaries(total)
    return total
