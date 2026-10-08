"""Inspect official MAPS pairs and freeze a deterministic model-free subset."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path

import mido
import soundfile as sf

from benchmarks.metrics import read_midi
from benchmarks.prepare import sha256

HERE = Path(__file__).parent
MANIFEST = HERE / "maps-enstdkcl-subset.json"
ZIP_SIZE = 2608287080
ZIP_MD5 = "72bbdf40eb7af69225755e165a0a0a08"


def resolve_root(path: Path) -> Path:
    root = path.resolve()
    if not (root / "ISOL").is_dir() and (root / "ENSTDkCl/ISOL").is_dir():
        root = root / "ENSTDkCl"
    if not all((root / category).is_dir() for category in ("ISOL", "RAND", "UCHO", "MUS")):
        raise ValueError("Expected ENSTDkCl root with ISOL/RAND/UCHO/MUS")
    return root


def pair_audio(root: Path) -> list[tuple[Path, Path, Path]]:
    pairs = []
    for wav in sorted(root.rglob("*.wav")):
        midi, txt = wav.with_suffix(".mid"), wav.with_suffix(".txt")
        if not midi.is_file() or not txt.is_file():
            raise ValueError(f"Incomplete MAPS pair: {wav.relative_to(root)}")
        if not wav.stem.endswith("_ENSTDkCl"):
            raise ValueError("Unexpected instrument subset")
        pairs.append((wav, midi, txt))
    if len(pairs) != len(list(root.rglob("*.mid"))) or len(pairs) != len(list(root.rglob("*.txt"))):
        raise ValueError("Unpaired MIDI/TXT files present")
    return pairs


def midi_controls(path: Path) -> list[dict]:
    seconds, events = 0., []
    for msg in mido.MidiFile(path):
        seconds += msg.time
        if msg.type == "control_change" and msg.control == 64:
            events.append({"time": seconds, "value": msg.value, "channel": msg.channel})
    return events


def txt_reference(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines()[1:]:
        if line.strip():
            onset, offset, pitch = line.split()
            rows.append({"startTime": float(onset), "endTime": float(offset), "pitch": int(pitch)})
    return sorted(rows, key=lambda n: (n["pitch"], n["startTime"]))


def check_txt(notes: list[dict], txt: list[dict]) -> dict:
    """MAPS TXT uses effective/pedal offsets, not always physical MIDI note-off."""
    # Group by pitch before time: rounding of simultaneous onsets in ASCII
    # must not change pitch ordering relative to the higher-precision MIDI.
    refs = sorted(notes, key=lambda n: (n["pitch"], n["startTime"]))
    txt = sorted(txt, key=lambda n: (n["pitch"], n["startTime"]))
    if len(refs) != len(txt):
        raise ValueError("MIDI/TXT note count differs")
    onset_diff, offset_diff = [], []
    for midi, text in zip(refs, txt):
        if midi["pitch"] != text["pitch"]:
            raise ValueError("MIDI/TXT pitches differ")
        onset_diff.append(abs(midi["startTime"]-text["startTime"]))
        offset_diff.append(abs(midi["sustainEndTime"]-text["endTime"]))
    # ASCII annotation precision decreases for larger time values.
    return {"maxOnsetDifference": max(onset_diff, default=0),
            "maxEffectiveOffsetDifference": max(offset_diff, default=0)}


def inspect(root):
    records, errors = [], []
    for wav, midi, txt in pair_audio(root):
        rel = wav.relative_to(root).as_posix()
        try:
            notes = read_midi(midi)
            controls = midi_controls(midi)
            info = sf.info(wav)
            durations = [n["endTime"]-n["startTime"] for n in notes]
            records.append({"audio": rel, "midi": midi.relative_to(root).as_posix(), "txt": txt.relative_to(root).as_posix(),
                            "mapsCategory": rel.split("/")[0], "style": rel.split("/")[1] if rel.startswith("ISOL/") else None,
                            "notes": notes, "cc64": controls, "sustain": any(n["sustainEndTime"]>n["endTime"]+1e-9 for n in notes),
                            "pedalDownRecorded": any(e["value"]>=64 for e in controls),
                            "duration": info.duration, "sampleRate": info.samplerate, "channels": info.channels, "subtype": info.subtype,
                            "minNoteDuration": min(durations, default=None), "maxNoteDuration": max(durations, default=None),
                            "pitchRange": [min((n["pitch"] for n in notes), default=None), max((n["pitch"] for n in notes), default=None)],
                            "txtAgreement": check_txt(notes, txt_reference(txt))})
        except (ValueError, OSError) as exc:
            errors.append({"audio": rel, "error": str(exc)})
    return records, errors


def select(records):
    """Prespecified coverage; no model results or random selection."""
    chosen = []
    used = set()
    def pick(pool, key, category, reason):
        eligible = [r for r in pool if r["audio"] not in used]
        if not eligible:
            raise ValueError(f"No eligible candidate: {category}/{reason}")
        item = min(eligible, key=lambda r: (*key(r), r["audio"]))
        used.add(item["audio"])
        chosen.append((item, category, reason))
    isolated = [r for r in records if r["mapsCategory"] == "ISOL" and r["style"] == "NO" and len(r["notes"]) == 1 and not r["pedalDownRecorded"]]
    for pitch in (36, 60, 84, 100):
        pick(isolated, lambda r: (abs(r["notes"][0]["pitch"]-pitch),abs(r["notes"][0]["velocity"]-80)), "isolated", f"Normal no-pedal single note nearest pitch {pitch}, then velocity 80")
    long = [r for r in records if r["style"] == "LG" and len(r["notes"]) == 1 and not r["pedalDownRecorded"]]
    for duration in (3.5, 5.5, 8., 12., 18.):
        pick(long, lambda r: (abs(r["maxNoteDuration"]-duration),abs(r["notes"][0]["velocity"]-80)), "long", f"No-pedal long note nearest official MIDI duration {duration}s")
    repeated = [r for r in records if r["style"] == "RE" and not r["pedalDownRecorded"]]
    for pitch in (48, 67, 90):
        pick(repeated, lambda r: (abs(r["pitchRange"][0]-pitch),abs(r["notes"][0]["velocity"]-80)), "repeated", f"Accelerating repeated-note sequence nearest pitch {pitch}")
    sustain = [r for r in records if r["style"] == "NO" and len(r["notes"]) == 1 and r["pedalDownRecorded"] and r["sustain"]]
    for pitch in (48, 67, 90):
        pick(sustain, lambda r: (abs(r["notes"][0]["pitch"]-pitch),abs(r["notes"][0]["velocity"]-80)), "sustain", f"Explicit CC64 down/up and extended release, nearest pitch {pitch}")
    for source, polyphony, center in (("UCHO",2,55), ("UCHO",3,67), ("RAND",2,55), ("RAND",3,70)):
        pool = [r for r in records if r["mapsCategory"] == source and len(r["notes"]) == polyphony and not r["pedalDownRecorded"]]
        pick(pool, lambda r: (abs(sum(n["pitch"] for n in r["notes"])/polyphony-center), abs(sum(n["velocity"] for n in r["notes"])/polyphony-80)), "chords", f"{source} no-pedal {polyphony}-note chord nearest average pitch {center}, then velocity 80")
    music = sorted([r for r in records if r["mapsCategory"] == "MUS" and r["duration"]>=15 and any(n["startTime"]<10 for n in r["notes"])], key=lambda r:r["audio"])
    if len(music)<5:
        raise ValueError("Five music candidates required")
    for item in music[:5]:
        used.add(item["audio"])
        chosen.append((item, "music", "First five lexicographic MUS pairs; original first 15s audio, score onsets in [0,10)s; boundaries fixed before inference"))
    assert len(chosen)==24 and len(used)==24
    return chosen


def freeze(root: Path, output: Path = MANIFEST):
    root = resolve_root(root)
    if output.exists():
        manifest = json.loads(output.read_text())
        verify(root, manifest)
        return manifest
    records, errors = inspect(root)
    candidates = select(records)
    manifest = {"version":1, "frozenAt":datetime.now(timezone.utc).isoformat(),
                "source":"https://zenodo.org/records/18160555", "release":"0.4", "subset":"ENSTDkCl",
                "zipFilename":"ENSTDkCl.zip", "zipBytes":ZIP_SIZE, "zipMd5":ZIP_MD5,
                "alignmentOffsetSeconds":0., "alignmentPolicy":"Raw official MIDI timeline; no predicted/per-note shifts",
                "selectionPolicy":"Deterministic MIDI/metadata-only nearest targets; lexical tie-breaks; 24 cases",
                "inventory":{"pairs":len(records)+len(errors), "validMidiPairs":len(records),
                             "categories":dict(Counter(r["mapsCategory"] for r in records)),
                             "audioFormats":dict(Counter(f"{r['sampleRate']}Hz/{r['channels']}ch/{r['subtype']}" for r in records)),
                             "pairErrors":errors, "cc64DownPairs":sum(r["pedalDownRecorded"] for r in records)}, "cases":[]}
    for index,(record,category,reason) in enumerate(candidates,1):
        window=[0.,10.] if category == "music" else [0.,record["duration"]]
        clip=[0.,15.] if category == "music" else [0.,record["duration"]]
        notes=[n for n in record["notes"] if window[0]<=n["startTime"]<window[1]]
        manifest["cases"].append({"caseId":f"{index:02d}_{category}", "category":category, "mapsCategory":record["mapsCategory"],
                                  "audio":record["audio"], "midi":record["midi"], "txt":record["txt"],
                                  "audioSha256":sha256(root/record["audio"]), "midiSha256":sha256(root/record["midi"]), "txtSha256":sha256(root/record["txt"]),
                                  "reason":reason, "audioWindowSeconds":clip, "evaluationOnsetWindowSeconds":window,
                                  "groundTruthNotes":len(notes), "sourceDurationSeconds":record["duration"],
                                  "pitchRange":record["pitchRange"], "sustain":any(n["sustainEndTime"]>n["endTime"]+1e-9 for n in notes),
                                  "cc64":record["cc64"], "noteDurationsSeconds":[n["endTime"]-n["startTime"] for n in notes] if category != "music" else None,
                                  "sampleRate":record["sampleRate"], "channels":record["channels"], "subtype":record["subtype"],
                                  "keyCensoredNotes":sum(n["endTime"]>clip[1] for n in notes), "pedalCensoredNotes":sum(n["sustainEndTime"]>clip[1] for n in notes),
                                  "txtAgreement":record["txtAgreement"]})
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(manifest,indent=2)+"\n")
    verify(root,manifest)
    return manifest


def verify(root,manifest):
    if manifest["subset"] != "ENSTDkCl" or not 20<=len(manifest["cases"])<=30:
        raise ValueError("Unexpected frozen subset")
    for case in manifest["cases"]:
        for key in ("audio","midi","txt"):
            path=(root/case[key]).resolve()
            if not path.is_relative_to(root.resolve()) or sha256(path)!=case[key+"Sha256"]:
                raise ValueError(f"Frozen source differs: {case['caseId']}/{key}")


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root",required=True,type=Path)
    args=parser.parse_args()
    result=freeze(args.dataset_root)
    print(json.dumps({"inventory":result["inventory"],"cases":[(c["caseId"],c["audio"],c["groundTruthNotes"]) for c in result["cases"]]},indent=2))
