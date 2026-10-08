"""Instrumented reproduction of piano_vad 0.0.6; only cap is configurable.

Original project: qiuqiangkong/piano_transcription_inference (MIT).
Preserves its truthiness checks, offset midpoint rule, next-onset closure and
last-output-frame stop. No pedal, onset or frame threshold policy is added.
"""
from __future__ import annotations

import numpy as np


def decode(frame, onset, onset_shift, offset, offset_shift, velocity,
           threshold, cap_frames=600):
    if cap_frames is not None and (type(cap_frames) is not int or cap_frames <= 0):
        raise ValueError("cap_frames must be a positive integer or None")
    traces = []
    bgn = frame_disappear = offset_occur = None

    def emit(fin, shift, reason):
        traces.append({"beginFrame": int(bgn), "endFrame": int(fin),
                       "onsetShift": float(onset_shift[bgn]), "offsetShift": float(shift),
                       "velocityRaw": float(velocity[bgn]), "reason": reason,
                       "firstOffsetFrame": None if offset_occur is None else int(offset_occur),
                       "firstFrameDisappear": None if frame_disappear is None else int(frame_disappear)})

    for i in range(len(onset)):
        if onset[i] == 1:
            if bgn:
                emit(max(i - 1, 0), 0, "next_onset")
                frame_disappear = offset_occur = None
            bgn = i
        if bgn and i > bgn:
            if frame[i] <= threshold and not frame_disappear:
                frame_disappear = i
            if offset[i] == 1 and not offset_occur:
                offset_occur = i
            if frame_disappear:
                use_offset = bool(offset_occur and offset_occur - bgn > frame_disappear - offset_occur)
                fin = offset_occur if use_offset else frame_disappear
                emit(fin, offset_shift[fin], "offset_peak_after_midpoint" if use_offset else "frame_disappearance")
                bgn = frame_disappear = offset_occur = None
            cap_hit = bgn and cap_frames is not None and i - bgn >= cap_frames
            if bgn and (cap_hit or i == len(onset) - 1):
                emit(i, offset_shift[i], "maximum_duration_cap" if cap_hit else "sequence_end")
                bgn = frame_disappear = offset_occur = None
    return sorted(traces, key=lambda item: item["beginFrame"])


def tuples(traces):
    return [[t[k] for k in ("beginFrame", "endFrame", "onsetShift", "offsetShift", "velocityRaw")] for t in traces]


def events_for_matrices(matrices, cap_frames, fps=100, threshold=.1):
    """Same float32/event conversion as RegressionPostProcessor, no GT input."""
    all_tuples, pitches, traces = [], [], []
    for column in range(matrices["frame_output"].shape[1]):
        values = [matrices[k][:, column] for k in ("frame_output", "onset_output", "onset_shift_output",
                  "offset_output", "offset_shift_output", "velocity_output")]
        decoded = decode(*values, threshold, cap_frames)
        all_tuples.extend(tuples(decoded))
        pitches.extend([column + 21] * len(decoded))
        traces.extend({"pitch": column + 21, **t} for t in decoded)
    if not all_tuples:
        return [], traces
    values = np.array(all_tuples)
    onset = (values[:, 0] + values[:, 2]) / fps
    offset = (values[:, 1] + values[:, 3]) / fps
    converted = np.stack((onset, offset, pitches, values[:, 4]), axis=-1).astype(np.float32)
    events = [{"onset_time": float(row[0]), "offset_time": float(row[1]),
               "midi_note": int(row[2]), "velocity": int(row[3] * 128)} for row in converted]
    return events, traces
