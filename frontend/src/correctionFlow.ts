// correctionFlow.ts — Pure logic for correction state, payload, and reload

import type { TranscriptionJob, CorrectionRequest, CorrectionResponse } from './transcriptionApi.js';

// --- Constants ---
// Backend limits (from docs/PROJECT_STATE.md)
export const PITCH_MIN = 21;
export const PITCH_MAX = 108;
export const VELOCITY_MIN = 1;
export const VELOCITY_MAX = 127;
export const CONFIDENCE_MIN = 0;
export const CONFIDENCE_MAX = 1;

// --- Types ---
export type NoteDraft = {
  pitch: number;
  startTime: number;
  endTime: number;
  velocity: number;
  confidence?: number;
  hand?: "unknown";
};

// --- Core Logic ---

/**
 * Determines the correct transcript URL to load, preferring corrected artifacts.
 */
export function selectTranscriptUrl(job: TranscriptionJob | null): string | null {
  if (!job?.result) return null;
  return job.result.correction?.exports.transcript ?? job.result.transcriptUrl ?? null;
}

/**
 * Returns the transcript URL that should be fetched next, skipping URLs that are already loaded.
 */
export function selectPendingTranscriptUrl(
  job: TranscriptionJob | null,
  loadedTranscriptUrl: string | null,
): string | null {
  const transcriptUrl = selectTranscriptUrl(job);
  if (!transcriptUrl || transcriptUrl === loadedTranscriptUrl) {
    return null;
  }
  return transcriptUrl;
}

/**
 * Reconstructs the audio URL for a recovered job from its upload id.
 */
export function selectJobAudioUrl(job: TranscriptionJob | null): string | null {
  if (!job?.uploadId) {
    return null;
  }
  return `/api/uploads/${job.uploadId}`;
}

/**
 * Returns the base revision for a correction request.
 */
export function getBaseRevision(job: TranscriptionJob | null): number {
  const revision = job?.result?.correction?.revision;
  if (revision === undefined) return 0;
  if (!Number.isInteger(revision) || revision < 0) {
    throw new Error(`Invalid base revision: ${revision}`);
  }
  return revision;
}

/**
 * Validates a note draft for backend compatibility.
 */
export function validateCorrectionNote(
  note: Omit<CorrectionRequest["notes"][number], "hand"> & { hand?: unknown },
  durationSeconds?: number,
): void {
  if (!Number.isInteger(note.pitch) || note.pitch < PITCH_MIN || note.pitch > PITCH_MAX) {
    throw new Error(`Pitch must be an integer between ${PITCH_MIN} and ${PITCH_MAX}, got ${note.pitch}`);
  }
  if (!Number.isFinite(note.startTime) || note.startTime < 0) {
    throw new Error(`Start time must be a finite number >= 0, got ${note.startTime}`);
  }
  if (!Number.isFinite(note.endTime) || note.endTime <= note.startTime) {
    throw new Error(`End time must be a finite number > startTime, got ${note.endTime}`);
  }
  if (durationSeconds !== undefined && note.endTime > durationSeconds) {
    throw new Error(`End time ${note.endTime} exceeds transcript duration ${durationSeconds}`);
  }
  if (!Number.isInteger(note.velocity) || note.velocity < VELOCITY_MIN || note.velocity > VELOCITY_MAX) {
    throw new Error(`Velocity must be an integer between ${VELOCITY_MIN} and ${VELOCITY_MAX}, got ${note.velocity}`);
  }
  if (typeof note.confidence !== "number" || !Number.isFinite(note.confidence) || note.confidence < CONFIDENCE_MIN || note.confidence > CONFIDENCE_MAX) {
    throw new Error(`Confidence must be a finite number between ${CONFIDENCE_MIN} and ${CONFIDENCE_MAX}, got ${note.confidence}`);
  }
  if (note.hand !== "unknown") {
    throw new Error(`Hand must be exactly "unknown", got ${note.hand}`);
  }
}

/**
 * Builds a CorrectionRequest payload from draft notes.
 * Throws if any note is invalid.
 */
export function buildCorrectionPayload(
  baseRevision: number,
  notes: Array<{
    pitch: number;
    startTime: number;
    endTime: number;
    velocity: number;
    confidence?: number;
    hand?: string;
  }>,
): CorrectionRequest {
  // Validate baseRevision
  if (!Number.isInteger(baseRevision) || baseRevision < 0 || !Number.isFinite(baseRevision)) {
    throw new Error(`baseRevision must be a non-negative integer, got ${baseRevision}`);
  }

  const validatedNotes = notes.map((note) => {
    // Validate required fields
    if (note.confidence === undefined) {
      throw new Error(`Confidence is required`);
    }
    if (note.hand !== "unknown") {
      throw new Error(`Hand must be exactly "unknown", got ${note.hand}`);
    }

    // Validate note structure
    validateCorrectionNote({
      pitch: note.pitch,
      startTime: note.startTime,
      endTime: note.endTime,
      velocity: note.velocity,
      confidence: note.confidence,
      hand: "unknown",
    });

    // Return only the required fields
    return {
      pitch: note.pitch,
      startTime: note.startTime,
      endTime: note.endTime,
      velocity: note.velocity,
      confidence: note.confidence,
      hand: "unknown" as const,
    };
  });

  return {
    baseRevision,
    notes: validatedNotes,
  };
}

/**
 * Updates the job state after a successful correction save.
 */
export function updateJobAfterSave(
  prevJob: TranscriptionJob | null,
  response: CorrectionResponse,
): TranscriptionJob | null {
  if (!prevJob?.result) return prevJob;

  return {
    ...prevJob,
    result: {
      ...prevJob.result,
      correction: {
        revision: response.revision,
        exports: response.exports,
      },
    },
  };
}

/**
 * Orchestrates a retry reload and preserves the pending URL on failure.
 */
export async function orchestrateRetryReload(
  pendingReloadUrl: string,
  reloadFn: (url: string) => Promise<void>,
  setReloadStatus: (status: 'reloading' | 'success' | 'error') => void,
  setPendingReloadUrl: (url: string | null) => void,
  onError?: (error: unknown) => void,
): Promise<void> {
  setReloadStatus('reloading');

  try {
    await reloadFn(pendingReloadUrl);
    setReloadStatus('success');
    setPendingReloadUrl(null);
  } catch (error) {
    setReloadStatus('error');
    setPendingReloadUrl(pendingReloadUrl);
    onError?.(error);
  }
}

/**
 * Orchestrates save + reload with injected functions.
 * Returns { success: boolean, response: CorrectionResponse, reloadError?: unknown }
 */
export async function orchestrateSaveAndReload(
  saveFn: (payload: CorrectionRequest) => Promise<CorrectionResponse>,
  reloadFn: (url: string) => Promise<void>,
  baseRevision: number,
  notes: CorrectionRequest["notes"],
  durationSeconds?: number,
): Promise<{
  success: boolean;
  response: CorrectionResponse;
  reloadError?: unknown;
}> {
  // Validate notes upfront
  for (const note of notes) {
    validateCorrectionNote(note, durationSeconds);
  }

  const payload = buildCorrectionPayload(baseRevision, notes);
  const response = await saveFn(payload);

  try {
    await reloadFn(response.exports.transcript);
    return { success: true, response };
  } catch (reloadError) {
    return { success: false, response, reloadError };
  }
}
