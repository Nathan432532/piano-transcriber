"""Freeze independent MIDI note plans and render piano audio before any model run."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess

import mido
import pretty_midi
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "backend/data/ground_truth/fixtures"
AUDIO = ROOT / "backend/data/ground_truth/rendered"
RENDERER = ROOT / "backend/.deps/fluidsynth-2.5.6/bin/fluidsynth.exe"
SOUNDFONT_SHA256 = "82475b91a76de15cb28a104707d3247ba932e228bada3f47bba63c6b31aaf7a1"
PLANS = {
    "single_notes": {"category": "isolated", "duration": 5, "notes": [(60, .5, 1, 80), (64, 1.5, 2, 80), (67, 2.5, 3, 80), (71, 3.5, 4, 80)]},
    "melody_repeated": {"category": "melody/repeated pitch", "duration": 5,
                        "notes": [(pitch, .5 + index * .4, .8 + index * .4, 80)
                                  for index, pitch in enumerate([60, 62, 64, 67, 67, 64, 62, 60])]},
    "overlapping_chords": {"category": "triads/overlap", "duration": 4,
                           "notes": [(pitch, .5, 1.7, 80) for pitch in [60, 64, 67]]
                                    + [(pitch, 1.4, 2.8, 80) for pitch in [62, 65, 69]]},
    "long_notes_sustain": {"category": "long notes/CC64", "duration": 6,
                           "notes": [(48, .5, 2.5, 80), (55, 1, 2.8, 80),
                                     (60, 3.1, 3.35, 80), (64, 3.5, 3.75, 80), (67, 3.9, 4.15, 80)],
                           "pedal": [(3, 127), (5, 0)]},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_midi(path: Path, plan: dict) -> None:
    midi = mido.MidiFile(type=0, ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.extend([mido.MetaMessage("set_tempo", tempo=500000, time=0), mido.Message("program_change", program=0, time=0)])
    events = []
    for pitch, start, end, velocity in plan["notes"]:
        events.extend([(round(start * 960), 2, mido.Message("note_on", note=pitch, velocity=velocity)),
                       (round(end * 960), 0, mido.Message("note_off", note=pitch, velocity=0))])
    for time, value in plan.get("pedal", []):
        events.append((round(time * 960), 1, mido.Message("control_change", control=64, value=value)))
    previous = 0
    for tick, _, message in sorted(events, key=lambda item: (item[0], item[1], getattr(item[2], "note", -1))):
        track.append(message.copy(time=tick - previous))
        previous = tick
    track.append(mido.MetaMessage("end_of_track", time=round(plan["duration"] * 960) - previous))
    midi.save(path)


def render_audio(renderer: Path, soundfont: Path, midi: Path, wav: Path) -> list[str]:
    command = [str(renderer), "-ni", "-R", "0", "-C", "0", "-r", "44100", "-g", "0.2",
               "-T", "wav", "-O", "s16", "-F", str(wav), str(soundfont), str(midi)]
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=60)
    return command


def prepare(renderer: Path = RENDERER) -> dict:
    soundfont = Path(pretty_midi.__file__).parent / "TimGM6mb.sf2"
    if not renderer.is_file():
        raise RuntimeError("Renderer missing; run scripts/setup-benchmark-renderer.ps1. Do not substitute sine-wave audio.")
    if sha256(soundfont) != SOUNDFONT_SHA256:
        raise RuntimeError("Unexpected SoundFont; do not silently change baseline timbre")
    FIXTURES.mkdir(parents=True, exist_ok=True)
    AUDIO.mkdir(parents=True, exist_ok=True)
    manifest_path = FIXTURES / "baseline-manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if sha256(renderer) != manifest["rendererExeSha256"]:
            raise RuntimeError("Renderer differs from frozen baseline")
        for fragment in manifest["fragments"]:
            midi, wav = ROOT / fragment["midi"], ROOT / fragment["audio"]
            if not midi.exists():
                write_midi(midi, PLANS[fragment["name"]])
            if sha256(midi) != fragment["midiSha256"]:
                raise RuntimeError("Frozen MIDI hash mismatch; existing baseline was not overwritten")
            if not wav.exists():
                render_audio(renderer, soundfont, midi, wav)
            if sha256(wav) != fragment["audioSha256"]:
                raise RuntimeError("Frozen audio hash mismatch; existing baseline was not overwritten")
        return manifest
    version = subprocess.check_output([str(renderer), "--version"], text=True)
    if "runtime version 2.5.6" not in version:
        raise RuntimeError("Use pinned FluidSynth 2.5.6")
    manifest = {"version": 1, "provenance": "New hand-authored note plans, frozen before inference; not derived from predictions",
                "audioKind": "synthetic piano SoundFont rendering, not microphone recordings",
                "rendererVersion": version.strip(), "rendererExeSha256": sha256(renderer),
                "soundfont": "pretty_midi/TimGM6mb.sf2", "soundfontSha256": sha256(soundfont),
                "prettyMidiVersion": importlib.metadata.version("pretty_midi"),
                "sampleRate": 44100, "gain": 0.2, "reverb": False, "chorus": False,
                "normalization": "none", "velocityReference": "Known MIDI note-on commands; no acoustic/loudness calibration", "fragments": []}
    for name, plan in PLANS.items():
        midi, wav = FIXTURES / f"{name}.mid", AUDIO / f"{name}.wav"
        write_midi(midi, plan)
        command = render_audio(renderer, soundfont, midi, wav)
        audio, rate = sf.read(wav)
        peak = float(abs(audio).max())
        if rate != 44100 or peak == 0 or peak >= 1:
            raise RuntimeError("Invalid/clipping rendered audio; no automatic gain adjustment permitted")
        metadata = {"name": name, "category": plan["category"], "notePlan": plan["notes"], "pedalPlan": plan.get("pedal", []),
                    "groundTruthNotes": len(plan["notes"]), "midi": midi.relative_to(ROOT).as_posix(),
                    "audio": wav.relative_to(ROOT).as_posix(), "midiSha256": sha256(midi), "audioSha256": sha256(wav),
                    "renderCommand": command, "durationSeconds": len(audio) / rate, "peakAmplitude": peak,
                    "velocityReliable": True}
        (FIXTURES / f"{name}.json").write_text(json.dumps(metadata, indent=2) + "\n")
        manifest["fragments"].append(metadata)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renderer", type=Path, default=RENDERER)
    args = parser.parse_args()
    print(json.dumps(prepare(args.renderer), indent=2))
