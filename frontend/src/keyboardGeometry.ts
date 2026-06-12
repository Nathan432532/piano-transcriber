export type KeyRect = {
  pitch: number;
  x: number;
  y: number;
  width: number;
  height: number;
};

const WHITE_KEY_CLASSES = new Set([0, 2, 4, 5, 7, 9, 11]);

export function isWhiteKey(pitch: number): boolean {
  return WHITE_KEY_CLASSES.has(pitch % 12);
}

export function getKeyboardHeight(canvasHeight: number): number {
  return Math.min(72, Math.max(44, canvasHeight * 0.22, canvasHeight * 0.32));
}

export function getKeyboardGeometry(
  pitchMin: number,
  pitchMax: number,
  width: number,
  keyboardTop: number,
  keyboardHeight: number,
): { whiteKeys: KeyRect[]; blackKeys: KeyRect[] } {
  const whitePitches = [];
  for (let pitch = pitchMin; pitch <= pitchMax; pitch += 1) {
    if (isWhiteKey(pitch)) {
      whitePitches.push(pitch);
    }
  }

  const whiteWidth = width / whitePitches.length;
  const whiteKeys = whitePitches.map((pitch, index) => ({
    pitch,
    x: index * whiteWidth,
    y: keyboardTop,
    width: whiteWidth,
    height: keyboardHeight,
  }));

  const whiteIndexByPitch = new Map(whitePitches.map((pitch, index) => [pitch, index]));
  const blackWidth = whiteWidth * 0.62;
  const blackHeight = keyboardHeight * 0.62;
  const blackKeys: KeyRect[] = [];

  for (let pitch = pitchMin; pitch <= pitchMax; pitch += 1) {
    if (isWhiteKey(pitch)) {
      continue;
    }

    const previousWhitePitch = findAdjacentWhitePitch(pitch, -1, pitchMin, pitchMax);
    const previousWhiteIndex = previousWhitePitch === null ? null : whiteIndexByPitch.get(previousWhitePitch);
    if (previousWhiteIndex === null || previousWhiteIndex === undefined) {
      continue;
    }

    const boundaryX = (previousWhiteIndex + 1) * whiteWidth;
    blackKeys.push({
      pitch,
      x: boundaryX - blackWidth / 2,
      y: keyboardTop,
      width: blackWidth,
      height: blackHeight,
    });
  }

  return { whiteKeys, blackKeys };
}

export function getPitchKeyRect(
  pitch: number,
  geometry: { whiteKeys: KeyRect[]; blackKeys: KeyRect[] },
): KeyRect | null {
  return geometry.whiteKeys.find((key) => key.pitch === pitch)
    ?? geometry.blackKeys.find((key) => key.pitch === pitch)
    ?? null;
}

function findAdjacentWhitePitch(
  pitch: number,
  direction: -1 | 1,
  pitchMin: number,
  pitchMax: number,
): number | null {
  for (let adjacentPitch = pitch + direction; adjacentPitch >= pitchMin && adjacentPitch <= pitchMax; adjacentPitch += direction) {
    if (isWhiteKey(adjacentPitch)) {
      return adjacentPitch;
    }
  }
  return null;
}
