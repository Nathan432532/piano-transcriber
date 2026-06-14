// correctionFlow.test.ts — Unit tests for correction flow logic

type TestFunction = () => void | Promise<void>;

const registeredTests: Array<{
  name: string;
  fn: TestFunction;
}> = [];

let currentSuite = '';

const test = (name: string, fn: TestFunction) => {
  registeredTests.push({
    name: currentSuite ? `${currentSuite} — ${name}` : name,
    fn,
  });
};

const it = test;

const describe = (name: string, fn: () => void) => {
  const previousSuite = currentSuite;
  currentSuite = previousSuite ? `${previousSuite} / ${name}` : name;

  try {
    fn();
  } finally {
    currentSuite = previousSuite;
  }
};

const assertEqual = <T>(actual: T, expected: T, message?: string) => {
  if (actual !== expected) {
    throw new Error(message || `Expected ${expected}, got ${actual}`);
  }
};

const assertOk = (value: unknown, message?: string) => {
  if (!value) {
    throw new Error(message || `Expected truthy value, got ${value}`);
  }
};

const assertThrows = (fn: () => unknown, message?: string) => {
  let didThrow = false;

  try {
    fn();
  } catch {
    didThrow = true;
  }

  if (!didThrow) {
    throw new Error(message || 'Expected function to throw');
  }
};

const assertRejects = async (
  fn: () => Promise<unknown>,
  message?: string,
) => {
  let didReject = false;

  try {
    await fn();
  } catch {
    didReject = true;
  }

  if (!didReject) {
    throw new Error(message || 'Expected promise to reject');
  }
};

import {
  selectTranscriptUrl,
  validateCorrectionNote,
  buildCorrectionPayload,
  updateJobAfterSave,
  getBaseRevision,
  orchestrateSaveAndReload,
  orchestrateRetryReload,
  PITCH_MIN,
  PITCH_MAX,
  VELOCITY_MIN,
  VELOCITY_MAX,
} from '../src/correctionFlow.js';

// --- Mock Data ---

const mockJobWithCorrection = {
  jobId: 'job-123',
  state: 'succeeded' as const,
  progress: {
    phase: 'complete' as const,
    percent: 100,
    message: 'Complete',
    updatedAt: new Date().toISOString(),
  },
  result: {
    transcriptUrl: 'original-transcript.json',
    exports: {},
    correction: {
      revision: 1,
      exports: {
        transcript: 'corrected-r1.json',
        midi: 'corrected-r1.mid',
      },
    },
  },
};

const mockJobWithoutCorrection = {
  jobId: 'job-123',
  state: 'succeeded' as const,
  progress: {
    phase: 'complete' as const,
    percent: 100,
    message: 'Complete',
    updatedAt: new Date().toISOString(),
  },
  result: {
    transcriptUrl: 'original-transcript.json',
    exports: {},
  },
};

const mockCorrectionResponse = {
  revision: 2,
  exports: {
    transcript: 'corrected-r2.json',
    midi: 'corrected-r2.mid',
  },
} as const;

const validNoteDraft = {
  pitch: 60,
  startTime: 1.0,
  endTime: 2.0,
  velocity: 100,
  confidence: 0.9,
  hand: "unknown" as const,
};

const invalidNoteDraft = {
  pitch: 150, // Outside range
  startTime: -1.0, // Negative
  endTime: 0.5, // Less than startTime
  velocity: 200, // Outside range
  confidence: 1.5, // Outside range
  hand: "unknown" as const,
};

// --- Tests ---

describe('selectTranscriptUrl', () => {
  it('prefers corrected transcript when available', () => {
    const url = selectTranscriptUrl(mockJobWithCorrection);
    assertEqual(url, 'corrected-r1.json');
  });

  it('falls back to original transcript when no correction exists', () => {
    const url = selectTranscriptUrl(mockJobWithoutCorrection);
    assertEqual(url, 'original-transcript.json');
  });

  it('returns null when job or result is missing', () => {
    assertEqual(selectTranscriptUrl(null), null);
    assertEqual(selectTranscriptUrl({ jobId: 'job-123' } as any), null);
  });
});

describe('validateCorrectionNote', () => {
  it('accepts valid notes', () => {
    validateCorrectionNote(validNoteDraft);
  });

  it('rejects invalid pitch', () => {
    assertThrows(() => validateCorrectionNote({ ...validNoteDraft, pitch: PITCH_MIN - 1 }));
    assertThrows(() => validateCorrectionNote({ ...validNoteDraft, pitch: PITCH_MAX + 1 }));
  });

  it('rejects invalid times', () => {
    assertThrows(() => validateCorrectionNote({ ...validNoteDraft, startTime: -0.1 }));
    assertThrows(() => validateCorrectionNote({ ...validNoteDraft, endTime: 0.5 })); // endTime <= startTime
  });

  it('rejects invalid velocity', () => {
    assertThrows(() => validateCorrectionNote({ ...validNoteDraft, velocity: VELOCITY_MIN - 1 }));
    assertThrows(() => validateCorrectionNote({ ...validNoteDraft, velocity: VELOCITY_MAX + 1 }));
  });

  it('rejects invalid confidence', () => {
    assertThrows(() => validateCorrectionNote({ ...validNoteDraft, confidence: -0.1 }));
    assertThrows(() => validateCorrectionNote({ ...validNoteDraft, confidence: 1.1 }));
    assertThrows(() => validateCorrectionNote({ ...validNoteDraft, confidence: NaN }));
    assertThrows(() => validateCorrectionNote({ ...validNoteDraft, confidence: Infinity }));
  });

  it('rejects missing confidence', () => {
    const { confidence, ...noteWithoutConfidence } = validNoteDraft;
    assertThrows(() => validateCorrectionNote(noteWithoutConfidence as any));
  });

  it('rejects non-unknown hand', () => {
    assertThrows(() => validateCorrectionNote({ ...validNoteDraft, hand: "left" }));
  });

  it('rejects times beyond duration', () => {
    assertThrows(() => validateCorrectionNote(validNoteDraft, 1.5)); // endTime=2.0 > duration=1.5
  });
});

describe('buildCorrectionPayload', () => {
  it('builds valid payload from notes', () => {
    const payload = buildCorrectionPayload(1, [{
      pitch: 60,
      startTime: 1.0,
      endTime: 2.0,
      velocity: 100,
      confidence: 0.9,
      hand: "unknown",
    }]);
    assertEqual(payload.baseRevision, 1);
    assertEqual(payload.notes.length, 1);
    assertEqual(payload.notes[0].pitch, 60);
    assertEqual(payload.notes[0].confidence, 0.9);
    assertEqual(payload.notes[0].hand, "unknown");
  });

  it('requires confidence and hand', () => {
    assertThrows(() => buildCorrectionPayload(1, [{
      pitch: 60,
      startTime: 1.0,
      endTime: 2.0,
      velocity: 100,
      // missing confidence and hand
    } as any]));
  });

  it('accepts baseRevision 0', () => {
    const payload = buildCorrectionPayload(0, [{
      pitch: 60,
      startTime: 1.0,
      endTime: 2.0,
      velocity: 100,
      confidence: 0.9,
      hand: "unknown",
    }]);
    assertEqual(payload.baseRevision, 0);
  });

  it('accepts positive baseRevision', () => {
    const payload = buildCorrectionPayload(5, [{
      pitch: 60,
      startTime: 1.0,
      endTime: 2.0,
      velocity: 100,
      confidence: 0.9,
      hand: "unknown",
    }]);
    assertEqual(payload.baseRevision, 5);
  });

  it('rejects negative baseRevision', () => {
    assertThrows(() => buildCorrectionPayload(-1, [{
      pitch: 60,
      startTime: 1.0,
      endTime: 2.0,
      velocity: 100,
      confidence: 0.9,
      hand: "unknown",
    }]));
  });

  it('rejects non-integer baseRevision', () => {
    assertThrows(() => buildCorrectionPayload(1.5, [{
      pitch: 60,
      startTime: 1.0,
      endTime: 2.0,
      velocity: 100,
      confidence: 0.9,
      hand: "unknown",
    }]));
  });

  it('rejects NaN baseRevision', () => {
    assertThrows(() => buildCorrectionPayload(NaN, [{
      pitch: 60,
      startTime: 1.0,
      endTime: 2.0,
      velocity: 100,
      confidence: 0.9,
      hand: "unknown",
    }]));
  });
});

describe('updateJobAfterSave', () => {
  it('updates job with new correction data', () => {
    const updatedJob = updateJobAfterSave(mockJobWithoutCorrection, mockCorrectionResponse);
    assertEqual(updatedJob?.result?.correction?.revision, 2);
    assertEqual(updatedJob?.result?.correction?.exports.transcript, 'corrected-r2.json');
  });

  it('preserves existing job fields', () => {
    const updatedJob = updateJobAfterSave(mockJobWithCorrection, mockCorrectionResponse);
    assertEqual(updatedJob?.jobId, 'job-123');
  });

  it('returns null for null input', () => {
    assertEqual(updateJobAfterSave(null, mockCorrectionResponse), null);
  });
});

describe('getBaseRevision', () => {
  it('returns 0 when no correction exists', () => {
    assertEqual(getBaseRevision(mockJobWithoutCorrection), 0);
  });

  it('returns the correction revision when available', () => {
    assertEqual(getBaseRevision(mockJobWithCorrection), 1);
  });

  it('returns 0 for null job', () => {
    assertEqual(getBaseRevision(null), 0);
  });

  it('throws for invalid revision', () => {
    assertThrows(() => getBaseRevision({
      result: { correction: { revision: -1 } },
    } as any));
  });
});

describe('assertThrows', () => {
  it('fails when the tested function does not throw', () => {
    let assertionFailed = false;

    try {
      assertThrows(() => undefined);
    } catch {
      assertionFailed = true;
    }

    assertEqual(assertionFailed, true);
  });
});

describe('orchestrateSaveAndReload', () => {
  it('calls save and reload with correct args', async () => {
    let saveCalledWith: any = null;
    let reloadCalledWith: any = null;
    const mockSave = async (payload: any) => {
      saveCalledWith = payload;
      return mockCorrectionResponse;
    };
    const mockReload = async (url: string) => {
      reloadCalledWith = url;
    };

    const result = await orchestrateSaveAndReload(
      mockSave,
      mockReload,
      1,
      [{
        pitch: 60,
        startTime: 1.0,
        endTime: 2.0,
        velocity: 100,
        confidence: 0.9,
        hand: "unknown",
      }],
      3.0,
    );

    assertEqual(saveCalledWith.baseRevision, 1);
    assertEqual(saveCalledWith.notes[0].pitch, 60);
    assertEqual(reloadCalledWith, mockCorrectionResponse.exports.transcript);
    assertEqual(result.success, true);
  });

  it('handles reload failure', async () => {
    const mockSave = async () => mockCorrectionResponse;
    const mockReload = async () => { throw new Error('Reload failed'); };

    const result = await orchestrateSaveAndReload(
      mockSave,
      mockReload,
      1,
      [{
        pitch: 60,
        startTime: 1.0,
        endTime: 2.0,
        velocity: 100,
        confidence: 0.9,
        hand: "unknown",
      }],
    );

    assertEqual(result.success, false);
    assertEqual((result.reloadError as Error).message, 'Reload failed');
  });

  it('rejects invalid notes', async () => {
    const mockSave = async () => mockCorrectionResponse;
    const mockReload = async () => {};

    await assertRejects(async () => {
      await orchestrateSaveAndReload(
        mockSave,
        mockReload,
        1,
        [{
          pitch: 10, // Invalid: below PITCH_MIN=21
          startTime: 1.0,
          endTime: 2.0,
          velocity: 100,
          confidence: 0.9,
          hand: "unknown",
        }],
      );
    });
  });
});

describe('orchestrateRetryReload', () => {
  it('emits reloading then success and clears the pending url', async () => {
    const exactUrl = 'https://example.test/transcript.json';
    const events: string[] = [];

    await orchestrateRetryReload(
      exactUrl,
      async (url) => {
        events.push(`reload:${url}`);
        await Promise.resolve();
      },
      (status) => {
        events.push(`status:${status}`);
      },
      (url) => {
        events.push(`pending:${url}`);
      },
    );

    assertEqual(events.length, 4);
    assertEqual(events[0], 'status:reloading');
    assertEqual(events[1], `reload:${exactUrl}`);
    assertEqual(events[2], 'status:success');
    assertEqual(events[3], 'pending:null');
  });

  it('emits reloading then error and preserves the exact pending url', async () => {
    const exactUrl = 'https://example.test/transcript.json?retry=1';
    const exactError = new Error('Reload failed');
    const events: string[] = [];
    let receivedError: unknown = null;

    await orchestrateRetryReload(
      exactUrl,
      async (url) => {
        events.push(`reload:${url}`);
        await Promise.resolve();
        throw exactError;
      },
      (status) => {
        events.push(`status:${status}`);
      },
      (url) => {
        events.push(`pending:${url}`);
      },
      (error) => {
        receivedError = error;
      },
    );

    assertEqual(events.length, 4);
    assertEqual(events[0], 'status:reloading');
    assertEqual(events[1], `reload:${exactUrl}`);
    assertEqual(events[2], 'status:error');
    assertEqual(events[3], `pending:${exactUrl}`);
    assertEqual(receivedError, exactError);
  });
});

const runTests = async () => {
  for (const registeredTest of registeredTests) {
    try {
      await registeredTest.fn();
      console.log(`✓ ${registeredTest.name}`);
    } catch (error) {
      console.error(`✗ ${registeredTest.name}`);
      throw error;
    }
  }
};

await runTests();
