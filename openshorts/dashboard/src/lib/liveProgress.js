export const LIVE_STATUS_LABELS = {
  iniciando: 'Iniciando',
  esperando: 'Esperando transmisión',
  capturando: 'Capturando',
  reconectando: 'Reconectando',
  deteniendo: 'Deteniendo',
  finalizando: 'Finalizando clips pendientes',
  detenido_por_disco: 'Captura detenida por espacio en disco',
  detenido: 'Detenido',
  error: 'Error',
};

export const LIVE_PHASE_LABELS = {
  preparando_ventana: 'Preparando el fragmento original',
  cortando_fragmento: 'Cortando el fragmento',
  adaptando_vertical: 'Adaptando a formato vertical',
  analizando_encuadre: 'Analizando encuadre y composición',
  ajustando_hook: 'Ajustando el hook al encuadre',
  generando_hook: 'Generando el hook',
  generando_subtitulos: 'Generando subtítulos',
  generando_hook_y_subtitulos: 'Generando hook y subtítulos',
  verificando_archivo: 'Verificando archivo y duración',
  generando_srt: 'Generando archivo SRT',
  finalizado: 'Finalizado',
  error: 'Error',
};

export function countLiveQueue(queue = []) {
  return queue.reduce((counts, item) => {
    if (item.status === 'en_cola') counts.pending += 1;
    else if (item.status === 'renderizando') counts.processing += 1;
    else if (item.status === 'completado') counts.completed += 1;
    else if (item.status === 'error') counts.errors += 1;
    return counts;
  }, { pending: 0, processing: 0, completed: 0, errors: 0 });
}

const queueRank = (status) => ({
  renderizando: 0,
  evaluando: 0,
  detectado: 0,
  en_cola: 1,
  completado: 2,
  error: 3,
  descartado_por_saturacion: 3,
  cancelado: 4,
}[status] ?? 5);

export function orderLiveQueue(queue = []) {
  return [...queue].sort((left, right) => {
    const rank = queueRank(left.status) - queueRank(right.status);
    if (rank) return rank;
    if (left.status === 'en_cola') {
      const scoreOrder = Number(right.predicted_score || 0) - Number(left.predicted_score || 0);
      return scoreOrder || Number(left.queued_at || 0) - Number(right.queued_at || 0);
    }
    return Number(right.updated_at || 0) - Number(left.updated_at || 0);
  });
}

export function formatLiveOffset(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  const values = hours > 0 ? [hours, minutes, remainder] : [minutes, remainder];
  return values.map((value) => String(value).padStart(2, '0')).join(':');
}

export function elapsedSince(timestamp, nowMs = Date.now()) {
  const started = Number(timestamp);
  if (!Number.isFinite(started) || started <= 0) return 0;
  return Math.max(0, Math.floor(nowMs / 1000 - started));
}

export function liveWaitReason(reason) {
  return ({
    otro_clip_en_procesamiento: 'En espera mientras se procesa otro clip',
    esperando_capacidad: 'Esperando capacidad de procesamiento',
    prioridad_de_captura: 'En pausa para dar prioridad a la captura',
  })[reason] || 'Esperando turno';
}

export function liveQueueStatus(status) {
  return ({
    detectado: 'Detectado',
    evaluando: 'Evaluando momento',
    en_cola: 'En cola',
    renderizando: 'Procesándose',
    completado: 'Completado',
    error: 'Error',
    descartado_por_saturacion: 'Descartado por saturación',
    cancelado: 'Cancelado',
  })[status] || 'Estado no disponible';
}
