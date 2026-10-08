"""Read-only explanations of the installed upstream decoder's decisions."""
from __future__ import annotations


def decoder_trace(frame, onset, onset_shift, offset, offset_shift, velocity, threshold):
    """Mirror piano_vad 0.0.6 for observation only; never used as app decoder."""
    traces = []
    bgn = frame_disappear = offset_occur = None

    def emit(fin, shift, reason):
        traces.append({"beginFrame": int(bgn), "endFrame": int(fin),
                       "onsetShift": float(onset_shift[bgn]), "offsetShift": float(shift),
                       "velocityRaw": float(velocity[bgn]), "reason": reason,
                       "firstOffsetFrame": None if offset_occur is None else int(offset_occur),
                       "firstFrameDisappear": None if frame_disappear is None else int(frame_disappear),
                       "onsetSeconds": (bgn + float(onset_shift[bgn])) / 100,
                       "offsetSeconds": (fin + float(shift)) / 100})

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
            if bgn and (i - bgn >= 600 or i == len(onset) - 1):
                emit(i, offset_shift[i], "six_second_cap" if i - bgn >= 600 else "sequence_end")
                bgn = frame_disappear = offset_occur = None
    return sorted(traces, key=lambda item: item["beginFrame"])


def padding_info(sample_count: int, original_samples: int, original_rate: int, output_frames: int) -> dict:
    padded_samples = ((sample_count + 159999) // 160000) * 160000
    return {"originalSamples": original_samples, "originalSampleRate": original_rate,
            "originalDuration": original_samples / original_rate,
            "preprocessedSamples": sample_count, "sampleRate": 16000,
            "preprocessedDuration": sample_count / 16000,
            "paddingSamples": padded_samples - sample_count, "paddingSeconds": (padded_samples - sample_count) / 16000,
            "paddedSamples": padded_samples, "segmentSamples": 160000,
            "segmentSeconds": 10, "segmentHopSamples": 80000,
            "outputFrames": output_frames, "lastOutputFrame": output_frames - 1,
            "lastOutputFrameTime": (output_frames - 1) / 100,
            "lastCenterInsideAudio": sample_count // 160,
            "lastCenterInsideAudioTime": (sample_count // 160) / 100,
            "lastFullyUnpaddedWindowCenter": (sample_count - 1024) // 160,
            "upstreamSliceLimit": sample_count,
            "sampleCountUsedAsFrameSlice": sample_count > output_frames}
