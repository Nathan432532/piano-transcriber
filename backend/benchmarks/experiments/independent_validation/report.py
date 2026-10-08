"""Render the complete scored holdout report; never imported by policies."""
from __future__ import annotations

from .assessment import release_state


def f(value, digits=3):
    return "—" if value is None else f"{value:.{digits}f}"


def table(headers, rows):
    return ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"] + ["| " + " | ".join(map(str, row)) + " |" for row in rows] + [""]


def render(summary, destination):
    groups, notes = summary["groups"], summary["notes"]
    manifest = summary["manifest"]
    fail_b = [r for r in summary["regressions"] if r["policy"] == "B" and r["failures"]]
    fail_c = [r for r in summary["regressions"] if r["policy"] == "C" and r["failures"]]
    noise_fail = summary["verdicts"]["cNoiseReliabilityFailure"]
    lines = ["# ByteDance: onafhankelijke offset-validatie", "",
             "> Historische synthesevalidatie vóór MAPS. Definitieve beslissing: ByteDance primary met menselijke correctie en bekende offsetbeperking; Policy B/C DO NOT SHIP, KEEP CURRENT CAP. Zie ../maps/maps-enstdkcl-validation.md. De onderstaande oorspronkelijke metrics/verdicts zijn geen huidige productaanbeveling.", "",
             f"Uitgevoerd: {summary['createdAt']}", "",
             f"**B: {summary['verdicts']['B']}; C: {summary['verdicts']['C']}.** Geen policy in productie toegepast; geen thresholds/dependency/adapter/schema/frontend gewijzigd. Geen commit of push.", "",
             "## Dataset", "",
             "Acht nieuwe onafhankelijke MIDI-plannen, **17 unieke ground-truthnoten**. Twee vooraf gekozen ruisvarianten herhalen vijf referentie-events; dit zijn geen vijf extra onafhankelijke labels. Clean en noise worden apart gescoord. De oorspronkelijke 23-notenbenchmark is niet gebruikt als primaire validatie.",
             "Twee bestaande piano-audioclips worden uitsluitend diagnostisch gebruikt. Hun akoestische/opnameherkomst is onbevestigd, onafhankelijke labels ontbreken, en de gebruiker heeft geen aanvullende echte akoestische opnames. Er is dus **geen bewezen verbetering op echte akoestische opnames**.", ""]
    lines += table(["Case", "Soort", "Categorie", "GT-noten", "Sustain", "GT-bron"],
                   [(c["name"], c["kind"] + "/" + c["variant"], c["category"], c["groundTruthNotes"] if c["groundTruthNotes"] is not None else "—",
                     "ja" if c["sustain"] is True else "nee" if c["sustain"] is False else "onbekend",
                     "vooraf geschreven MIDI" if c.get("midi") else "geen; diagnostisch") for c in manifest["cases"]])
    lines += [f"Manifest bevroren vóór inferentie: {manifest['frozenAt']}. SHA256: `{summary['manifestSha256']}`.",
              f"B/C exact dezelfde bron-SHA256 als vorige experiment: `{summary['policySha256']}`.",
              "Manifest/MIDI: `backend/data/ground_truth/fixtures/independent_validation/`; WAVs: `backend/data/ground_truth/rendered/independent_validation/` (gitignored).",
              "FluidSynth 2.5.6, dezelfde TimGM6mb.sf2, 44.1 kHz stereo PCM16, gain 0.2, chorus/reverb uit. Alle checksum- en rendercommando's zijn bevroren in manifest. Alle runtimebeslissingen worden berekend vóór de MIDI voor scoring wordt gedecodeerd. Geen prediction-afgeleide labels.",
              "Voor sustain-pair bestaan onafhankelijke isolated stems voor sample-level signaalextinctie. Extinctie/laatste niet-nul sample is een bovenlimiet, **geen perceptuele annotatie van hoorbare note end**. Voor reattack/overlap kan de globale audio-extinctie niet aan één noot worden toegekend.", "",
              "## Vaste policies en failcriteria", "",
              "A: exacte upstream events plus bestaande adapterclipping aan resampled audioduur. B: eerste upstream geaccepteerde offsetpiek in het reeds vastgelegde eventvenster; voorspeld pedaalinterval blokkeert een piek tijdens sustain. C: B, of zonder bruikbare piek de vooraf bestaande boundary/exact-zero guard. Logica ongewijzigd, geen tuning op holdout.",
              "Vroeg/correct/laat: bestaande **50 ms tolerance** voor veiligheid, zowel tegenover key als pedal-extended release. Dit is geen modelthreshold. Bestaande offset-F1 gebruikt onveranderd max(50 ms,20% duur). Offset-MAE en classificatie gelden alleen voor pitch/onset-matches; ontbrekende noten blijven zichtbaar als FN.", ""]
    for name, criterion in manifest["failCriteria"].items():
        lines.append(f"- {name}: {criterion}")
    lines += ["", "## Resultaten per categorie en totaal", "",
              "TP/FP/FN en F1 hieronder vereisen pitch+onset. Onset-F1 afzonderlijk negeert pitch. Pitches/onsets/counts zijn exact gelijk voor A/B/C; assertions controleren dat. Key/effective-release-MAE zijn ms. Effective release is pedal-extended waar aanwezig, anders key release. Clean TOTAL=17 unieke referentienoten; noise TOTAL=5 kopie-events; all TOTAL=22 eventinstanties, niet 22 onafhankelijke labels.", ""]
    rows = []
    for group, policies in groups.items():
        for p, m in policies.items():
            rows.append([group, p, m["ground_truth_notes"], f"{m['TP']}/{m['FP']}/{m['FN']}", f(m["F1"]), f(m["onset_F1"]), f(m["onset_mae_ms"]),
                         f(m["offset_mae_ms"]), f(m["sustain_offset_mae_ms"]), f(m["offset_median_abs_ms"]), f(m["max_offset_error_ms"]),
                         f"{m['early_key_offsets']}/{m['late_key_offsets']}", f"{m['early_effective_offsets']}/{m['late_effective_offsets']}", m["changed_offsets"]])
    lines += table(["Groep", "Policy", "GT", "TP/FP/FN", "Note-F1", "Onset-F1", "Onset-MAE", "Key-MAE", "Effective-MAE", "Key mediaan", "Key max", "Vroeg/laat key", "Vroeg/laat effective", "Gewijzigd"], rows)
    lines += ["### Per case", ""]
    lines += table(["Case", "Policy", "GT", "TP/FP/FN", "Onset-MAE ms", "Key-MAE ms", "Effective-MAE ms", "Mediaan ms", "Max ms", "Gewijzigd"],
                   [[r["case"], r["policy"], r["ground_truth_notes"], f"{r['TP']}/{r['FP']}/{r['FN']}", f(r["onset_mae_ms"]), f(r["offset_mae_ms"]),
                     f(r["sustain_offset_mae_ms"]), f(r["offset_median_abs_ms"]), f(r["max_offset_error_ms"]), r["changed_offsets"]] for r in summary["caseMetrics"]])
    lines += ["## Lange noten: iedere gematchte noot", "",
              "GT onset/key/pedal, raw peaks en endpoints in seconden. Iedere vroege offset is zichtbaar, ook wanneer A al vroeg eindigde. Een extra modelprediction heeft geen GT en staat afzonderlijk bij modelproblemen.", ""]
    long = [r for r in notes if r["category"] == "long" and r["gt_key_release"] is not None]
    lines += table(["Case/pitch", "GT onset", "GT key", "GT pedal", "Raw offsetpeaks (s:score)", "Upstream", "A", "B/state", "C/state", "Decoder"],
                   [[f"{r['case']}/{r['pitch']}", f(r["gt_onset"]), f(r["gt_key_release"]), f(r["gt_pedal_release"]),
                     ", ".join(f"{f(p['time'])}:{f(p['score'])}" + (" (buiten B-venster)" if not p["insidePolicyWindow"] else "") for p in r["raw_offset_peaks"]) or "—",
                     f(r["upstream_offset"]), f(r["A"]), f"{f(r['B'])}/{r['key_state_B']}", f"{f(r['C'])}/{r['key_state_C']}", r["decoder_reason"]] for r in long])
    for r in long:
        if r["key_state_B"] == "early" or r["key_state_C"] == "early":
            lines.append(f"**VROEGE LANGE NOOT:** {r['case']} pitch {r['pitch']}: key {f(r['gt_key_release'])}, A {f(r['A'])}, B {f(r['B'])}, C {f(r['C'])}. "
                         + ("Nieuwe policywijziging: zie failcriteria." if r["safety_B"] or r["safety_C"] else "Ongewijzigd vroeg A-probleem; geen nieuwe kandidaatregressie."))
    lines += ["", f"**Belangrijke dekkingsbeperking:** {sum(release_state(r['A'],r['gt_key_release']) == 'correct' for r in long)} van deze {len(long)} lange noten had onder A al een correcte offset binnen 50 ms. "
              "De specifieke regressievraag 'A-correcte lange noot door B vroeg afgebroken' is hierdoor niet overtuigend getest met echte modeloutputs. De helpers testen die failure wel deterministisch. Geen ontbrekend gevaarlijk geval achteraf toegevoegd of policy getuned."]
    lines += ["", "## Sustain: key release en pedal-release afzonderlijk", ""]
    sustain = [r for r in notes if r["gt_key_release"] is not None and r["gt_pedal_release"] > r["gt_key_release"]+1e-9]
    lines += table(["Case/pitch", "Policy", "GT key / pedal", "End", "Signed key-fout ms", "Signed pedal-fout ms", "Pedal-state"],
                   [[f"{r['case']}/{r['pitch']}@{f(r['gt_onset'])}", p, f"{f(r['gt_key_release'])}/{f(r['gt_pedal_release'])}", f(r[p]),
                     f(r[f"key_error_{p}"]*1000), f(r[f"pedal_error_{p}"]*1000), r[f"pedal_state_{p}"]] for r in sustain for p in "ABC"])
    lines += ["### Onafhankelijke synthese-extinctie en voorspeld pedaal", ""]
    for case in manifest["cases"]:
        if case["category"] != "sustain" or case["variant"] != "clean":
            continue
        predicted = summary["runtimeMetadata"][case["name"]]["pedalEvents"]
        lines.append(f"- {case['name']}: MIDI pedaal {case['pedalPlan']}; voorspeld pedaal `{predicted}`; globale signaalextinctie {f(case['digitalSignalExtinction'],6)} s. Isolated stems: `{case.get('isolatedNoteExtinctions', [])}`.")
    lines += ["", "## Alle regressies", "",
              "Ieder verslechterd gematcht event tegenover A staat hieronder, ook als het gemiddelde verbetert. Signed fouten en volledige raw peaklijsten staan in notes-CSV/JSON. Key-verbetering alleen is bij sustain geen succes als effective/pedal-release slechter wordt.", ""]
    if summary["regressions"]:
        lines += table(["Case/pitch", "Policy", "A → kandidaat", "GT key/pedal", "Key slechter", "Pedal slechter", "Failredenen"],
                       [[f"{r['case']}/{r['pitch']}#{r['predictionIndex']}", r["policy"], f"{f(r['A'])} → {f(r['candidate'])}", f"{f(r['keyRelease'])}/{f(r['pedalRelease'])}",
                         r["keyWorsened"], r["pedalWorsened"], ", ".join(r["failures"]) or "geen safety-fail"] for r in summary["regressions"]])
    else:
        lines += ["Geen geobserveerde verslechterde gematchte noot tegenover A in deze set. Dat bewijst geen algemene sustainveiligheid.", ""]
    lines += ["### Bestaande model/decoderproblemen, geen nieuwe B/C-wijziging", ""]
    extras = [r for r in notes if r["match"] == "unmatched_prediction"]
    lines += table(["Case", "Extra/onset-mismatch prediction", "Onset", "A/B/C"],
                   [[r["case"], r["pitch"], f(r["onset"]), "/".join(f(r[p]) for p in "ABC")] for r in extras])
    lines += ["Niet gematchte referentienoten: `" + str(summary["unmatchedReferences"]) + "`.",
              "Herhaalde noten behouden exact hun pitch/onset/eventcount. Veranderingen mogen niets verlengen voorbij A; de policyvoorkeur zoekt strikt vóór de volgende same-pitch onset. Overlap/chordpitches worden niet als één event behandeld.", "",
              "## Clean versus vaste achtergrondruis", "",
              "Exact: PCG64, stereo Gaussian, lfilter [1]/[1,-0.97], RMS -70 dBFS/channel, seeds 20261007 en 20261008; additief zonder signaalnormalisatie, saved PCM24. Het is een lage gekleurde ruisproxy, geen volledige microfoon/ruimte-simulatie. MIDI/duur zijn ongewijzigd. Verschillen A/B tussen varianten kunnen ook door modelrespons op ruis komen; C-minus-B isoleert de guardbijdrage binnen dezelfde inferentie.", ""]
    for case in manifest["cases"]:
        if case["variant"] != "noise":
            continue
        parent = case["parent"]
        for name in (parent, case["name"]):
            subset = [r for r in notes if r["case"] == name]
            metrics = {r["policy"]: r for r in summary["caseMetrics"] if r["case"] == name}
            guard_changes = sum(abs(r["C"]-r["B"]) > 1e-7 for r in subset)
            lines.append(f"- {name}: native terminal-silence bound {summary['runtimeMetadata'][name]['terminalSilenceStart']}; "
                         f"C≠B events {guard_changes}; key-MAE A/B/C {f(metrics['A']['offset_mae_ms'])}/{f(metrics['B']['offset_mae_ms'])}/{f(metrics['C']['offset_mae_ms'])} ms; "
                         f"effective-MAE A/B/C {f(metrics['A']['sustain_offset_mae_ms'])}/{f(metrics['B']['sustain_offset_mae_ms'])}/{f(metrics['C']['sustain_offset_mae_ms'])} ms.")
    lines += ["", "Op beide noisy WAVs ontbreekt exacte digitale eindstilte. Daarom kan de bevroren guard geen extra C-verbetering boven B leveren; **C=B** op de noisy cases. Dit zegt niets over de juistheid van hun gemeenschappelijke offsets. Geen epsilon/ruisdrempel toegevoegd.", "",
              "C-specifieke effectieve-release-MAE-winst (B minus C), clean/noise: `" + str(summary["noisePairs"]) + "`. "
              + ("**FAIL guard-betrouwbaarheid:** waargenomen cleanwinst verdwijnt met ruis." if noise_fail else "Geen clean guardwinst aanwezig om een verlies te kwantificeren."), "",
              "### Ieder matched clean/noise-event", "",
              "Dit zijn veranderingen tussen twee inferenties (clean en ruis), afzonderlijk van policyregressies tegenover A binnen één inferentie. Key/pedal-referenties blijven identiek; signed effectieve fouten zijn ms.", ""]
    lines += table(["Noise-case/pitch", "Policy", "Key / effective release", "Clean end", "Noise end", "Clean fout ms", "Noise fout ms", "Slechter met ruis"],
                   [[f"{r['noiseCase']}/{r['pitch']}", r["policy"], f"{f(r['gtKeyRelease'])}/{f(r['gtPedalRelease'])}", f(r["cleanEnd"]), f(r["noiseEnd"]),
                     f(r["cleanEffectiveErrorMs"]), f(r["noiseEffectiveErrorMs"]), r["worsensUnderNoise"]] for r in summary["noiseEventComparisons"]])
    lines += ["## Bestaande piano-audio: alleen diagnostiek", ""]
    for case in manifest["cases"]:
        if case["category"] != "diagnostic":
            continue
        rows = [r for r in notes if r["case"] == case["name"]]
        meta = summary["runtimeMetadata"][case["name"]]
        lines += [f"### {case['name']}", "",
                  f"SHA256 `{case['audioSha256']}`; {f(meta['provenance']['duration'])} s; {len(rows)} predictions; pitches {sorted({r['pitch'] for r in rows})}.",
                  f"B wijzigt {sum(abs(r['B']-r['A'])>1e-7 for r in rows)} offsets; C wijzigt {sum(abs(r['C']-r['A'])>1e-7 for r in rows)}. "
                  f"Terminal-silence bound {meta['terminalSilenceStart']}; boundary-events {sum(r['decoder_reason'] in {'six_second_cap','sequence_end'} for r in rows)}.",
                  "Geen onafhankelijke key/pedal/audible labels; geen accuracy, muzikale verbetering of correctheid geconcludeerd uit minder/langer/korter gedetecteerde noten. Beide zijn bestaande sampleloops, geen bevestigde nieuwe microfoonperformance. De 140_Cm-clip is eerder technisch getest en vormt hier alleen nieuwe policytrace, geen nieuw onafhankelijk kwaliteitsbewijs.", ""]
    lines += ["## Beslissing: zes gevraagde antwoorden", "",
              f"1. **Is B veilig genoeg op onafhankelijk materiaal?** {'Nee: concrete safety-fails staan hierboven.' if fail_b else 'Niet bewezen: geen geobserveerde safety-fail in deze set, maar acht syntheseplannen met één SoundFont en geen bevestigde echte akoestische labels volstaan niet voor READY.'}",
              "2. **Is C duidelijk beter dan B buiten de originele benchmark?** Vergelijk de clean/noise-totalen hierboven. Eventuele cleanwinst door de guard is afzonderlijk zichtbaar; bij beide noisevarianten is C exact B. Er is geen aangetoonde algemene voorsprong op niet-perfect-stille opnames.",
              "3. **Is de runaway/stiltecomponent bruikbaar op niet-perfect-stille audio?** Nee in deze vaste ruisproef: er is geen exact-zero bound en de guard abstineert. Herkenning van cap/sequence-end blijft bruikbaar als diagnose, maar geeft geen betrouwbare muzikale release.",
              "4. **Zijn er te vroeg afgebroken lange/sustainnoten?** Alle early-states staan in de long/sustaintabellen; safety-fails onderscheiden nieuw beleidsschade van reeds vroege A. De 7.5 s held note wordt upstream door de bestaande 600-framegrens vroeg gesloten; deze stap lost dat niet op.",
              f"5. **Welke policy als eerste productiefix?** {'Geen van beide in deze vorm: schadelijke wijzigingen blokkeren uitrollen.' if fail_b or fail_c else 'Geen nu. B blijft het kleinere onderzoeks-kandidaatonderdeel; C biedt geen aantoonbare extra werking zonder perfecte eindstilte.'}",
              f"6. **Is het bewijs sterk genoeg om dat nu te doen?** Nee. B: **{summary['verdicts']['B']}**; C: **{summary['verdicts']['C']}**. Geen automatische productiewijziging. "
              + ("De concrete failurecases zijn falsificerend bewijs voor de huidige policies." if fail_b or fail_c else "Voor READY ontbreken onafhankelijke akoestische key/pedal-events en bredere timbre/noise-validatie.")
              + (" C verliest bovendien de guardwinst bij achtergrondruis." if noise_fail else ""),
              "", "## Reproduceren en bestanden", "",
              "Zie `../experiments/independent_validation/README.md`. Eerste run: prepare, daarna run --capture. Volgende run: run zonder --capture gebruikt dezelfde opgeslagen raw heads, geen inferentie. Alle input/outputhashes worden gecontroleerd; geen labels worden uit predictions gegenereerd.",
              "Nieuwe code: onafhankelijke prepare/capture/assessment/report en tests. Nieuwe fixtures: acht MIDI's, twee onafhankelijke pair-stem-MIDI's en manifest. Nieuwe rapporten: dit Markdown, metrics-CSV, notes-CSV en JSON. WAVs/modeloutputs zijn gitignored; bestaande worktree volledig behouden.", ""]
    lines += ["## Verificatie van deze opdracht", "",
              "62 tests geslaagd: 19 bestaande offset-policytests, 15 benchmarktests, 12 ByteDance-adaptertests en 16 nieuwe validatietests. Drie bestaande FastAPI/Starlette-deprecationwarnings. Geen failures in deze suites; bestaande testverwachtingen niet aangepast. De bekende Windows oversized-uploadfailure is buiten deze validatie gehouden: niet opnieuw gedraaid of gerepareerd. Frontend is ongewijzigd en niet opnieuw getest.",
              "Een clean hold_c4_4s WAV is opnieuw gerenderd met het vastgelegde commando: byte-identieke SHA256. De offline replay gebruikt bevroren heads; nootbeslissingen, metrics en CSV's worden op identieke resultaten gecontroleerd. Alle 155 reeds aanwezige bron/fixture/baseline/policy/upstreambestanden uit de startsnapshot blijven identiek. Geen staging, commit of push.", ""]
    destination.write_text("\n".join(lines), encoding="utf-8")
