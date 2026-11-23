import test from 'node:test';
import assert from 'node:assert/strict';
import {
  countLiveQueue, elapsedSince, formatLiveOffset, liveQueueStatus,
  liveWaitReason, orderLiveQueue,
} from '../src/lib/liveProgress.js';

test('live queue counts each processing state without merging pending and active', () => {
  assert.deepEqual(countLiveQueue([
    { status: 'en_cola' }, { status: 'renderizando' },
    { status: 'completado' }, { status: 'error' },
  ]), { pending: 1, processing: 1, completed: 1, errors: 1 });
});

test('live queue is ordered by processing state and actual score priority', () => {
  const ordered = orderLiveQueue([
    { id: 'done', status: 'completado', updated_at: 100 },
    { id: 'low', status: 'en_cola', predicted_score: 20, queued_at: 1 },
    { id: 'active', status: 'renderizando' },
    { id: 'high', status: 'en_cola', predicted_score: 80, queued_at: 2 },
    { id: 'error', status: 'error', updated_at: 200 },
  ]);
  assert.deepEqual(ordered.map((item) => item.id), ['active', 'high', 'low', 'done', 'error']);
});

test('live progress helpers format source offsets and real phase wait durations', () => {
  assert.equal(formatLiveOffset(65), '01:05');
  assert.equal(formatLiveOffset(3665), '01:01:05');
  assert.equal(elapsedSince(100, 125000), 25);
  assert.equal(liveWaitReason('prioridad_de_captura'), 'En pausa para dar prioridad a la captura');
  assert.equal(liveQueueStatus('descartado_por_saturacion'), 'Descartado por saturación');
});
