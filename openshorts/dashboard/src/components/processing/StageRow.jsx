import React from 'react';
import {
  CheckCircle2,
  Loader2,
  AlertTriangle,
  Clock,
  FastForward,
  RotateCcw,
} from 'lucide-react';

export default function StageRow({
  stageKey,
  stageData = {},
  onRetryStage = null,
  isRetrying = false,
}) {
  const status = stageData.status || 'pending';
  const label = stageData.label || stageKey;
  const percent = stageData.percent;
  const isCompleted = status === 'completed';
  const isRunning = status === 'running';
  const isFailed = status === 'failed';
  const isSkipped = status === 'skipped';
  const isPending = status === 'pending';

  const formatUnits = (units, bytes, speed) => {
    if (bytes && speed) {
      const mb = (bytes / (1024 * 1024)).toFixed(1);
      const mbps = (speed / (1024 * 1024)).toFixed(1);
      return `${mb} MB (${mbps} MB/s)`;
    }
    if (units && units.label === 'seconds' && units.total) {
      return `${Math.round(units.done)}s / ${Math.round(units.total)}s`;
    }
    if (units && units.total) {
      return `${units.done}/${units.total} ${units.label || ''}`;
    }
    return null;
  };

  const unitsText = formatUnits(stageData.units, stageData.bytes, stageData.speed);

  // Colores y bordes según estado
  let containerBg = 'bg-black/10 border-rule/50';
  let badgeIcon = <Clock size={14} className="text-muted/60" />;

  if (isCompleted) {
    containerBg = 'bg-emerald-500/5 border-emerald-500/20';
    badgeIcon = <CheckCircle2 size={15} className="text-emerald-400 shrink-0" />;
  } else if (isRunning) {
    containerBg = 'bg-brass/5 border-brass/40 shadow-sm shadow-brass/5';
    badgeIcon = <Loader2 size={15} className="animate-spin text-brass shrink-0" />;
  } else if (isFailed) {
    containerBg = 'bg-rose-500/10 border-rose-500/30';
    badgeIcon = <AlertTriangle size={15} className="text-rose-400 shrink-0" />;
  } else if (isSkipped) {
    containerBg = 'bg-transparent border-rule/30 opacity-60';
    badgeIcon = <FastForward size={14} className="text-muted/50 shrink-0" />;
  }

  return (
    <div
      className={`p-3 rounded-card border transition-all duration-300 ${containerBg}`}
      data-stage={stageKey}
      data-status={status}
    >
      <div className="flex items-center justify-between gap-2">
        {/* Lado izquierdo: icono y título con tachado en completado */}
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="shrink-0">{badgeIcon}</div>
          <span
            className={`text-xs font-medium font-sans truncate transition-colors ${
              isCompleted
                ? 'line-through text-muted/70'
                : isRunning
                ? 'text-ink font-semibold'
                : isFailed
                ? 'text-rose-300 font-semibold'
                : 'text-ink2'
            }`}
          >
            {label}
          </span>
          {isSkipped && (
            <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-white/5 text-muted border border-rule/40">
              Omitida
            </span>
          )}
        </div>

        {/* Lado derecho: métricas y duración */}
        <div className="flex items-center gap-2 font-mono text-micro text-muted shrink-0">
          {unitsText && isRunning && (
            <span className="text-brass hidden sm:inline">{unitsText}</span>
          )}
          {percent != null && isRunning && (
            <span className="text-brass font-bold">{Math.round(percent)}%</span>
          )}
          {stageData.duration_seconds != null && (
            <span className="opacity-75">{Math.round(stageData.duration_seconds)}s</span>
          )}
        </div>
      </div>

      {/* Barra de progreso de la etapa */}
      {!isSkipped && !isPending && (
        <div
          className="mt-2.5 w-full h-1.5 rounded-full bg-black/20 border border-rule/40 overflow-hidden"
          role="progressbar"
          aria-valuenow={isCompleted ? 100 : percent != null ? Math.round(percent) : 0}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Progreso de ${label}`}
        >
          {isCompleted ? (
            <div className="h-full bg-emerald-500 rounded-full w-full transition-all duration-300" />
          ) : isFailed ? (
            <div className="h-full bg-rose-500 rounded-full w-full" />
          ) : percent != null && percent > 0 ? (
            <div
              className="h-full bg-brass rounded-full transition-all duration-300"
              style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
            />
          ) : (
            <div className="h-full w-1/3 bg-brass/50 rounded-full animate-indeterminate" />
          )}
        </div>
      )}

      {/* Razón de omisión si aplica */}
      {isSkipped && stageData.skipped_reason && (
        <p className="text-[11px] text-muted italic mt-1.5">
          {stageData.skipped_reason}
        </p>
      )}

      {/* Mensaje de error y botón de reintento si la etapa falló */}
      {isFailed && (
        <div className="mt-2.5 pt-2 border-t border-rose-500/20 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <p className="text-xs text-rose-400 font-mono break-words leading-relaxed">
            {stageData.error || 'La etapa falló durante su ejecución.'}
          </p>
          {onRetryStage && (
            <button
              type="button"
              onClick={() => onRetryStage(stageKey)}
              disabled={isRetrying}
              className="btn-primary text-xs py-1.5 px-3 shrink-0 flex items-center justify-center gap-1.5 bg-rose-500/20 text-rose-200 border-rose-500/40 hover:bg-rose-500/30 focus:ring-2 focus:ring-rose-400 focus:outline-none"
            >
              {isRetrying ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <RotateCcw size={12} />
              )}
              <span>Reintentar desde esta etapa</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
