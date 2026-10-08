# Lokale ByteDance-integratie en verificatie

> Historisch end-to-end-bewijs. Definitieve kwaliteitsbeslissing na MAPS:
> **BYTEDANCE READY WITH KNOWN OFFSET LIMITATION**; Policy B/C **DO NOT SHIP**;
> **KEEP CURRENT CAP**. Zie `PROJECT_STATE.md` voor de actuele stagedemo-status.

Datum: 2026-10-05. Geen commit gemaakt. ByteDance is de primaire engine op
verzoek van de projecteigenaar; Basic Pitch blijft als expliciete referentie.

## Onderzoek en kleinste integratie

De bestaande `TranscriptionAdapter` in `backend/app/transcription_jobs.py`
vereist `load(context)` en `transcribe(context, report_progress)`. De context
bevat het persistent jobrecord en uploadpad. De adapter retourneert `_transcript`
met canonical schema plus `transcriptUrl`, `exports`, `noteCount`,
`durationSeconds`. De bestaande runner valideert dit, schrijft transcript.json /
transcription.mid, en publiceert dezelfde jobstatus/artifactlinks.

ByteDance implementeert precies dat contract in `backend/app/bytedance_adapter.py`.
De factory kiest nu op basis van `job.engine`: `bytedance` of `basic-pitch`.
De bestaande expliciete demo-config blijft behouden voor Basic Pitch-tests/demo;
ByteDance-jobs kunnen niet via de demo-adapter slagen. Onbekende runnerconfiguratie
blijft een gecontroleerde MODEL_LOAD_FAILED. API en frontend kiezen standaard
ByteDance. `VITE_TRANSCRIPTION_ENGINE=basic-pitch` kiest de referentie expliciet.
Er is geen automatische enginefallback na een inferentiefout.

Geen wijzigingen in correction-, artifact-, MIDI- of schemastructuur.
Er is geen extra queue, database, workerpipeline of nieuwe abstractielaag.
Modellen worden volgens de bestaande architectuur per job geladen; caching en
CPU-optimalisatie zijn niet meegenomen.

## Welke package en welke eerdere experimenten?

De repo-spike en Git-commit `042c58a` verwijzen naar Kong/Qiu /
`piano_transcription_inference`, gekoppeld aan de ByteDance-trainingrepo.
`git log --all -S piano_transcription_inference`, huidige scripts en tracked
bestanden leverden geen eerder uitgevoerd ByteDance-resultaat op. De aanwezige
ground-truth/benchmark-documentatie is een plan; geen fixture-MIDI's of echte
ground truth gevonden. De eerdere kwaliteitsclaim kon dus niet historisch
gereproduceerd worden. Deze run is nieuw en reproduceerbaar.

Upstream-bronnen:

- Inference: https://github.com/qiuqiangkong/piano_transcription_inference
- Package 0.0.6: https://pypi.org/project/piano-transcription-inference/0.0.6/
- Training: https://github.com/bytedance/piano_transcription
- Checkpoint: https://zenodo.org/records/4034264
- Modelmetadata: https://zenodo.org/api/records/4034264

Package-metadata vermeldt MIT; de inference-repo/wheel bevat geen zelfstandig
LICENSE-bestand. De trainingrepo vermeldt Apache 2.0. Zenodo-recordmetadata
vermeldt CC BY 4.0. Attributie checkpoint: Qiuqiang Kong, *High-resolution Piano
Transcription with Pedals by Regressing Onsets and Offsets Times*, 2020,
DOI 10.5281/zenodo.4034264. Model niet geherdistribueerd of aan Git toegevoegd;
download blijft van de oorspronkelijke bron. Geen trainingscode gevendord.

## Geteste Windows/CPU-runtime

- Officiële CPython 3.11.9 x64, bestaande `.venv` en gitignored interpretermap.
- `piano-transcription-inference==0.0.6`.
- `torch==2.7.1+cpu`, van de officiële PyTorch CPU-wheelindex; CUDA niet nodig.
- `torchlibrosa==0.1.0`, librosa 0.11.0, NumPy 1.26.4.
- Numba 0.59.1 / llvmlite 0.42.0 uit de behouden Windows-basislock.
- Basic Pitch 0.4.0 / TensorFlow 2.15.0 blijven beschikbaar in dezelfde omgeving.
- Extra exacte dependencyversies: `backend/requirements-bytedance-windows.lock.txt`.
- `pip check` geslaagd. psutil 7.2.2 gebruikt voor de geheugenmeting.

Upstream beschrijft oorspronkelijk Python 3.7 / PyTorch 1.4 en noemt Windows
ongetest. De combinatie hierboven is daadwerkelijk op deze Windows-machine
uitgevoerd. Geen monkeypatches van third-party packages, oudere NumPy-aliases,
CUDA, globale `torch.load`-patches of gewijzigde beveiligingsinstellingen nodig.
De moderne weights-only loader accepteert het officiële checkpoint.

Checkpoint: `CRNN_note_F1=0.9677_pedal_F1=0.9186.pth`, 171966578 bytes.
Zenodo MD5: `22b961b77c1878239fec963362097045` (geverifieerd).
SHA-256: `c3fa9730725bf4a762f1c14bc80cd5986eacda01b026f5a4a2525cd607876141`.
Setup gebruikt PowerShell-download om upstream's niet-portabele `wget` te vermijden.
De adapter vereist een aanwezig checkpoint; startscript controleert checksum.

## Output naar canonical JSON

Audio wordt met librosa mono geladen/resampled naar 16000 Hz.
Upstream `est_note_events` bevat `midi_note`, `onset_time`, `offset_time`,
`velocity`; die worden `pitch`, `startTime`, `endTime`, `velocity`.
`noteName` wordt uit pitch afgeleid; `hand` blijft unknown.
ByteDance heeft geen per-event confidence. Voor het bestaande vereiste veld
gebruiken we `reg_onset_output` op het dichtstbijzijnde 100 Hz frame voor die pitch:
een expliciete ongekalibreerde onsetscore, niet vergelijkbaar met Basic Pitch's
amplitude/confidence. Er wordt geen fictieve constante confidence gebruikt.

Upstream padt naar segmenten van 10 s. Events die buiten de echte audioduur
beginnen worden uitgesloten; eindtijden worden begrensd. In deze run waren er
15 raw events en 15 canonical events, waarvan 6 offsets tot de audioduur begrensd.
De resampled duur is 3.4321875 s (oorspronkelijk 3.432131519 s).
`est_pedal_events` bevat 4 pedaalintervallen. Het huidige schema ondersteunt die
niet; originele en corrected MIDI bevatten in deze slice alleen noten.
Dit is een expliciete beperking, geen volledige upstream-MIDI-pariteit.

## Echte browserproef

Audio: `140_Cm_Piano_VKeys_02_268_2.wav`, stereo 24-bit PCM, 44100 Hz.
SHA-256: `66ff0c8706d151f8980a633a3563a8671131f1b05e9199bec650495fba9686d7`.
Dit is exact dezelfde ongewijzigde audio als de Basic Pitch-proef.

ByteDance-job: `7bdb9b2e-b128-4222-8f25-8df87a7f3f8d`.
Started 11:13:44Z; finished 11:14:49Z, 65 s inclusief jobinitialisatie/artifacts.
Serverlog bevestigt lokaal checkpoint, `Using CPU`, daadwerkelijke modelsegmenten.
Tijdens deze browserrun draaiden ook regressietests; jobtijd is geen zuivere
benchmarktijd. De aparte procesmetingen hieronder zijn afzonderlijk vermeld.

1. Upload via bestaande React-interface: HTTP 200; jobcreatie HTTP 202.
2. Echte ByteDance-inferentie: Succeeded, 15 noten, canonical transcript.json geladen.
3. transcription.mid aangemaakt en met mido geparseerd.
4. Eerste noot via Edit: pitch 67 naar 68; start 0.2118072808 naar 0.23 s;
   einde 1.507229805 s en velocity 65 behouden.
5. Save + Save Corrections: corrected-r1.json en corrected-r1.mid gemaakt.
6. Echte browserrefresh: dezelfde job/revisie 1 en pitch 68 / start 0.23 s zichtbaar.
7. Nieuwe HTTP-client controleert revision discovery en persisted artifacts.
8. Alle 15 corrected MIDI-noten matchen JSON: pitch/velocity exact, start/einde
   binnen 1/960 s (1.042 ms). Precies één JSON-noot gewijzigd; originals byte-identiek.

Read-only hercontrole:

```powershell
& .\.venv\Scripts\python.exe backend/scripts/verify_real_pipeline.py --engine bytedance --job-id 7bdb9b2e-b128-4222-8f25-8df87a7f3f8d
```

De algemene verifier is ook end-to-end uitgevoerd op een nieuwe ByteDance-job
69bb3895-7f32-40ec-a6a4-ae38e9aa3cb5: 15 noten, pitchcorrectie 67 naar 68,
revisie 1, alle JSON/MIDI-controles geslaagd. De gedocumenteerde setup is opnieuw
idempotent uitgevoerd: dependencies/checkpoint/pip check geslaagd.

## Tests en grenzen

- Backend: **112 passed, 2 failed**, inclusief 12 nieuwe ByteDance-regressiecases.
- Dezelfde bestaande Windows-fouten: oversized-upload unlink/WinError32 en
  parallelle TestClient-startup bij idempotency (`400 Invalid upload path`).
- Frontend: vier testbestanden geslaagd, inclusief extra Basic Pitch-reference-selectietest; typecheck en production build geslaagd.
- Definitieve gerichte adaptertests na de laatste configuratiecheck: 47 passed. PowerShell/Python-syntaxcontroles en git diff --check geslaagd.
- Adapterrouting, malformed-output-validatie, padding, model/inferencefouten en
  gedeelde artifact/correctierevisieflow zijn getest. Echte inferentie afzonderlijk bewezen.
- Bekende UI-demolabel en onjuiste duurweergave blijven bestaan; na refresh nog 8 s.
- MP3 en lange audio niet getest. CPU-runtime nog niet geoptimaliseerd.

## Besluit over eerdere uncommitted Basic Pitch-wijzigingen

- Behouden: engine-onafhankelijke API/JSON/MIDI-verifier, nu met `--engine`.
- Behouden: Windows-basislock als bewezen gedeelde dependencybasis en Basic Pitch-reference.
- Behouden: start-basic-pitch.ps1 en oorspronkelijk verificatieverslag als reproduceerbare referentie.
- Vervangen: Basic Pitch als primaire README-startprocedure en projectrichting.
- Bijgewerkt: PROJECT_STATE en historische spike gemarkeerd als achterhaald.
- Model, interpreter, venv, uploads, testjobs en WAV-bestanden blijven buiten Git.
- Niets gestaged of gecommit. Geen unrelated bugfixes/editorfeatures uitgevoerd.

Aanbevolen volgende stap: een kleine, gecontroleerde ByteDance-kwaliteitsproef
met bekende MIDI-ground-truth (korte akkoorden/arpeggio inclusief sustain) voordat
we thresholds aanpassen of editorfeatures uitbreiden. Controleer vooral ontbrekende
beginnoten en langere offsets; note-count alleen is geen kwaliteitsmaat.


# Vergelijking op dezelfde piano-opname

Audio: `140_Cm_Piano_VKeys_02_268_2.wav`. Geen ground truth gevonden; geen kwaliteitsrangschikking.

| Meting | Basic Pitch | ByteDance |
| --- | ---: | ---: |
| Noten | 27.000 | 15.000 |
| Laden (s) | 31.684 | 19.298 |
| Decode + inferentie (s) | 6.933 | 36.063 |
| Totaal (s) | 38.617 | 55.361 |
| Piek RSS (MiB) | 497.469 | 816.871 |

Een verse Python-processessie per model; één meting per model. Import/modelinitialisatie inbegrepen in laden; processtart niet inbegrepen. Geheugen bemonsterd elke 50 ms. CPU-defaults en cachetoestand zijn niet gestandaardiseerd.

## basic-pitch: alle canonical noten

| Pitch | Naam | Start (s) | Einde (s) | Velocity |
| ---: | --- | ---: | ---: | ---: |
| 53 | F3 | 0.011610 | 1.451247 | 69 |
| 62 | D4 | 0.011610 | 0.522449 | 71 |
| 67 | G4 | 0.011610 | 0.208980 | 87 |
| 79 | G5 | 0.011610 | 0.476009 | 59 |
| 58 | A#3 | 0.104490 | 0.359909 | 58 |
| 67 | G4 | 0.220590 | 0.998458 | 62 |
| 72 | C5 | 0.417959 | 0.638549 | 76 |
| 62 | D4 | 0.638549 | 0.847528 | 62 |
| 74 | D5 | 0.638549 | 0.917188 | 94 |
| 62 | D4 | 0.847528 | 1.428027 | 80 |
| 79 | G5 | 0.882358 | 1.439637 | 61 |
| 72 | C5 | 1.068118 | 1.451247 | 75 |
| 67 | G4 | 1.277098 | 1.486077 | 56 |
| 55 | G3 | 1.497687 | 2.137520 | 82 |
| 67 | G4 | 1.497687 | 1.718277 | 49 |
| 74 | D5 | 1.497687 | 1.718277 | 64 |
| 59 | B3 | 1.509297 | 1.718277 | 59 |
| 64 | E4 | 1.509297 | 2.485819 | 70 |
| 60 | C4 | 1.718277 | 1.938866 | 88 |
| 67 | G4 | 1.718277 | 2.114300 | 71 |
| 60 | C4 | 1.938866 | 3.403007 | 75 |
| 72 | C5 | 1.938866 | 2.079470 | 56 |
| 55 | G3 | 2.137520 | 3.403007 | 77 |
| 74 | D5 | 2.137520 | 2.276839 | 64 |
| 79 | G5 | 2.346499 | 2.497429 | 71 |
| 84 | C6 | 2.567089 | 3.066318 | 68 |
| 64 | E4 | 2.892168 | 3.391397 | 64 |

## bytedance: alle canonical noten

| Pitch | Naam | Start (s) | Einde (s) | Velocity |
| ---: | --- | ---: | ---: | ---: |
| 67 | G4 | 0.211807 | 1.507230 | 65 |
| 72 | C5 | 0.427599 | 1.060000 | 76 |
| 74 | D5 | 0.640756 | 1.490000 | 97 |
| 62 | D4 | 0.854802 | 1.505447 | 62 |
| 72 | C5 | 1.068635 | 1.502008 | 74 |
| 60 | C4 | 1.494267 | 3.415257 | 82 |
| 74 | D5 | 1.496178 | 2.130000 | 94 |
| 64 | E4 | 1.496776 | 3.432187 | 82 |
| 55 | G3 | 1.497715 | 3.432187 | 80 |
| 59 | B3 | 1.501609 | 3.430000 | 78 |
| 67 | G4 | 1.713380 | 3.432187 | 77 |
| 72 | C5 | 1.927350 | 3.432187 | 69 |
| 74 | D5 | 2.142709 | 3.432187 | 69 |
| 79 | G5 | 2.355188 | 3.432187 | 81 |
| 84 | C6 | 2.567895 | 3.414718 | 87 |
