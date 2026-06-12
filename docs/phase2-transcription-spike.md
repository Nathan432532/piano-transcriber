# Phase 2 Transcription Spike

## Samenvatting

Aanbevolen engine: Basic Pitch.

Fallback: Kong/Qiu piano transcription (`piano-transcription-inference` / ByteDance piano transcription).

Reviewer-verdict van de eerste spike: `FAIL`.

## Aanbevolen oplossing

Gebruik Basic Pitch als eerste Fase 2-prototype achter een async worker. Reden: licht model, Apache-2.0, praktisch haalbaar voor korte solo-piano uploads op CPU en output die naar note-events kan worden genormaliseerd.

Gebruik Kong/Qiu alleen als fallback of latere kwaliteitsmodus na aparte licentiecheck en CPU/RAM-benchmark.

## Async worker-architectuur

- `POST /api/uploads`: blijft uploaden, valideren en opslaan.
- `POST /api/transcriptions`: maakt job aan met `uploadId`, gekozen engine en status `queued`.
- Worker verwerkt jobs buiten request/response.
- `GET /api/transcriptions/{jobId}`: retourneert `queued`, `running`, `succeeded` of `failed`, plus `progress`, `error` en transcript.
- Optioneel SSE endpoint voor live progress.
- Op 2 vCPU: start met een enkele worker en harde timeout per job.

## Resource-inschatting

Basic Pitch:

- Verwacht haalbaar op Ubuntu VPS met 2 vCPU, circa 8 GiB RAM en Docker.
- CPU-bound; verwacht seconden tot tientallen seconden per minuut audio.
- Exacte runtime en peak RSS moeten lokaal worden gemeten.

Kong/Qiu:

- Zwaardere PyTorch-stack.
- Mogelijk geschikt voor korte clips, maar geen default zonder benchmark.
- Risico op hogere RAM-druk en langere verwerkingstijd.

## Schema-mapping

Normaliseer modeloutput naar:

```ts
pitch: number
noteName: string
startTime: number
endTime: number
velocity: number
confidence: number
hand: "unknown"
```

- `pitch`: MIDI pitch.
- `noteName`: afgeleid uit pitch.
- `startTime` / `endTime`: onset en offset in seconden.
- `velocity`: model- of MIDI-velocity, genormaliseerd naar bestaande frontendverwachting.
- `hand`: altijd `"unknown"` in Fase 2.

## Confidence-policy

- Presenteer `confidence` niet als harde per-note modelzekerheid zonder onderbouwing.
- Voor Basic Pitch: alleen vullen met een expliciet gedefinieerde adapter-score als onset/frame probabilities beschikbaar en gevalideerd zijn.
- Voor Kong/Qiu: MIDI-output bevat niet vanzelf een confidence; gebruik geen gefingeerde confidence.
- Tijdelijke fallback mag een conservatieve constante gebruiken als de API dit duidelijk als `adapterConfidencePolicy` documenteert.

## GO/NO-GO

- GO: Basic Pitch prototype achter async worker.
- NO-GO: synchrone transcriptie binnen upload request.
- NO-GO: Kong/Qiu als default zonder licentiecheck, benchmark en foutafhandeling.
- NO-GO: package-installatie of model-download zonder aparte implementatiestap.

## Resterende Reviewer-findings

1. Frontend progress en foutafhandeling concreet maken: states, polling/SSE, retry, timeout, user-facing errors en partial failure behavior.
2. MIDI-ground-truth testplan concreet maken: datasets of MIDI-render pipeline, tolerances, metrics en benchmarkcases.
3. Generated artifacts en gitignore/retention uitwerken: model cache, jobs, transcripts, exports, benchmarkdata, ground truth, retention en cleanup.
4. Licentiecontrole opsplitsen: Basic Pitch, PyPI package, ByteDance repo, model weights, datasets en eventuele ffmpeg/runtime dependencies apart beoordelen.
