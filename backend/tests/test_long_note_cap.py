import numpy as np
import pytest

from benchmarks.maps.experiments.long_note_cap.decoder import decode, events_for_matrices, tuples


def heads(frames=1801, start=100, disappear=None, offset=None):
    frame = np.ones(frames)
    onset, peaks = np.zeros(frames), np.zeros(frames)
    onset[start] = 1
    if disappear is not None:
        frame[disappear:] = 0
    if offset is not None:
        peaks[offset] = 1
    return frame, onset, np.zeros(frames), peaks, np.zeros(frames), np.ones(frames) * .5, .1


def test_short_note_identical_for_all_caps():
    values = heads(disappear=350, offset=340)
    expected = decode(*values, 600)
    assert expected[0]["endFrame"] == 340
    for cap in (1200, 3000, None):
        assert decode(*values, cap) == expected


@pytest.mark.parametrize("disappear,expected,reason", [(699, 699, "frame_disappearance"),
    (700, 700, "frame_disappearance"), (701, 700, "maximum_duration_cap")])
def test_frame_disappearance_precedes_cap_check_at_exact_boundary(disappear, expected, reason):
    result = decode(*heads(disappear=disappear), 600)[0]
    assert result["endFrame"] == expected and result["reason"] == reason


def test_long_note_only_duration_cap_changes():
    values = heads(disappear=1600, offset=1590)
    assert [decode(*values, cap)[0]["endFrame"] for cap in (600, 1200, 3000, None)] == [700, 1300, 1590, 1590]
    assert all(decode(*values, cap)[0]["beginFrame"] == 100 for cap in (600, 1200, 3000, None))


def test_repeated_onset_closes_previous_before_next_start_for_every_cap():
    values = heads()
    values[1][500] = 1
    for cap in (600, 1200, 3000, None):
        first, second = decode(*values, cap)
        assert first["endFrame"] == 499 and first["reason"] == "next_onset"
        assert second["beginFrame"] == 500


def test_continuing_activation_is_bounded_by_available_output_without_cap():
    values = heads(frames=1001, offset=200)
    result = decode(*values, None)[0]
    assert result["firstOffsetFrame"] == 200
    assert result["endFrame"] == 1000 and result["reason"] == "sequence_end"


def test_audio_end_clipping_reuses_production_normalizer_without_decoder_trim():
    from app.bytedance_adapter import normalize_bytedance_notes
    values = heads(frames=1001)
    keys = ("frame_output", "onset_output", "onset_shift_output", "offset_output", "offset_shift_output", "velocity_output")
    matrices = {k: np.zeros((1001, 88)) for k in keys}
    for key, value in zip(keys, values[:6]):
        matrices[key][:, 39] = value
    matrices["reg_onset_output"] = np.ones((1001, 88))
    events, _ = events_for_matrices(matrices, None)
    assert events[0]["offset_time"] == 10
    note = normalize_bytedance_notes({"est_note_events": events, "output_dict": matrices}, 8)[0]
    assert note["pitch"] == 60 and note["endTime"] == 8


def test_joined_segments_do_not_reset_no_cap_note_at_seam():
    # A deframed sequence has joins at 750 and 1250; no decoder reset there.
    result = decode(*heads(frames=2000, disappear=1700, offset=1690), None)[0]
    assert result["beginFrame"] == 100 and result["endFrame"] == 1690


def test_actual_deframe_selects_chunks_without_averaging_overlap():
    from piano_transcription_inference.inference import PianoTranscription
    raw = np.stack([np.full((1001, 1), value) for value in (.9, .002, .4)])
    joined = PianoTranscription.deframe(None, raw)
    assert joined.shape == (2000, 1)
    assert joined[749, 0] == .9 and joined[750, 0] == .002
    assert joined[1249, 0] == .002 and joined[1250, 0] == .4


def test_pitches_end_independently_in_chord():
    keys = ("frame_output", "onset_output", "onset_shift_output", "offset_output", "offset_shift_output", "velocity_output")
    matrices = {key: np.zeros((1801, 88)) for key in keys}
    for column, end in ((39, 350), (43, 1600)):
        for key, value in zip(keys, heads(disappear=end)[:6]):
            matrices[key][:, column] = value
    events, _ = events_for_matrices(matrices, None)
    assert [(e["midi_note"], e["offset_time"]) for e in events] == [(60, 3.5), (64, 16)]


def test_instrumented_baseline_matches_actual_installed_decoder_on_random_heads():
    from piano_transcription_inference.piano_vad import note_detection_with_onset_offset_regress
    rng = np.random.default_rng(1904)
    for _ in range(12):
        frame = rng.random(1600)
        onset = (rng.random(1600) < .008).astype(float)
        offset = (rng.random(1600) < .015).astype(float)
        args = (frame, onset, rng.uniform(-.5, .5, 1600), offset, rng.uniform(-.5, .5, 1600), rng.random(1600), .1)
        assert tuples(decode(*args, 600)) == [list(map(float, row)) for row in note_detection_with_onset_offset_regress(*args)]
