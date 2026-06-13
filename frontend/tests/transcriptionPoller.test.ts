import { TranscriptionApiError, type TranscriptionJob } from '../src/transcriptionApi.js';
import { TranscriptionPoller, type PollerStatus } from '../src/transcriptionPoller.js';

class FakeTimers {
  now = 0;
  private nextId = 1;
  private timers: Array<{ id: number; due: number; callback: () => void }> = [];

  setTimeout(callback: () => void, ms: number): number {
    const id = this.nextId;
    this.nextId += 1;
    this.timers.push({ id, due: this.now + ms, callback });
    this.timers.sort((a, b) => a.due - b.due);
    return id;
  }

  clearTimeout(id: number): void {
    this.timers = this.timers.filter((timer) => timer.id !== id);
  }

  advance(ms: number): void {
    this.now += ms;
    const due = this.timers.filter((timer) => timer.due <= this.now);
    this.timers = this.timers.filter((timer) => timer.due > this.now);
    for (const timer of due) {
      timer.callback();
    }
  }

  nextDelay(): number | null {
    if (this.timers.length === 0) {
      return null;
    }
    return Math.max(0, this.timers[0].due - this.now);
  }

  pendingCount(): number {
    return this.timers.length;
  }
}

await test('polls active jobs, slows after unchanged work, and stops on terminal state', async () => {
  const timers = new FakeTimers();
  const updates: TranscriptionJob[] = [];
  const statuses: PollerStatus[] = [];
  const responses = [
    makeJob('job-1', 'queued', 0, 'Waiting for worker'),
    makeJob('job-1', 'queued', 0, 'Waiting for worker'),
    makeJob('job-1', 'queued', 0, 'Waiting for worker'),
    makeJob('job-1', 'running', 5, 'Validating upload'),
    makeJob('job-1', 'succeeded', 100, 'Transcription ready'),
  ];
  const poller = new TranscriptionPoller({
    fetchJob: async () => responses.shift() ?? makeJob('job-1', 'succeeded', 100, 'Transcription ready'),
    onUpdate: (job) => updates.push(job),
    onStatus: (status) => statuses.push(status),
    timers,
    now: () => timers.now,
  });

  poller.start('job-1');
  await flush();
  assertEqual(updates[0].state, 'queued');
  assertEqual(timers.nextDelay(), 1000);

  timers.advance(1000);
  await flush();
  assertEqual(updates.length, 2);
  assertEqual(timers.nextDelay(), 1000);

  timers.advance(29000);
  await flush();
  assertEqual(last(statuses).stillWorking, true);
  assertEqual(timers.nextDelay(), 3000);

  timers.advance(3000);
  await flush();
  assertEqual(updates[3].state, 'running');
  assertEqual(timers.nextDelay(), 1000);

  timers.advance(1000);
  await flush();
  assertEqual(last(updates).state, 'succeeded');
  assertEqual(last(statuses).isPolling, false);
  assertEqual(timers.pendingCount(), 0);
});

await test('backs off on temporary network failures while keeping the last status', async () => {
  const timers = new FakeTimers();
  const updates: TranscriptionJob[] = [];
  const statuses: PollerStatus[] = [];
  let attempts = 0;
  const poller = new TranscriptionPoller({
    fetchJob: async () => {
      attempts += 1;
      if (attempts === 1) {
        return makeJob('job-1', 'running', 25, 'Detecting notes');
      }
      if (attempts < 8) {
        throw new TypeError('temporary network failure');
      }
      return makeJob('job-1', 'running', 26, 'Detecting notes');
    },
    onUpdate: (job) => updates.push(job),
    onStatus: (status) => statuses.push(status),
    timers,
    now: () => timers.now,
  });

  poller.start('job-1');
  await flush();
  assertEqual(last(updates).progress.percent, 25);

  for (const expectedDelay of [1000, 2000, 4000, 8000, 15000, 15000]) {
    timers.advance(timers.nextDelay() ?? 0);
    await flush();
    assertEqual(last(updates).progress.percent, 25);
    assertEqual(last(statuses).networkIssue, true);
    assertEqual(timers.nextDelay(), expectedDelay);
  }

  timers.advance(15000);
  await flush();
  assertEqual(last(updates).progress.percent, 26);
  assertEqual(last(statuses).networkIssue, false);
});

await test('refresh recovery starts from a stored job id and stops on not found or cleanup', async () => {
  const timers = new FakeTimers();
  const terminalErrors: TranscriptionApiError[] = [];
  const abortedSignals: AbortSignal[] = [];
  const poller = new TranscriptionPoller({
    fetchJob: (_jobId, signal) => {
      abortedSignals.push(signal);
      return new Promise(() => undefined);
    },
    onUpdate: () => undefined,
    onTerminalError: (error) => terminalErrors.push(error),
    timers,
    now: () => timers.now,
  });

  poller.start('stored-job-id');
  poller.stop();
  assertEqual(abortedSignals[0].aborted, true);
  assertEqual(timers.pendingCount(), 0);

  const notFoundPoller = new TranscriptionPoller({
    fetchJob: async () => {
      throw new TranscriptionApiError('JOB_NOT_FOUND', 404);
    },
    onUpdate: () => undefined,
    onTerminalError: (error) => terminalErrors.push(error),
    timers,
    now: () => timers.now,
  });

  notFoundPoller.start('expired-or-missing');
  await flush();
  assertEqual(terminalErrors[0].code, 'JOB_NOT_FOUND');
  assertEqual(notFoundPoller.getStatus().isPolling, false);
});

await test('ignores stale same-job responses after restart with terminal initial job', async () => {
  const timers = new FakeTimers();
  const updates: TranscriptionJob[] = [];
  let resolveFirstPoll: (job: TranscriptionJob) => void = () => {
    throw new Error('First poll promise was not created');
  };
  const poller = new TranscriptionPoller({
    fetchJob: () =>
      new Promise<TranscriptionJob>((resolve) => {
        resolveFirstPoll = resolve;
      }),
    onUpdate: (job) => updates.push(job),
    timers,
    now: () => timers.now,
  });

  poller.start('job-1');
  poller.start('job-1', makeJob('job-1', 'cancelled', 100, 'Transcription was cancelled'));
  resolveFirstPoll?.(makeJob('job-1', 'running', 50, 'Detecting notes'));
  await flush();

  assertEqual(updates.length, 0);
  assertEqual(poller.getStatus().isPolling, false);
  assertEqual(timers.pendingCount(), 0);
});

function makeJob(
  jobId: string,
  state: TranscriptionJob['state'],
  percent: number,
  message: string,
): TranscriptionJob {
  return {
    jobId,
    state,
    progress: {
      phase: state === 'succeeded' ? 'complete' : state === 'running' ? 'inferencing' : state,
      percent,
      message,
      updatedAt: '2026-06-13T00:00:00Z',
    },
    error: null,
    result:
      state === 'succeeded'
        ? {
            transcriptUrl: null,
            exports: {},
            noteCount: 8,
            durationSeconds: 0.25,
          }
        : null,
  };
}

async function flush(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

async function test(name: string, run: () => Promise<void>): Promise<void> {
  try {
    await run();
  } catch (error) {
    throw new Error(`${name}: ${error instanceof Error ? error.message : String(error)}`, { cause: error });
  }
}

function last<T>(values: T[]): T {
  return values[values.length - 1];
}

function assertEqual<T>(actual: T, expected: T): void {
  if (actual !== expected) {
    throw new Error(`Expected ${String(expected)}, received ${String(actual)}`);
  }
}
