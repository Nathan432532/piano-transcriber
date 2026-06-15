# Piano Audio Transcriber

Persoonlijke lokale tool en stagedemo voor korte piano-audio. De app laat lokaal een WAV/MP3 uploaden of een synthetische demo laden, speelt de audio in de browser af, visualiseert noten als piano-roll en falling keys, en ondersteunt een asynchrone transcriptiejob met correcties en exports wanneer de runner echte transcript-artifacts produceert.

Dit is geen productieproduct voor externe gebruikers: opslag is lokaal op schijf, er is geen authenticatie, geen database, geen externe queue en geen automatische cleanup.

## Architectuur

- `backend/`: FastAPI API. Uploads, jobs, idempotencyrecords en artifacts worden als bestanden bewaard onder `backend/data` of onder `PIANO_TRANSCRIBER_DATA_DIR`.
- `frontend/`: React + TypeScript + Vite single-page app.
- `shared/transcript.schema.json`: gedeeld transcriptcontract voor `version`, `source` en `notes`.
- `backend/data/samples/demo.wav` en `backend/data/samples/demo.transcript.json`: lokale synthetische demo-assets.
- Lokale services tijdens gebruik: FastAPI op `127.0.0.1:8000` en Vite op `127.0.0.1:5173`.

De backend valideert uploads voordat ze worden opgeslagen. Alleen echte `.wav` en `.mp3` bestanden worden geaccepteerd, met extensiecheck, header sniffing, maximale grootte, maximale duur en gesanitiseerde bestandsnamen. Browserplayback hangt af van de codecs die de browser ondersteunt.

## Installatie

Vanaf deze repository:

```bash
cd /apps/projects/piano-transcriber

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt

cd /apps/projects/piano-transcriber/frontend
npm ci
```

## Lokaal starten

Terminal 1, backend:

```bash
cd /apps/projects/piano-transcriber
. .venv/bin/activate
PYTHONPATH=backend python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2, frontend:

```bash
cd /apps/projects/piano-transcriber/frontend
npm run dev
```

Open daarna `http://127.0.0.1:5173`.

Als `backend/data/samples/demo.wav` ontbreekt, kan de demo opnieuw worden gegenereerd met:

```bash
cd /apps/projects/piano-transcriber
. .venv/bin/activate
python backend/scripts/generate_demo_wav.py
```

## Gebruik

De eerste pagina start leeg. Kies `Load demo` om `/api/transcripts/demo` en `/api/samples/demo` te laden, of upload een korte WAV/MP3 via de uploadknop.

Bij upload doet de frontend:

1. `POST /api/uploads` met het audiobestand.
2. Toont direct de geuploade audio en een demo-vormig transcript uit de uploadresponse.
3. Start een transcriptiejob met `POST /api/transcriptions`, engine `basic-pitch`, opties `{ "minPitch": 21, "maxPitch": 108 }` en een `Idempotency-Key`.
4. Pollt `GET /api/transcriptions/{jobId}` totdat de job `succeeded`, `failed` of `cancelled` is.

De jobstatus toont `queued`, `running`, `succeeded`, `failed` of `cancelled`, inclusief fase, percentage en bericht. Actieve polling gebeurt ongeveer elke seconde; als de status lang niet verandert schakelt de poller naar een tragere interval. Tijdelijke netwerkfouten krijgen backoff-retries. `JOB_NOT_FOUND` en `JOB_EXPIRED` stoppen de poller als terminale fouten.

Een lopende job kan worden geannuleerd met `DELETE /api/transcriptions/{jobId}`. De backend markeert de job dan als `cancelled`; blokkende inferentie kan alleen op runner-checkpoints worden onderbroken.

## Transcriptie en runners

De API accepteert bij jobcreatie alleen engine `basic-pitch`. Welke runner daadwerkelijk draait wordt bepaald door `PIANO_TRANSCRIBER_RUNNER_MODE`.

- Default `demo`: de job loopt door de demo-runner. Die levert jobmetadata zoals `noteCount` en `durationSeconds`, maar geen `transcript.json` of MIDI-export.
- `basic-pitch`: laadt Basic Pitch en probeert echte note events uit de audio te maken. Bij succes schrijft de backend `transcript.json` en `transcription.mid` als job-artifacts.

De frontend gebruikt de demo-transcriptdata voor directe visualisatie na upload. Als een geslaagde job een `transcriptUrl` teruggeeft, laadt de frontend dat canonical transcript opnieuw en gebruikt die data voor weergave en correcties.

## Weergave en playback

De UI bevat:

- native browser-audiocontrols plus knoppen voor play, pause en restart;
- afspeelsnelheden `0.50x`, `0.75x` en `1.0x`;
- een tijdsreadout op basis van `audio.currentTime`;
- een canvas piano-roll met playhead;
- een canvas falling-keys weergave met toetsenbord;
- een notentabel met pitch, start, end, velocity en confidence.

Beide visualisaties zijn gesynchroniseerd met de audio via `requestAnimationFrame` en `audio.currentTime`.

## Noten en correcties

Het transcriptformaat gebruikt per noot:

```json
{
  "pitch": 60,
  "noteName": "C4",
  "startTime": 0.25,
  "endTime": 0.85,
  "velocity": 82,
  "confidence": 0.99,
  "hand": "unknown"
}
```

De gedeelde schemafile en correctieflow gebruiken het volledige pianobereik MIDI `21..108`. Correcties valideren:

- `pitch`: integer `21..108`;
- `startTime` en `endTime`: eindtijd groter dan starttijd, niet negatief en niet voorbij de transcriptduur;
- `velocity`: integer `1..127`;
- `confidence`: getal `0..1`;
- `hand`: alleen `"unknown"`.

In de UI selecteer je een noot via `Edit` in de notentabel. Pitch, timing, velocity en confidence zijn aanpasbaar. Wijzigingen blijven eerst als draft-notes in de frontend staan; `Save Corrections` verstuurt daarna `PUT /api/transcriptions/{jobId}/corrections`.

## Revision-aware opslaan en persistence

Correcties zijn revision-aware. De frontend stuurt `baseRevision`; de backend weigert verouderde saves met `CORRECTION_REVISION_CONFLICT` (`409`) wanneer de opgeslagen revision inmiddels hoger is.

Bij succesvolle correctie:

- blijft het originele `transcript.json` en `transcription.mid` immutable bestaan;
- schrijft de backend nieuwe artifacts zoals `corrected-r1.json` en `corrected-r1.mid`;
- bewaart de backend de actuele correction revision en exportlinks in het jobrecord;
- laadt de frontend de gecorrigeerde transcript-URL opnieuw als canonical transcript;
- kiest de frontend voortaan de gecorrigeerde transcript-URL boven de originele via de jobresult-correction.

Jobs en artifacts blijven lokaal op schijf onder de data-map staan. `expiresAt` wordt door de API gecontroleerd bij laden; er is geen automatische opruimtaak.

## Exports

Beschikbare downloadlinks worden alleen getoond wanneer de jobresult ze bevat.

- Origineel transcript: `/api/transcriptions/{jobId}/artifacts/transcript.json`.
- Originele MIDI-export: `/api/transcriptions/{jobId}/artifacts/transcription.mid`.
- Gecorrigeerd transcript: `/api/transcriptions/{jobId}/artifacts/corrected-r{revision}.json`.
- Gecorrigeerde MIDI-export: `/api/transcriptions/{jobId}/artifacts/corrected-r{revision}.mid`.

De MIDI-writer is lokaal geïmplementeerd en schrijft een enkel trackbestand met 480 ticks per seconde. In default demo-runner mode zijn er geen job-artifact exports; de losse demo-transcript en demo-audio blijven wel beschikbaar.

## API-overzicht

- `GET /api/health`: `{ "status": "ok" }`.
- `GET /api/transcripts/demo`: synthetisch transcript.
- `GET /api/samples/demo`: `demo.wav`.
- `POST /api/uploads`: valideert en bewaart WAV/MP3, retourneert `uploadId`, `audioUrl` en een direct bruikbaar transcript.
- `GET /api/uploads/{uploadId}`: serveert opgeslagen upload.
- `POST /api/transcriptions`: maakt idempotente job; vereist header `Idempotency-Key`.
- `GET /api/transcriptions/{jobId}`: jobstatus/resultaat.
- `GET /api/transcriptions/{jobId}/artifacts/{artifact}`: downloadt toegestane JSON/MIDI artifacts.
- `PUT /api/transcriptions/{jobId}/corrections`: slaat revision-aware correcties op.
- `DELETE /api/transcriptions/{jobId}`: annuleert een niet-terminale job.

Foutresponses van de transcriptieroutes gebruiken `detail.code`, `detail.message`, `detail.retryable` en optioneel `detail.details`. Relevante codes zijn onder andere `UPLOAD_NOT_FOUND`, `UNSUPPORTED_ENGINE`, `INVALID_OPTIONS`, `MODEL_LOAD_FAILED`, `MODEL_INFERENCE_FAILED`, `JOB_NOT_FOUND`, `JOB_EXPIRED`, `JOB_TERMINAL`, `JOB_NOT_SUCCEEDED`, `CORRECTION_REVISION_CONFLICT`, `INVALID_CORRECTION`, `IDEMPOTENCY_CONFLICT`, `CANCELLED` en `UNKNOWN_ERROR`.

## Configuratie

Backend environment variables:

- `PIANO_TRANSCRIBER_DATA_DIR`: root voor lokale data, default `backend/data`.
- `PIANO_TRANSCRIBER_MAX_UPLOAD_BYTES`: default `20971520`.
- `PIANO_TRANSCRIBER_MAX_AUDIO_SECONDS`: default `120`.
- `PIANO_TRANSCRIBER_AUTO_RUN_TRANSCRIPTIONS`: default `1`; zet op `0` om jobs niet automatisch via FastAPI background tasks te starten.
- `PIANO_TRANSCRIBER_RUNNER_MODE`: default `demo`; ondersteund: `demo`, `basic-pitch`.
- `PIANO_TRANSCRIBER_BASIC_PITCH_MODEL_PATH`: optioneel pad naar Basic Pitch modelbestand of SavedModel-map.
- `PIANO_TRANSCRIBER_JOB_TTL_DAYS`: default `7`.
- `PIANO_TRANSCRIBER_IDEMPOTENCY_TTL_SECONDS`: default `86400`.

Frontend environment variables:

- `VITE_API_BASE_URL`: API-base, default `http://localhost:8000`.

FastAPI CORS staat alleen de lokale Vite-origins `http://localhost:5173` en `http://127.0.0.1:5173` toe.

## Tests en checks

Backend tests:

```bash
cd /apps/projects/piano-transcriber
. .venv/bin/activate
PYTHONPATH=backend python -m pytest
```

Frontend tests:

```bash
cd /apps/projects/piano-transcriber/frontend
npm run test
```

Frontend lint, typecheck en build:

```bash
cd /apps/projects/piano-transcriber/frontend
npm run lint
npm run typecheck
npm run build
```

Er is op dit moment geen backend lint- of typecheck-script in de repository geconfigureerd.

## Praktische beperkingen

- Default runner mode `demo` produceert geen echte transcript-artifacts of MIDI-export voor jobs.
- Echte Basic Pitch-inferentie vereist dat het Pythonpakket en een bruikbaar model beschikbaar zijn; laad- en inferentiefouten worden als jobfout vastgelegd.
- Uploadlimieten zijn 20 MiB en 120 seconden tenzij environment variables ze aanpassen.
- MP3-duur wordt gelezen met `mutagen`; er wordt geen `ffmpeg` aangeroepen.
- Er is geen login, autorisatie, virus scanning, deduplicatie, retentiejob of database.
- Lokale `backend/data` kan bestaande uploads, jobs en artifacts bevatten uit eerdere runs.
