# Project State

## Doel

Piano Transcriber is een webapp voor korte solo-piano-opnames: upload, validatie, playback, automatische transcriptie, pianorol en falling-keys-weergave.

## Huidige fase

**Fase 2 — echte transcriptie en correctie voor de MVP.**

Fase 1 met upload, playback en visualisatie op basis van testdata is afgerond.

Belangrijke checkpoints:

* `fa5bd3d4e6a6e88ee8510b2afb35f15162d2ff60` — complete Fase-1 visualizer MVP
* `b01110f` — async transcription job UI integration
* `ec81dca` — transcription job concurrency hardening
* `fe45026` — Basic Pitch runtime dependency
* `1476c4f` — persistent transcript JSON and MIDI artifacts
* `8e9a359` — atomic correction artifact publication met immutable `corrected-r<N>.json`/`corrected-r<N>.mid` en failure-injectiontests

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
* **Correction API**: immutable `corrected-r<N>.json`/`corrected-r<N>.mid` artifacts worden volledig geschreven en gecontroleerd vóór publicatie via één metadata-`save_job`; failure-injectiontests en 100 backendtests + 20 correction-tests groen.

## Huidige live status

De live API draait met echte Basic Pitch-inferentie, persistente artifactdownloads en **correction API**.

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
* **Correction API**: immutable `corrected-r<N>.json`/`corrected-r<N>.mid` artifacts worden volledig geschreven en gecontroleerd vóór publicatie via één metadata-`save_job`; failure-injectiontests en 100 backendtests + 20 correction-tests groen.

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
* **Correction API**: alleen filesystem-backed storage getest; geen deployment- of service-runtimechecks.

## Correction API — Geïmplementeerd (2026-06-14)

### Backendcontract
- **Requestvalidatie:**
  - `noteName` is **verboden** (automatisch gegenereerd uit `pitch`).
  - Onbekende velden in `notes` worden **geweigerd** (422 `INVALID_CORRECTION`).
  - Verplichte velden: `baseRevision`, `pitch`, `startTime`, `endTime`, `velocity`, `confidence`, `hand`.
  - `baseRevision` is verplicht, integer, en `>= 0`.
  - `pitch` is integer `21..108`.
  - `velocity` is integer `1..127`.
  - `confidence` is eindig en `0..1`.
  - `hand` is exact `"unknown"`.
  - Lege `notes`-array is toegestaan.
  - Tijdsgrenzen: `endTime > startTime` **en** `endTime <= durationSeconds`.

- **Responses:**
  - Succes (200):
    ```json
    {
      "revision": 1,
      "exports": {
        "transcript": "/api/transcriptions/{jobId}/artifacts/corrected-r1.json",
        "midi": "/api/transcriptions/{jobId}/artifacts/corrected-r1.mid"
      }
    }
    ```
  - Fouten: `CORRECTION_REVISION_CONFLICT` (409), `INVALID_CORRECTION` (422), `JOB_NOT_FOUND` (404), `JOB_NOT_SUCCEEDED` (409).

- **Artifacts:** Immutable `corrected-r<N>.json`/`corrected-r<N>.mid` worden atomisch gepubliceerd.

### Frontendimplementatie
- **API-client:** `putCorrection(jobId: string, body: CorrectionRequest): Promise<CorrectionResponse>` toegevoegd, nu met:
  - Route: `PUT /api/transcriptions/{jobId}/corrections` (meervoud).
  - Request: `baseRevision` + `notes` met `startTime`, `endTime`, `velocity`, `confidence`, `hand` (alles verplicht); `confidence` tussen `0` en `1`; `hand` exact `"unknown"`.
  - Response: `revision` + `exports.transcript`/`exports.midi`.
- **Artifactlinks:** `transcriptionArtifactLinks` uitgebreid met ondersteuning voor `corrected-r<N>.json`/`corrected-r<N>.mid` wanneer `result.correction` aanwezig is.
- **Types:** `CorrectionRequest`, `CorrectionResponse`, `CorrectionArtifactLink` gecorrigeerd naar het definitieve contract.
- **Tests:**
  - Succesvolle correctie (200, valide response).
  - Alle vier backendfoutcodes (404, 409, 422 `INVALID_CORRECTION`, 409 voor JOB_NOT_SUCCEEDED).
  - URL, PUT-methode, `Content-Type: application/json`.
  - Artifactlinks alleen wanneer `correction` aanwezig is.

### Commit 2 — Revision-aware editor/draft/save-flow en canonical corrected-transcript reload

#### Herstelronde (2026-06-14)
- **Status:** HERZIEN NODIG
- **Reviewer:** FAIL (4e2806c)
- **Opmerkingen:**
  - Validatie, orchestration-helper, en backendgrenzen zijn hersteld.
  - Wacht op onafhankelijke review van de herstelwijzigingen.
- **Belangrijk:**
  - Commit 2 is **niet** voltooid.
  - Commit 3 is **niet** gestart.
  - Geen onbewezen PASS/VOLTOOID-claims.

#### Wijzigingen in herstelronde
- `confidence` en `hand` zijn nu verplicht in `CorrectionRequest`.
- `hand` is een literal type `"unknown"`.
- `VELOCITY_MIN` is gecorrigeerd van `0` naar `1`.
- Validatie voor `pitch` (21–108), `velocity` (1–127), `confidence` (0–1), en `hand` (exact `"unknown"`).
- `buildCorrectionPayload` gebruikt nu de gecorrigeerde backendgrenzen.
- `orchestrateSaveAndReload` is toegevoegd voor de kritieke save-flow.
- `loadCanonicalTranscript` gebruikt nu de nieuwe transcript-URL.
- Tests zijn uitgebreid met validatie, orchestration, en backendgrenzen.
- `styles.css` is hersteld naar HEAD.
- `package.json` bevat de bedoelde correction-flow-test; `package-lock.json` is hersteld naar HEAD.

## Bewust uitgesteld na Commit 2

- Dit is een persoonlijke tool en stagedemo, geen productie-service voor externe gebruikers.
- Commit 2 is functioneel compleet zodra de normale correctieflow, tests en build slagen.
- Zeldzame concurrency-hardening is geen releaseblocker voor deze scope.
- Bekend uitgesteld issue: een late `cancelJob`-response kan een oudere job opnieuw installeren wanneer cancellation en het starten van een nieuwe sessie overlappen.
- Bekend uitgesteld issue: een stale canonical fetch kan nog een misleidende `console.error` emitten, hoewel stale React state writes zijn afgeschermd.
- De UI-pitchrange `21..108` is bewust en volgt het volledige piano/backend-contract; de eerdere `48..84`-weergaverange komt niet terug.
- Start niet direct een nieuwe demo of upload terwijl een cancellation nog afloopt.
- Deze punten kunnen later worden herzien, maar openen Commit 2 niet automatisch opnieuw.

### Huidige Status
- **Commit 2:** FUNCTIONEEL KLAAR — De normale correctieflow, tests en build slagen. Bekende zeldzame concurrency-randgevallen zijn bewust uitgesteld voor deze persoonlijke tool en stagedemo.
- **Volgende stap:** Laatste mechanische controles uitvoeren en Commit 2 afronden. Commit 3 is nog niet gestart.
- **Notitie:** Tijdens deze ronde zijn **geen** backendwijzigingen uitgevoerd; alleen frontend-uitbreiding en tests.

### Open vervolgwerk
Na bewezen live Basic Pitch-inferentie:
- benchmark uitvoeren met MIDI-ground-truth;
- exacte licenties en hashes van package, model en weights vastleggen;
- queue-timeout, heartbeat en stale-worker-detectie;
- MP3-ondersteuning;
- correctie-editor in een latere fase.

## Context- en tokenregel
Gebruik dit bestand als canonieke actuele projectstatus.

* Lees het eenmaal bij de start van een projecttaak.
* Reconstrueer afgerond werk niet opnieuw uit brede repositoryscans, oude chats of volledige Git-historiek.
* Lees alleen bestanden die noodzakelijk zijn voor de actuele taak.
* Voeg geen volledige logs of cumulatieve testgeschiedenis toe.
* Werk dit bestand eenmaal compact bij na een betekenisvolle afgeronde taak.
