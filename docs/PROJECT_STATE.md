# Project State

## Doel

Piano Transcriber is een webapp voor korte solo-piano-opnames: upload, validatie, playback, automatische transcriptie, pianorol en falling-keys-weergave.

## Huidige fase

**Fase 2 — echte transcriptie voor de MVP.**

Fase 1 met upload, playback en visualisatie op basis van testdata is afgerond.

Belangrijke checkpoints:

* `fa5bd3d4e6a6e88ee8510b2afb35f15162d2ff60` — complete Fase-1 visualizer MVP
* `b01110f` — async transcription job UI integration
* `ec81dca` — transcription job concurrency hardening
* `fe45026` — Basic Pitch runtime dependency
* `1476c4f` — persistent transcript JSON and MIDI artifacts

Controleer het actuele `HEAD` alleen wanneer dit voor de taak nodig is.

## Reeds geïmplementeerd

* WAV-upload, validatie en browser-playback.
* Pianorol en falling keys gesynchroniseerd met audio.
* Async transcriptiejobs met create-, polling-, cancel- en statusroutes.
* Idempotency voor jobcreatie binnen het lokale single-process prototype.
* Frontendpolling met backoff, foutafhandeling, cancellation en herstel na refresh.
* Demo-runner en `BasicPitchTranscriptionAdapter`.
* `basic-pitch==0.4.0`, TensorFlow 2.15 en het package-eigen SavedModel zijn aanwezig.
* Geslaagde transcriptiejobs publiceren persistente transcript JSON- en MIDI-artifacts via veilige downloadroutes.
* Adapter- en backendtests waren groen bij de laatste relevante checkpoints.
* OpenClaw hostcontrol ondersteunt inspect, exec, logs, update, restart en rollback.

## Huidige live status

De live API draait met echte Basic Pitch-inferentie en persistente artifactdownloads.

Bewezen op 2026-06-14:

* `backend/.deps` is coherent hersteld naar `setuptools==80.10.2`.
* `pkg_resources` is aanwezig vanuit `backend/.deps/pkg_resources`.
* `distutils` laadt via `backend/.deps/setuptools/_distutils`.
* `tensorflow==2.15.0` en `basic_pitch.inference` importeren in de live runtime.
* `/api/health` geeft `200 OK`.
* `backend/data/samples/demo.wav` job `7b57bce8-c142-4e35-8644-96e69d67f00e` eindigde als `succeeded`, `engine=basic-pitch`, `noteCount=8`.
* tijdelijke 2s stilte-WAV job `47e851b4-1873-4043-a2a0-8fd44ffccd25` eindigde als `succeeded`, `engine=basic-pitch`, `noteCount=0`.
* Demo-artifacts: `transcript.json` gaf `200 application/json` en parsebare JSON, `transcription.mid` gaf `200 audio/midi` met MIDI-header `MThd`.
* Stilte-artifacts: `transcript.json` gaf `200 application/json` en parsebare JSON, `transcription.mid` gaf `200 audio/midi` met MIDI-header `MThd`.
* Ontbrekende artifacts en path traversal via de artifactdownloadroute geven `404`.
* containerlogs tonen echte Basic Pitch-inferentie met `Predicting MIDI for ...wav...`.

De dependencycontext vereist nog steeds dat `backend/.deps` via `site.addsitedir(...)` wordt geladen, zodat de setuptools `distutils`-shim actief wordt.

## Huidig doel

Echte Basic Pitch-inferentie en persistent artifact export zijn live geactiveerd en gevalideerd in de bestaande Piano Transcriber-container.

Persistent artifact export is live bewezen:

* geslaagde jobs schrijven `transcript.json` en `transcription.mid`;
* `result.exports` bevat alleen servergegenereerde links voor bestaande artifacts;
* downloadroutes beperken bestandsnamen, blokkeren path traversal en geven `404` bij ontbrekende artifacts;
* frontend toont JSON- en MIDI-links alleen wanneer aanwezig.

Actieve live configuratie:

* `SETUPTOOLS_USE_DISTUTILS=local`
* `PIANO_TRANSCRIBER_RUNNER_MODE=basic-pitch`
* `PIANO_TRANSCRIBER_BASIC_PITCH_MODEL_PATH=/host/projects/piano-transcriber/backend/.deps/basic_pitch/saved_models/icassp_2022/nmp`
* `PYTHONPATH=/host/projects/piano-transcriber/backend`
* laad `/host/projects/piano-transcriber/backend/.deps` met `site.addsitedir(...)`

## Belangrijke beperkingen

* Verwijder de dependencyrollbackmap niet:
  `backend/.deps.rollback-20260613-184451`
* Verwijder de setuptools-pre-fix rollbackmap niet:
  `backend/.deps.rollback-20260614-setuptools-pre`
* Verwijder geen hostcontrol-rollbacksnapshot.
* Wijzig tijdens Piano Transcriber-werk niet de OpenClaw-gatewaycontainer.
* Herhaal het modelselectieonderzoek niet.
* Basic Pitch blijft de gekozen prototype-engine.
* Kong/Qiu/ByteDance blijft fallback.
* Borg bij toekomstige dependency-regeneratie expliciet `setuptools<81`, omdat Basic Pitch/resampy via `pkg_resources` loopt.
* Geen professionele bladmuziek, handdetectie of correctie-editor in deze taak.
* Multi-process en distributed-worker-garanties vallen nog buiten de huidige scope.

## Open vervolgwerk

Na bewezen live Basic Pitch-inferentie:

* benchmark uitvoeren met MIDI-ground-truth;
* exacte licenties en hashes van package, model en weights vastleggen;
* queue-timeout, heartbeat en stale-worker-detectie;
* MP3-ondersteuning;
* correctie-editor in een latere fase.

## Context- en tokenregel

Gebruik dit bestand als canonieke actuele projectstatus.

* Lees het eenmaal bij de start van een projecttaak.
* Reconstrueer afgerond werk niet opnieuw uit brede repositoryscans, oude chats of volledige Git-historiek.
* Lees alleen bestanden die noodzakelijk zijn voor de actuele taak.
* Voeg geen volledige logs of cumulatieve testgeschiedenis toe.
* Werk dit bestand eenmaal compact bij na een betekenisvolle afgeronde taak.
