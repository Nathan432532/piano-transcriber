"""Score uncorrected artifacts from the running application's two real adapters."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import time
import uuid

import httpx

from .metrics import aggregate, score, read_midi
from .prepare import ROOT, FIXTURES, sha256

CSV_FIELDS = ["fragment", "engine", "ground_truth_notes", "predicted_notes", "TP", "FP", "FN", "precision", "recall", "F1",
              "pitch_TP", "pitch_FP", "pitch_FN", "pitch_precision", "pitch_recall", "pitch_F1",
              "onset_TP", "onset_FP", "onset_FN", "onset_precision", "onset_recall", "onset_F1",
              "onset_mae_ms", "onset_median_abs_ms", "offset_mae_ms", "offset_bias_ms", "sustain_offset_mae_ms",
              "offset_TP", "offset_F1", "velocity_mae", "runtime_seconds"]


def get_json(client, url):
    response = client.get(url)
    response.raise_for_status()
    return response.json()


def predict(client, upload_id, engine, timeout):
    start = time.perf_counter()
    response = client.post("/api/transcriptions", headers={"Idempotency-Key": str(uuid.uuid4())},
                           json={"uploadId": upload_id, "engine": engine, "options": {"minPitch": 21, "maxPitch": 108}})
    response.raise_for_status()
    job_id = response.json()["jobId"]
    while True:
        job = get_json(client, f"/api/transcriptions/{job_id}")
        if job["state"] in {"succeeded", "failed", "cancelled"}:
            break
        if time.perf_counter() - start > timeout:
            raise RuntimeError(f"Timeout; do not score incomplete job {job_id}")
        time.sleep(1)
    if job["state"] != "succeeded" or job["engine"] != engine:
        raise RuntimeError(f"Actual engine job failed: {job}")
    result = job["result"]
    if not result.get("transcriptUrl") or not result.get("exports", {}).get("midi") or result.get("correction"):
        raise RuntimeError("Real uncorrected artifacts required; demo/corrected output is forbidden")
    transcript = get_json(client, result["transcriptUrl"])
    midi = client.get(result["exports"]["midi"])
    midi.raise_for_status()
    return transcript, midi.content, job, time.perf_counter() - start


def render_report(summary: dict, path: Path) -> None:
    lines = ["# Baselinebenchmark met onafhankelijke MIDI-ground-truth", "", f"Uitgevoerd: {summary['createdAt']}.", "",
             "Vier nieuwe handgeschreven MIDI-noteplannen zijn vóór inferentie bevroren. Geen ground-truth uit predictions, geen correcties, geen thresholdtuning.",
             "Er waren geen bestaande onafhankelijke piano-MIDI/audio-paren. Aanwezige model-MIDI's zijn uitgesloten; demo.wav is een sinusdemo en niet als pianokwaliteitstest gebruikt.",
             "Audio: synthetische piano met de reeds aanwezige pretty_midi TimGM6mb.sf2 en officiële portable FluidSynth 2.5.6. Geen microfoonopnames.",
             "", "## Bestanden en herkomst", "", "Alle inputhashes, vaste noteplannen, pedaalcommando's en rendercommando's staan in ground_truth/baseline-manifest.json.",
             "Renderer: https://github.com/FluidSynth/fluidsynth/releases/tag/v2.5.6 (portable x64 cpp11, LGPL). SoundFont wordt niet gevendord; herkomst is de bestaande pretty_midi-package. Geen nieuwe Python-dependencies geïnstalleerd.",
             "44.1 kHz stereo PCM16, GM Acoustic Grand Piano (program 0), gain 0.2, chorus/reverb uit, geen normalisatie. SoundFont-attack/release is onderdeel van deze beperkte test."]
    for fragment in summary["manifest"]["fragments"]:
        lines.append(f"- {fragment['name']}.mid + {fragment['name']}.wav: {fragment['groundTruthNotes']} noten; {fragment['category']}; MIDI SHA256 {fragment['midiSha256']}; WAV SHA256 {fragment['audioSha256']}.")
    lines += ["", "## Matching", "",
              "mir_eval 0.8.2 maximum bipartite één-op-één matching. Exact dezelfde integer MIDI-pitch (1 cent bij omzetting naar Hz); onsetafstand <=50 ms; strict=False. mir_eval rondt afstanden op vier decimalen (0.1 ms) af. Offsets tellen niet mee in primaire TP/FP/FN en precision/recall/F1.",
              "Pitch-only P/R/F1 vergelijkt aantallen events per pitch en negeert timing volledig. Onset-only P/R/F1 matcht onsets één-op-één binnen 50 ms en negeert pitch. Primaire note-F1 vereist pitch én onset. Deze drie scores zijn verschillende vragen, geen verwisselbare accuracycijfers.",
              "Offset-F1 is afzonderlijk: pitch+onset én offset binnen max(50 ms, 20% MIDI-nootduur). Timing-MAE/mediaan/bias worden uitsluitend over primaire matches berekend; NA als er geen matches zijn.",
              "Ground-truth endTime is MIDI key release, niet het einde van hoorbare resonantie. Bij CC64 staat sustainEndTime apart: release bij pedal-up of same-pitch reattack. Zowel key-release-offset-MAE als pedal-aware-MAE wordt gerapporteerd; geen van beide verandert onset-F1.",
              "Velocity MAE voor ByteDance vergelijkt met bekende MIDI note-on commando's, zonder akoestische kalibratie. Voor Basic Pitch niet gerapporteerd: diens velocity is een amplitudeproxy. Velocity weegt niet mee in de scores.",
              "Diagnostiek koppelt residuen eerst op gelijke pitch/dichtstbijzijnde onset (verkeerde timing), daarna op nabije onset/verkeerde pitch; overblijvende events zijn gemist/extra. Dit is een heuristische foutbeschrijving en verandert geen scores.",
              "Totaalscores zijn microaggregaties uit opgetelde TP/FP/FN; timingfouten worden per gematchte noot gewogen. Geen gemiddelde van clip-F1's.",
              "Bron matching: https://mir-eval.readthedocs.io/latest/api/transcription.html", "", "## Resultaten", "",
              "| Fragment | Engine | GT | Pred | TP | FP | FN | Note P | Note R | Note F1 | Pitch F1 | Onset F1 | Onset MAE ms | Offset MAE ms |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in summary["rows"] + summary["totals"]:
        fields = [row[key] for key in ("fragment", "engine", "ground_truth_notes", "predicted_notes", "TP", "FP", "FN", "precision", "recall", "F1", "pitch_F1", "onset_F1", "onset_mae_ms", "offset_mae_ms")]
        lines.append("| " + " | ".join("NA" if v is None else f"{v:.6f}" if isinstance(v, float) else str(v) for v in fields) + " |")
    lines += ["", "## Concrete fouten", ""]
    for row in summary["rows"]:
        lines += [f"### {row['fragment']} / {row['engine']}", ""]
        diagnostics = row["diagnostics"]
        for key in ("right_pitch_wrong_timing", "wrong_pitch", "missed", "extra"):
            lines.append(f"- {key}: {len(diagnostics[key])}; voorbeelden: `{json.dumps(diagnostics[key][:2])}`.")
        offsets = sorted(diagnostics["correct"], key=lambda pair: abs(pair["prediction"]["endTime"] - pair["reference"]["endTime"]), reverse=True)
        for pair in offsets[:2]:
            ref, pred = pair["reference"], pair["prediction"]
            lines.append(f"- Pitch {ref['pitch']}, GT onset {ref['startTime']:.3f} s: onset voorspeld {pred['startTime']:.3f} s; key-release GT {ref['endTime']:.3f} s, voorspeld {pred['endTime']:.3f} s; offsetdelta {(pred['endTime']-ref['endTime'])*1000:+.1f} ms; pedal-aware release {ref['sustainEndTime']:.3f} s.")
        lines.append("")
    lines += ["## Grenzen en interpretatie", "",
              "23 handgeschreven noten, één eenvoudige SoundFont, vier clips, één baseline-run. Geen statistisch robuuste modelrangschikking; geen bewijs voor microfoonopnames, andere piano's, ruis, ruime pitchrange of complexe pedaalbewegingen. Resultaten zijn gevoelig voor timbre en MIDI-offset versus akoestische release.",
              "ByteDance blijft primair zoals gevraagd, ongeacht deze run. Een scoreverschil is uitsluitend geldig voor deze bevroren synthetische set. Er is geen engine-, schema-, editor-, fallback- of thresholdwijziging gedaan.",
              "Modelpredictions zijn de ongewijzigde canonical artifacts van de bestaande API/adapters. ByteDance's bestaande clipping tot audioduur en onsetconfidenceproxy blijven behouden. Server runtimes omvatten per-job loading en polling; geen performancebenchmark.",
              "Kleinste volgende stap: voeg één echte piano-opname met onafhankelijke performance-MIDI toe en analyseer dezelfde foutcategorieën vóór een parameterwijziging."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(api: str, output: Path, timeout: float) -> dict:
    manifest_path = FIXTURES / "baseline-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for fragment in manifest["fragments"]:
        for key in ("midi", "audio"):
            if sha256(ROOT / fragment[key]) != fragment[key + "Sha256"]:
                raise RuntimeError("Frozen ground truth/audio changed; refusing baseline")
        if len(read_midi(ROOT / fragment["midi"])) != fragment["groundTruthNotes"]:
            raise RuntimeError("Reference note-count mismatch")
    output.mkdir(parents=True, exist_ok=False)
    for folder in ("ground_truth", "audio", "predictions/bytedance", "predictions/basic_pitch", "reports"):
        (output / folder).mkdir(parents=True)
    shutil.copyfile(manifest_path, output / "ground_truth/baseline-manifest.json")
    metadata = {"createdAt": datetime.now(timezone.utc).isoformat(), "api": api,
                "gitCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "manifestSha256": sha256(manifest_path), "python": platform.python_version(),
                "versions": {p: importlib.metadata.version(p) for p in ["basic-pitch", "piano-transcription-inference", "torch", "tensorflow", "mir_eval", "mido"]},
                "adapterSha256": {engine: sha256(ROOT / f"backend/app/{engine}_adapter.py") for engine in ["basic_pitch", "bytedance"]},
                "modelSha256": {"bytedance": sha256(ROOT / "backend/data/models/CRNN_note_F1=0.9677_pedal_F1=0.9186.pth"),
                                "basic_pitch_saved_model_pb": sha256(ROOT / ".venv/Lib/site-packages/basic_pitch/saved_models/icassp_2022/nmp/saved_model.pb")}}
    (output / "reports/environment.json").write_text(json.dumps(metadata, indent=2) + "\n")
    rows = []
    with httpx.Client(base_url=api, timeout=30, trust_env=False) as client:
        client.get("/api/health").raise_for_status()
        for fragment in manifest["fragments"]:
            reference = read_midi(ROOT / fragment["midi"])
            shutil.copyfile(ROOT / fragment["midi"], output / "ground_truth" / f"{fragment['name']}.mid")
            shutil.copyfile(ROOT / fragment["audio"], output / "audio" / f"{fragment['name']}.wav")
            with (ROOT / fragment["audio"]).open("rb") as file:
                response = client.post("/api/uploads", files={"file": (f"{fragment['name']}.wav", file, "audio/wav")})
            response.raise_for_status()
            upload_id = response.json()["uploadId"]
            for engine in ("bytedance", "basic-pitch"):
                print(f"Running {fragment['name']} / {engine}", flush=True)
                transcript, midi, job, runtime = predict(client, upload_id, engine, timeout)
                destination = output / "predictions" / engine.replace("-", "_") / fragment["name"]
                destination.with_suffix(".json").write_text(json.dumps(transcript, indent=2) + "\n")
                destination.with_suffix(".mid").write_bytes(midi)
                destination.with_suffix(".job.json").write_text(json.dumps(job, indent=2) + "\n")
                # No corrections or pitch/time filtering before scoring.
                row = {"fragment": fragment["name"], "engine": engine, "runtime_seconds": runtime,
                       **score(reference, transcript["notes"], velocity_reliable=fragment["velocityReliable"] and engine == "bytedance")}
                rows.append(row)
                (output / "reports" / f"{fragment['name']}-{engine}.json").write_text(json.dumps(row, indent=2) + "\n")
                print(f"TP={row['TP']} FP={row['FP']} FN={row['FN']} note F1={row['F1']:.6f}", flush=True)
    totals = [{"fragment": "TOTAL", "engine": engine,
               "runtime_seconds": sum(row["runtime_seconds"] for row in rows if row["engine"] == engine),
               **aggregate([row for row in rows if row["engine"] == engine])} for engine in ("bytedance", "basic-pitch")]
    summary = {**metadata, "manifest": manifest, "rows": rows, "totals": totals}
    (output / "reports/summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    with (output / "reports/benchmark-results.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows + totals)
    render_report(summary, output / "reports/benchmark-report.md")
    # Recheck source fixtures after the run to detect contamination/mutations.
    for fragment in manifest["fragments"]:
        for key in ("midi", "audio"):
            assert sha256(ROOT / fragment[key]) == fragment[key + "Sha256"]
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=ROOT / "backend/data/benchmarks/runs" / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-baseline"))
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    result = run(args.api, args.output, args.timeout)
    print(json.dumps(result["totals"], indent=2))
