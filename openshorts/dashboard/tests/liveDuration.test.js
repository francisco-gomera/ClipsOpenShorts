import assert from 'node:assert/strict';
import test from 'node:test';
import { buildLiveCreatePayload, validateLiveDuration } from '../src/lib/liveDuration.js';

test('default LIVE duration values produce the API payload', () => {
  assert.deepEqual(buildLiveCreatePayload(' https://youtube.com/live/example ', '30', '60'), {
    url: 'https://youtube.com/live/example', min_clip_seconds: 30, max_clip_seconds: 60,
  });
});

test('accepts inclusive limits and equal durations', () => {
  for (const [minimum, maximum] of [[10, 30], [60, 60], [120, 240], [10, 240]]) {
    assert.equal(validateLiveDuration(String(minimum), String(maximum)).error, '');
  }
});

test('rejects empty, fractional, out-of-range and reversed values', () => {
  for (const [minimum, maximum] of [['', '60'], ['10.5', '60'], ['9', '60'],
    ['30', '241'], ['61', '60']]) {
    assert.ok(validateLiveDuration(minimum, maximum).error);
    assert.throws(() => buildLiveCreatePayload('https://youtube.com/live/id', minimum, maximum));
  }
});
