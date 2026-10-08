"""Exercise the running API with real artifacts, or verify a browser-created correction.

This creates persistent test data unless --job-id is supplied. It does not mock
inference. Browser refresh must additionally be checked in the actual frontend.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import time
import uuid

import httpx
import mido


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def get_json(client: httpx.Client, url: str) -> dict:
    response = client.get(url)
    response.raise_for_status()
    return response.json()


def midi_notes(payload: bytes) -> list[dict]:
    midi = mido.MidiFile(file=io.BytesIO(payload))
    seconds = 0.0
    active: dict[tuple[int, int], tuple[float, int]] = {}
    notes = []
    for message in midi:
        seconds += message.time
        if message.type == "note_on" and message.velocity > 0:
            key = (message.channel, message.note)
            require(key not in active, "Overlapping same-pitch MIDI notes need separate verification")
            active[key] = (seconds, message.velocity)
        elif message.type == "note_off" or (message.type == "note_on" and message.velocity == 0):
            key = (message.channel, message.note)
            require(key in active, "Unmatched MIDI note-off")
            start, velocity = active.pop(key)
            notes.append(dict(pitch=message.note, startTime=start, endTime=seconds, velocity=velocity))
    require(not active, "Unclosed MIDI notes")
    return notes


def verify(args: argparse.Namespace) -> dict:
    with httpx.Client(base_url=args.api, timeout=30.0, trust_env=False) as client:
        if args.job_id:
            job_id = args.job_id
        else:
            with args.audio.open("rb") as audio:
                response = client.post("/api/uploads", files={"file": (args.audio.name, audio, "audio/wav")})
            response.raise_for_status()
            upload = response.json()
            response = client.post("/api/transcriptions", headers={"Idempotency-Key": str(uuid.uuid4())},
                                   json={"uploadId": upload["uploadId"], "engine": args.engine,
                                         "options": {"minPitch": 21, "maxPitch": 108}})
            response.raise_for_status()
            job_id = response.json()["jobId"]
            deadline = time.monotonic() + args.timeout
            while True:
                job = get_json(client, f"/api/transcriptions/{job_id}")
                if job["state"] in {"succeeded", "failed", "cancelled"}:
                    break
                require(time.monotonic() < deadline, f"Job timeout: {job_id}")
                time.sleep(1)

        job_url = f"/api/transcriptions/{job_id}"
        job = get_json(client, job_url)
        require(job["state"] == "succeeded", f"Job did not succeed: {job}")
        require(job["engine"] == args.engine, "Unexpected engine")
        result = job["result"]
        require(bool(result.get("transcriptUrl") and result.get("exports", {}).get("midi")),
                "Missing real artifacts; demo-runner output is not accepted")
        original_response = client.get(result["transcriptUrl"])
        original_response.raise_for_status()
        original_bytes = original_response.content
        original = original_response.json()
        require(bool(original["notes"]), "No detected notes; cannot demonstrate one-note correction")
        demo = get_json(client, "/api/transcripts/demo")
        require(original["notes"] != demo["notes"], "Transcript is identical to fixed demo notes")
        original_midi_response = client.get(result["exports"]["midi"])
        original_midi_response.raise_for_status()
        original_midi = original_midi_response.content
        require(len(midi_notes(original_midi)) == len(original["notes"]), "Original MIDI count mismatch")

        if not args.job_id:
            require(not result.get("correction"), "Fresh job unexpectedly has corrections")
            corrected_notes = deepcopy(original["notes"])
            corrected_notes[0]["pitch"] += -1 if corrected_notes[0]["pitch"] == 108 else 1
            fields = ("pitch", "startTime", "endTime", "velocity", "confidence", "hand")
            response = client.put(f"{job_url}/corrections", json={"baseRevision": 0,
                                  "notes": [{key: note[key] for key in fields} for note in corrected_notes]})
            response.raise_for_status()

    # A fresh client simulates a new session: discover current revision from disk-backed job metadata.
    with httpx.Client(base_url=args.api, timeout=30.0, trust_env=False) as client:
        recovered = get_json(client, job_url)
        correction = recovered["result"].get("correction")
        require(bool(correction), "Correction did not persist")
        corrected = get_json(client, correction["exports"]["transcript"])
        require(len(corrected["notes"]) == len(original["notes"]), "Unexpected note-count change")
        changed = [index for index, (old, new) in enumerate(zip(original["notes"], corrected["notes"])) if old != new]
        require(len(changed) == 1, f"Expected exactly one changed note, found {changed}")
        changed_note = corrected["notes"][changed[0]]
        midi_response = client.get(correction["exports"]["midi"])
        midi_response.raise_for_status()
        parsed = midi_notes(midi_response.content)
        tolerance = 1 / 960 + 1e-9
        require(len(parsed) == len(corrected["notes"]), "Corrected MIDI count mismatch")
        remaining = list(parsed)
        for note in corrected["notes"]:
            matches = [item for item in remaining if item["pitch"] == note["pitch"]
                       and item["velocity"] == note["velocity"]
                       and abs(item["startTime"] - note["startTime"]) <= tolerance
                       and abs(item["endTime"] - note["endTime"]) <= tolerance]
            require(bool(matches), f"JSON/MIDI mismatch: {note}")
            remaining.remove(matches[0])
        require(client.get(result["transcriptUrl"]).content == original_bytes, "Original JSON changed")
        require(client.get(result["exports"]["midi"]).content == original_midi, "Original MIDI changed")
        return dict(status="passed", api=args.api, engine=job["engine"], jobId=job_id, noteCount=len(parsed),
                    revision=correction["revision"], changedNoteIndex=changed[0], changedNote=changed_note,
                    exports=correction["exports"], timingToleranceSeconds=tolerance,
                    originalJsonSha256=hashlib.sha256(original_bytes).hexdigest(),
                    correctedMidiSha256=hashlib.sha256(midi_response.content).hexdigest(),
                    browserRefresh="Verify separately in frontend; this script checks fresh API retrieval")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("basic-pitch", "bytedance"), default="bytedance")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--audio", type=Path, default=Path(__file__).resolve().parents[1] / "data/samples/demo.wav")
    parser.add_argument("--job-id", help="Read-only verification of an existing browser-corrected job")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify(args)
    rendered = json.dumps(report, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
