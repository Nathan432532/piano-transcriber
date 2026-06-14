export type TranscriptionState = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export type TranscriptionProgress = {
  phase:
    | 'queued'
    | 'validating'
    | 'preprocessing'
    | 'loading_model'
    | 'inferencing'
    | 'postprocessing'
    | 'saving'
    | 'complete'
    | 'failed'
    | 'cancelled';
  percent: number;
  message: string;
  updatedAt: string;
};

export type TranscriptionErrorCode =
  | 'UPLOAD_NOT_FOUND'
  | 'UNSUPPORTED_ENGINE'
  | 'INVALID_OPTIONS'
  | 'QUEUE_TIMEOUT'
  | 'TRANSCRIPTION_TIMEOUT'
  | 'MODEL_LOAD_FAILED'
  | 'MODEL_INFERENCE_FAILED'
  | 'WORKER_LOST'
  | 'CANCELLED'
  | 'JOB_NOT_FOUND'
  | 'JOB_EXPIRED'
  | 'JOB_TERMINAL'
  | 'JOB_NOT_SUCCEEDED'
  | 'IDEMPOTENCY_CONFLICT'
  | 'UNKNOWN_ERROR';

export type TranscriptionErrorPayload = {
  code: TranscriptionErrorCode;
  message: string;
  retryable: boolean;
  details?: unknown;
};

export type TranscriptionResult = {
  transcriptUrl: string | null;
  exports: Record<string, string>;
  noteCount?: number;
  durationSeconds?: number;
  correction?: {
    revision: number;
    artifactUrls: {
      json: string;
      midi: string;
    };
  };
};

export type TranscriptionJob = {
  jobId: string;
  uploadId?: string;
  engine?: string;
  state: TranscriptionState;
  createdAt?: string;
  startedAt?: string | null;
  finishedAt?: string | null;
  expiresAt?: string;
  progress: TranscriptionProgress;
  error?: TranscriptionErrorPayload | null;
  result?: TranscriptionResult | null;
  links?: { self?: string };
};

export type CorrectionRequest = {
  notes: Array<{
    pitch: number;
    onset: number;
    offset: number;
    confidence?: number;
  }>;
  metadata?: {
    noteCount: number;
    durationSeconds: number;
  };
};

export type CorrectionResponse = {
  jobId: string;
  revision: number;
  artifactUrls: {
    json: string;
    midi: string;
  };
};

export type CorrectionArtifactLink = {
  key: 'corrected-json' | 'corrected-midi';
  label: string;
  href: string;
  revision: number;
};

export type TranscriptionArtifactLink = {
  key: 'json' | 'midi';
  label: string;
  href: string;
} | CorrectionArtifactLink;

export type TranscriptionApiDetail = {
  detail?: Partial<TranscriptionErrorPayload> | string;
};

export type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export class TranscriptionApiError extends Error {
  code: TranscriptionErrorCode;
  retryable: boolean;
  status: number | null;
  details?: unknown;

  constructor(code: TranscriptionErrorCode, status: number | null = null, details?: unknown) {
    super(userMessageForErrorCode(code));
    this.name = 'TranscriptionApiError';
    this.code = code;
    this.retryable = retryableForErrorCode(code);
    this.status = status;
    this.details = details;
  }
}

export const TRANSCRIPTION_JOB_STORAGE_KEY = 'piano-transcriber.currentTranscriptionJobId';

const ERROR_MESSAGES: Record<TranscriptionErrorCode, string> = {
  UPLOAD_NOT_FOUND: 'The uploaded audio could not be found. Upload it again.',
  UNSUPPORTED_ENGINE: 'This transcription engine is not available.',
  INVALID_OPTIONS: 'Some transcription settings are invalid.',
  QUEUE_TIMEOUT: 'The job waited too long. Try again.',
  TRANSCRIPTION_TIMEOUT: 'Transcription took too long for this prototype. Try a shorter audio file.',
  MODEL_LOAD_FAILED: 'The transcription engine could not be started.',
  MODEL_INFERENCE_FAILED: 'The audio could not be transcribed.',
  WORKER_LOST: 'The transcription worker stopped responding. Try again.',
  CANCELLED: 'The transcription was cancelled.',
  JOB_NOT_FOUND: 'This transcription job no longer exists.',
  JOB_EXPIRED: 'This transcription job has expired. Upload the audio again.',
  JOB_TERMINAL: 'This job has already finished.',
  JOB_NOT_SUCCEEDED: 'This job has not succeeded yet. Wait for completion or retry.',
  IDEMPOTENCY_CONFLICT: 'This retry does not match the original request. Start a new transcription.',
  UNKNOWN_ERROR: 'Something went wrong during transcription.',
};

const RETRYABLE_CODES = new Set<TranscriptionErrorCode>([
  'QUEUE_TIMEOUT',
  'TRANSCRIPTION_TIMEOUT',
  'MODEL_LOAD_FAILED',
  'MODEL_INFERENCE_FAILED',
  'WORKER_LOST',
  'UNKNOWN_ERROR',
]);

const KNOWN_ERROR_CODES = new Set(Object.keys(ERROR_MESSAGES));

const STATUS_CODE_TO_ERROR_CODE: Record<number, TranscriptionErrorCode> = {
  404: 'JOB_NOT_FOUND',
  409: 'JOB_NOT_SUCCEEDED',
  422: 'INVALID_OPTIONS',
};

export function isTerminalState(state: TranscriptionState): boolean {
  return state === 'succeeded' || state === 'failed' || state === 'cancelled';
}

export function userMessageForErrorCode(code: string | null | undefined): string {
  if (code && KNOWN_ERROR_CODES.has(code)) {
    return ERROR_MESSAGES[code as TranscriptionErrorCode];
  }
  return ERROR_MESSAGES.UNKNOWN_ERROR;
}

export function retryableForErrorCode(code: string | null | undefined): boolean {
  return Boolean(code && RETRYABLE_CODES.has(code as TranscriptionErrorCode));
}

export function transcriptionArtifactLinks(result: TranscriptionResult | null | undefined): TranscriptionArtifactLink[] {
  if (!result) {
    return [];
  }

  const links: TranscriptionArtifactLink[] = [];
  if (result.transcriptUrl) {
    links.push({ key: 'json', label: 'Transcript JSON', href: result.transcriptUrl });
  }
  if (result.exports.midi) {
    links.push({ key: 'midi', label: 'MIDI', href: result.exports.midi });
  }

  // Add corrected artifact links if present
  if (result.correction) {
    const { revision, artifactUrls } = result.correction;
    if (artifactUrls?.json) {
      links.push({
        key: 'corrected-json',
        label: `Corrected JSON (r${revision})`,
        href: artifactUrls.json,
        revision,
      });
    }
    if (artifactUrls?.midi) {
      links.push({
        key: 'corrected-midi',
        label: `Corrected MIDI (r${revision})`,
        href: artifactUrls.midi,
        revision,
      });
    }
  }

  return links;
}

export function makeIdempotencyKey(): string {
  const cryptoApi = globalThis.crypto;
  if (cryptoApi && 'randomUUID' in cryptoApi) {
    return cryptoApi.randomUUID();
  }
  return `transcription-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function createTranscriptionApiClient(fetchImpl: FetchLike, apiBase: string) {
  const apiUrl = (path: string) => (path.startsWith('http') ? path : `${apiBase}${path}`);

  const requestJson = async <T>(path: string, init?: RequestInit): Promise<T> => {
    const response = await fetchImpl(apiUrl(path), init);
    if (!response.ok) {
      throw await errorFromResponse(response);
    }
    return (await response.json()) as T;
  };

  return {
    create(uploadId: string, idempotencyKey: string, signal?: AbortSignal) {
      return requestJson<TranscriptionJob>('/api/transcriptions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': idempotencyKey,
        },
        body: JSON.stringify({
          uploadId,
          engine: 'basic-pitch',
          options: { minPitch: 21, maxPitch: 108 },
        }),
        signal,
      });
    },
    get(jobId: string, signal?: AbortSignal) {
      return requestJson<TranscriptionJob>(`/api/transcriptions/${jobId}`, { signal });
    },
    cancel(jobId: string, signal?: AbortSignal) {
      return requestJson<TranscriptionJob>(`/api/transcriptions/${jobId}`, {
        method: 'DELETE',
        signal,
      });
    },
    putCorrection(jobId: string, body: CorrectionRequest, signal?: AbortSignal): Promise<CorrectionResponse> {
      return requestJson<CorrectionResponse>(`/api/transcriptions/${jobId}/correction`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
        signal,
      });
    },
  };
}

export async function createWithNetworkRetries(
  createJob: (signal?: AbortSignal) => Promise<TranscriptionJob>,
  options: {
    signal?: AbortSignal;
    sleep?: (ms: number) => Promise<void>;
    delays?: number[];
  } = {},
): Promise<TranscriptionJob> {
  const sleep = options.sleep ?? ((ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms)));
  const delays = options.delays ?? [1000, 2000, 4000];
  let attempt = 0;

  for (;;) {
    try {
      return await createJob(options.signal);
    } catch (error) {
      if (options.signal?.aborted || error instanceof TranscriptionApiError || attempt >= delays.length) {
        throw error;
      }
      await sleep(delays[attempt]);
      attempt += 1;
    }
  }
}

async function errorFromResponse(response: Response): Promise<TranscriptionApiError> {
  const payload = (await response.json().catch(() => null)) as TranscriptionApiDetail | null;
  const detail = payload?.detail;
  
  let code: TranscriptionErrorCode = 'UNKNOWN_ERROR';
  if (typeof detail === 'object' && detail !== null && 'code' in detail) {
    code = KNOWN_ERROR_CODES.has(String(detail.code)) ? (detail.code as TranscriptionErrorCode) : 'UNKNOWN_ERROR';
  } else if (STATUS_CODE_TO_ERROR_CODE[response.status]) {
    code = STATUS_CODE_TO_ERROR_CODE[response.status];
  }
  
  const errorDetails = typeof detail === 'object' && detail !== null && 'details' in detail ? detail.details : undefined;
  const errorRetryable = typeof detail === 'object' && detail !== null && 'retryable' in detail ? Boolean(detail.retryable) : false;
  
  const error = new TranscriptionApiError(code, response.status, errorDetails);
  error.retryable = errorRetryable;
  return error;
}
