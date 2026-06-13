import { isTerminalState, TranscriptionApiError, type TranscriptionJob } from './transcriptionApi.js';

type TimerApi = {
  setTimeout(callback: () => void, ms: number): number;
  clearTimeout(id: number): void;
};

export type PollerStatus = {
  isPolling: boolean;
  networkIssue: boolean;
  stillWorking: boolean;
  nextDelayMs: number | null;
  consecutiveUnchangedMs: number;
};

export type TranscriptionPollerOptions = {
  fetchJob: (jobId: string, signal: AbortSignal) => Promise<TranscriptionJob>;
  onUpdate: (job: TranscriptionJob) => void;
  onTerminalError?: (error: TranscriptionApiError) => void;
  onStatus?: (status: PollerStatus) => void;
  timers?: TimerApi;
  now?: () => number;
};

const ACTIVE_POLL_MS = 1000;
const SLOW_POLL_MS = 3000;
const UNCHANGED_THRESHOLD_MS = 30000;
const BACKOFF_DELAYS_MS = [1000, 2000, 4000, 8000, 15000];

export class TranscriptionPoller {
  private readonly fetchJob: TranscriptionPollerOptions['fetchJob'];
  private readonly onUpdate: TranscriptionPollerOptions['onUpdate'];
  private readonly onTerminalError?: TranscriptionPollerOptions['onTerminalError'];
  private readonly onStatus?: TranscriptionPollerOptions['onStatus'];
  private readonly timers: TimerApi;
  private readonly now: () => number;
  private timerId: number | null = null;
  private abortController: AbortController | null = null;
  private generation = 0;
  private jobId: string | null = null;
  private stopped = true;
  private lastSignature: string | null = null;
  private lastChangeAt = 0;
  private networkFailureCount = 0;
  private status: PollerStatus = {
    isPolling: false,
    networkIssue: false,
    stillWorking: false,
    nextDelayMs: null,
    consecutiveUnchangedMs: 0,
  };

  constructor(options: TranscriptionPollerOptions) {
    this.fetchJob = options.fetchJob;
    this.onUpdate = options.onUpdate;
    this.onTerminalError = options.onTerminalError;
    this.onStatus = options.onStatus;
    this.timers =
      options.timers ??
      ({
        setTimeout: (callback, ms) => window.setTimeout(callback, ms),
        clearTimeout: (id) => window.clearTimeout(id),
      } satisfies TimerApi);
    this.now = options.now ?? (() => Date.now());
  }

  start(jobId: string, initialJob?: TranscriptionJob): void {
    this.stop();
    this.generation += 1;
    this.jobId = jobId;
    this.stopped = false;
    this.lastChangeAt = this.now();
    this.lastSignature = initialJob ? jobSignature(initialJob) : null;
    this.networkFailureCount = 0;
    this.emitStatus({
      isPolling: !initialJob || !isTerminalState(initialJob.state),
      networkIssue: false,
      stillWorking: false,
      nextDelayMs: null,
      consecutiveUnchangedMs: 0,
    });

    if (initialJob && isTerminalState(initialJob.state)) {
      return;
    }
    if (initialJob) {
      this.schedule(ACTIVE_POLL_MS, false, 0);
      return;
    }
    this.pollNow();
  }

  stop(): void {
    this.stopped = true;
    this.jobId = null;
    if (this.timerId !== null) {
      this.timers.clearTimeout(this.timerId);
      this.timerId = null;
    }
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }
    this.emitStatus({
      isPolling: false,
      networkIssue: false,
      stillWorking: false,
      nextDelayMs: null,
      consecutiveUnchangedMs: 0,
    });
  }

  getStatus(): PollerStatus {
    return this.status;
  }

  private async pollNow(): Promise<void> {
    if (this.stopped || !this.jobId) {
      return;
    }
    const abortController = new AbortController();
    this.abortController = abortController;
    const activeJobId = this.jobId;
    const activeGeneration = this.generation;

    try {
      const job = await this.fetchJob(activeJobId, abortController.signal);
      if (this.stopped || activeJobId !== this.jobId || activeGeneration !== this.generation) {
        return;
      }
      this.abortController = null;
      this.networkFailureCount = 0;
      this.onUpdate(job);
      const signature = jobSignature(job);
      if (signature !== this.lastSignature) {
        this.lastSignature = signature;
        this.lastChangeAt = this.now();
      }

      if (isTerminalState(job.state)) {
        this.emitStatus({
          isPolling: false,
          networkIssue: false,
          stillWorking: false,
          nextDelayMs: null,
          consecutiveUnchangedMs: 0,
        });
        return;
      }

      const unchangedMs = this.now() - this.lastChangeAt;
      const nextDelay = unchangedMs >= UNCHANGED_THRESHOLD_MS ? SLOW_POLL_MS : ACTIVE_POLL_MS;
      this.schedule(nextDelay, false, unchangedMs);
    } catch (error) {
      if (
        this.stopped ||
        activeJobId !== this.jobId ||
        activeGeneration !== this.generation ||
        abortController.signal.aborted
      ) {
        return;
      }
      this.abortController = null;
      const apiError = error instanceof TranscriptionApiError ? error : null;
      if (apiError && (apiError.code === 'JOB_NOT_FOUND' || apiError.code === 'JOB_EXPIRED')) {
        this.onTerminalError?.(apiError);
        this.emitStatus({
          isPolling: false,
          networkIssue: false,
          stillWorking: false,
          nextDelayMs: null,
          consecutiveUnchangedMs: 0,
        });
        return;
      }
      const delay = BACKOFF_DELAYS_MS[Math.min(this.networkFailureCount, BACKOFF_DELAYS_MS.length - 1)];
      this.networkFailureCount += 1;
      this.schedule(delay, true, this.now() - this.lastChangeAt);
    }
  }

  private schedule(delayMs: number, networkIssue: boolean, consecutiveUnchangedMs: number): void {
    if (this.stopped) {
      return;
    }
    if (this.timerId !== null) {
      this.timers.clearTimeout(this.timerId);
    }
    this.timerId = this.timers.setTimeout(() => {
      this.timerId = null;
      void this.pollNow();
    }, delayMs);
    this.emitStatus({
      isPolling: true,
      networkIssue,
      stillWorking: !networkIssue && consecutiveUnchangedMs >= UNCHANGED_THRESHOLD_MS,
      nextDelayMs: delayMs,
      consecutiveUnchangedMs,
    });
  }

  private emitStatus(status: PollerStatus): void {
    this.status = status;
    this.onStatus?.(status);
  }
}

function jobSignature(job: TranscriptionJob): string {
  return `${job.state}:${job.progress.phase}:${job.progress.percent}:${job.progress.message}`;
}
