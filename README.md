# Piano Audio Transcriber

Persoonlijke lokale tool voor korte piano-audio. De app laat lokaal een WAV/MP3 uploaden of een synthetische demo laden, speelt de audio in de browser af, visualiseert noten als piano-roll en falling keys, en ondersteunt een asynchrone transcriptiejob met correcties en exports wanneer de runner echte transcript-artifacts produceert.

Dit is geen productieproduct voor externe gebruikers: opslag is lokaal op schijf, er is geen authenticatie, geen database, geen externe queue en geen automatische cleanup.

## Architectuur

- `backend/`: FastAPI API. Uploads, jobs, idempotencyrecords en artifacts worden als bestanden bewaard onder `backend/data` of onder `PIANO_TRANSCRIBER_DATA_DIR`.
- `frontend/`: React + TypeScript + Vite single-page app.
- `shared/transcript.schema.json`: gedeeld transcriptcontract voor `version`, `source` en `notes`.
- `backend/data/samples/demo.wav` en `backend/data/samples/demo.transcript.json`: lokale synthetische demo-assets.
- Lokale services tijdens gebruik: FastAPI op `127.0.0.1:8000` en Vite op `127.0.0.1:5173`.

De backend valideert uploads voordat ze worden opgeslagen. Alleen echte `.wav` en `.mp3` bestanden worden geaccepteerd, met extensiecheck, header sniffing, maximale grootte, maximale duur en gesanitiseerde bestandsnamen. Browserplayback hangt af van de codecs die de browser ondersteunt.

## Installatie

### Windows: ByteDance als primaire engine

Vervang `<repo>` in de voorbeelden door jouw checkoutpad. Models, runtime en
datasetdata blijven lokaal; persoonlijke gebruikerspaden horen niet in de code.

ByteDance Piano Transcription is nu de primaire engine, via
`piano-transcription-inference==0.0.6`. Basic Pitch blijft een expliciete referentie.
Beide adapters gebruiken dezelfde jobs, canonical transcript JSON, correcties en
MIDI-export. Er is geen tweede pipeline en geen automatische fallback na een fout.

De stagedemo gebruikt **ByteDance + menselijke correctie + bekende offsetbeperking**.
Op de bevroren MAPS ENSTDkCl-subset (24 cases, 585 officiële MIDI-noten) behaalde
ByteDance F1 85,5% en recall 92,5%, tegenover Basic Pitch 65,3% en 58,5%.
Onset-MAE was 13,1 tegenover 14,2 ms; key-release-MAE 301,8 tegenover 219,8 ms
op de verschillende gematchte nootsets. Dit ondersteunt de enginekeuze voor
deze subset, geen algemene accuracyclaim voor alle piano-audio.
De warme CPU-benchmark nam circa 317,4 s voor ByteDance en 5,7 s voor Basic Pitch;
dit zijn geen cold API-joblatenties. Note ends blijven handmatige controle vereisen.
De upstream 600-framecap (ongeveer zes seconden) blijft behouden: verhogen of
verwijderen verhelpt de segmentproblemen niet en veroorzaakt regressies.
Offset Policy B en C zijn **DO NOT SHIP** als algemene fixes en staan buiten productie.
Zie [MAPS-validatie](backend/benchmarks/maps/maps-enstdkcl-validation.md) en
[capdiagnose](backend/benchmarks/maps/maps-long-note-cap-diagnosis.md).

De bestaande Python 3.11.9 `.venv` is geschikt. Voor een nieuwe omgeving: maak eerst
de officiële Python 3.11-omgeving zoals hieronder beschreven; daarna:

```powershell
Set-Location '<repo>'
& .\scripts\setup-bytedance.ps1
```

Dit installeert CPU PyTorch 2.7.1, de vastgezette extra dependencies uit
`backend/requirements-bytedance-windows.lock.txt`, en downloadt het officiële
Zenodo-checkpoint (171966578 bytes). De checksum wordt gecontroleerd. De bestaande
Windows-lock blijft als gedeelde basis/reference-runtime behouden. Er is geen
CUDA of GPU nodig. De upstream-package doet zelf een `wget`-download; onze setup
downloadt vooraf met PowerShell en de adapter vereist een lokaal checkpoint.

Terminal 1:

```powershell
Set-Location '<repo>'
& .\scripts\start-bytedance.ps1
```

Terminal 2:

```powershell
Set-Location '<repo>\frontend'
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8000'
$env:VITE_TRANSCRIPTION_ENGINE = 'bytedance'
npm.cmd run dev -- --strictPort
```

Open `http://127.0.0.1:5173`. Modelinitialisatie gebeurt bij elke nieuwe job volgens
de bestaande runnerarchitectuur; de eerste uitvoering kan trager zijn. Setup en
modeldownload zijn eenmalig; de huidige machine is al ingericht.

Volledige API-controle (maakt een nieuwe job en correctie):

```powershell
Set-Location '<repo>'
& .\.venv\Scripts\python.exe backend/scripts/verify_real_pipeline.py --engine bytedance --audio '.\140_Cm_Piano_VKeys_02_268_2.wav'
```

Browsercontrole: upload dezelfde opname, wacht op `Succeeded`, open `Edit`, wijzig
één noot, klik `Save` en `Save Corrections`, refresh en controleer revisie/noot.
De API-verifier kan daarna met `--engine bytedance --job-id '<uuid>'` de opgeslagen
JSON/MIDI read-only vergelijken. Gebruik geen `Load demo` als inferentiebewijs.

ByteDance geeft note- en pedaalevents. Deze eerste integratie exporteert alleen
noten omdat het bestaande schema/editor geen pedaal ondersteunt. `confidence`
is het onsetmodelscore op het dichtstbijzijnde 100 Hz frame, geen gekalibreerde
nootzekerheid en niet rechtstreeks vergelijkbaar met Basic Pitch-confidence.
Events uit upstream-padding buiten de audioduur worden weggelaten; eindtijden
worden begrensd op de werkelijke resampled audioduur. WAV is bewezen; MP3 nog niet.

Zie `docs/local-bytedance-verification.md` voor onderzoek, licentie/modelidentiteit,
de browserproef, modelvergelijking en bestaande testproblemen.

### Windows: Basic Pitch als referentie (geverifieerd op 2026-10-05)

Gebruik **64-bit CPython 3.11**. De geteste omgeving gebruikt Python 3.11.9,
Basic Pitch 0.4.0, TensorFlow 2.15.0, NumPy 1.26.4, Numba 0.59.1 en
llvmlite 0.42.0. Python 3.12/3.14 past niet bij de TensorFlow-versie die Basic
Pitch 0.4.0 hier vereist. De bestaande adapter gebruikt het package-eigen
TensorFlow SavedModel; ONNX/CoreML/TFLite zijn voor deze procedure niet nodig.

De exact geïnstalleerde Windows-dependencies staan in
`backend/requirements-windows.lock.txt`. Gebruik die lock voor deze runtime,
zodat latere dependencyupdates de bewezen combinatie niet stilzwijgend wijzigen.
Het bestaande algemene `backend/requirements.txt` blijft beschikbaar.

Op deze machine staat de officiële Python 3.11.9-interpreter al onder
`backend/.deps/python311/python.exe`, en is `.venv` eraan gekoppeld. Beide mappen
zijn gitignored. Bewaar de interpretermap: de virtualenv gebruikt deze als basis.
Er is geen systeem-Python of PATH-wijziging nodig om de app te starten.

Voor een nieuwe installatie kun je een officiële 64-bit Python 3.11 gebruiken,
of de officiële Python NuGet-distributie installatievrij uitpakken:

```powershell
Set-Location '<repo>'
New-Item -ItemType Directory -Force backend/.deps | Out-Null
Invoke-WebRequest 'https://www.nuget.org/api/v2/package/python/3.11.9' -OutFile backend/.deps/python311.zip
Expand-Archive backend/.deps/python311.zip -DestinationPath backend/.deps/python311-package
Copy-Item backend/.deps/python311-package/tools -Destination backend/.deps/python311 -Recurse
& .\backend\.deps\python311\python.exe -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r backend/requirements-windows.lock.txt
& .\.venv\Scripts\python.exe -m pip check
Set-Location frontend
npm.cmd ci
```

Voer de bootstrap alleen uit als deze runtime nog ontbreekt. Een virtualenv
hoeft niet geactiveerd te worden: de onderstaande commando's gebruiken steeds
haar eigen interpreter. Bij Windows Application Control-fouten: wijzig geen
beveiligingsinstellingen; controleer dat de officiële interpreter en de geteste
dependency-lock gebruikt worden. De nieuwere automatisch gekozen Numba 0.68.0
werd op deze machine geblokkeerd; de vastgezette 0.59.1 werkte.

**Starten, terminal 1 (backend):**

```powershell
Set-Location '<repo>'
& .\scripts\start-basic-pitch.ps1
```

Het script kiest expliciet `PIANO_TRANSCRIBER_RUNNER_MODE=basic-pitch`, zet
`PIANO_TRANSCRIBER_AUTO_RUN_TRANSCRIPTIONS=1`, selecteert het SavedModel onder
`.venv/Lib/site-packages/basic_pitch/saved_models/icassp_2022/nmp`, en bewaart
uploads/jobs/artifacts onder `backend/data`. Het start één Uvicorn-proces op
`127.0.0.1:8000` zonder autoreload, met de asyncio/h11-runtime.

**Starten, terminal 2 (frontend):**

```powershell
Set-Location '<repo>\frontend'
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8000'
$env:VITE_TRANSCRIPTION_ENGINE = 'basic-pitch'
npm.cmd run dev -- --strictPort
```

Open `http://127.0.0.1:5173`. Stop beide services met Ctrl+C in hun terminal.
De eerste inferentie kan door modelinitialisatie en audiodecoder/JIT-initialisatie
langer duren; deze uitvoering blijft lokaal op CPU. WAV-decoding loopt via
librosa/SoundFile; de proef omvatte ook een stereo 24-bit PCM-WAV op 44.1 kHz.
MP3-decoding is met deze procedure nog niet apart bewezen.

**Herhaalbare controle via API:**

```powershell
Set-Location '<repo>'
& .\.venv\Scripts\python.exe backend/scripts/verify_real_pipeline.py --engine basic-pitch
# Voor eigen pianoaudio:
& .\.venv\Scripts\python.exe backend/scripts/verify_real_pipeline.py --engine basic-pitch --audio '.\140_Cm_Piano_VKeys_02_268_2.wav'
```

Dit script uploadt, start een nieuwe job, vereist echte JSON/MIDI-artifacts,
wijzigt één pitch, slaat revisie 1 op en haalt die met een nieuwe API-client op.
Het parseert de MIDI met mido en vergelijkt alle noten met de corrected JSON:
pitch/velocity exact, start/einde binnen één MIDI-tick (circa 1.042 ms). Ook
controleert het dat originele artifacts intact blijven. Het creëert persistente
testjobs en accepteert geen demo-runner-resultaat. Default audio is de bestaande
synthetische `demo.wav`; dit bewijst de technische keten, geen pianokwaliteit.

**Browsercontrole:** upload audio via de uploadknop, wacht op `Succeeded` en
werkelijke artifactlinks, open `Edit`, wijzig één noot, klik `Save` en daarna
`Save Corrections`. Controleer de corrected links en `Revision: 1`. Refresh de
pagina en controleer de gewijzigde noot opnieuw. Gebruik steeds dezelfde browser
en frontend-origin: jobherstel gebruikt localStorage. Kies niet `Load demo` als
bewijs van automatische transcriptie.

Een reeds via de browser gecorrigeerde job kan zonder nieuwe schrijfacties
inhoudelijk gecontroleerd worden:

```powershell
& .\.venv\Scripts\python.exe backend/scripts/verify_real_pipeline.py --engine basic-pitch --job-id '<job-uuid>'
```

Zie `docs/local-basic-pitch-verification.md` voor de daadwerkelijk uitgevoerde
proef, modelidentiteit, resultaten en afzonderlijke bestaande testproblemen.

### Linux/macOS: algemene installatie

Deze historische algemene requirements installeren de Basic Pitch-referentie,
niet de geteste ByteDance/PyTorch Windows-runtime. De primaire stagedemo gebruikt
de Windows-procedure hierboven. Deze algemene route is geen ByteDance-startbewijs.

Vanaf deze repository:

```bash
cd /piano-transcriber

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt

cd /piano-transcriber/frontend
npm ci
```

## Lokaal starten

Terminal 1, backend:

```bash
cd /piano-transcriber
. .venv/bin/activate
PIANO_TRANSCRIBER_RUNNER_MODE=basic-pitch PYTHONPATH=backend python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2, frontend:

```bash
cd /piano-transcriber/frontend
VITE_TRANSCRIPTION_ENGINE=basic-pitch npm run dev
```

Open daarna `http://127.0.0.1:5173`.

Als `backend/data/samples/demo.wav` ontbreekt, kan de demo opnieuw worden gegenereerd met:

```bash
cd /piano-transcriber
. .venv/bin/activate
python backend/scripts/generate_demo_wav.py
```

## Gebruik

De eerste pagina start leeg. Kies `Load demo` om `/api/transcripts/demo` en `/api/samples/demo` te laden, of upload een korte WAV/MP3 via de uploadknop.

Bij upload doet de frontend:

1. `POST /api/uploads` met het audiobestand.
2. Toont direct de geuploade audio en een demo-vormig transcript uit de uploadresponse.
3. Start een transcriptiejob met `POST /api/transcriptions`, engine `bytedance` (of expliciete Basic Pitch-referentie), opties `{ "minPitch": 21, "maxPitch": 108 }` en een `Idempotency-Key`.
4. Pollt `GET /api/transcriptions/{jobId}` totdat de job `succeeded`, `failed` of `cancelled` is.

De jobstatus toont `queued`, `running`, `succeeded`, `failed` of `cancelled`, inclusief fase, percentage en bericht. Actieve polling gebeurt ongeveer elke seconde; als de status lang niet verandert schakelt de poller naar een tragere interval. Tijdelijke netwerkfouten krijgen backoff-retries. `JOB_NOT_FOUND` en `JOB_EXPIRED` stoppen de poller als terminale fouten.

Een lopende job kan worden geannuleerd met `DELETE /api/transcriptions/{jobId}`. De backend markeert de job dan als `cancelled`; blokkende inferentie kan alleen op runner-checkpoints worden onderbroken.

## Transcriptie en runners

De API accepteert `bytedance` en `basic-pitch`; default is `bytedance`. Het jobrecord bepaalt de echte adapter. `PIANO_TRANSCRIBER_RUNNER_MODE=demo` bewaart alleen de bestaande Basic Pitch-demo/testmodus; ByteDance-jobs gebruiken altijd de echte adapter. Een onbekende runnerconfiguratie faalt gecontroleerd.

- Expliciete `demo`: de job loopt door de demo-runner. Die levert jobmetadata zoals `noteCount` en `durationSeconds`, maar geen `transcript.json` of MIDI-export.
- Default `bytedance`: laadt het lokale PyTorch-checkpoint op CPU en normaliseert note-events naar hetzelfde transcript/artifactcontract.
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

De MIDI-writer is lokaal geïmplementeerd en schrijft een enkel trackbestand met 480 ticks per kwartnoot (960 per seconde bij 120 BPM). In expliciete demo-runner mode zijn er geen job-artifact exports; de losse demo-transcript en demo-audio blijven wel beschikbaar.

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
- `PIANO_TRANSCRIBER_RUNNER_MODE`: default `bytedance`; ondersteund: `demo`, `basic-pitch`, `bytedance`.
- `PIANO_TRANSCRIBER_BYTEDANCE_MODEL_PATH`: checkpointpad, default `backend/data/models/CRNN_note_F1=0.9677_pedal_F1=0.9186.pth`.
- `PIANO_TRANSCRIBER_BASIC_PITCH_MODEL_PATH`: optioneel pad naar Basic Pitch modelbestand of SavedModel-map.
- `PIANO_TRANSCRIBER_JOB_TTL_DAYS`: default `7`.
- `PIANO_TRANSCRIBER_IDEMPOTENCY_TTL_SECONDS`: default `86400`.

Frontend environment variables:

- `VITE_API_BASE_URL`: API-base, default `http://localhost:8000`.
- `VITE_TRANSCRIPTION_ENGINE`: default `bytedance`; kies `basic-pitch` voor de referentie.

FastAPI CORS staat alleen de lokale Vite-origins `http://localhost:5173` en `http://127.0.0.1:5173` toe.

## Tests en checks

Backend tests:

```bash
cd /piano-transcriber
. .venv/bin/activate
PYTHONPATH=backend python -m pytest
```

Frontend tests:

```bash
cd /piano-transcriber/frontend
npm run test
```

Frontend lint, typecheck en build:

```bash
cd /piano-transcriber/frontend
npm run lint
npm run typecheck
npm run build
```

Er is op dit moment geen backend lint- of typecheck-script in de repository geconfigureerd.

## Praktische beperkingen

- Expliciete runner mode `demo` produceert geen echte transcript-artifacts of MIDI-export voor jobs.
- Echte Basic Pitch-inferentie vereist dat het Pythonpakket en een bruikbaar model beschikbaar zijn; laad- en inferentiefouten worden als jobfout vastgelegd.
- Uploadlimieten zijn 20 MiB en 120 seconden tenzij environment variables ze aanpassen.
- MP3-duur wordt gelezen met `mutagen`; er wordt geen `ffmpeg` aangeroepen.
- Er is geen login, autorisatie, virus scanning, deduplicatie, retentiejob of database.
- Lokale `backend/data` kan bestaande uploads, jobs en artifacts bevatten uit eerdere runs.
