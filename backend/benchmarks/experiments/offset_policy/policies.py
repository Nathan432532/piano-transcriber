"""Offset-only candidates. No reference MIDI or reference timings enter here.

Rules fixed before scoring: reuse upstream's accepted peaks/thresholds, bound
their search by this event's upstream end and the next same-pitch onset, respect
predicted pedal intervals. Boundary-only guard uses exact digital terminal
silence, never an amplitude threshold or an arbitrary maximum note duration.
"""
from __future__ import annotations

import numpy as np

BOUNDARY_REASONS = {"six_second_cap", "sequence_end"}


def terminal_silence_start(samples: np.ndarray, sample_rate: int) -> float | None:
    """First sample after the final nonzero sample in *all* native audio channels.

    No near-silence tolerance. All-zero audio provides no usable endpoint.
    The endpoint is an acoustic upper bound, not an individual key release.
    """
    if sample_rate <= 0 or samples.ndim not in (1, 2) or not np.all(np.isfinite(samples)):
        raise ValueError("Finite mono/stereo audio and positive sample rate required")
    nonzero = samples != 0 if samples.ndim == 1 else np.any(samples != 0, axis=1)
    indices = np.flatnonzero(nonzero)
    if not len(indices) or indices[-1] == len(samples) - 1:
        return None
    return (int(indices[-1]) + 1) / sample_rate


def peak_candidate(event: dict, trace: dict, matrices: dict, duration: float,
                   pedal_events: list[dict], next_onset: float | None) -> tuple[float | None, str]:
    """First already-accepted offset peak inside this decoded event's window.

    Uses upstream offset_output (threshold .3, monotonic neighbour=4), not a
    newly thresholded/local-max head. Window: strictly after onset, at/before
    min(upstream end, audio duration), strictly before next same-pitch onset.
    A peak inside a predicted pedal interval is skipped, not moved to pedal-up.
    """
    column = event["midi_note"] - 21
    begin = trace["beginFrame"]
    upper = min(float(event["offset_time"]), duration)
    blocked = False
    for index in np.flatnonzero(matrices["offset_output"][:, column]):
        if index <= begin:
            continue
        time = (int(index) + float(matrices["offset_shift_output"][index, column])) / 100
        same_upstream_peak = trace["reason"] == "offset_peak_after_midpoint" and index == trace["endFrame"]
        # Raw parabolic time is float64; upstream events are float32. The same
        # peak can lie a few nanoseconds above its own decoded event timestamp.
        window_time = float(event["offset_time"]) if same_upstream_peak else time
        if window_time <= event["onset_time"] or window_time > upper or (next_onset is not None and window_time >= next_onset):
            continue
        if any(p["onset_time"] <= time < p["offset_time"] for p in pedal_events):
            blocked = True
            continue
        return time, f"accepted_offset_peak_frame_{index}"
    return None, "predicted_pedal_blocks_peaks" if blocked else "no_usable_accepted_offset_peak"


def runaway_guard(end: float, onset: float, reason: str, silence_start: float | None) -> tuple[float, str]:
    if reason not in BOUNDARY_REASONS:
        return end, "not_a_decoder_boundary"
    if silence_start is None or not onset < silence_start < end:
        return end, "boundary_flagged_without_usable_terminal_silence"
    return silence_start, "decoder_boundary_bounded_by_exact_terminal_silence"


def evaluate_event(event: dict, trace: dict, matrices: dict, duration: float,
                   pedal_events: list[dict], next_onset: float | None,
                   silence_start: float | None) -> dict:
    """Return four endpoint candidates; pitches, onsets, count remain untouched."""
    a = min(float(event["offset_time"]), duration)  # Unchanged production clipping.
    peak, reason = peak_candidate(event, trace, matrices, duration, pedal_events, next_onset)
    b = a if peak is None else peak
    if peak is not None and trace["reason"] == "offset_peak_after_midpoint" and reason == f"accepted_offset_peak_frame_{trace['endFrame']}":
        b = a  # Same physical peak: retain the original float32 event exactly.
    d, d_reason = runaway_guard(a, float(event["onset_time"]), trace["reason"], silence_start)
    c = b if peak is not None else d
    assert all(event["onset_time"] < end <= duration for end in (a, b, c, d))
    return {"A": a, "B": b, "C": c, "D": d, "raw_candidate_offset": peak,
            "reason_B": reason, "reason_C": reason if peak is not None else d_reason,
            "reason_D": d_reason, "decoder_boundary": trace["reason"] in BOUNDARY_REASONS}
