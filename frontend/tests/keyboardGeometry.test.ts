import { getKeyboardGeometry, getKeyboardHeight, getPitchKeyRect } from '../src/keyboardGeometry.js';

const geometry = getKeyboardGeometry(48, 84, 880, 220, 64);

assertEqual(geometry.whiteKeys.length, 22);
assertEqual(geometry.blackKeys.length, 15);

const firstWhite = geometry.whiteKeys[0];
const firstBlack = geometry.blackKeys[0];

assertEqual(firstWhite.pitch, 48);
assertEqual(firstWhite.x, 0);
assertEqual(firstWhite.y, 220);
assertEqual(firstWhite.height, 64);

assertEqual(firstBlack.pitch, 49);
assertEqual(firstBlack.y, 220);
assertOk(firstBlack.height < firstWhite.height, 'black keys should be shorter than white keys');
assertOk(firstBlack.width < firstWhite.width, 'black keys should be narrower than white keys');
assertOk(firstBlack.x > firstWhite.x, 'black key should be inset from previous white key');
assertOk(
  firstBlack.x + firstBlack.width < geometry.whiteKeys[1].x + geometry.whiteKeys[1].width,
  'black key should sit above the gap between neighboring white keys',
);

assertEqual(getPitchKeyRect(48, geometry), firstWhite);
assertEqual(getPitchKeyRect(49, geometry), firstBlack);
assertEqual(getPitchKeyRect(47, geometry), null);

assertEqual(getKeyboardHeight(160), 51.2);
assertEqual(getKeyboardHeight(360), 72);

function assertEqual<T>(actual: T, expected: T): void {
  if (actual !== expected) {
    throw new Error(`Expected ${String(expected)}, received ${String(actual)}`);
  }
}

function assertOk(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}
