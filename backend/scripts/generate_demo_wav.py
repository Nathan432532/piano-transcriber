from __future__ import annotations

import json
import math
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.transcript import DEMO_TRANSCRIPT  # noqa: E402


SAMPLE_RATE = 44100
AMPLITUDE = 10000


def midi_to_frequency(pitch: int) -> float:
    return 440.0 * (2 ** ((pitch - 69) / 12))


def render_sample(path: Path) -> None:
    duration = float(DEMO_TRANSCRIPT["source"]["duration"])
    frame_count = int(duration * SAMPLE_RATE)
    frames = [0.0 for _ in range(frame_count)]

    for note in DEMO_TRANSCRIPT["notes"]:
        frequency = midi_to_frequency(int(note["pitch"]))
        start = int(float(note["startTime"]) * SAMPLE_RATE)
        end = min(int(float(note["endTime"]) * SAMPLE_RATE), frame_count)
        note_length = max(end - start, 1)
        for frame in range(start, end):
            local = frame - start
            attack = min(local / (0.02 * SAMPLE_RATE), 1.0)
            release = min((note_length - local) / (0.08 * SAMPLE_RATE), 1.0)
            envelope = max(min(attack, release), 0.0)
            frames[frame] += math.sin(2 * math.pi * frequency * frame / SAMPLE_RATE) * envelope

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        for value in frames:
            sample = int(max(min(value * AMPLITUDE, 32767), -32768))
            wav.writeframesraw(sample.to_bytes(2, "little", signed=True))


def main() -> None:
    sample_dir = ROOT / "backend" / "data" / "samples"
    render_sample(sample_dir / "demo.wav")
    (sample_dir / "demo.transcript.json").write_text(json.dumps(DEMO_TRANSCRIPT, indent=2) + "\n")


if __name__ == "__main__":
    main()
