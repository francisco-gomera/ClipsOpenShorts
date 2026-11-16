import React from 'react';
import { Clock, CheckCircle2, Loader2, Sparkles } from 'lucide-react';

export default function GlobalProgress({
  percent,
  mode = 'indeterminate',
  etaSeconds = null,
  etaConfidence = 'none',
  stageIndex = 0,
  stageTotal = 6,
  currentStageName = '',
  status = 'processing',
}) {
  const isComplete = status === 'completed' || percent === 100;
  const isIndeterminate = mode === 'indeterminate' || percent == null || percent <= 0;
  const hasHistoryEta = etaConfidence === 'history' && etaSeconds !== null && etaSeconds > 0;

  const formatEta = (seconds) => {
    if (!seconds || seconds <= 0) return null;
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    if (mins > 0) {
      return `${mins}m ${secs}s`;
    }
    return `${secs}s`;
  };

  return (
    <div className="p-4 rounded-card bg-paper border border-rule space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono uppercase tracking-wider text-muted">
            {isComplete ? 'Procesamiento Completado' : 'Progreso Global'}
          </span>
          {!isComplete && (
            <span className="text-micro font-mono px-2 py-0.5 rounded-full bg-brass/10 text-brass border border-brass/20">
              Etapa {Math.min(stageIndex || 1, stageTotal)} de {stageTotal}
            </span>
          )}
        </div>

        {/* ETA o Estado */}
        <div className="flex items-center gap-1.5 text-xs font-mono">
          {hasHistoryEta ? (
            <span className="flex items-center gap-1 text-ink2">
              <Clock size={13} className="text-brass shrink-0" />
              <span>ETA: {formatEta(etaSeconds)}</span>
            </span>
          ) : !isComplete ? (
            <span className="text-muted text-[11px] flex items-center gap-1">
              <Loader2 size={11} className="animate-spin text-brass" />
              <span>Calculando ritmo</span>
            </span>
          ) : (
            <span className="flex items-center gap-1 text-emerald-400 font-medium">
              <CheckCircle2 size={13} />
              <span>100%</span>
            </span>
          )}
        </div>
      </div>

      {/* Barra de progreso global */}
      <div
        className="relative w-full h-2.5 rounded-full bg-black/20 border border-rule overflow-hidden"
        role="progressbar"
        aria-valuenow={percent != null ? Math.round(percent) : 0}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-busy={!isComplete}
        aria-label="Progreso general del procesamiento"
      >
        {isComplete ? (
          <div className="h-full bg-emerald-500 rounded-full transition-all duration-500 w-full" />
        ) : !isIndeterminate ? (
          <div
            className="h-full bg-gradient-to-r from-brass/80 to-brass rounded-full transition-all duration-300 relative"
            style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
          >
            <div className="absolute inset-0 bg-white/20 animate-pulse" />
          </div>
        ) : (
          /* Modo indeterminado: animación de escaneo continuo sin porcentajes ficticios */
          <div className="h-full w-2/5 bg-gradient-to-r from-transparent via-brass/60 to-transparent rounded-full animate-indeterminate" />
        )}
      </div>

      {/* Mensaje descriptivo inferior */}
      <div className="flex items-center justify-between text-micro text-muted font-mono">
        <span>
          {currentStageName ? `Etapa actual: ${currentStageName}` : 'Iniciando canalización...'}
        </span>
        {percent != null && percent > 0 && <span>{Math.round(percent)}%</span>}
      </div>
    </div>
  );
}
