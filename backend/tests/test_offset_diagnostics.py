import numpy as np

from benchmarks.offset_helpers import decoder_trace, padding_info


def heads(frames=1001, onset_index=350, offset_index=400, disappear_index=501):
    frame = np.ones(frames)
    if disappear_index is not None:
        frame[disappear_index:] = 0
    onset, offset = np.zeros(frames), np.zeros(frames)
    onset[onset_index] = 1
    if offset_index is not None:
        offset[offset_index] = 1
    return frame, onset, np.zeros(frames), offset, np.zeros(frames), np.ones(frames), .1


def test_offset_peak_before_midpoint_is_not_final_note_end():
    trace = decoder_trace(*heads())[0]
    assert trace["firstOffsetFrame"] == 400
    assert trace["firstFrameDisappear"] == 501
    assert trace["reason"] == "frame_disappearance"
    assert trace["offsetSeconds"] == 5.01


def test_offset_peak_after_midpoint_is_used_once_frame_disappears():
    trace = decoder_trace(*heads(offset_index=500, disappear_index=510))[0]
    assert trace["reason"] == "offset_peak_after_midpoint"
    assert trace["offsetSeconds"] == 5


def test_continuing_frame_activation_hits_six_second_cap_despite_offset_peak():
    trace = decoder_trace(*heads(onset_index=390, offset_index=415, disappear_index=None))[0]
    assert trace["firstOffsetFrame"] == 415
    assert trace["firstFrameDisappear"] is None
    assert trace["reason"] == "six_second_cap"
    assert trace["offsetSeconds"] == 9.9


def test_last_frame_closes_note_without_offset_or_frame_disappearance():
    trace = decoder_trace(*heads(frames=500, onset_index=100, offset_index=None, disappear_index=None))[0]
    assert trace["reason"] == "sequence_end"
    assert trace["offsetSeconds"] == 4.99


def test_repeated_onset_closes_previous_note_at_preceding_frame():
    values = heads(frames=500, onset_index=100, offset_index=None, disappear_index=None)
    values[1][200] = 1
    traces = decoder_trace(*values)
    assert traces[0]["reason"] == "next_onset"
    assert traces[0]["endFrame"] == 199
    assert traces[1]["beginFrame"] == 200


def test_padding_distinguishes_sample_count_from_frame_count():
    info = padding_info(128918, 355328, 44100, 1001)
    assert info["paddingSamples"] == 31082
    assert info["lastCenterInsideAudio"] == 805
    assert info["lastOutputFrame"] == 1000
    assert info["sampleCountUsedAsFrameSlice"] is True
