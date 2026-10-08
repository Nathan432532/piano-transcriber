import numpy as np
import pytest

from benchmarks.experiments.offset_policy.policies import evaluate_event, terminal_silence_start


def inputs(*, peak=400, reason="frame_disappearance", end=5.01, onset=3.5):
    matrices = {"offset_output": np.zeros((1001, 88)), "offset_shift_output": np.zeros((1001, 88))}
    if peak is not None:
        matrices["offset_output"][peak, 71 - 21] = 1
    return {"midi_note": 71, "onset_time": onset, "offset_time": end}, {
        "beginFrame": round(onset * 100), "endFrame": round(end * 100), "reason": reason}, matrices


def evaluate(values=None, *, pedal=None, next_onset=None, silence=None, duration=8):
    return evaluate_event(*(values or inputs()), duration, pedal or [], next_onset, silence)


def test_usable_accepted_peak_replaces_delayed_frame_end():
    result = evaluate()
    assert result["A"] == result["D"] == 5.01
    assert result["B"] == result["C"] == result["raw_candidate_offset"] == 4


@pytest.mark.parametrize("peak", [349, 350, 600])
def test_peak_before_onset_at_onset_or_after_decoded_window_is_ignored(peak):
    result = evaluate(inputs(peak=peak))
    assert result["B"] == result["A"]
    assert result["raw_candidate_offset"] is None


def test_raw_score_without_upstream_accepted_peak_is_not_rethresholded():
    values = inputs(peak=None)
    values[2]["reg_offset_output"] = np.ones((1001, 88))
    assert evaluate(values)["raw_candidate_offset"] is None


def test_predicted_sustain_blocks_key_release_peak_and_uses_later_peak():
    values = inputs(end=5.2)
    values[2]["offset_output"][505, 50] = 1
    result = evaluate(values, pedal=[{"onset_time": 3, "offset_time": 5}])
    assert result["B"] == 5.05


def test_sustain_without_usable_later_peak_keeps_upstream():
    result = evaluate(pedal=[{"onset_time": 3, "offset_time": 5}])
    assert result["B"] == result["A"]
    assert result["reason_B"] == "predicted_pedal_blocks_peaks"


def test_runaway_boundary_is_bounded_by_observed_terminal_silence():
    result = evaluate(inputs(peak=None, reason="six_second_cap", end=9.5), silence=5.6)
    assert result["A"] == result["B"] == 8
    assert result["C"] == result["D"] == 5.6


def test_sequence_boundary_is_also_identifiable_without_a_new_duration_cap():
    result = evaluate(inputs(peak=None, reason="sequence_end", end=10), silence=6)
    assert result["D"] == 6


def test_long_boundary_note_without_exact_silence_is_flagged_but_preserved():
    result = evaluate(inputs(peak=None, reason="six_second_cap", end=9.5), duration=12)
    assert result["D"] == 9.5
    assert result["decoder_boundary"]


def test_correct_normal_note_is_not_cut_by_guard():
    values = inputs(peak=400, end=4, reason="offset_peak_after_midpoint")
    result = evaluate(values, silence=3.8)
    assert all(result[p] == 4 for p in "ABCD")


def test_repeated_notes_never_merge_or_steal_next_event_peak():
    event, trace, matrices = inputs()
    result = evaluate((event, trace, matrices), next_onset=4)
    assert result["raw_candidate_offset"] is None
    assert event == {"midi_note": 71, "onset_time": 3.5, "offset_time": 5.01}


def test_other_chord_pitch_peak_does_not_change_this_pitch():
    values = inputs(peak=None)
    values[2]["offset_output"][400, 65 - 21] = 1
    assert evaluate(values)["B"] == 5.01


def test_same_upstream_peak_float32_rounding_preserves_original_endpoint():
    values = inputs(peak=400, end=4.001, reason="offset_peak_after_midpoint")
    values[2]["offset_shift_output"][400, 50] = .100002
    result = evaluate(values)
    assert result["raw_candidate_offset"] > result["A"]
    assert result["B"] == result["C"] == result["A"]


def test_exact_terminal_silence_considers_both_channels_without_epsilon():
    audio = np.zeros((10, 2))
    audio[4, 1] = 1e-30
    assert terminal_silence_start(audio, 10) == .5
    audio[-1, 0] = 1e-30
    assert terminal_silence_start(audio, 10) is None
    assert terminal_silence_start(np.zeros((10, 2)), 10) is None


def test_silence_at_or_before_onset_cannot_make_invalid_note():
    values = inputs(peak=None, reason="sequence_end", end=10)
    assert evaluate(values, silence=3.5)["D"] == 8


def test_an_accepted_spurious_peak_can_cut_a_correct_long_note_early():
    # Deliberate counterexample: runtime evidence cannot tell that this accepted
    # in-window peak is spurious. This records the candidate's known limitation.
    values = inputs(peak=100, onset=.5, end=5)
    assert evaluate(values)["B"] == 1
    assert evaluate(values)["A"] == 5


def test_missing_pedal_prediction_leaves_an_early_peak_unprotected():
    values = inputs(peak=400, onset=3.5, end=5.2)
    assert evaluate(values, pedal=[])["B"] == 4
    assert evaluate(values, pedal=[{"onset_time": 3, "offset_time": 5}])["B"] == 5.2


def test_guard_is_acoustic_bound_not_key_release_for_a_silently_held_note():
    # A legitimate key can stay held after a sampled instrument has decayed to
    # digital zero. Boundary provenance + silence cannot recover physical release.
    values = inputs(peak=None, onset=.5, end=6.5, reason="six_second_cap")
    assert evaluate(values, silence=5)["D"] == 5
