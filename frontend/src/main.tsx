import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { getKeyboardGeometry, getKeyboardHeight, getPitchKeyRect, isWhiteKey } from './keyboardGeometry';
import {
  createTranscriptionApiClient,
  createWithNetworkRetries,
  isTerminalState,
  makeIdempotencyKey,
  TRANSCRIPTION_JOB_STORAGE_KEY,
  TranscriptionApiError,
  userMessageForErrorCode,
  type TranscriptionJob,
} from './transcriptionApi';
import { TranscriptionPoller, type PollerStatus } from './transcriptionPoller';
import './styles.css';

type Hand = 'unknown';

type Note = {
  pitch: number;
  noteName: string;
  startTime: number;
  endTime: number;
  velocity: number;
  confidence: number;
  hand: Hand;
};

type Transcript = {
  version: string;
  source: {
    kind: 'synthetic' | 'uploaded';
    filename: string;
    duration: number;
  };
  notes: Note[];
};

type UploadResponse = {
  uploadId: string;
  originalFilename: string;
  duration: number;
  size: number;
  audioUrl: string;
  transcript: Transcript;
};

type AppState = 'empty' | 'loading' | 'ready' | 'error';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
const SPEEDS = [0.5, 0.75, 1] as const;
const PITCH_MIN = 48;
const PITCH_MAX = 84;
const transcriptionApi = createTranscriptionApiClient(fetch, API_BASE);

function apiUrl(path: string): string {
  if (path.startsWith('http')) {
    return path;
  }
  return `${API_BASE}${path}`;
}

function durationFromTranscript(transcript: Transcript | null): number {
  if (!transcript) {
    return 8;
  }
  const maxNote = transcript.notes.reduce((max, note) => Math.max(max, note.endTime), 0);
  return Math.max(transcript.source.duration, maxNote, 1);
}

function stateLabel(job: TranscriptionJob): string {
  const labels: Record<TranscriptionJob['state'], string> = {
    queued: 'Queued',
    running: 'Running',
    succeeded: 'Succeeded',
    failed: 'Failed',
    cancelled: 'Cancelled',
  };
  return labels[job.state];
}

function jobResultHasArtifacts(job: TranscriptionJob | null): boolean {
  if (!job?.result) {
    return false;
  }
  return Boolean(job.result.transcriptUrl || Object.keys(job.result.exports).length > 0);
}

function drawPianoRoll(
  canvas: HTMLCanvasElement,
  notes: Note[],
  currentTime: number,
  duration: number,
): void {
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth * ratio;
  const height = canvas.clientHeight * ratio;
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }

  const ctx = canvas.getContext('2d');
  if (!ctx) {
    return;
  }

  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#121417';
  ctx.fillRect(0, 0, w, h);

  const pitchCount = PITCH_MAX - PITCH_MIN + 1;
  const rowHeight = h / pitchCount;

  for (let pitch = PITCH_MIN; pitch <= PITCH_MAX; pitch += 1) {
    const y = h - (pitch - PITCH_MIN + 1) * rowHeight;
    ctx.fillStyle = isWhiteKey(pitch) ? '#1f252b' : '#181d22';
    ctx.fillRect(0, y, w, Math.ceil(rowHeight));
  }

  ctx.strokeStyle = '#2f3840';
  ctx.lineWidth = 1;
  for (let time = 0; time <= duration; time += 1) {
    const x = (time / duration) * w;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  }

  for (const note of notes) {
    const x = (note.startTime / duration) * w;
    const noteWidth = Math.max(((note.endTime - note.startTime) / duration) * w, 4);
    const y = h - (note.pitch - PITCH_MIN + 1) * rowHeight + 1;
    const active = currentTime >= note.startTime && currentTime <= note.endTime;
    ctx.fillStyle = active ? '#ffd166' : '#3ddc97';
    ctx.fillRect(x, y, noteWidth, Math.max(rowHeight - 2, 5));
  }

  const playheadX = (currentTime / duration) * w;
  ctx.strokeStyle = '#f45b69';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(playheadX, 0);
  ctx.lineTo(playheadX, h);
  ctx.stroke();
}

function drawFallingKeys(
  canvas: HTMLCanvasElement,
  notes: Note[],
  currentTime: number,
  duration: number,
): void {
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth * ratio;
  const height = canvas.clientHeight * ratio;
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }

  const ctx = canvas.getContext('2d');
  if (!ctx) {
    return;
  }

  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  const keyboardHeight = getKeyboardHeight(h);
  const strikeY = h - keyboardHeight;
  const keyboardGeometry = getKeyboardGeometry(PITCH_MIN, PITCH_MAX, w, strikeY, keyboardHeight);
  const fallWindow = Math.max(3.5, duration / 3);

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#0f1115';
  ctx.fillRect(0, 0, w, h);

  for (const key of keyboardGeometry.whiteKeys) {
    ctx.fillStyle = '#171c21';
    ctx.fillRect(key.x, 0, Math.ceil(key.width), strikeY);
    ctx.strokeStyle = '#252d35';
    ctx.lineWidth = 1;
    ctx.strokeRect(key.x, 0, key.width, strikeY);
  }

  for (const key of keyboardGeometry.blackKeys) {
    ctx.fillStyle = '#101419';
    ctx.fillRect(key.x, 0, key.width, strikeY);
  }

  ctx.strokeStyle = '#f45b69';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(0, strikeY);
  ctx.lineTo(w, strikeY);
  ctx.stroke();

  const activePitches = new Set(
    notes
      .filter((note) => currentTime >= note.startTime && currentTime <= note.endTime)
      .map((note) => note.pitch),
  );

  for (const note of notes) {
    const key = getPitchKeyRect(note.pitch, keyboardGeometry);
    if (!key) {
      continue;
    }
    const notePadding = Math.min(3, key.width * 0.16);
    const x = key.x + notePadding;
    const yStart = strikeY - ((note.startTime - currentTime) / fallWindow) * strikeY;
    const yEnd = strikeY - ((note.endTime - currentTime) / fallWindow) * strikeY;
    const top = Math.min(yStart, yEnd);
    const bottom = Math.max(yStart, yEnd);
    if (bottom < 0 || top > strikeY) {
      continue;
    }
    const active = currentTime >= note.startTime && currentTime <= note.endTime;
    ctx.fillStyle = active ? '#ffd166' : '#4dabf7';
    ctx.fillRect(x, Math.max(top, 0), Math.max(key.width - notePadding * 2, 3), Math.max(bottom - top, 10));
  }

  for (const key of keyboardGeometry.whiteKeys) {
    const active = activePitches.has(key.pitch);
    ctx.fillStyle = active ? '#ffd166' : '#f3f5f7';
    ctx.fillRect(key.x + 1, key.y + 1, Math.max(key.width - 2, 3), key.height - 2);
    ctx.strokeStyle = '#4a5662';
    ctx.strokeRect(key.x + 1, key.y + 1, Math.max(key.width - 2, 3), key.height - 2);
  }

  for (const key of keyboardGeometry.blackKeys) {
    const active = activePitches.has(key.pitch);
    ctx.fillStyle = active ? '#f45b69' : '#151a20';
    ctx.fillRect(key.x, key.y + 1, key.width, key.height);
    ctx.strokeStyle = '#07090c';
    ctx.strokeRect(key.x, key.y + 1, key.width, key.height);
  }
}

function Visualization({
  kind,
  notes,
  currentTime,
  duration,
}: {
  kind: 'roll' | 'falling';
  notes: Note[];
  currentTime: number;
  duration: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    if (kind === 'roll') {
      drawPianoRoll(canvas, notes, currentTime, duration);
    } else {
      drawFallingKeys(canvas, notes, currentTime, duration);
    }
  }, [currentTime, duration, kind, notes]);

  return (
    <canvas
      ref={canvasRef}
      className={kind === 'roll' ? 'roll-canvas' : 'falling-canvas'}
      aria-label={kind === 'roll' ? 'Piano roll visualization' : 'Falling keys visualization'}
    />
  );
}

function App() {
  const [state, setState] = useState<AppState>('empty');
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1);
  const [isPlaying, setIsPlaying] = useState(false);
  const [job, setJob] = useState<TranscriptionJob | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [pollerStatus, setPollerStatus] = useState<PollerStatus>({
    isPolling: false,
    networkIssue: false,
    stillWorking: false,
    nextDelayMs: null,
    consecutiveUnchangedMs: 0,
  });
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const frameRef = useRef<number | null>(null);
  const pollerRef = useRef<TranscriptionPoller | null>(null);
  const createAbortRef = useRef<AbortController | null>(null);

  const duration = useMemo(() => durationFromTranscript(transcript), [transcript]);

  useEffect(() => {
    pollerRef.current = new TranscriptionPoller({
      fetchJob: (jobId, signal) => transcriptionApi.get(jobId, signal),
      onUpdate: (nextJob) => {
        setJob(nextJob);
        setJobError(nextJob.error ? userMessageForErrorCode(nextJob.error.code) : null);
        window.localStorage.setItem(TRANSCRIPTION_JOB_STORAGE_KEY, nextJob.jobId);
      },
      onTerminalError: (apiError) => {
        setJobError(apiError.message);
        setError(apiError.message);
        setState('error');
        window.localStorage.removeItem(TRANSCRIPTION_JOB_STORAGE_KEY);
      },
      onStatus: setPollerStatus,
    });

    const storedJobId = window.localStorage.getItem(TRANSCRIPTION_JOB_STORAGE_KEY);
    if (storedJobId) {
      pollerRef.current.start(storedJobId);
    }

    return () => {
      pollerRef.current?.stop();
      createAbortRef.current?.abort();
    };
  }, []);

  const startPollingJob = (nextJob: TranscriptionJob) => {
    setJob(nextJob);
    setJobError(nextJob.error ? userMessageForErrorCode(nextJob.error.code) : null);
    window.localStorage.setItem(TRANSCRIPTION_JOB_STORAGE_KEY, nextJob.jobId);
    pollerRef.current?.start(nextJob.jobId, nextJob);
  };

  useEffect(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.playbackRate = speed;
    }
  }, [speed]);

  useEffect(() => {
    const tick = () => {
      const audio = audioRef.current;
      if (audio) {
        setCurrentTime(audio.currentTime);
      }
      frameRef.current = window.requestAnimationFrame(tick);
    };
    if (isPlaying) {
      frameRef.current = window.requestAnimationFrame(tick);
    }
    return () => {
      if (frameRef.current !== null) {
        window.cancelAnimationFrame(frameRef.current);
      }
    };
  }, [isPlaying]);

  const loadDemo = async () => {
    setState('loading');
    setError(null);
    setJob(null);
    setJobError(null);
    window.localStorage.removeItem(TRANSCRIPTION_JOB_STORAGE_KEY);
    pollerRef.current?.stop();
    setIsPlaying(false);
    try {
      const response = await fetch(apiUrl('/api/transcripts/demo'));
      if (!response.ok) {
        throw new Error('Could not load demo transcript');
      }
      const demoTranscript = (await response.json()) as Transcript;
      setTranscript(demoTranscript);
      setAudioUrl(apiUrl('/api/samples/demo'));
      setCurrentTime(0);
      setState('ready');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Demo loading failed');
      setState('error');
    }
  };

  const onUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setState('loading');
    setError(null);
    setJob(null);
    setJobError(null);
    setIsPlaying(false);
    pollerRef.current?.stop();
    createAbortRef.current?.abort();
    createAbortRef.current = new AbortController();
    try {
      const data = new FormData();
      data.append('file', file);
      const response = await fetch(apiUrl('/api/uploads'), {
        method: 'POST',
        body: data,
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(payload?.detail ?? 'Upload failed');
      }
      const payload = (await response.json()) as UploadResponse;
      setTranscript(payload.transcript);
      setAudioUrl(apiUrl(payload.audioUrl));
      setCurrentTime(0);
      const idempotencyKey = makeIdempotencyKey();
      const createdJob = await createWithNetworkRetries(
        (signal) => transcriptionApi.create(payload.uploadId, idempotencyKey, signal),
        { signal: createAbortRef.current.signal },
      );
      startPollingJob(createdJob);
      setState('ready');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed');
      setState('error');
    } finally {
      createAbortRef.current = null;
      event.target.value = '';
    }
  };

  const cancelJob = async () => {
    if (!job || isTerminalState(job.state)) {
      return;
    }
    setJobError(null);
    try {
      const cancelled = await transcriptionApi.cancel(job.jobId);
      startPollingJob(cancelled);
    } catch (err) {
      if (err instanceof TranscriptionApiError) {
        setJobError(err.message);
      } else {
        setJobError('Could not cancel transcription right now.');
      }
    }
  };

  const play = async () => {
    if (!audioRef.current) {
      return;
    }
    audioRef.current.playbackRate = speed;
    await audioRef.current.play();
  };

  const pause = () => {
    audioRef.current?.pause();
  };

  const restart = async () => {
    if (!audioRef.current) {
      return;
    }
    audioRef.current.currentTime = 0;
    setCurrentTime(0);
    await audioRef.current.play();
  };

  return (
    <main className="app-shell">
      <section className="topbar">
        <div>
          <h1>Piano Audio Transcriber</h1>
          <p>Upload a short WAV/MP3 and watch the prototype transcription job status.</p>
        </div>
        <label className="upload-button">
          Upload audio
          <input
            type="file"
            accept=".wav,.mp3,audio/wav,audio/mpeg"
            onChange={onUpload}
            disabled={state === 'loading'}
          />
        </label>
      </section>

      <section className="transport">
        <audio
          ref={audioRef}
          src={audioUrl ?? undefined}
          controls
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          onEnded={() => setIsPlaying(false)}
          onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
        />
        <div className="button-row">
          <button type="button" onClick={play} disabled={!audioUrl || state === 'loading'}>
            Play
          </button>
          <button type="button" onClick={pause} disabled={!audioUrl || state === 'loading'}>
            Pause
          </button>
          <button type="button" onClick={restart} disabled={!audioUrl || state === 'loading'}>
            Restart
          </button>
        </div>
        <div className="speed-row" aria-label="Playback speed">
          {SPEEDS.map((value) => (
            <button
              key={value}
              type="button"
              className={speed === value ? 'active' : ''}
              onClick={() => setSpeed(value)}
            >
              {value.toFixed(value === 1 ? 1 : 2)}x
            </button>
          ))}
        </div>
        <div className="time-readout">
          {currentTime.toFixed(2)}s / {duration.toFixed(2)}s
        </div>
      </section>

      {job && (
        <section className={`job-panel job-panel-${job.state}`} aria-live="polite">
          <div className="job-panel-header">
            <div>
              <div className="job-kicker">Transcription job</div>
              <strong>{stateLabel(job)}</strong>
            </div>
            <span className="job-id">Job {job.jobId}</span>
          </div>
          <div className="progress-track" aria-label={`Progress ${job.progress.percent}%`}>
            <div className="progress-fill" style={{ width: `${job.progress.percent}%` }} />
          </div>
          <div className="job-details">
            <span>{job.progress.percent}%</span>
            <span>Phase: {job.progress.phase}</span>
            <span>{job.progress.message}</span>
          </div>
          {pollerStatus.stillWorking && <p className="job-note">Still working...</p>}
          {pollerStatus.networkIssue && (
            <p className="job-note warning">
              Network connection is unstable. Keeping the last known status visible and retrying.
            </p>
          )}
          {jobError && <p className="job-note error-text">{jobError}</p>}
          {job.state === 'succeeded' && !jobResultHasArtifacts(job) && (
            <p className="job-note">
              Prototype job completed. No real model transcript or export artifact was produced yet.
            </p>
          )}
          {!isTerminalState(job.state) && (
            <button type="button" onClick={cancelJob}>
              Cancel transcription
            </button>
          )}
        </section>
      )}

      {state === 'loading' && <section className="state-panel">Uploading audio and starting transcription job...</section>}
      {state === 'empty' && (
        <section className="state-panel state-panel-actions">
          <div>
            <strong>No audio loaded yet.</strong>
            <p>Upload a short piano file or open the synthetic demo transcript.</p>
          </div>
          <button type="button" onClick={loadDemo}>
            Load demo
          </button>
        </section>
      )}
      {state === 'error' && (
        <section className="state-panel state-panel-actions error">
          <div>
            <strong>Error: {error}</strong>
            <p>Try the demo transcript or upload another WAV/MP3 file.</p>
          </div>
          <button type="button" onClick={loadDemo}>
            Load demo
          </button>
        </section>
      )}

      {state === 'ready' && transcript && (
        <>
          <section className="meta-strip">
            <span>{transcript.source.filename}</span>
            <span>{transcript.notes.length} notes</span>
            <span>{transcript.source.kind === 'uploaded' ? 'demo visualization for uploaded audio' : 'synthetic demo'}</span>
          </section>

          <section className="visual-grid">
            <div className="visual-block">
              <div className="visual-title">Piano roll</div>
              <Visualization kind="roll" notes={transcript.notes} currentTime={currentTime} duration={duration} />
            </div>
            <div className="visual-block">
              <div className="visual-title">Falling keys</div>
              <Visualization kind="falling" notes={transcript.notes} currentTime={currentTime} duration={duration} />
            </div>
          </section>
        </>
      )}
    </main>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
