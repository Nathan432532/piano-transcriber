"""Scoring-only helpers. References never enter inference or offset policies."""
from __future__ import annotations

import statistics

from benchmarks.metrics import ONSET_TOLERANCE

# Fixed before inference: existing 50 ms tolerance, used for safety reporting,
# not as a model threshold. Standard offset-F1 keeps its original 20% rule.
RELEASE_TOLERANCE = ONSET_TOLERANCE


def release_state(end, release):
    delta = end - release
    if delta < -RELEASE_TOLERANCE:
        return "early"
    if delta > RELEASE_TOLERANCE:
        return "late"
    return "correct"


def safety_findings(row, policy):
    """Fail predicates on matched notes only; no changes to runtime outputs."""
    key, pedal = row["gt_key_release"], row["gt_pedal_release"]
    if key is None:
        return []
    a, candidate = row["A"], row[policy]
    changed = abs(candidate - a) > 1e-7
    if not changed:
        return []
    findings = []
    if row["category"] == "long" and release_state(a, key) == "correct" and release_state(candidate, key) == "early":
        findings.append("FAIL_correct_long_note_cut_early")
    if pedal > key + 1e-9 and candidate < a and abs(candidate-pedal) > abs(a-pedal) + RELEASE_TOLERANCE:
        findings.append("FAIL_sustain_pedal_error_worsens_after_early_move")
    target = pedal if pedal > key + 1e-9 else key
    if candidate < a and release_state(candidate, target) == "early":
        findings.append("FAIL_changed_offset_before_independent_release")
    return findings


def enhance_metrics(metrics, rows, policy):
    result = {k: v for k, v in metrics.items() if k not in {"diagnostics", "errors"}}
    matched = [r for r in rows if r["gt_key_release"] is not None]
    sustain = [r for r in matched if r["gt_pedal_release"] > r["gt_key_release"] + 1e-9]
    result.update(
        changed_offsets=sum(abs(r[policy]-r["A"]) > 1e-7 for r in rows),
        early_key_offsets=sum(release_state(r[policy], r["gt_key_release"]) == "early" for r in matched),
        late_key_offsets=sum(release_state(r[policy], r["gt_key_release"]) == "late" for r in matched),
        early_effective_offsets=sum(release_state(r[policy], r["gt_pedal_release"]) == "early" for r in matched),
        late_effective_offsets=sum(release_state(r[policy], r["gt_pedal_release"]) == "late" for r in matched),
        max_offset_error_ms=max((abs(r[policy]-r["gt_key_release"])*1000 for r in matched), default=None),
        max_pedal_error_ms=max((abs(r[policy]-r["gt_pedal_release"])*1000 for r in matched), default=None),
        sustain_matched_notes=len(sustain),
        sustain_key_mae_ms=statistics.mean(abs(r[policy]-r["gt_key_release"])*1000 for r in sustain) if sustain else None,
        sustain_pedal_mae_ms=statistics.mean(abs(r[policy]-r["gt_pedal_release"])*1000 for r in sustain) if sustain else None,
        worsened_key_notes=sum(abs(r[policy]-r["gt_key_release"]) > abs(r["A"]-r["gt_key_release"])+1e-7 for r in matched),
        worsened_pedal_notes=sum(abs(r[policy]-r["gt_pedal_release"]) > abs(r["A"]-r["gt_pedal_release"])+1e-7 for r in matched),
        improved_key_notes=sum(abs(r[policy]-r["gt_key_release"]) < abs(r["A"]-r["gt_key_release"])-1e-7 for r in matched),
        improved_pedal_notes=sum(abs(r[policy]-r["gt_pedal_release"]) < abs(r["A"]-r["gt_pedal_release"])-1e-7 for r in matched),
        safety_fail_notes=sum(bool(safety_findings(r, policy)) for r in matched),
        audio_boundary_notes=sum(r[policy] == r["audio_duration"] for r in rows),
    )
    return result
