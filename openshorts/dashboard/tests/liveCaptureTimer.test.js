import assert from 'node:assert/strict';
import test from 'node:test';
import { captureElapsedSeconds, captureTimerStatus, formatCaptureElapsed } from '../src/lib/liveCaptureTimer.js';

test('formats elapsed capture time as hours, minutes and seconds', () => {
  assert.equal(formatCaptureElapsed(0), '00:00:00');
  assert.equal(formatCaptureElapsed(332), '00:05:32');
  assert.equal(formatCaptureElapsed(4509), '01:15:09');
});

test('calculates from Unix seconds and continues through reconnection', () => {
  const reconnecting = { status: 'reconectando', capture_started_at: 100, capture_ended_at: null };
  assert.equal(captureElapsedSeconds(reconnecting, 225_000), 125);
  assert.equal(captureTimerStatus(reconnecting), 'Reconectando');
});

test('freezes at the persisted end timestamp and handles sessions without capture data', () => {
  const finished = { status: 'detenido', capture_started_at: 100,
    capture_ended_at: 120, capture_elapsed_seconds: 20 };
  assert.equal(captureElapsedSeconds(finished, 999_000), 20);
  assert.equal(captureTimerStatus(finished), 'Captura finalizada');

  assert.equal(captureElapsedSeconds({ status: 'error' }, 999_000), 0);
  assert.equal(captureTimerStatus({ status: 'error' }), 'No llegó a iniciarse la captura');
  assert.equal(captureTimerStatus({ status: 'esperando' }), 'Esperando captura');
});
