"""Write the cap diagnosis and plot from completed offline replays."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from benchmarks.maps.report import table
from .run import VARIANTS, seam_observations


def plot(cache, destination):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True, layout="constrained")
    for axis, (case, pitch, cap_time) in zip(axes, (("07_long", 82, 6.51), ("08_long", 62, 6.50), ("09_long", 31, 6.51))):
        directory = cache / "predictions/bytedance" / case
        with np.load(directory / "raw-segment-heads.npz") as raw:
            for segment, color in ((0, "#536e9a"), (1, "#c97831")):
                seconds = np.arange(1001) / 100 + 5 * segment
                axis.plot(seconds, raw["frame_output"][segment, :, pitch - 21], color=color,
                          linewidth=1.4, linestyle="--", label=f"raw segment {segment}")
        with np.load(directory / "library-framewise-output.npz") as joined:
            seconds = np.arange(len(joined["frame_output"])) / 100
            axis.plot(seconds, joined["frame_output"][:, pitch - 21], color="#23816f", linewidth=2, label="deframed output")
        axis.axvline(cap_time, color="#a64e59", linestyle=":", label="600-frame cap")
        axis.axvline(7.5, color="#202934", linestyle=":", label="deframe join")
        axis.axhline(.1, color="#707070", linewidth=.8, label="unchanged frame threshold")
        axis.set(xlim=(5.8, 9.5), ylim=(-.03, 1.03), ylabel="frame activation", title=f"{case}, MIDI pitch {pitch}")
        axis.grid(alpha=.15)
    axes[0].legend(loc="upper right", fontsize=8, ncol=2)
    axes[-1].set_xlabel("Global audio time (seconds)")
    fig.suptitle("Raising the cap exposes disagreement between overlapping model segments")
    fig.savefig(destination, dpi=150)
    plt.close(fig)


def run(output):
    targeted = json.loads((output / "targeted-summary.json").read_text())
    full = json.loads((output / "full-summary.json").read_text())
    assert targeted["manifestSha256"] == full["manifestSha256"]
    cache = Path(full["cache"])
    seams = seam_observations(cache)
    (output / "segment-seam-observations.json").write_text(json.dumps(seams, indent=2) + "\n")
    plot(cache, output / "segment-frame-activation.png")
    fmt = lambda x: "—" if x is None else f"{x:.3f}" if isinstance(x, float) else str(x)
    lines = ["# MAPS: diagnose van de zes-seconden-cap", "",
        "8 oktober 2026. Beslissing: **KEEP CURRENT CAP**. Geen productieadapter/dependency gewijzigd; geen thresholds, offsetpeakregel, onset/pitch-/pedaallogica of Policy B/C toegepast. De cap is een echte decoderlimiet, maar verhogen/verwijderen is op deze data geen verdedigbare kleine productiefix.", "",
        "## Root cause en timing", "",
        "Geïnstalleerd `piano-transcription-inference==0.0.6`: `.venv/Lib/site-packages/piano_transcription_inference/piano_vad.py`, functie `note_detection_with_onset_offset_regress`, regel 64. De exacte conditie:", "",
        "```python", "if bgn and (i - bgn >= 600 or i == onset_output.shape[0] - 1):", "```", "",
        "De decoder schrijft dan een event op frame i en wist bgn/frame_disappear/offset_occur. Dit is een harde letterlijke constante, geen configureerbare adapterwaarde. De cap wordt gecontroleerd na de bestaande frame-disappearance/offset-midpointregel. Een volgende onset sluit de vorige noot eerder af op i−1. Een onset op frame 0 wordt door upstream truthiness anders behandeld; dat gedrag is bewust niet gerepareerd in dit experiment.", "",
        "Werkelijke configuratie: `config.py:1,6` heeft sample_rate=16000, frames_per_second=100. `models.py:159–161,178` berekent hop_size=16000//100=160 samples en gebruikt die als spectrogramhop. Dus **160/16000=0,010 s/frame**, en **600×0,010=6,000 s**. `utilities.py:401–402` converteert events via `(frame + regression_shift)/100`; de uiteindelijke eventduur is `6 + (offset_shift−onset_shift)/100`, daarom ongeveer zes seconden. Bij het gemeten geval pitch 31 is beginframe 51, endframe 651, onsetshift −0,428922 en offsetshift 0: duur 6,004289 s vóór float32-eventconversie.", "",
        "## Historische reden", "",
        "Een aparte read-only upstream checkout toont dat de 600-conditie al aanwezig is in de eerste commit [9300eaa, 6 mei 2020](https://github.com/qiuqiangkong/piano_transcription_inference/commit/9300eaab2feb1b0a8f97009a5d436b0db133ca2b). `git log -S 600`, de vier commits die piano_vad.py wijzigden, blame en broncomments geven geen keuzeonderbouwing. Het enige comment bij deze tak is ‘Offset not detected’. Ook de README en 24 beschikbare upstream issue/PR-bodies leveren geen verklaring voor precies zes seconden. **reason unknown**. Niet bewezen dat het een workaround voor segmentgrenzen is. De huidige [upstream bron](https://github.com/qiuqiangkong/piano_transcription_inference/blob/master/piano_transcription_inference/piano_vad.py) heeft dezelfde conditie.", "",
        "## Audio → model → decoder → canonical", "",
        "Audio wordt door de bestaande binding met librosa naar 16 kHz mono omgezet. Lange input krijgt overlappende modelsegmenten; de modelheads worden vervolgens gedeframed tot één tijdreeks. Eén nootdecoder per pitch loopt over die samengevoegde tijdreeks. De cap is dus **decoder-only en onafhankelijk van een individuele segmentlengte**. Op de cap staat frameactivatie bij de vier lange matches nog duidelijk boven 0,1 (circa 0,714–0,988); het netwerk is daar nog actief. Geen echte offset is vereist voor de cap-stop.", "",
        "De bestaande adapter verandert de upstream end niet wanneer die binnen audio ligt; hij clipt uitsluitend ends voorbij echte audioduur en laat starts buiten echte audio weg. De canonical JSON bevat daarom dezelfde te vroege cap-end. In het experiment is dezelfde bestaande `normalize_bytedance_notes` gebruikt, zonder wijzigingen.", "",
        "## Segmentatie en gevonden tweede beperking", "",
        "`inference.py:18,77–94,125–173`: segment_samples=160000, dus 10 s; enframe-hop=80000, dus 5 s en 50% overlap. Audio wordt met nullen tot een veelvoud van 10 s gepad. Elk segment krijgt een eigen model-forward, zonder GRU-hidden-state-overdracht. De framehead conditioneert mede op onset/offsetheads (`models.py:242–246`). Segment B start op 5 s en bevat de oorspronkelijke onset rond 0,5 s dus niet. Het effect daarvan is hier observationeel vastgesteld; een causale modelablatietest is niet uitgevoerd.", "",
        "Deframe verwijdert bij meerdere segmenten hun laatste center=True-frame. Het bewaart frames 0–749 uit segment 0, frames 250–749 uit middensegmenten en frames 250–999 uit het laatste segment. **Geen averaging, blending of nootstitching**: joins op globale frames 750,1250,1750,... (7,5/12,5/17,5 s). De decoderstate wordt daar niet gereset; een noot kan technisch over joins blijven bestaan, mits de geselecteerde heads actief blijven.", "",
        "Op drie lange MAPS-noten is dat niet het geval. Op hetzelfde fysieke tijdstip 7,5 s levert segment 0 nog frameactivatie >0,1, terwijl segment 1 vrijwel nul levert. Deframe schakelt naar segment 1 en veroorzaakt een frame-disappearance-stop op exact 7,5 s zodra de cap die niet eerder afbreekt:", "",
        table(["Case/pitch", "Framehead segment 0 @7,5s", "Framehead segment 1 @7,5s", "Nocap decoder stop"],
              [(r["case"] + "/" + str(r["pitch"]), f"{r['segment0Frame']:.9f}", f"{r['segment1Frame']:.9f}", "frame 750: frame_disappearance") for r in seams if r["globalTime"] == 7.5]), "",
        "Grafiek: `experiments/long_note_cap/results/segment-frame-activation.png` (relatief aan dit rapport).", "",
        "Modeloutput na zes seconden is aanwezig: 2000/3000 samengevoegde frames voor de langere clips. Maar aanwezigheid van output betekent niet dat de framehead de aangehouden noot blijft herkennen. Bij pitch 31 is ook een latere offsetpeak op 17,225 s aanwezig; die kan de al op 7,5 s beëindigde noot niet herstellen. De oorspronkelijke 18,05 s noot heeft dus zowel een capprobleem als een segment/model-headprobleem.", "",
        "Verder blijft `inference.py:94` `[0:audio_len]` gebruiken met **samples** als slice-index op een **frame**-matrix. Daardoor blijft gepadde output meestal aanwezig: 1001 frames bij één segment en 2000/3000 bij langere clips. Dit bestaande probleem is hier alleen beschreven, niet gerepareerd. De adapterclips blijven exact gelijk.", "",
        "## Offline varianten en targeted gate", "",
        "Lokale decoderreproductie onder `experiments/long_note_cap/decoder.py`; alleen maximum decoderduur verschilt. A=600 frames, cap-variant B=1200, C=3000, D=None. **Cap-variant B is niet de eerder verworpen offset Policy B.** Geen upstream monkeypatch; geen modelinferentie; geen herbinning of thresholdtuning. De cached accepted peaks/shifts/frameheads blijven onveranderd.", "",
        "3000 frames is gekozen als beschikbare-output-bovengrens van deze bevroren cache, niet uit GT-release: maximaal 3000 frames. C kan op deze input geen vroege duurcap triggeren en is daarom bounded-equivalent aan D. Ook D heeft de bestaande finite-array-loop en last-frame-stop; geen oneindige zoeklus. Op langere toekomstige input zijn B/C/D niet equivalent.", "",
        f"Targeted eerst: {', '.join(targeted['caseIds'])}. De normale controls, repeated, sustain en akkoord zijn unchanged; drie long-matches verbeteren enigszins en één verslechtert. Dat is technisch plausibel voor een volledige **risicocontrole**, niet voldoende voor productiegoedkeuring. Daarna exact dezelfde 24 frozen cases. Manifest SHA256 `{full['manifestSha256']}`.", "",
        "A wordt op alle 88 pitches van iedere clip exact vergeleken met de geïnstalleerde upstreamdecoder, de gecachete library-events en canonical JSON. Ook raw-segmentheads → upstream deframe → cached matrices is bit-exact gecontroleerd. Alle package-/adapter-/model-/audio-/artifact-hashes zijn gevalideerd. Geen ground truth beschikbaar in de decoderfunctie; labels worden pas na globale decoding gekoppeld voor scoring en traces.", "",
        "## Alle vijf lange noten", "",
        "Endtijden in seconden op dezelfde raw MIDI-tijdlijn (geen shifts). ‘Beste fout’ hieronder is slechts diagnostiek van de vier vooraf gekozen globale regels; er wordt geen per-noot policy gekozen.", ""]
    long_rows = []
    for case in ("05_long", "06_long", "07_long", "08_long", "09_long"):
        matches = {v: next(r for r in full["notes"] if r["case"] == case and r["variant"] == v and r["match"] != "FP") for v in VARIANTS}
        ref = matches["A_600"]
        errors = [abs(r["key_error"]) for r in matches.values() if r["key_error"] is not None]
        long_rows.append((case, ref["pitch"], fmt(ref["gt_key_release"] - ref["gt_onset"]),
                          fmt(ref["gt_onset"]), fmt(ref["gt_key_release"]),
                          *[fmt(matches[v]["pred_end"]) for v in VARIANTS], fmt(min(errors)) if errors else "FN in alle varianten"))
    lines += [table(["Case", "Pitch", "GT duur", "GT onset", "GT key end", "A end", "B end", "C end", "D end", "Beste abs fout s"], long_rows), "",
        "Pitch 105 wordt door alle varianten gemist; andere voorspelde pitches blijven FP. Pitch 95 verslechtert van 460 ms te laat naar 1602 ms te laat; upstream loopt door tot 10 s padded sequence-end en canonical clipt op 7,662 s. Pitches 82/62/31 winnen slechts ongeveer één seconde en eindigen alsnog te vroeg op de segmentjoin. **Geen lange match krijgt een release binnen ±50 ms.**", "",
        "## Long-note traces en normale controls", "",
        "Targeted-summary.json bevat alle matched noottraces voor alle varianten: GT onset/key/pedal/duration, audio duration, decoderframes/shifts/reason, canonical end/clipping, offsetpeaks en frame-/offsethead-observaties. De ontbrekende pitch 105 staat als FN in targeted/full-notes.csv. Hieronder de vier cap-matches plus twee redelijk gedecodeerde normale controls; key=pedal bij deze S0-cases.", ""]
    baseline_traces = [t for t in targeted["traces"] if t["variant"] == "A_600" and (t["category"] == "long" or t["case"] in ("01_isolated", "02_isolated"))]
    lines += [table(["Case/pitch", "GT onset/key/pedal", "GT duur/audio duur", "Raw onset", "Begin/endframe", "Raw end/canonical", "Reden / clipping", "Activatie @cap", "Accepted peaks na onset"],
        [(f"{t['case']}/{t['pitch']}", '/'.join(f"{t[k]:.6f}" for k in ("gt_onset", "gt_key_release", "gt_pedal_release")),
          f"{t['trueKeyDuration']:.6f}/{t['audioDuration']:.6f}", f"{(t['decoder']['beginFrame']+t['decoder']['onsetShift'])/100:.6f}",
          f"{t['decoder']['beginFrame']}/{t['decoder']['endFrame']}", f"{t['rawOffset']:.6f}/{t['canonicalEnd']:.6f}",
          f"{t['decoder']['reason']} / {t['clipped']}", fmt(next((h['frameActivation'] for h in t['headLandmarks'] if h['landmark']=='sixSecondPoint'),None)),
          str([round(p['time'],6) for p in t['acceptedOffsetPeaks']])) for t in baseline_traces]), "",
        "## Full MAPS replay", "",
        "Een-op-één gelijke MIDI-pitch, onset ≤50 ms; offsets apart, bestaande MAPS evaluator/mir_eval. Elke variant heeft exact dezelfde **541 TP / 139 FP / 44 FN**, precision 0,795588, recall 0,924786, F1 0,855336; onset-MAE **13,083 ms**. Pitch/start/velocity/confidence zijn op volledige canonical lijsten identiek gecontroleerd. Alleen vijf canonical ends wijzigen: vier TP en één FP, uitsluitend in long-cases.", ""]
    fields = [("Key MAE ms", "offset_mae_ms"), ("Key mediaan ms", "offset_median_abs_ms"), ("Key max ms", "offset_max_abs_ms"),
              ("Effective MAE ms", "sustain_offset_mae_ms"), ("Effective mediaan ms", "sustain_offset_median_abs_ms"),
              ("Effective max ms", "sustain_offset_max_abs_ms"), (">250 ms", "offset_gt250ms"), (">500 ms", "offset_gt500ms"),
              (">1 s", "offset_gt1s"), ("Early >50 ms", "offset_early"), ("Late >50 ms", "offset_late"),
              ("Scored end exact audio", "audio_end_exact"), ("Upstream end beyond audio, all real starts", "upstreamBeyondAudio"),
              ("Canonical beyond audio", "canonicalBeyondAudio")]
    lines += [table(["Metric", *VARIANTS], [(name, *[fmt(full['groups']['TOTAL'][v][key]) for v in VARIANTS]) for name,key in fields]), "",
        table(["Categorie", "Key MAE A / B,C,D ms", "Key mediaan A / B,C,D ms", "Key max A / B,C,D ms", "Effective MAE A / B,C,D ms"],
              [(category, *[f"{groups['A_600'][key]:.3f} / {groups['D_no_cap'][key]:.3f}" for key in
                ("offset_mae_ms", "offset_median_abs_ms", "offset_max_abs_ms", "sustain_offset_mae_ms")]) for category,groups in full['groups'].items() if category != 'TOTAL']), "",
        "## Actief gecontroleerde regressies", "",
        "- **Normal/repeated/sustain/chords/music:** canonical noten en ends blijven op alle geselecteerde cases identiek. Next-onset sluit eerdere same-pitch noten nog steeds op het voorafgaande frame; geen nieuw doorlopen over een volgende onset. Pitches worden onafhankelijk gedecodeerd; geen nieuwe koppeling tussen akkoordnoten. Dit is bewijs voor deze subset, geen garantie voor alle audio.",
        "- **Long pitch 95:** nieuwe duidelijke regressie: end 6,520→7,662 s, absolute key/effective-fout 0,460→1,602 s. Frameactivatie blijft zelfs op 10 s padded output 0,981. Geen geaccepteerde offset; langer laten doorlopen maakt spurious sustained activation riskanter.",
        "- **False positive pitch 74 in 08_long:** ongewenste duur 6,500→7,500 s; de FP-count blijft gelijk maar de extra noot wordt één seconde langer. Dit telt niet mee in matched offset-MAE en is daarom expliciet vermeld.",
        "- **Long pitch 82/62/31:** beperkt beter, maar nieuwe stop is de framehead-discontinuïteit bij 7,5 s. Drie fouten blijven 1,095/5,008/11,063 s te vroeg. Een hogere cap herstelt geen ontbrekende modelactivatie.",
        "- **Audio-end:** upstream-events voorbij echte audio 19→20 (alle echte starts, inclusief muziekcontext na scorevenster), scored canonical grensends 5→6; canonical nooit voorbij audio door ongewijzigde clipping. Dit is geen bewijs dat die clips correcte releases hebben.",
        "- **Eerder correcte matches:** geen door deze capvarianten nieuw beschadigde correcte ±50 ms-release op deze subset. De één al foute lange noot en verlengde FP zijn wel relevante regressies; meer fouten >500 ms (97→98) en >1 s (36→37).",
        "- **Ruis:** geen nieuwe gecontroleerde noise-inferentie uitgevoerd; cached spurious activations/FP en deterministische persistent-headtests laten het mechanisme zien. Een capvrij decoderpad kan op langere input doorgaan tot beschikbare output stopt; dat is begrensd maar geen kwaliteitsgarantie.", "",
        "Full-changes.csv vermeldt alle vijf veranderde noten voor elk van B/C/D; full-results.csv geeft per case alle metrics en flags. targeted/full-notes.csv bewaart TP/FN/FP afzonderlijk. De oude MAPS-resultaten zijn niet overschreven.", "",
        "## Stagedemo-aanbeveling en maximaal drie opties", "",
        "**KEEP CURRENT CAP.** De huidige cap veroorzaakt een zichtbare fout, maar simpel verhogen verwijdert die niet: een gemiddeld voordeel van slechts **3,397 ms** overall en een nog steeds 11,063 s fout op de langste noot, tegenover een nieuwe >1 s releasefout en een langere FP. Dat is geen veilige, merkbare productverbetering voor een demo met menselijke correctie.", "",
        "1. **Cap behouden** — kleinste/veiligste huidige keuze. Bekende duurbeperking documenteren en handmatig corrigeren. Geen codewijziging nodig.",
        "2. **Cap verhogen via een expliciete lokale decoderwrapper** — kleiner dan herontwerp, maar nu afgewezen door regressie en resterende segmentfouten. De library biedt geen instelling: alleen een extra adapterparameter is technisch onvoldoende. Niet als productexperiment aanbevelen op huidig bewijs.",
        "3. **Begrensd vervolgonderzoek naar segmentheads/deframing en decodercontinuïteit** — ingrijpender; eerst offline bewijs verzamelen rond 7,5 s joins voordat een lokale wrapper of wijziging van samenvoegen wordt overwogen. Geen garantie dat alleen een decoderwijziging de ontbrekende frameactivatie kan herstellen. Geen grote refactor of productiewijziging nu.", "",
        "De kleinste verdedigbare productiewijziging op dit bewijs is **geen runtimewijziging**. Als verder onderzoek gewenst is, is het nieuwe gerichte probleem de segmenthead-discrepantie, niet de constante geïsoleerd. Policy B blijft verworpen; Policy C is niet gebruikt.", "",
        "## Tests, runtime en reproduceren", "",
        "60 relevante tests: nieuwe captests (13), MAPS, ByteDance-adapter, bestaande offsetdiagnostiek en matcher. Drie bestaande deprecationwarnings. Tests omvatten korte noot, exacte capgrens/stopvolgorde, lange noot, next-onset, persistent activation, finite-output-stop, adapterclipping, joins zonder decoderreset, echte deframe-chunkselectie, onafhankelijke akkoordpitches en actual-upstream-baseline-equivalentie op deterministische random heads.", "",
        f"Geen modelinferentie uitgevoerd. Targeted replay {targeted['offlineReplaySeconds']:.1f} s; full replay {full['offlineReplaySeconds']:.1f} s inclusief cachehashes, decoding, scoring en raw-deframeverificatie. Dit zijn offline analysetijden, geen productinference-latenties.", "",
        "Vanuit backend, met dezelfde bestaande Python 3.11-venv en ongewijzigde externe MAPS-cache:", "",
        "```powershell",
        "$capRoot = '<MAPS-root>\\ENSTDkCl'",
        "$capCache = '<MAPS-root>\\evaluation-20261007'",
        "$capOutput = 'benchmarks/maps/experiments/long_note_cap/results'",
        "& '..\\.venv\\Scripts\\python.exe' -m benchmarks.maps.experiments.long_note_cap.run --dataset-root $capRoot --cache $capCache --output $capOutput --stage targeted",
        "if ($LASTEXITCODE -ne 0) { throw 'Targeted replay failed' }",
        "& '..\\.venv\\Scripts\\python.exe' -m benchmarks.maps.experiments.long_note_cap.run --dataset-root $capRoot --cache $capCache --output $capOutput --stage full",
        "if ($LASTEXITCODE -ne 0) { throw 'Full replay failed' }",
        "& '..\\.venv\\Scripts\\python.exe' -m benchmarks.maps.experiments.long_note_cap.report --output $capOutput",
        "```", "",
        "297 bestaande repo-/dependency-/cachebestanden zijn vooraf met SHA256 beschermd. Definitieve controle en volledige git-status worden naast dit rapport geleverd. Dataset/ZIP/WAV/MIDI zijn niet toegevoegd aan de repo. Alle toevoegingen zijn experimentele code, tests en nieuwe rapportartefacten. Geen commit/stage/push, geen productie- of dependencypatch.", ""]
    destination = Path(__file__).parents[2] / "maps-long-note-cap-diagnosis.md"
    destination.write_text("\n".join(lines), encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    run(parser.parse_args().output.resolve())
