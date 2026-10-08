"""Generate the MAPS review from cached scores; never run or alter a model."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import statistics

import numpy as np

from benchmarks.metrics import read_midi
from benchmarks.prepare import sha256
from .dataset import MANIFEST, midi_controls, pair_audio, resolve_root, txt_reference, verify

HERE = Path(__file__).parent
ENGINES = ("bytedance", "basic_pitch")


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"] +
                     ["| " + " | ".join(str(x) for x in row) + " |" for row in rows])


def common_matches(rows):
    """Compare errors on identical GT identities without changing the matcher."""
    selected = {engine: {(r["case"], r["referenceIndex"]): r for r in rows
                         if r["engine"] == engine and r["match"] == "TP"} for engine in ENGINES}
    common = selected[ENGINES[0]].keys() & selected[ENGINES[1]].keys()
    result = {}
    for engine in ENGINES:
        result[engine] = {"matched": len(common)}
        for field in ("onset_error", "key_error", "pedal_error"):
            values = [abs(selected[engine][key][field]) * 1000 for key in sorted(common)
                      if selected[engine][key][field] is not None]
            result[engine][field] = {"n": len(values), "mae_ms": statistics.mean(values) if values else None,
                                    "median_ms": statistics.median(values) if values else None}
    return result


def annotation_audit(root, manifest):
    windows = {c["audio"]: c["evaluationOnsetWindowSeconds"] for c in manifest["cases"]}
    differences, selected_differences = [], []
    max_selected, max_onset = 0., 0.
    pairs = pair_audio(root)
    for wav, mid, txt in pairs:
        relative = wav.relative_to(root).as_posix()
        refs = sorted(read_midi(mid), key=lambda n: (n["pitch"], n["startTime"]))
        texts = txt_reference(txt)
        assert len(refs) == len(texts)
        controls = midi_controls(mid)
        for ref, text in zip(refs, texts):
            assert ref["pitch"] == text["pitch"]
            max_onset = max(max_onset, abs(ref["startTime"] - text["startTime"]))
            difference = ref["sustainEndTime"] - text["endTime"]
            window = windows.get(relative)
            selected = window is not None and window[0] <= ref["startTime"] < window[1]
            if selected:
                max_selected = max(max_selected, abs(difference))
            if abs(difference) > .001:
                row = {"audio": relative, "pitch": ref["pitch"], "onset": ref["startTime"],
                       "keyRelease": ref["endTime"], "effectiveRelease": ref["sustainEndTime"],
                       "txtRelease": text["endTime"], "difference": difference,
                       "pedalDownAtSameTimestampAsKeyRelease": any(e["value"] >= 64 and
                           abs(e["time"] - ref["endTime"]) < 1e-9 for e in controls)}
                differences.append(row)
                if selected:
                    selected_differences.append(row)
    return {"pairs": len(pairs), "maxOnsetDifferenceSeconds": max_onset,
            "selectedMaxEffectiveDifferenceSeconds": max_selected,
            "selectedEffectiveDifferencesOver1ms": selected_differences,
            "fullDatasetEffectiveDifferencesOver1ms": sorted(differences, key=lambda x: -abs(x["difference"]))}


def selected_traces(summary, output):
    matched = [t for t in summary["traces"] if t["key_error"] is not None]
    # Prefer genuine late releases after pedal release, not merely key/pedal ambiguity.
    selected = [("late", t) for t in sorted(matched, key=lambda t: -t["pedal_error"])[:2]]
    selected += [("early", t) for t in sorted(matched, key=lambda t: t["key_error"])[:2]]
    correct_long = [t for t in matched if t["category"] == "long" and abs(t["key_error"]) <= .05]
    selected += [("correct_long", t) for t in correct_long[:1]]
    for category in ("sustain", "repeated", "chords"):
        candidates = [t for t in matched if t["category"] == category]
        selected.append((category, max(candidates, key=lambda t: abs(t["policyBOffset"] - t["canonicalOffset"]))))
    # Include a previously correct endpoint that B cuts, plus a pedal regression.
    for kind, predicate in (("B_correct_cut", lambda t: abs(t["key_error"]) <= .05 and t["policyBOffset"] < t["gt_key_release"] - .05),
                            ("B_sustain_regression", lambda t: t["gt_pedal_release"] > t["gt_key_release"] and
                             abs(t["policyBOffset"] - t["gt_pedal_release"]) > abs(t["pedal_error"]) + .05)):
        candidates = [t for t in matched if predicate(t)]
        if candidates:
            selected.append((kind, max(candidates, key=lambda t: t["canonicalOffset"] - t["policyBOffset"])))
    result = []
    for kind, trace in selected:
        item = {"selection": kind, **trace}
        directory = output / "predictions/bytedance" / trace["case"]
        with np.load(directory / "library-framewise-output.npz") as matrices:
            column = trace["pitch"] - 21
            observations = []
            for name, seconds in (("key_release", trace["gt_key_release"]),
                                  ("pedal_release", trace["gt_pedal_release"]),
                                  ("decoder_end", trace["canonicalOffset"]),
                                  ("B_end", trace["policyBOffset"])):
                frame = round(seconds * 100)
                if frame < len(matrices["frame_output"]):
                    observations.append({"landmark": name, "frame": frame,
                        "frameActivation": float(matrices["frame_output"][frame, column]),
                        "offsetRegression": float(matrices["reg_offset_output"][frame, column]),
                        "acceptedOffsetPeak": bool(matrices["offset_output"][frame, column])})
            item["headObservations"] = observations
        result.append(item)
    return result, bool(correct_long)


def run(root, output):
    root = resolve_root(root)
    manifest = json.loads(MANIFEST.read_text())
    verify(root, manifest)
    summary = json.loads((output / "maps-enstdkcl-summary.json").read_text())
    assert summary["manifestSha256"] == sha256(MANIFEST)
    common = common_matches(summary["notes"])
    audit = annotation_audit(root, manifest)
    traces, has_correct_long = selected_traces(summary, output)
    review = {"manifestSha256": sha256(MANIFEST), "commonMatchedGroundTruth": common,
              "annotationAudit": audit, "correctByteDanceLongNoteFound": has_correct_long,
              "selectedTraces": traces}
    (HERE / "maps-enstdkcl-review.json").write_text(json.dumps(review, indent=2) + "\n")
    changes = summary["policyBChanges"]
    with (HERE / "maps-enstdkcl-policy-b-changes.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(changes[0]))
        writer.writeheader()
        writer.writerows(changes)
    groups = summary["groups"]
    totals = groups["TOTAL"]
    lines = ["# MAPS ENSTDkCl: onafhankelijke akoestische validatie", "",
        "Run 7 oktober 2026. **BYTEDANCE READY WITH KNOWN OFFSET LIMITATION**; **B DO NOT SHIP**.", "",
        "ByteDance blijft de primaire engine voor een demo met menselijke correctie van korte passages. Deze test rechtvaardigt geen claim van foutloze MIDI of betrouwbare lange nootduren. Policy B beschadigt correcte releases en blijft uitsluitend offline. Geen productiecode, thresholds, decoder, schema of editor gewijzigd.", "",
        "## Data, integriteit en labels", "",
        "Officiële [Zenodo-release 0.4](https://zenodo.org/records/18160555), uitsluitend ENSTDkCl.zip. Grootte **2608287080 bytes**, gecontroleerde MD5 **72bbdf40eb7af69225755e165a0a0a08**. ZIP en uitgepakte data staan buiten de repo, onder `<MAPS-root>`. Het uitgepakte payload is **4325567515 bytes**; samen met ZIP **6933854595 bytes (6,46 GiB)**, exclusief inferentiecache en kleine metadata. ZIP bevat 12239 entries; 3999 WAV/MIDI/TXT-paren: ISOL 999, RAND 1200, UCHO 1770, MUS 30.", "",
        "MAPS gebruikt fysieke Disklavier-piano's, aangestuurd door MIDI; dit is akoestische audio met onafhankelijke bronlabels, geen menselijke liveperformance. ENSTDkCl is de close-microphone-conditie. Zie de [oorspronkelijke auteurs](https://adasp.telecom-paris.fr/resources/2010-07-08-maps-database/). ByteDance vermeldt [MAESTRO-training](https://github.com/bytedance/piano_transcription/blob/master/README.md); MAESTRO is niet gebruikt als validatiedata.", "",
        "Alle geïnspecteerde audio: 44100 Hz, stereo PCM16. Naamstammen met `_ENSTDkCl` koppelen WAV, type-0 MIDI en TXT. MIDI note-on/off, velocity, tempo en CC64 worden rechtstreeks gelezen uit officiële MID-bestanden. Ground truth komt nooit uit predictions of appcorrecties. CC64 down/up is daadwerkelijk gecontroleerd, niet afgeleid uit alleen S0/S1 in de naam.", "",
        "Raw MIDI-tijdlijn: globale shift **0 s**, geen voorspellinggestuurde alignment. Mechanische toets-/hamerrespons en akoestische uitsterving kunnen afwijken van MIDI-commando's; onsetmatching is daarom geen bewijs van sample-exacte audio/MIDI-alignment. De hier gemeten secondegrote duurfouten kunnen niet worden verklaard door een kleine constante onsetlatentie.", "",
        f"Per-pitch ASCII/MIDI-audit: {audit['pairs']} paren, maximale onsetafwijking {audit['maxOnsetDifferenceSeconds']*1000:.3f} ms. Op de daadwerkelijk gescoorde subset maximaal {audit['selectedMaxEffectiveDifferenceSeconds']*1000:.3f} ms verschil tussen TXT en CC64-effectieve release, **geen verschil boven 1 ms**.", "",
        f"Buiten de geselecteerde vensters zijn {len(audit['fullDatasetEffectiveDifferencesOver1ms'])} afwijkende effectieve TXT-releases gevonden, maximaal 1,633 s. Concreet: bk_xmas1, pitch 37, onset 316,052 s; note-off en CC64-down staan beide op 316,206 s, maar note-off staat eerst in MIDI. TXT loopt door tot 317,839 s. De bestaande MIDI-parser respecteert eventvolgorde. Deze afwijking ligt buiten het [0,10)s-scorevenster; labels en matcher zijn niet aangepast. Volledige uitzonderingen staan in review.json.", "",
        "Bij de eerste modelvrije audit gaf sortering op afgeronde gelijktijdige ASCII-onsets tien onterechte pitch-orderflags in MUS. Daarom is de oorspronkelijke selectie gekozen uit 20 toen geaccepteerde MUS-bestanden. De nieuwe helper groepeert per pitch; alle 3999 paren hebben overeenkomende aantallen/pitches. De **al bevroren 24 cases blijven ongewijzigd**; de historische flags zijn transparant bewaard in het manifest. De selectie is dus de eerste vijf lexicografische MUS-bestanden van die oorspronkelijke geaccepteerde inventaris, niet van de later gecorrigeerde volledige inventaris.", "",
        "## Bevroren subset", "",
        f"Manifest bevroren vóór inferentie op {manifest['frozenAt']}; SHA256 `{sha256(MANIFEST)}`. Vier normale noten, vijf lange noten, drie repeated, drie sustain, vier akkoorden, vijf muziekfragmenten. Selectie alleen op MIDI/metadata: dichtst bij vooraf gekozen pitch-/duurdoelen, velocity 80 als tweede criterium, lexicografische ties. Geen selectie op modelkwaliteit.", "",
        "Muziek: oorspronkelijke samples [0,15)s als invoer voor beide modellen; score onsets [0,10)s. Overige cases: volledige audio. Ends worden niet afgeknipt tot het scorevenster. Geen geselecteerde GT-release valt voorbij het audiovenster (0 censored notes). Onderstaande stammen hebben steeds officiële .wav/.mid/.txt-partners; exacte relatieve paden en SHA256 staan in het manifest.", ""]
    lines += [table(["Case", "Type", "Originele stem", "GT", "Pitchrange", "CC64 down", "Audio / onset-score (s)"],
        [(c["caseId"], c["category"], Path(c["audio"]).stem, c["groundTruthNotes"], str(c["pitchRange"]),
          any(e["value"] >= 64 for e in c["cc64"]), f"{c['audioWindowSeconds']} / {c['evaluationOnsetWindowSeconds']}") for c in manifest["cases"]]), "",
        "## Matching en vergelijking", "",
        "Bestaande `benchmarks.metrics.score/read_midi/aggregate`, mir_eval 0.8.2: één-op-één matching, gelijke integer MIDI-pitch (1 cent tolerantie), onset ≤50 ms, offset uitgesloten van primaire matching. Micro-aggregatie over alle noten. MAE/mediaan/max alleen op gematchte noten; gemiste noten blijven FN, extra noten FP. De onsetmaximumfout wordt begrensd door de matcher en zegt niets over de fouten van FN/FP.", ""]
    fields = [("GT", "ground_truth_notes"), ("Predicted", "predicted_notes"), ("TP", "TP"), ("FP", "FP"), ("FN", "FN"),
              ("Precision", "precision"), ("Recall", "recall"), ("F1", "F1"), ("Onset MAE ms", "onset_mae_ms"),
              ("Onset mediaan ms", "onset_median_abs_ms"), ("Onset max ms", "onset_max_abs_ms"),
              ("Key offset MAE ms", "offset_mae_ms"), ("Key offset mediaan ms", "offset_median_abs_ms"), ("Key offset max ms", "offset_max_abs_ms"),
              ("CC64 effective MAE ms", "sustain_offset_mae_ms"), ("CC64 effective mediaan ms", "sustain_offset_median_abs_ms"),
              ("CC64 effective max ms", "sustain_offset_max_abs_ms"), ("Key error >250 ms", "offset_gt250ms"),
              ("Key error >500 ms", "offset_gt500ms"), ("Key error >1 s", "offset_gt1s"),
              ("Key early >50 ms", "offset_early"), ("Key late >50 ms", "offset_late"),
              ("End exact audio duration", "audio_end_exact"), ("End within 10 ms audio duration", "audio_end_near10ms")]
    fmt = lambda x: f"{x:.3f}" if isinstance(x, float) else x
    lines += [table(["Metric", "ByteDance A", "Basic Pitch"], [(label, *[fmt(totals[e][key]) for e in ENGINES]) for label, key in fields]), "",
        "ByteDance heeft overall meer FP (139 tegenover 120), ondanks veel hogere recall. De hypothese ‘Basic Pitch altijd meer extra noten’ klopt dus niet. Basic Pitch geeft meer FP bij losse/lange/sustainnoten en akkoorden; ByteDance bij repeated en muziek. Repeated F1 is hier hoger voor Basic Pitch. ByteDance is sterker in de overige categorieën, maar de long-score laat de gemiste pitch 105 expliciet meetellen.", "",
        "De offsetgemiddelden hierboven hebben verschillende coverage (541 versus 342 matches). Ter controle volgt vergelijking op dezelfde onafhankelijke GT-identiteiten die **beide** modellen matchten; geen nieuwe matching of selectie op offsetkwaliteit.", "",
        table(["Engine", "Gedeelde GT matches", "Onset MAE ms", "Key MAE ms", "Effective MAE ms"],
              [(e, common[e]["matched"], *[fmt(common[e][k]["mae_ms"]) for k in ("onset_error", "key_error", "pedal_error")]) for e in ENGINES]), "",
        "## Per categorie", "",
        table(["Categorie", "Engine", "GT", "Pred", "TP/FP/FN", "P/R/F1", "Onset MAE/mediaan/max ms", "Key MAE/mediaan/max ms", "Effective MAE ms"],
              [(category, e, m["ground_truth_notes"], m["predicted_notes"], f"{m['TP']}/{m['FP']}/{m['FN']}",
                '/'.join(f"{m[k]:.3f}" for k in ("precision", "recall", "F1")),
                '/'.join(f"{m[k]:.1f}" for k in ("onset_mae_ms", "onset_median_abs_ms", "onset_max_abs_ms")),
                '/'.join(f"{m[k]:.1f}" for k in ("offset_mae_ms", "offset_median_abs_ms", "offset_max_abs_ms")), f"{m['sustain_offset_mae_ms']:.1f}")
               for category, engines in groups.items() if category != "TOTAL" for e, m in engines.items() if e in ENGINES]), "",
        "Per bestand en aanvullende categorieflags (early/late, grensends, >250/500/1000 ms) staan in results.csv. Elke TP/FN/FP met pitch en raw timing staat in note-results.csv.", "",
        "## Lange noten en sustain", "",
        "Alle vier gematchte lange ByteDance-noten eindigen door de upstream **600-frame / ongeveer zes seconden cap**, niet door de adapter. De 3,587 s hoge noot (pitch 105) is volledig gemist; voorspelde pitches 103 en 104 zijn FP. Er is **geen correcte lange ByteDance-noot binnen ±50 ms** in deze subset: een correct voorbeeld kan dus niet eerlijk worden getoond. Basic Pitch treft de 12 s nootduur wel binnen 43 ms; beide engines hebben andere ernstige long-fouten.", ""]
    duration_rows = [r for r in summary["notes"] if r["category"] in ("long", "sustain") and r["engine"] in ENGINES and r["match"] != "FP"]
    lines += [table(["Case", "Engine", "Pitch", "GT onset", "Key release", "Pedal release", "Pred end", "Key error s", "Effective error s", "Match"],
        [(r["case"], r["engine"], r["pitch"], *[fmt(r[k]) for k in ("gt_onset", "gt_key_release", "gt_pedal_release", "pred_end", "key_error", "pedal_error")], r["match"]) for r in duration_rows]), "",
        "De drie losse sustaincases hebben onafhankelijke CC64-down/up. ByteDance matcht alle drie zonder FP; twee ends liggen circa 73–79 ms vóór pedaalrelease, de hoge noot 1,65 s erna. Pedal-extended release betekent hier release volgens MIDI-eventvolgorde en same-pitch-reattackregels van de bestaande parser; dit is **geen meting van volledige akoestische uitsterving**. In muziek verklaren veel late key offsets een vrijwel juiste pedaalrelease, terwijl de cap en andere late releases daar niet door worden verklaard.", "",
        "## Concrete model → decoder → adapter traces", "",
        "Raw segmentheads, gedeframede output en upstream events zijn extern gecachet. Elke gespiegeld verklaarde decoderbeslissing is vergeleken met de geïnstalleerde upstream decoder; upstream onset/end wordt vervolgens vergeleken met canonical output. Review.json bevat geselecteerde traces, offsetpeaks, frameactivatie en offsethead bij key/pedal/end/B-landmarks. Hieronder minstens twee echte late en twee vroege gevallen, plus sustain/repeated/akkoord en B-regressies.", "",
        table(["Selectie", "Case/pitch", "Key / pedal s", "Upstream / canonical s", "Decoder", "First offset/frame-disappear", "B end s", "Clipped"],
              [(t["selection"], f"{t['case']}/{t['pitch']}", f"{t['gt_key_release']:.4f}/{t['gt_pedal_release']:.4f}",
                f"{t['upstreamOffset']:.4f}/{t['canonicalOffset']:.4f}", t["decoder"]["reason"],
                f"{t['decoder']['firstOffsetFrame']}/{t['decoder']['firstFrameDisappear']}", f"{t['policyBOffset']:.4f}", t["clippingApplied"]) for t in traces]), "",
        "De 18,049 s noot eindigt upstream/canonical op 6,510 s; de offsethead heeft pas een geaccepteerde peak op 17,225 s. De cap verhindert dat die deze noot beëindigt. Bij de 11,994 s noot wordt een peak al op 0,542 s geaccepteerd terwijl frameactivatie blijft staan; A eindigt door de cap op 6,500 s, B kiest die vroege peak en beschadigt de noot verder. Dit bevestigt echte-audio decoderlimieten en toont tegelijk waarom ‘eerste peak altijd gebruiken’ geen algemene fix is.", "",
        "Het repeated-voorbeeld eindigt upstream in gepadde output via sequence_end en wordt door de bestaande adapter op echte audioduur geclipt; dit behoudt te lange canonical timing. Padding en decoder zijn observeerbaar, maar zijn hier niet gewijzigd.", "",
        "## Policy B: uitsluitend offline", "",
        f"Ongewijzigde policybron SHA256 `{summary['policyBSha256']}`. Alleen B-resultaat gebruikt, zonder C/D-scoring of silence bound. GT wordt pas **na** B-berekening aan diagnostiek gekoppeld. Pitch/onsets/TP/FP/FN zijn identiek aan A.", "",
        table(["Categorie", "Key MAE A/B ms", "Key mediaan A/B ms", "Key max A/B ms", "Effective MAE A/B ms", "Key beter/slechter", "Effective beter/slechter", "Nieuw early / correct key cut / sustainregressie"],
              [(category, *[f"{engines['bytedance'][k]:.1f}/{engines['bytedance_B_offline'][k]:.1f}" for k in
                 ("offset_mae_ms", "offset_median_abs_ms", "offset_max_abs_ms", "sustain_offset_mae_ms")],
                f"{engines['bytedance_B_offline']['key_improved']}/{engines['bytedance_B_offline']['key_worsened']}",
                f"{engines['bytedance_B_offline']['effective_improved']}/{engines['bytedance_B_offline']['effective_worsened']}",
                f"{engines['bytedance_B_offline']['new_early']}/{engines['bytedance_B_offline']['correct_key_cut_early']}/{engines['bytedance_B_offline']['sustain_regression']}") for category, engines in groups.items()]), "",
        "B verandert 73 gescoorde voorspellingen: 69 gematchte noten en vier FP. Key-release wordt beter bij 30 en slechter bij 39 matches; effectieve release beter bij 16 en slechter bij 53. ‘Nieuw early’ betekent B >50 ms vóór **effectieve** GT-release terwijl A dat niet was: 44 noten. Daarvan los gerapporteerd 27 eerder correcte fysieke releases die B te vroeg afbreekt en 19 sustainregressies (>50 ms extra effectieve fout). Deze groepen overlappen en mogen niet worden opgeteld. Alle 69 veranderde matches staan in policy-b-changes.csv.", "",
        "B verbetert de hoge sustainnoot, maar dat compenseert de beschadiging van correcte repeated/chord/muzieknoten niet. Overall key MAE **301,8 → 324,1 ms**; effective MAE **148,5 → 182,6 ms**. Beslissing: **B DO NOT SHIP** als algemene offsetfix.", "",
        "## CPU-performance en reproduceerbaarheid", ""]
    lines += [table(["Engine", "Inferentie totaal s", "Model load s", "Peak process RSS MiB", "Versies"],
        [(e, f"{totals[e]['runtime_seconds']:.3f}", f"{sum(m['modelLoadSeconds'] or 0 for k,m in summary['provenance'].items() if k.endswith('/'+e)):.3f}",
          f"{totals[e]['peak_rss_mib']:.1f}", str(summary['provenance']['01_isolated/'+e]['identity']['versions'])) for e in ENGINES]), "",
        "Windows CPU, bestaande Python 3.11.9 omgeving. Modellen één keer geladen per engine, clips sequentieel; adapters onveranderd. Runtime omvat transcribe + canonical validatie, exclusief model-load, diskcache en rapportage. Totaal inclusief model-load: ByteDance circa 320,5 s, Basic Pitch 7,3 s. Dit is een warme lokale benchmark, geen cold HTTP-joblatentie en geen hardware-onafhankelijke snelheidsclaim. RSS is elke 100 ms gesampled voor het hele proces; tussenliggende pieken kunnen worden gemist. CPU-threads/defaults zijn niet aangepast. Per-clip timing staat in CSV; SHA256 van audio, modelbestanden, adapter/upstreamcode en versies staat in elke externe provenance.json.", "",
        "Zie README.md voor download, checksum, externe paden, frozen manifest, modelruns en offline replay. Cache met afwijkende audio/engine/model/artifacts wordt geweigerd; gebruik dan een nieuwe outputdirectory, overschrijf geen eerdere run.", "",
        "## Beperkingen en besluit", "",
        "24 cases, één fysieke piano/microfoonconditie, vijf korte muziekfragmenten; muziek draagt 518/585 labels bij. Geen volledige datasetbenchmark, geen gecontroleerde achtergrondruisvergelijking, geen menselijke liveperformance en geen velocitykwaliteitclaim. Native pre-roll RMS is alleen diagnostisch gemeten; geen causaliteitsclaim over ruis. Hoge pitch 105 en lange-notencap zijn echte beperkingen. Alle raw metrics gebruiken onafhankelijke MIDI-labels zonder shifts of tuning.", "",
        "**BYTEDANCE READY WITH KNOWN OFFSET LIMITATION**: de hogere pitch/onset-recall en F1 ondersteunen ByteDance als primaire engine, met menselijke correctie voor de stagedemo. Lange nootduren zijn aantoonbaar onbetrouwbaar. **B DO NOT SHIP**. Aanbevolen volgende stap, alleen na beoordeling: een begrensd decoderonderzoek naar de zes-seconden-cap, met deze bevroren set als regressiecontrole en aparte aandacht voor sustain/repeated. Geen globale first-offsetpolicy invoeren.", "",
        "## Tests en worktree", "",
        "61 relevante tests geslaagd (MAPS 15, bestaande benchmark/ByteDance/policies samen 46), drie bestaande deprecationwarnings. De eerste testrun onder standaard Windows-temp faalde bij testfixture-setup door tempdirectoryrechten; een expliciete verse tempdirectory binnen de chatworkspace verhelpt dit zonder codewijziging. De bestaande uploadbug is buiten deze offline validatie gelaten. Geen commit/stage/push. Vooraf bestaande 105 Git-zichtbare bestanden worden met SHA256 gecontroleerd op ongewijzigde inhoud; volledige git-status wordt afzonderlijk geleverd.", ""]
    (HERE / "maps-enstdkcl-validation.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"commonMatches": common, "selectedTraceCount": len(traces), "correctLongFound": has_correct_long,
                      "annotationExceptions": len(audit['fullDatasetEffectiveDifferencesOver1ms']),
                      "selectedAnnotationExceptions": len(audit['selectedEffectiveDifferencesOver1ms'])}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.dataset_root, args.output.resolve())
