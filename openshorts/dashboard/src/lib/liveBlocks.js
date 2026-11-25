export const LIVE_BLOCK_PHASE_LABELS = {
  grabando: 'Grabando',
  cerrado: 'Cerrado',
  en_cola: 'En cola',
  transcribiendo: 'Transcribiendo',
  seleccionando: 'Seleccionando momentos',
  renderizando: 'Renderizando',
  completado: 'Completado',
  error: 'Error',
  omitido: 'Omitido',
};

const PENDING_PHASES = new Set(['cerrado', 'en_cola', 'transcribiendo', 'seleccionando', 'renderizando', 'error']);

export function summarizeLiveBlocks(blocks = []) {
  return {
    total: blocks.length,
    pending: blocks.filter((block) => PENDING_PHASES.has(block.phase)).length,
    completed: blocks.filter((block) => block.phase === 'completado').length,
  };
}

export function liveBlockPhaseLabel(phase) {
  return LIVE_BLOCK_PHASE_LABELS[phase] || String(phase || 'Estado desconocido').replaceAll('_', ' ');
}
