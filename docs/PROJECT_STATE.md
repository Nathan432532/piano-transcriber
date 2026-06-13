# Project State

## Doel

Piano Transcriber is een lokale webapp voor korte piano-audio: upload, validatie, playback en visualisatie van noten in pianorol en falling-keys weergave.

## Huidige fase

Fase 1 is handmatig goedgekeurd. Laatste Fase-1-checkpoint:

`fa5bd3d4e6a6e88ee8510b2afb35f15162d2ff60`

De read-only Fase-2-transcriptiespike is afgerond met Reviewer-verdict `PASS WITH NOTES`. Basic Pitch is de aanbevolen prototype-engine achter een asynchrone worker.

Eerste Fase-2-backendslice is lokaal geïmplementeerd: persistente async transcriptiejobs met pollingroutes, idempotent create-contract en een deterministische demo-runner zonder echte Basic Pitch-inference. De lokale single-process create-route gebruikt een per-key lock voor Idempotency-Key-hergebruik; `queued -> running` wordt binnen het lokale single-process prototype atomisch geclaimd. Idempotent hergebruik van een bestaande job schedult geen extra background runner. Multi-process/distributed locking of distributed worker-garanties worden niet geclaimd.

Eerste Fase-2-frontendslice is lokaal geïmplementeerd: upload start nu een async transcriptiejob via de bestaande routes, de UI pollt jobstatus met backoff/still-working gedrag, ondersteunt cancellation, herstelt een opgeslagen jobId na refresh en toont prototype-resultaten zonder downloadlinks wanneer echte artifacts ontbreken.

## Fase 1 werkt aantoonbaar

- WAV-upload werkt.
- Ongeldige uploads worden geweigerd.
- Max file size en max duration zijn configureerbaar.
- Bestandsnamen worden gesanitized; uploads worden als UUID opgeslagen.
- Upload path-containment is aanwezig.
- Uploads worden niet uitgevoerd.
- Browser playback via `<audio>` werkt.
- Demo-transcript gebruikt het interne schema met `pitch`, `noteName`, `startTime`, `endTime`, `velocity`, `confidence` en `hand: "unknown"`.
- Pianorol en falling keys renderen op basis van `audio.currentTime`.
- Play, pause, restart en snelheden 0.5x, 0.75x en 1.0x werken.
- Loading, empty, error en ready states zijn aanwezig.
- Virtueel pianoklavier is zichtbaar onderaan de falling-keys canvas.
- Witte toetsen zijn zichtbaar; zwarte toetsen worden boven de witte toetsen getekend.
- Falling keys bewegen richting het klavier.

## Resterende beperkingen

- Nog geen echte nootdetectie of model-inference; Fase-2 gebruikt voorlopig een deterministische demo-runner.
- Nog geen transcript- of MIDI-exportartifactroutes; geslaagde demo-jobs publiceren daarom geen downloadlinks voor die artifacts.
- De frontend gebruikt nog de bestaande synthetische demo-transcriptie voor visualisaties; een geslaagde demo-job is nog geen echte modeltranscriptie.
- Nog geen automatische queue-timeout, worker heartbeat, stale-worker-detectie of watchdog-failing.
- Demo-transcript is statisch.
- Geen browser-e2e of canvas-pixeltest bewezen.
- Alleen WAV-upload is aantoonbaar geaccepteerd in Fase 1; MP3 hoort bij Fase 2-onderzoek.
- Confidence is nog geen modelscore.
- `hand` blijft voorlopig `"unknown"`.
- Het benchmarkplan is nog contract, geen uitgevoerde implementatie.
- Licenties moeten bij implementatie opnieuw worden vastgelegd voor de exacte packageversies, modelartifacts en hashes.

## Uitgevoerde tests

- `PYTHONPATH=backend:backend/.deps python3 -m pytest backend/tests` -> 7 passed, 2 bestaande FastAPI deprecation warnings.
- `PYTHONPATH=backend:backend/.deps python3 -m pytest backend/tests` -> 16 passed, 2 bestaande FastAPI deprecation warnings na de eerste Fase-2-backendslice.
- `PYTHONPATH=backend:backend/.deps python3 -m pytest backend/tests` -> 18 passed, 2 bestaande FastAPI deprecation warnings na Fase-2-remediation van links/idempotency.
- `PYTHONPATH=backend:backend/.deps python3 -m pytest backend/tests` -> 21 passed, 2 bestaande FastAPI deprecation warnings na het hardenen van transcriptiejob-concurrency.
- `npm run test` -> passed.
- `npm run lint` -> passed.
- `npm run typecheck` -> passed.
- `npm run build` -> passed.
- `npm run test` -> passed na de eerste Fase-2-frontendslice met tests voor create/cancel/errorcopy, polling, terminale states, retry/backoff en refresh-herstel.
- `npm run lint` -> passed na de eerste Fase-2-frontendslice.
- `npm run typecheck` -> passed na de eerste Fase-2-frontendslice.
- `npm run build` -> passed na de eerste Fase-2-frontendslice.
- Smokechecks: frontend 200, API health 200, demo-audio 200/705644 bytes, geldige WAV-upload 200 met duration 8.0 en 8 notes, ongeldige upload 400.
- `git check-ignore` bevestigde dat uploads, dependencies en build-output genegeerd worden.

## Git status

Relevante lokale checkpoints:

- `b01110f` — async transcription job UI integration.
- `ec81dca` — harden transcription job concurrency.

De eerder bekende backend-concurrencybeperking rond idempotent hergebruik en dubbele background runners is opgelost in het lokale single-process prototype. Voor vervolgwerk blijven de multi-process/distributed worker-garanties expliciet buiten claim.

## Eerstvolgende taak

Start na het documentatiecheckpoint een nieuwe OpenClaw-sessie. Bepaal daarin één afgebakende eerste Fase-2-implementatietaak op basis van `docs/phase2-transcription-spike.md`. Installeer nog geen package en download geen model voordat de exacte versie, licentie, artifactbron en resource-aanpak voor die implementatiestap zijn bevestigd.
