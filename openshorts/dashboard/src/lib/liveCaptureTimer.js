export function captureElapsedSeconds(session, nowMs = Date.now()) {
  const startedAt = Number(session?.capture_started_at);
  if (!Number.isFinite(startedAt) || startedAt <= 0) return 0;

  const persistedEnd = session?.capture_ended_at;
  const endedAt = persistedEnd == null ? Number(nowMs) / 1000 : Number(persistedEnd);
  if (!Number.isFinite(endedAt)) return 0;
  return Math.max(0, Math.floor(endedAt - startedAt));
}

export function formatCaptureElapsed(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  return [hours, minutes, remainder].map((value) => String(value).padStart(2, '0')).join(':');
}

export function captureTimerStatus(session) {
  if (!session?.capture_started_at) {
    return ['detenido', 'error'].includes(session?.status)
      ? 'No llegó a iniciarse la captura'
      : 'Esperando captura';
  }
  if (session.capture_ended_at != null) return 'Captura finalizada';
  if (session.status === 'reconectando') return 'Reconectando';
  if (session.status === 'deteniendo' || session.status === 'finalizando') return 'Finalizando captura';
  if (session.status === 'esperando') return 'Esperando emisión';
  if (session.status === 'error') return 'Cerrando captura';
  return 'Capturando';
}
