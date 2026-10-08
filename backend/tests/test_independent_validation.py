import json

import numpy as np
import pytest
import soundfile as sf

from benchmarks.metrics import read_midi, score
from benchmarks.prepare import PLANS as ORIGINAL_PLANS, sha256, write_midi
from benchmarks.experiments.independent_validation.prepare import (
    PLANS, FIXTURES, POLICY, POLICY_SHA, NOISE_CASES, add_noise, validate_plans,
)
from benchmarks.experiments.independent_validation.assessment import release_state, safety_findings, enhance_metrics
from benchmarks.experiments.offset_policy.policies import terminal_silence_start


def test_holdout_plan_coverage_and_independence():
    validate_plans()
    assert sum(len(p["notes"]) for p in PLANS.values()) == 17
    assert {p["category"] for p in PLANS.values()} == {"long", "sustain", "repeated", "overlap"}
    assert all(p["notes"] != original["notes"] for p in PLANS.values() for original in ORIGINAL_PLANS.values())


@pytest.mark.parametrize("name", list(PLANS))
def test_independent_midi_round_trip_and_byte_reproducibility(name, tmp_path):
    plan = PLANS[name]
    a, b = tmp_path / "a.mid", tmp_path / "b.mid"
    write_midi(a, plan)
    write_midi(b, plan)
    assert a.read_bytes() == b.read_bytes()
    refs = read_midi(a)
    assert len(refs) == len(plan["notes"])
    expected = sorted(plan["notes"], key=lambda n: (n[1], n[0], n[2]))
    for ref, (pitch, start, end, velocity) in zip(refs, expected):
        assert ref["pitch"] == pitch and ref["velocity"] == velocity
        assert ref["startTime"] == pytest.approx(start, abs=1/960)
        assert ref["endTime"] == pytest.approx(end, abs=1/960)
        assert ref["sustainEndTime"] >= ref["endTime"]


def test_pedal_reattack_reference_is_independent_and_preserves_two_notes(tmp_path):
    path = tmp_path / "pedal.mid"
    write_midi(path, PLANS["pedal_reattack"])
    first, second = read_midi(path)
    assert first["endTime"] == pytest.approx(.8)
    assert first["sustainEndTime"] == pytest.approx(1.8)
    assert second["endTime"] == pytest.approx(2.2)
    assert second["sustainEndTime"] == pytest.approx(3.8)


def test_noise_is_fixed_signal_independent_and_survives_pcm24(tmp_path):
    source = np.zeros((44100, 2))
    changed_source = source.copy()
    changed_source[100:200] = .01
    first = add_noise(source, 20261007)
    assert np.array_equal(first, add_noise(source, 20261007))
    assert np.allclose(add_noise(changed_source, 20261007)-changed_source, first, atol=1e-18)
    assert np.sqrt(np.mean(first*first, axis=0)) == pytest.approx([10**(-70/20)]*2)
    path = tmp_path / "noise.wav"
    sf.write(path, first, 44100, subtype="PCM_24")
    saved, rate = sf.read(path, always_2d=True)
    assert rate == 44100 and terminal_silence_start(saved, rate) is None


def test_existing_policy_and_frozen_midi_are_not_retuned():
    assert sha256(POLICY) == POLICY_SHA
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    assert manifest["policySha256"] == POLICY_SHA
    for case in manifest["cases"]:
        if case.get("midi"):
            from benchmarks.prepare import ROOT
            assert sha256(ROOT / case["midi"]) == case["midiSha256"]
    for name, (parent, _) in NOISE_CASES.items():
        clean = next(c for c in manifest["cases"] if c["name"] == parent)
        noise = next(c for c in manifest["cases"] if c["name"] == name)
        assert clean["midiSha256"] == noise["midiSha256"]
        assert clean["sampleCount"] == noise["sampleCount"]


def note_row(**overrides):
    return {"category": "long", "gt_key_release": 5., "gt_pedal_release": 5.,
            "A": 5., "B": 4., "C": 4., "audio_duration": 8., **overrides}


def test_correct_long_note_cut_early_is_a_failure():
    row = note_row()
    assert "FAIL_correct_long_note_cut_early" in safety_findings(row, "B")
    assert "FAIL_changed_offset_before_independent_release" in safety_findings(row, "B")


def test_sustain_key_improvement_cannot_hide_pedal_regression():
    row = note_row(category="sustain", gt_key_release=1., gt_pedal_release=5., A=5., B=1.01)
    assert abs(row["B"]-row["gt_key_release"]) < abs(row["A"]-row["gt_key_release"])
    assert "FAIL_sustain_pedal_error_worsens_after_early_move" in safety_findings(row, "B")


def test_existing_early_baseline_is_separate_from_new_policy_harm():
    row = note_row(A=4., B=4., C=4.)
    assert release_state(row["A"], row["gt_key_release"]) == "early"
    assert safety_findings(row, "B") == []


def test_scoring_keeps_false_positives_misses_and_empty_offset_errors_visible():
    refs = [{"pitch": 60, "startTime": 1., "endTime": 2., "sustainEndTime": 2.}]
    predictions = [{"pitch": 61, "startTime": 1., "endTime": 2.}]
    metrics = score(refs, predictions)
    rows = [note_row(gt_key_release=None, gt_pedal_release=None, A=2., B=1.8, C=1.8)]
    result = enhance_metrics(metrics, rows, "B")
    assert (result["TP"], result["FP"], result["FN"]) == (0, 1, 1)
    assert result["offset_mae_ms"] is None and result["max_offset_error_ms"] is None
    assert result["changed_offsets"] == 1 and result["early_key_offsets"] == 0
