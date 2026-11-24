const PREVIEW_STATUSES = {
  capturando: { label: 'En directo', tone: 'active' },
  iniciando: { label: 'Preparando', tone: 'neutral' },
  esperando: { label: 'Esperando emisión', tone: 'neutral' },
  reconectando: { label: 'Reconectando', tone: 'neutral' },
  deteniendo: { label: 'Cerrando captura', tone: 'neutral' },
  finalizando: { label: 'Cerrando captura', tone: 'neutral' },
  detenido: { label: 'Captura finalizada', tone: 'neutral' },
  error: { label: 'Error de captura', tone: 'neutral' },
};

export function previewStatus(sessionStatus) {
  return PREVIEW_STATUSES[sessionStatus] || { label: 'Estado no disponible', tone: 'neutral' };
}
