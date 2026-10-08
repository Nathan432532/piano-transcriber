"""Write independent MIDI plans and freeze rendered WAVs before inference."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pretty_midi
from scipy.signal import lfilter
import soundfile as sf

from benchmarks.prepare import ROOT, RENDERER, SOUNDFONT_SHA256, sha256, write_midi, render_audio
from benchmarks.experiments.offset_policy.policies import terminal_silence_start

FIXTURES = ROOT / "backend/data/ground_truth/fixtures/independent_validation"
AUDIO = ROOT / "backend/data/ground_truth/rendered/independent_validation"
POLICY = Path(__file__).parents[1] / "offset_policy/policies.py"
POLICY_SHA = "f6e1d8b8a311e0e23b2c84f9451b1aa91cf50758dafd267b45dca55e2446814e"
PLANS = {
    "hold_c4_4s": {"category": "long", "duration": 5.6, "notes": [(60, .4, 4.4, 88)]},
    "hold_a4_55s": {"category": "long", "duration": 7.2, "notes": [(69, .6, 6.1, 88)]},
    "hold_e4_75s": {"category": "long", "duration": 9.2, "notes": [(64, .5, 8, 88)]},
    "pedal_g4": {"category": "sustain", "duration": 6, "notes": [(67, .4, 1.4, 88)], "pedal": [(.3, 127), (4.6, 0)]},
    "pedal_pair": {"category": "sustain", "duration": 6.6, "notes": [(60, .5, 1, 88), (64, 1.5, 2.25, 88)], "pedal": [(.3, 127), (5.4, 0)]},
    "pedal_reattack": {"category": "sustain", "duration": 5, "notes": [(67, .4, .8, 88), (67, 1.8, 2.2, 88)], "pedal": [(.3, 127), (3.8, 0)]},
    "repeated_d4": {"category": "repeated", "duration": 4.5, "notes": [(62, .4+i*.65, .75+i*.65, 88) for i in range(5)]},
    "staggered_chord": {"category": "overlap", "duration": 5.2, "notes": [(48, .4, 3.6, 88), (60, .4, 1.6, 88), (64, .9, 2.5, 88), (67, 1.3, 3.2, 88)]},
}
NOISE_CASES = {"pedal_g4_noise": ("pedal_g4", 20261007), "staggered_chord_noise": ("staggered_chord", 20261008)}
DIAGNOSTIC_FILES = ["140_Cm_Piano_VKeys_02_268_2.wav", "120_G_Offbeat_01_53_SP.wav"]
FAIL_CRITERIA = {
    "releaseToleranceSeconds": .05,
    "long": "Candidate changes an A-correct long note to end >50 ms before key release",
    "sustain": "Candidate moves earlier towards key release while worsening pedal-release error by >50 ms",
    "repeated": "Candidate changes pitch/onset/count, merges events or extends into the next same-pitch onset",
    "wrongPeak": "Selected peak cuts before independently known release by >50 ms; report even if A was also wrong",
    "noise": "C-specific (C vs B) benefit disappears when exact terminal silence is replaced by fixed low background noise",
    "decision": "Any observed harmful premature change prevents READY; lack of verified real recordings also prevents READY",
}


def validate_plans(plans=PLANS):
    assert len(plans) >= 8
    assert sum(p["category"] == "long" for p in plans.values()) >= 2
    assert sum(p["category"] == "sustain" for p in plans.values()) >= 2
    for plan in plans.values():
        for pitch, start, end, velocity in plan["notes"]:
            assert 21 <= pitch <= 108 and 0 <= start < end <= plan["duration"] and 1 <= velocity <= 127
        for time, value in plan.get("pedal", []):
            assert 0 <= time <= plan["duration"] and 0 <= value <= 127


def add_noise(audio, seed):
    """Fixed PCG64 stereo Gaussian noise, pole .97, RMS -70 dBFS/channel.

    No signal-dependent scaling, denoising, normalization or threshold tuning.
    """
    rng = np.random.Generator(np.random.PCG64(seed))
    noise = lfilter([1], [1, -.97], rng.standard_normal(audio.shape), axis=0)
    target = 10 ** (-70 / 20)
    noise *= target / np.sqrt(np.mean(noise * noise, axis=0))
    return audio + noise


def freeze():
    validate_plans()
    assert sha256(POLICY) == POLICY_SHA, "Do not tune the existing policies"
    manifest_path = FIXTURES / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        verify(manifest)
        return manifest
    soundfont = Path(pretty_midi.__file__).parent / "TimGM6mb.sf2"
    assert sha256(soundfont) == SOUNDFONT_SHA256
    assert RENDERER.is_file()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    AUDIO.mkdir(parents=True, exist_ok=True)
    # All independent MIDI plans exist before the first audio render/inference.
    for name, plan in PLANS.items():
        write_midi(FIXTURES / f"{name}.mid", plan)
    manifest = {"version": 1, "frozenAt": datetime.now(timezone.utc).isoformat(),
                "groundTruthSource": "Independent hand-authored MIDI plans, written before inference; no prediction labels",
                "policySha256": POLICY_SHA, "failCriteria": FAIL_CRITERIA,
                "rendererExeSha256": sha256(RENDERER), "soundfontSha256": sha256(soundfont),
                "renderSettings": {"sampleRate": 44100, "subtype": "PCM_16", "gain": .2, "reverb": False, "chorus": False},
                "cases": []}
    for name, plan in PLANS.items():
        midi, wav = FIXTURES / f"{name}.mid", AUDIO / f"{name}.wav"
        command = render_audio(RENDERER, soundfont, midi, wav)
        samples, rate = sf.read(wav, always_2d=True)
        assert rate == 44100 and 0 < abs(samples).max() < 1
        # Exact signal extinction is observable, NOT a perceptual audible-end label.
        case = {"name": name, "kind": "synthetic", "category": plan["category"], "variant": "clean",
                "sustain": bool(plan.get("pedal")), "groundTruthNotes": len(plan["notes"]),
                "notePlan": plan["notes"], "pedalPlan": plan.get("pedal", []),
                "midi": midi.relative_to(ROOT).as_posix(), "audio": wav.relative_to(ROOT).as_posix(),
                "midiSha256": sha256(midi), "audioSha256": sha256(wav), "renderCommand": command,
                "sampleCount": len(samples), "sampleRate": rate,
                "digitalSignalExtinction": terminal_silence_start(samples, rate),
                "audibleEndGroundTruth": None, "audibleEndExplanation": "No independent perceptual label; digital extinction is only an upper bound",
                "isolatedNoteExtinctions": []}
        # Pair stems provide source-independent, per-note decay upper bounds.
        # No stem is input to inference or any policy decision.
        if name == "pedal_pair":
            for index, note in enumerate(plan["notes"]):
                stem_plan = {**plan, "notes": [note]}
                stem_midi = FIXTURES / f"{name}-stem-{index}.mid"
                stem_wav = AUDIO / f"{name}-stem-{index}.wav"
                write_midi(stem_midi, stem_plan)
                render_audio(RENDERER, soundfont, stem_midi, stem_wav)
                stem, stem_rate = sf.read(stem_wav, always_2d=True)
                case["isolatedNoteExtinctions"].append({"pitch": note[0], "onset": note[1],
                    "end": terminal_silence_start(stem, stem_rate),
                    "audio": stem_wav.relative_to(ROOT).as_posix(), "audioSha256": sha256(stem_wav),
                    "midi": stem_midi.relative_to(ROOT).as_posix(), "midiSha256": sha256(stem_midi)})
        manifest["cases"].append(case)
    for name, (parent, seed) in NOISE_CASES.items():
        clean = next(c for c in manifest["cases"] if c["name"] == parent)
        audio, rate = sf.read(ROOT / clean["audio"], always_2d=True)
        noisy = add_noise(audio, seed)
        assert abs(noisy).max() < 1
        wav = AUDIO / f"{name}.wav"
        sf.write(wav, noisy, rate, subtype="PCM_24")
        saved, _ = sf.read(wav, always_2d=True)
        assert terminal_silence_start(saved, rate) is None
        case = {**clean, "name": name, "variant": "noise", "parent": parent,
                "audio": wav.relative_to(ROOT).as_posix(), "audioSha256": sha256(wav),
                "digitalSignalExtinction": None, "isolatedNoteExtinctions": [],
                "renderCommand": None,
                "noise": {"seed": seed, "generator": "numpy PCG64", "distribution": "independent stereo Gaussian",
                          "filterNumerator": [1], "filterDenominator": [1, -.97], "rmsDbFSPerChannel": -70,
                          "signalDependentScaling": False, "subtype": "PCM_24"}}
        manifest["cases"].append(case)
    for filename in DIAGNOSTIC_FILES:
        path = ROOT / filename
        if not path.is_file():
            continue
        info = sf.info(path)
        manifest["cases"].append({"name": path.stem, "kind": "existing_audio_unverified_origin",
                                 "category": "diagnostic", "variant": "existing", "sustain": None,
                                 "groundTruthNotes": None, "midi": None,
                                 "audio": filename, "audioSha256": sha256(path),
                                 "sampleCount": info.frames, "sampleRate": info.samplerate,
                                 "groundTruthSource": None,
                                 "provenanceLimitation": "Existing piano loop; acoustic recording/instrument source and independent labels not documented"})
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify(manifest)
    return manifest


def verify(manifest):
    assert sha256(POLICY) == manifest["policySha256"] == POLICY_SHA
    for case in manifest["cases"]:
        for key in ("audio", "midi"):
            if case.get(key):
                assert sha256(ROOT / case[key]) == case[key+"Sha256"], f"Frozen {key} differs: {case['name']}"
        for stem in case.get("isolatedNoteExtinctions", []):
            for key in ("audio", "midi"):
                assert sha256(ROOT / stem[key]) == stem[key+"Sha256"]


if __name__ == "__main__":
    result = freeze()
    print(json.dumps({"frozenAt": result["frozenAt"], "cases": [(c["name"], c["groundTruthNotes"]) for c in result["cases"]]}, indent=2))
