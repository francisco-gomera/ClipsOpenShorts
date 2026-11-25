import test from 'node:test';
import assert from 'node:assert/strict';
import { liveBlockPhaseLabel, summarizeLiveBlocks } from '../src/lib/liveBlocks.js';

test('block summary counts pending, complete and omitted states', () => {
  assert.deepEqual(summarizeLiveBlocks([
    { phase: 'grabando' }, { phase: 'renderizando' }, { phase: 'error' },
    { phase: 'completado' }, { phase: 'omitido' },
  ]), { total: 5, pending: 2, completed: 1 });
});

test('block cards show Spanish labels and a readable fallback', () => {
  assert.equal(liveBlockPhaseLabel('seleccionando'), 'Seleccionando momentos');
  assert.equal(liveBlockPhaseLabel('cruza_hueco'), 'cruza hueco');
});
