import test from 'node:test';
import assert from 'node:assert/strict';
import { previewStatus } from '../src/lib/livePreviewStatus.js';

test('maps every capture status to truthful preview copy', () => {
  const expected = {
    capturando: ['En directo', 'active'],
    iniciando: ['Preparando', 'neutral'],
    esperando: ['Esperando emisión', 'neutral'],
    reconectando: ['Reconectando', 'neutral'],
    deteniendo: ['Cerrando captura', 'neutral'],
    finalizando: ['Cerrando captura', 'neutral'],
    detenido: ['Captura finalizada', 'neutral'],
    error: ['Error de captura', 'neutral'],
  };

  for (const [status, [label, tone]] of Object.entries(expected)) {
    assert.deepEqual(previewStatus(status), { label, tone });
  }
  assert.deepEqual(previewStatus('desconocido'), {
    label: 'Estado no disponible', tone: 'neutral',
  });
});
