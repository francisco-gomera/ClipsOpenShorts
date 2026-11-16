import React from 'react';
import { Clock, CheckCircle2, Loader2 } from 'lucide-react';

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
    if (mins > 0) return `${mins}m ${secs}s`;
    return `${secs}s`;
  };

  return (
    <div
      className="p-4 rounded-card bg-surface border border-border space-y-3"
      role="region"
      aria-label="Progreso global del procesamiento"
    >
      {/* Header row */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-brand font-semibold uppercase tracking-widest text-text-secondary">
            {isComplete ? 'Procesamiento Completado' : 'Progreso Global'}
          </span>
          {!isComplete && (
            <span className="text-[10px] font-ui px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
              Etapa {Math.min(stageIndex || 1, stageTotal)} de {stageTotal}
            </span>
          )}
        </div>

        {/* ETA / status */}
        <div className="flex items-center gap-1.5 text-xs font-ui shrink-0">
          {hasHistoryEta ? (
            <span className="flex items-center gap-1 text-text-secondary">
              <Clock size={13} className="text-primary shrink-0" aria-hidden="true" />
              <span>ETA: {formatEta(etaSeconds)}</span>
            </span>
          ) : !isComplete ? (
            <span className="text-text-secondary text-[11px] flex items-center gap-1">
              <Loader2 size={11} className="animate-spin text-primary" aria-hidden="true" />
              <span>Calculando ritmo</span>
            </span>
          ) : (
            <span className="flex items-center gap-1 text-success font-semibold">
              <CheckCircle2 size={13} aria-hidden="true" />
              <span>100%</span>
            </span>
          )}
        </div>
      </div>

      {/* Progress bar */}
      <div
        className="relative w-full h-2.5 rounded-full bg-surface-elevated border border-border overflow-hidden"
        role="progressbar"
        aria-valuenow={percent != null ? Math.round(percent) : 0}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-busy={!isComplete}
        aria-label="Progreso general del procesamiento"
      >
        {isComplete ? (
          <div className="h-full bg-success rounded-full transition-all duration-500 w-full" />
        ) : !isIndeterminate ? (
          <div
            className="h-full bg-primary rounded-full transition-all duration-300 relative"
            style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
          >
            <div className="absolute inset-0 bg-white/10 animate-pulse" />
          </div>
        ) : (
          /* Indeterminate: scan animation, no fake percentages */
          <div className="h-full w-2/5 bg-gradient-to-r from-transparent via-primary/60 to-transparent rounded-full animate-indeterminate" />
        )}
      </div>

      {/* Footer label row */}
      <div className="flex items-center justify-between text-[11px] text-text-secondary font-ui">
        <span>
          {currentStageName
            ? `Etapa actual: ${currentStageName}`
            : 'Iniciando canalización...'}
        </span>
        {percent != null && percent > 0 && (
          <span className="font-brand font-semibold text-primary">
            {Math.round(percent)}%
          </span>
        )}
      </div>
    </div>
  );
}
