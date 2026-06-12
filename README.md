# Piano Audio Transcriber

Fase 1 is a local vertical slice for uploading short piano audio, playing it in the browser, and visualizing fixed/generated note data in two synchronized views.

## Architecture

- `backend`: FastAPI API with local file storage under `backend/data`.
- `frontend`: React + TypeScript + Vite web app.
- `shared/transcript.schema.json`: shared transcript contract for generated notes.
- `backend/data/samples/demo.wav`: synthetic public-domain-style test tone created in this repository.
- `backend/data/uploads`: local upload storage, ignored by git.

The server validates uploaded audio before storing it. It accepts only `.wav` and `.mp3`, checks content signatures, enforces `PIANO_TRANSCRIBER_MAX_UPLOAD_BYTES`, enforces `PIANO_TRANSCRIBER_MAX_AUDIO_SECONDS`, sanitizes filenames, stores files with UUID names, and serves uploads only through fixed API routes.

Both visualizations use Canvas. Canvas is a good fit for this phase because the piano roll and falling keys redraw continuously from `audio.currentTime`, and the data is small enough to keep the implementation direct without a charting dependency.

## Requirements

- Python 3.11+
- Node.js 20+
- npm

No database, queue, Docker, system packages, ML model, MIDI export, sheet music, or deployment is used in this phase.

## Setup

From the repository root:

```bash
cd /host/projects/piano-transcriber

python3 -m pip install --target backend/.deps -r backend/requirements.txt

cd frontend
npm install --include=dev
```

## Start Locally

Terminal 1:

```bash
cd /host/projects/piano-transcriber
PYTHONPATH=backend:backend/.deps python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
cd /host/projects/piano-transcriber/frontend
npm run dev
```

Open `http://127.0.0.1:5173`.

The app starts empty with actions to upload audio or load the synthetic demo. Uploading a valid WAV/MP3 stores it locally and returns the fixed test-note transcript for visualization.

## Tests And Checks

```bash
cd /host/projects/piano-transcriber
PYTHONPATH=backend:backend/.deps python3 -m pytest backend/tests

cd /host/projects/piano-transcriber/frontend
npm run lint
npm run typecheck
npm run build
```

## Configuration

- `PIANO_TRANSCRIBER_DATA_DIR`: defaults to `backend/data`.
- `PIANO_TRANSCRIBER_MAX_UPLOAD_BYTES`: defaults to `20971520` bytes.
- `PIANO_TRANSCRIBER_MAX_AUDIO_SECONDS`: defaults to `120`.
- `VITE_API_BASE_URL`: frontend API base URL, defaults to `http://localhost:8000`.

## Transcript Format

Each note uses the internal format:

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

## Limitations

- Transcription is not real yet. Uploads receive fixed generated note data.
- MP3 duration is read with the local Python dependency `mutagen`; no system audio tooling such as ffmpeg is required.
- Browser playback depends on codecs supported by the user's browser.
- The visual pitch range is C3 to C6 for this slice, not the full 88-key piano.
- Uploaded files are local development artifacts and are not deduplicated, garbage-collected, or scanned by antivirus.

## Next Steps

- Replace fixed note generation with a real transcription pipeline.
- Add full 88-key range controls and zooming.
- Add richer transcript validation at the API boundary.
- Add upload cleanup and retention policy.
- Add end-to-end browser tests once the product flow stabilizes.
