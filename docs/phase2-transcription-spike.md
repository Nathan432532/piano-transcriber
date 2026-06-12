# Phase 2 Transcription Spike

## Samenvatting

Aanbevolen engine: Basic Pitch.

Fallback: Kong/Qiu piano transcription (`piano-transcription-inference` / ByteDance piano transcription), alleen na aparte licentie- en resourcebevestiging.

Reviewer-verdict van de eerste spike: `FAIL`; dit document remedieert de vier open findings als implementatiecontract voor het Fase 2-prototype.

Reviewer-verdict na remediation: `PASS WITH NOTES`.

Resterende Reviewer-notes:

- De licentiecontrole blijft artifact-, versie- en hash-afhankelijk en moet bij daadwerkelijke implementatie opnieuw worden vastgelegd.
- Benchmark en `.gitignore`-regels zijn nog plan/contract, geen uitgevoerde implementatie.

## Aanbevolen oplossing

Gebruik Basic Pitch als eerste Fase 2-prototype achter een async worker. Reden: licht model, verifieerbare Apache-2.0 bron/package/model-card signalen, praktisch haalbaar voor korte solo-piano uploads op CPU en output die naar note-events kan worden genormaliseerd.

Gebruik Kong/Qiu alleen als fallback of latere kwaliteitsmodus na aparte controle van package, repository, pretrained checkpoint, runtime dependencies en resourcegebruik. De PyPI-package meldt MIT, maar gekoppelde GitHub-repo's, externe artifacts en pretrained weights moeten apart worden vastgelegd voordat ze in het portfolio-project worden opgenomen.

## Async worker-architectuur

- `POST /api/uploads`: blijft uploaden, valideren en opslaan.
- `POST /api/transcriptions`: maakt of hergebruikt een transcriptiejob voor `uploadId`, `engine` en optionele engine-config.
- Worker verwerkt jobs buiten request/response.
- `GET /api/transcriptions/{jobId}`: retourneert jobstatus, progress, foutinformatie, artifactlinks en transcript wanneer beschikbaar.
- `DELETE /api/transcriptions/{jobId}`: vraagt cancellation aan voor niet-terminale jobs.

## Frontend progress en foutafhandeling

### Job states

Toegestane states:

- `queued`: job is persistent aangemaakt, maar nog niet door een worker geclaimd.
- `running`: worker heeft de job geclaimd en werkt aan validatie, preprocessing, inference of postprocessing.
- `succeeded`: transcriptie is volledig genormaliseerd en persistent opgeslagen.
- `failed`: job is terminaal mislukt; `error` is verplicht.
- `cancelled`: gebruiker of serverbeleid heeft verwerking gestopt; `error.code` is `CANCELLED`.

Terminale states: `succeeded`, `failed`, `cancelled`.

Toegestane transitions:

- `queued -> running`
- `queued -> cancelled`
- `queued -> failed`
- `running -> succeeded`
- `running -> failed`
- `running -> cancelled`

Niet toegestaan:

- Een terminale job mag nooit terug naar `queued` of `running`.
- `failed -> succeeded` mag niet; retry maakt een nieuwe job of hergebruikt idempotent alleen dezelfde request zolang de oorspronkelijke job nog niet terminaal is.
- `cancelled -> running` mag niet; opnieuw starten maakt een nieuwe job.

### Progresscontract

`progress` is altijd aanwezig:

```json
{
  "phase": "queued",
  "percent": 0,
  "message": "Waiting for worker",
  "updatedAt": "2026-06-12T12:00:00Z"
}
```

`phase` is een van `queued`, `validating`, `preprocessing`, `loading_model`, `inferencing`, `postprocessing`, `saving`, `complete`, `failed`, `cancelled`.

`percent` is integer `0..100` en monotoon niet-dalend binnen dezelfde job. Percent-banden:

- `queued`: `0`
- `validating`: `1..5`
- `preprocessing`: `5..15`
- `loading_model`: `15..25`
- `inferencing`: `25..85`
- `postprocessing`: `85..95`
- `saving`: `95..99`
- `complete`: `100`
- `failed`: laatste bekende percent, niet verplicht `100`
- `cancelled`: laatste bekende percent, niet verplicht `100`

Als een engine geen fijne voortgang kan rapporteren, gebruikt de worker fase-gebaseerde voortgang binnen deze banden. Tijdens `inferencing` mag percent alleen stijgen op basis van bekende chunks of elapsed-time-estimate; de UI mag dit niet presenteren als exacte modelprogress. `updatedAt` wordt bij elke worker heartbeat vernieuwd. Een `running` job waarvan `updatedAt` ouder is dan `workerHeartbeatTimeoutSeconds` geldt voor de API als `unknown/stale` en de frontend toont dit als herstelbare serververtraging totdat backend de job terminaal markeert.

### Polling/SSE-keuze

Fase 2 gebruikt polling als default. Motivatie: eenvoudig binnen de bestaande FastAPI/frontendstructuur, betrouwbaar achter eenvoudige reverse proxies en lokale dev-servers, en voldoende voor korte CPU-jobs met lage jobfrequentie. SSE blijft optioneel voor later en is geen Fase 2-vereiste.

Pollingcontract:

- Na `POST /api/transcriptions`: direct navigeren naar transcriptiestatus.
- Poll `GET /api/transcriptions/{jobId}` elke 1000 ms zolang state `queued` of `running` is.
- Na 30 opeenvolgende seconden zonder state/progress-wijziging: verlaag naar elke 3000 ms en toon `Still working...`.
- Stop polling bij `succeeded`, `failed`, `cancelled`, `404 JOB_NOT_FOUND`, `410 JOB_EXPIRED`.
- Bij tijdelijk netwerkfalen: exponential backoff `1s, 2s, 4s, 8s, 15s`, daarna elke 15s; behoud de laatst bekende jobstatus in beeld.

### API voorbeelden

Job aanmaken:

```http
POST /api/transcriptions
Content-Type: application/json
Idempotency-Key: 2e6f0a2a-84aa-4f6f-8d0f-3a6cf6f07e51
```

```json
{
  "uploadId": "0f45f2db-65c2-42df-89d1-5a4b57f3f3c1",
  "engine": "basic-pitch",
  "options": {
    "minPitch": 21,
    "maxPitch": 108
  }
}
```

Response `202 Accepted`:

```json
{
  "jobId": "7fa8c4a5-6c5d-4c0e-88fc-fd5b0610bb3d",
  "state": "queued",
  "progress": {
    "phase": "queued",
    "percent": 0,
    "message": "Waiting for worker",
    "updatedAt": "2026-06-12T12:00:00Z"
  },
  "links": {
    "self": "/api/transcriptions/7fa8c4a5-6c5d-4c0e-88fc-fd5b0610bb3d"
  }
}
```

Running response:

```json
{
  "jobId": "7fa8c4a5-6c5d-4c0e-88fc-fd5b0610bb3d",
  "uploadId": "0f45f2db-65c2-42df-89d1-5a4b57f3f3c1",
  "engine": "basic-pitch",
  "state": "running",
  "createdAt": "2026-06-12T12:00:00Z",
  "startedAt": "2026-06-12T12:00:03Z",
  "finishedAt": null,
  "expiresAt": "2026-06-19T12:00:00Z",
  "progress": {
    "phase": "inferencing",
    "percent": 52,
    "message": "Detecting notes",
    "updatedAt": "2026-06-12T12:00:15Z"
  },
  "error": null,
  "result": null
}
```

Succeeded response:

```json
{
  "jobId": "7fa8c4a5-6c5d-4c0e-88fc-fd5b0610bb3d",
  "uploadId": "0f45f2db-65c2-42df-89d1-5a4b57f3f3c1",
  "engine": "basic-pitch",
  "state": "succeeded",
  "progress": {
    "phase": "complete",
    "percent": 100,
    "message": "Transcription ready",
    "updatedAt": "2026-06-12T12:00:32Z"
  },
  "error": null,
  "result": {
    "transcriptUrl": "/api/transcriptions/7fa8c4a5-6c5d-4c0e-88fc-fd5b0610bb3d/result",
    "exports": {
      "midi": "/api/transcriptions/7fa8c4a5-6c5d-4c0e-88fc-fd5b0610bb3d/exports/midi"
    },
    "noteCount": 148,
    "durationSeconds": 31.2
  }
}
```

Failed response:

```json
{
  "jobId": "7fa8c4a5-6c5d-4c0e-88fc-fd5b0610bb3d",
  "state": "failed",
  "progress": {
    "phase": "failed",
    "percent": 25,
    "message": "Transcription failed",
    "updatedAt": "2026-06-12T12:00:10Z"
  },
  "error": {
    "code": "MODEL_LOAD_FAILED",
    "message": "The transcription engine could not be started.",
    "retryable": true,
    "details": {
      "engine": "basic-pitch"
    }
  },
  "result": null
}
```

Cancellation:

- `DELETE /api/transcriptions/{jobId}` returns a cancelled job with `error.code=CANCELLED` when accepted.
- If the job is already `succeeded`, `failed` or `cancelled`, return `409 JOB_TERMINAL` with current jobstatus.
- If native inference cannot be interrupted immediately, backend sets `cancelRequestedAt`; the worker must publish no result after that and must persist `cancelled` after the current engine call/checkpoint.

### Timeouts, retries en idempotency

Backend defaults:

- `queueTimeoutSeconds`: 300; expired queued jobs become `failed` with `QUEUE_TIMEOUT`.
- `workerHeartbeatTimeoutSeconds`: 30; stale running jobs are exposed as recoverable warning and are failed by backend watchdog after 120 seconds stale with `WORKER_LOST`.
- `jobTimeoutSeconds`: 180 for Fase 2 prototype; timeout becomes `failed` with `TRANSCRIPTION_TIMEOUT`.
- `jobTtlDays`: 7 for jobs/results unless benchmark artifacts expliciet anders zeggen.

Idempotency:

- `POST /api/transcriptions` requires `Idempotency-Key` from the frontend for retryable create requests.
- Same `Idempotency-Key` + same body within 24h returns the existing non-terminal or terminal job.
- Same key with different body returns `409 IDEMPOTENCY_CONFLICT`.
- Browser refresh never creates a new job if the status page has a known `jobId`; it resumes polling that `jobId`.

Retries:

- Frontend retries only network/5xx create failures with the same idempotency key.
- Frontend does not auto-retry terminal `failed` jobs; it shows a Retry action that creates a new job with a new idempotency key, except non-retryable validation/license/config errors.
- `retryable=true` means retry may be offered; `retryable=false` means the user must change input/config or wait for operator action.

### Foutcodes en gebruikersmeldingen

| Code | HTTP/status | Retryable | Gebruikersmelding |
| --- | --- | --- | --- |
| `UPLOAD_NOT_FOUND` | 404 | false | `The uploaded audio could not be found. Upload it again.` |
| `UNSUPPORTED_ENGINE` | 400 | false | `This transcription engine is not available.` |
| `INVALID_OPTIONS` | 400 | false | `Some transcription settings are invalid.` |
| `QUEUE_TIMEOUT` | failed | true | `The job waited too long. Try again.` |
| `TRANSCRIPTION_TIMEOUT` | failed | true | `Transcription took too long for this prototype. Try a shorter audio file.` |
| `MODEL_LOAD_FAILED` | failed | true | `The transcription engine could not be started.` |
| `MODEL_INFERENCE_FAILED` | failed | true | `The audio could not be transcribed.` |
| `WORKER_LOST` | failed | true | `The transcription worker stopped responding. Try again.` |
| `CANCELLED` | cancelled | false | `The transcription was cancelled.` |
| `JOB_NOT_FOUND` | 404 | false | `This transcription job no longer exists.` |
| `JOB_EXPIRED` | 410 | false | `This transcription job has expired. Upload the audio again.` |
| `JOB_TERMINAL` | 409 | false | `This job has already finished.` |
| `IDEMPOTENCY_CONFLICT` | 409 | false | `This retry does not match the original request. Start a new transcription.` |
| `UNKNOWN_ERROR` | failed | true | `Something went wrong during transcription.` |

### Browser-refresh, verbindingsverlies en onbekende jobs

- Store `jobId`, `uploadId`, `engine`, `createdAt` and current idempotency key in route state and local storage.
- On refresh, if `jobId` exists, fetch `GET /api/transcriptions/{jobId}` and resume polling.
- If local storage has only `uploadId` but no job, show the upload as ready and require explicit start.
- During temporary connectivity loss, keep the last progress visible, show `Reconnecting...`, back off polling, and do not create duplicate jobs.
- Unknown local job + API `404 JOB_NOT_FOUND`: show expired/not found state and offer re-upload or start-over.
- API `410 JOB_EXPIRED`: remove cached jobId and require a fresh upload/transcription.
- Unexpected backend state outside the enum: stop destructive actions, show `UNKNOWN_ERROR`, and log the raw state for debugging.

## MIDI-ground-truth benchmarkplan

### Fixtures

Sla reproduceerbare kleine fixtures op onder `backend/data/ground_truth/fixtures/` met per fixture:

- `fixture_id.mid`: handgemaakte MIDI als ground truth.
- `fixture_id.json`: metadata met BPM, time signature, soundfont/render command, expected note count, sustain events, noise profile en SHA-256 van MIDI en gerenderde WAV.
- `fixture_id.wav`: alleen in Git als klein, reproduceerbaar en licentievrij; anders regenereren en gitignore toepassen.

Minimale fixtures:

- `single_notes_c_major`: C4-E4-G4-B4, 500 ms notes, stilte ertussen.
- `dyads_triads_inversions`: tertsen, kwinten, majeur/mineur drieklanken en inversions.
- `fast_passage_16ths_120bpm`: 16e-noten op 120 BPM over twee octaven.
- `dense_chords_60bpm`: vier- tot zesklanken met overlappende offsets.
- `sustain_pedal_arpeggio`: sustain CC64 met overlappende resonantie.
- `noisy_single_notes`: single notes gemixt met reproduceerbare pink/white noise op SNR 30 dB en 20 dB.

### Reproduceerbare rendering

Render MIDI naar mono WAV via een vastgelegde software synth, soundfont en sample rate:

- `fluidsynth` met vast gekozen permissieve `.sf2` soundfont, of een andere expliciet gelicenseerde renderer.
- Rendercommand, toolversie, soundfontnaam, soundfontlicentie en SHA-256 worden in metadata opgeslagen.
- Output: WAV mono, 44.1 kHz of 22.05 kHz, pieknormalisatie uitgeschakeld of exact vastgelegd.
- Noise wordt deterministisch toegevoegd met vaste random seed per fixture.
- Rendering-script hoort later onder `backend/benchmarks/` of `scripts/benchmarks/`; deze spike voert het niet uit.

### Matching en metrics

Parse ground truth en predicted notes naar `(pitch, onset, offset, velocity)`.

Matchingregels:

- Match alleen binnen dezelfde MIDI pitch.
- Sorteer per pitch op onset.
- Gebruik bipartite/greedy matching met minimale onset-afwijking, waarbij elke predicted en ground-truth note maximaal een keer matcht.
- Onsettolerantie: `<= 50 ms` voor normale fixtures, `<= 30 ms` voor single-note fixtures.
- Offsettolerantie: `<= max(50 ms, 20% van ground-truth duur)`; bij sustain-fixtures apart rapporteren met en zonder offsetscore.
- Een note telt als correct voor note-F1 als pitch en onset matchen; offset-F1 is een aanvullende strengere metric waarbij ook offset binnen tolerantie valt.
- Velocityfout: voor gematchte notes `mean_absolute_error` op velocity `0..127` plus genormaliseerde MAE `0..1`. Als de engine geen echte velocity heeft, markeer `velocity_source=adapter/default` en laat velocity niet meewegen in GO/NO-GO.

Metrics per fixture en totaal:

- `true_positives`, `false_positives`, `false_negatives`
- `precision = TP / (TP + FP)`
- `recall = TP / (TP + FN)`
- `f1 = 2 * precision * recall / (precision + recall)`
- `offset_f1` volgens strengere offsetmatch
- `velocity_mae`, `velocity_source`
- `runtime_seconds`, `peak_rss_mb`, `engine_version`, `model_identifier`, `host_cpu`, `python_version`

### Prototype-acceptatiecriteria

Fase 2 prototype is acceptabel wanneer Basic Pitch op de fixture-set:

- `single_notes_c_major`: note-F1 >= 0.95.
- `dyads_triads_inversions`: note-F1 >= 0.85.
- `fast_passage_16ths_120bpm`: note-F1 >= 0.75.
- `dense_chords_60bpm`: note-F1 >= 0.70.
- `sustain_pedal_arpeggio`: onset-F1 >= 0.80 en offset-F1 afzonderlijk gerapporteerd.
- `noisy_single_notes` 30 dB: note-F1 >= 0.85; 20 dB: note-F1 >= 0.70.
- Geen fixture veroorzaakt crash of infinite wait.
- Runtime <= 2x audio duration plus 20 seconds per file op de doel-VPS, of expliciet NO-GO/optimalisatie-item.
- Peak RSS <= 2 GiB per worker voor Basic Pitch.

### Benchmarkresultaten

Resultaten gaan naar `backend/data/benchmarks/runs/YYYYMMDD-HHMMSS_engine_version_gitsha/` met:

- `summary.json`: totale metrics en acceptatiebesluit.
- `fixtures/{fixture_id}.json`: per-fixture metrics, metadata, errors en artifact hashes.
- `predictions/{fixture_id}.mid` en eventueel genormaliseerde `predicted_notes.json`.
- `logs/worker.log` en `environment.json`.

Elke runmetadata bevat `engine`, `engine_version`, `model_identifier`, `git_commit`, `command`, `fixture_manifest_sha256`, `created_at`, `duration_seconds_total`, `peak_rss_mb_max`, `pass_fail` en `notes`.

## Generated artifacts, Git en retention

Alle runtime-data onder `backend/data/` is standaard lokaal en gitignored, behalve kleine reproduceerbare fixtures/manifests die expliciet worden toegestaan.

| Directory | Inhoud | Lifecycle | Git-beleid | Cleanup/retention |
| --- | --- | --- | --- | --- |
| `backend/data/models/` | Handmatig geplaatste of later beheerde modelbestanden die niet uit package cache komen. | Persistent lokaal; vervangen alleen via expliciete model-updatetaak. | Volledig gitignored; geen weights in Git. | Geen automatische cleanup behalve orphaned/oude versies na expliciete bevestiging. |
| `backend/data/transcriptions/` | Genormaliseerde transcript JSON per geslaagde job. | Persistent zolang job/resultaat geldig is. | Volledig gitignored; bevat user uploads/resultaten. | Verwijder met job na `jobTtlDays` default 7, tenzij door gebruiker/export bewaard. |
| `backend/data/jobs/` | Job records, state, progress, idempotency records en error metadata. | Persistent runtime-state voor resume/retry. | Volledig gitignored. | Terminale jobs na 7 dagen; idempotency records na 24h of wanneer jobretention verloopt. |
| `backend/data/exports/` | Gegenereerde MIDI/CSV/JSON exports per job. | Afgeleid artifact, opnieuw maakbaar uit transcript waar mogelijk. | Volledig gitignored. | Samen met transcript/job na 7 dagen; tijdelijke downloadbestanden na 24h als apart aangemaakt. |
| `backend/data/benchmarks/` | Benchmark runs, metrics, predictions, logs en environment snapshots. | Persistent lokaal voor vergelijking tussen engineversies. | Runs gitignored; kleine golden summary snapshots mogen later alleen bewust in Git. | Bewaar laatste 10 runs of 30 dagen; handmatig pinnen mogelijk via `keep=true` in metadata. |
| `backend/data/ground_truth/` | MIDI-fixtures, manifests, rendermetadata en eventueel kleine gerenderde WAVs. | Persistent reproduceerbare benchmarkbasis. | `fixtures/**/*.mid` en `fixtures/**/*.json` mogen in Git als licentievrij en klein; gerenderde WAVs/cache standaard gitignored tenzij expliciet klein en licentievrij. | Geen automatische cleanup voor Git-fixtures; gegenereerde render/cachebestanden kunnen worden herbouwd en mogen na 30 dagen weg. |
| `backend/data/model-cache/` | Download/cache van package- of frameworkmodellen, checkpoints en converted weights. | Afgeleid lokaal cachemateriaal. | Volledig gitignored. | Mag automatisch worden opgeschoond bij diskdruk; behoud alleen actieve modelversie, of LRU met max size. |

Later benodigde `.gitignore`-regels, nu niet toepassen:

```gitignore
/backend/data/models/**
/backend/data/transcriptions/**
/backend/data/jobs/**
/backend/data/exports/**
/backend/data/benchmarks/runs/**
/backend/data/benchmarks/tmp/**
/backend/data/model-cache/**
/backend/data/ground_truth/**/*.wav
/backend/data/ground_truth/**/*.flac
/backend/data/ground_truth/**/*.mp3
/backend/data/ground_truth/rendered/**
!/backend/data/ground_truth/
!/backend/data/ground_truth/fixtures/
!/backend/data/ground_truth/fixtures/**/*.mid
!/backend/data/ground_truth/fixtures/**/*.json
```

Voordat fixtures in Git mogen: bevestig licentie/eigenaarschap, grootte, deterministische generatie en afwezigheid van user/private audio.

## Opgesplitste licentiecontrole

Deze controle is read-only en zonder install/download uitgevoerd. Definitieve implementatie moet licenties opnieuw vastleggen voor de exacte packageversies, hashes en artifacts die werkelijk worden gebruikt.

| Artifact | Licentie voor zover verifieerbaar | Primaire bron | Gevolg voor portfolio-project | Onzekerheid/vervolgcontrole |
| --- | --- | --- | --- | --- |
| Spotify Basic Pitch package (`basic-pitch` PyPI) | Apache License 2.0 volgens PyPI/projectbeschrijving. | PyPI `basic-pitch` projectpagina: https://pypi.org/project/basic-pitch/ | Geschikt voor portfolio-project mits NOTICE/license-attributie en dependency-licenties worden meegenomen. | Verifieer exacte versie en wheel/sdist metadata bij implementatie. |
| Basic Pitch repository | Apache License 2.0 volgens repo LICENSE. | GitHub LICENSE: https://github.com/spotify/basic-pitch/blob/main/LICENSE | Geschikt; behoud copyright/license notices. | Controleer of gebruikte code exact uit deze repo/tag komt. |
| Basic Pitch model weights / model card | Hugging Face model card herhaalt Apache-2.0 tekst voor Basic Pitch. | Hugging Face `spotify/basic-pitch` README/model card: https://huggingface.co/spotify/basic-pitch | Waarschijnlijk geschikt als weights onder dezelfde projectlicentie vallen. | Leg exacte model artifact/hash vast; als weights uit package of andere host komen, controleer aparte license file of metadata. |
| Basic Pitch runtime dependencies | Ten minste `librosa`/audio stack en TensorFlow/TFLite/CoreML afhankelijk van install path; licenties niet in deze spike volledig uitgewerkt. | Package metadata/lockfile later; PyPI noemt librosa-compatibele audio input. | Geen blokkade voor spike, maar release/portfolio moet dependency notice audit doen. | Maak bij implementatie een dependency list met versies en licenties; controleer ffmpeg/libsndfile/audioread indien gebruikt voor MP3. |
| `piano-transcription-inference` package | MIT License volgens PyPI metadata/classifier. | PyPI `piano-transcription-inference`: https://pypi.org/project/piano-transcription-inference/ | Package zelf lijkt bruikbaar voor portfolio met MIT notice. | PyPI details zijn deels unverified; controleer sdist/wheel LICENSE en exacte versie. |
| Qiu/Kong inference repository en artifacts | GitHub-repo toont geen LICENSE-bestand in de zichtbare listing; licentie niet eenduidig verifieerbaar vanuit repo. PyPI package meldt MIT. | GitHub `qiuqiangkong/piano_transcription_inference`: https://github.com/qiuqiangkong/piano_transcription_inference en PyPI hierboven. | Niet als default opnemen totdat repo/package/artifactslicenties gelijk en vastgelegd zijn. | Controleer repo LICENSE in clone/tag, package sdist, voorbeeld-audio licenties en externe modeldownload. |
| Qiu/Kong MAPS repository | GitHub UI toont MIT license, maar raw LICENSE fetch moet bij implementatie worden bevestigd. | GitHub `qiuqiangkong/music_transcription_MAPS`: https://github.com/qiuqiangkong/music_transcription_MAPS | Alleen relevant als code/artifacts hieruit worden gebruikt; MIT lijkt portfolio-compatibel. | MAPS dataset zelf is een aparte licentiekwestie; niet opnemen zonder datasetlicentiecontrole. |
| ByteDance training repository | Geen LICENSE-bestand zichtbaar/verifieerbaar in repo-listing; licentie onbekend. | GitHub `bytedance/piano_transcription`: https://github.com/bytedance/piano_transcription | Niet rechtstreeks kopieren of vendoren in portfolio zonder expliciete licentiebevestiging. | Controleer clone/tag op LICENSE, headers en issues/releases; vraag desnoods upstream toestemming. |
| ByteDance/Qiu pretrained model weights | Inference README zegt dat pretrained model van Zenodo record `4034264` wordt gedownload; licentie van Zenodo artifact is in deze spike niet bevestigd. | PyPI/GitHub README verwijst naar https://zenodo.org/record/4034264 | Niet gebruiken als default totdat Zenodo license, checksum en redistribution/use terms vastliggen. | Controleer Zenodo metadata, files, license, checksum en of weightslicentie afwijkt van package/repo. |

Licentieconclusie: Basic Pitch blijft de veiligste default voor het prototype. Kong/Qiu/ByteDance blijft fallback alleen na artifact-specifieke licentie- en resourcecheck, omdat package-, repository- en weightslicenties niet aantoonbaar gelijk zijn op basis van de huidige read-only controle.

## GO/NO-GO

- GO: Basic Pitch prototype achter async worker met polling, persistent jobstatus en expliciete error states.
- GO: prototype benchmarken tegen de gecontroleerde MIDI-fixtures voordat enginekwaliteit wordt geclaimd.
- NO-GO: synchrone transcriptie binnen upload request.
- NO-GO: Kong/Qiu als default zonder licentiecheck, benchmark en foutafhandeling.
- NO-GO: package-installatie of model-download zonder aparte implementatiestap.
