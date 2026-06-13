import {
  createTranscriptionApiClient,
  createWithNetworkRetries,
  TranscriptionApiError,
  userMessageForErrorCode,
  type TranscriptionJob,
} from '../src/transcriptionApi.js';

const queuedJob = makeJob('job-1', 'queued', 0);
const cancelledJob = makeJob('job-1', 'cancelled', 0);

await test('client creates, fetches, cancels, and maps API errors', async () => {
  const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
  const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ input, init });
    if (String(input).endsWith('/api/transcriptions') && init?.method === 'POST') {
      return jsonResponse(queuedJob, 202);
    }
    if (String(input).endsWith('/api/transcriptions/job-1') && init?.method === 'DELETE') {
      return jsonResponse(cancelledJob, 200);
    }
    if (String(input).endsWith('/api/transcriptions/missing')) {
      return jsonResponse(
        { detail: { code: 'JOB_NOT_FOUND', message: 'ignored server text', retryable: false } },
        404,
      );
    }
    return jsonResponse(queuedJob, 200);
  };
  const client = createTranscriptionApiClient(fetchImpl, 'http://api.test');

  const created = await client.create('upload-1', 'idem-1');
  const fetched = await client.get('job-1');
  const cancelled = await client.cancel('job-1');

  assertEqual(created.state, 'queued');
  assertEqual(fetched.jobId, 'job-1');
  assertEqual(cancelled.state, 'cancelled');
  assertEqual(calls[0].input, 'http://api.test/api/transcriptions');
  assertEqual((calls[0].init?.headers as Record<string, string>)['Idempotency-Key'], 'idem-1');
  assertEqual(JSON.parse(String(calls[0].init?.body)).engine, 'basic-pitch');
  assertEqual(calls[2].init?.method, 'DELETE');

  await assertRejects(async () => client.get('missing'), (error) => {
    assertOk(error instanceof TranscriptionApiError, 'expected TranscriptionApiError');
    const apiError = error as TranscriptionApiError;
    assertEqual(apiError.code, 'JOB_NOT_FOUND');
    assertEqual(apiError.message, 'This transcription job no longer exists.');
  });
});

await test('create retry keeps the same request operation for temporary failures', async () => {
  let attempts = 0;
  const sleeps: number[] = [];
  const job = await createWithNetworkRetries(
    async () => {
      attempts += 1;
      if (attempts < 3) {
        throw new TypeError('network down');
      }
      return queuedJob;
    },
    {
      sleep: async (ms) => {
        sleeps.push(ms);
      },
      delays: [1000, 2000, 4000],
    },
  );

  assertEqual(job.jobId, 'job-1');
  assertEqual(attempts, 3);
  assertDeepEqual(sleeps, [1000, 2000]);
});

await test('error code copy follows the transcription contract', async () => {
  assertEqual(userMessageForErrorCode('MODEL_LOAD_FAILED'), 'The transcription engine could not be started.');
  assertEqual(userMessageForErrorCode('JOB_EXPIRED'), 'This transcription job has expired. Upload the audio again.');
  assertEqual(userMessageForErrorCode('UNKNOWN_CODE'), 'Something went wrong during transcription.');
});

function makeJob(jobId: string, state: TranscriptionJob['state'], percent: number): TranscriptionJob {
  return {
    jobId,
    state,
    progress: {
      phase: state === 'succeeded' ? 'complete' : state === 'running' ? 'inferencing' : state,
      percent,
      message: state,
      updatedAt: '2026-06-13T00:00:00Z',
    },
    error: state === 'cancelled' ? { code: 'CANCELLED', message: 'cancelled', retryable: false } : null,
    result: null,
  };
}

function jsonResponse(payload: unknown, status: number): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

async function test(name: string, run: () => Promise<void>): Promise<void> {
  try {
    await run();
  } catch (error) {
    throw new Error(`${name}: ${error instanceof Error ? error.message : String(error)}`, { cause: error });
  }
}

async function assertRejects(run: () => Promise<unknown>, inspect: (error: unknown) => void): Promise<void> {
  try {
    await run();
  } catch (error) {
    inspect(error);
    return;
  }
  throw new Error('Expected rejection');
}

function assertEqual<T>(actual: T, expected: T): void {
  if (actual !== expected) {
    throw new Error(`Expected ${String(expected)}, received ${String(actual)}`);
  }
}

function assertDeepEqual(actual: unknown, expected: unknown): void {
  const actualJson = JSON.stringify(actual);
  const expectedJson = JSON.stringify(expected);
  if (actualJson !== expectedJson) {
    throw new Error(`Expected ${expectedJson}, received ${actualJson}`);
  }
}

function assertOk(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}
