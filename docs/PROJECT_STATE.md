# Project State

## Doel

Piano Transcriber is een lokale webapp voor korte piano-audio: upload, validatie, playback en visualisatie van noten in pianorol en falling-keys weergave.

## Huidige fase

Fase 1 is handmatig goedgekeurd. Laatste checkpoint-commit:

`fa5bd3d4e6a6e88ee8510b2afb35f15162d2ff60`

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

- Nog geen echte nootdetectie of model-inference.
- Demo-transcript is statisch.
- Geen browser-e2e of canvas-pixeltest bewezen.
- Alleen WAV-upload is aantoonbaar geaccepteerd in Fase 1; MP3 hoort bij Fase 2-onderzoek.
- Confidence is nog geen modelscore.
- `hand` blijft voorlopig `"unknown"`.

## Uitgevoerde tests

- `PYTHONPATH=backend:backend/.deps python3 -m pytest backend/tests` -> 7 passed, 2 bestaande FastAPI deprecation warnings.
- `npm run test` -> passed.
- `npm run lint` -> passed.
- `npm run typecheck` -> passed.
- `npm run build` -> passed.
- Smokechecks: frontend 200, API health 200, demo-audio 200/705644 bytes, geldige WAV-upload 200 met duration 8.0 en 8 notes, ongeldige upload 400.
- `git check-ignore` bevestigde dat uploads, dependencies en build-output genegeerd worden.

## Git status

Voor deze sessieoverdracht gestart vanaf schone `master` op checkpoint `fa5bd3d`.

## Eerstvolgende taak

Remedieer de read-only Fase 2-spike: werk de vier resterende Reviewer-findings uit zonder direct implementatie, package-installatie of model-download.
