import React from 'react';
import {
  CheckCircle2,
  XCircle,
  Loader2,
  Circle,
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

  // Container style per status
  let containerClass = 'py-3';
  let icon;

  if (isCompleted) {
    containerClass += ' bg-primary-soft/50';
    icon = <CheckCircle2 size={15} className="text-success shrink-0" aria-hidden="true" />;
  } else if (isRunning) {
    containerClass += '';
    icon = <Loader2 size={15} className="animate-spin text-primary shrink-0" aria-hidden="true" />;
  } else if (isFailed) {
    containerClass += '';
    icon = <XCircle size={15} className="text-error shrink-0" aria-hidden="true" />;
  } else if (isSkipped) {
    containerClass += ' opacity-50';
    icon = <FastForward size={14} className="text-text-secondary shrink-0" aria-hidden="true" />;
  } else {
    // pending
    icon = <Circle size={14} className="text-text-secondary shrink-0" aria-hidden="true" />;
  }

  return (
    <div
      className={containerClass}
      role="listitem"
      data-stage={stageKey}
      data-status={status}
      aria-label={`Etapa: ${label}, estado: ${status}`}
    >
      <div className="flex items-center justify-between gap-2 px-1">
        {/* Left: icon + label */}
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="shrink-0">{icon}</div>
          <span
            className={`text-sm font-ui transition-colors truncate ${
              isCompleted
                ? 'line-through text-text-secondary'
                : isRunning
                ? 'text-text-primary font-semibold'
                : isFailed
                ? 'text-error font-semibold'
                : 'text-text-secondary'
            }`}
          >
            {label}
          </span>
          {isSkipped && (
            <span className="text-[10px] font-ui uppercase px-1.5 py-0.5 rounded bg-surface-elevated text-text-secondary border border-border">
              Omitida
            </span>
          )}
        </div>

        {/* Right: metrics / duration */}
        <div className="flex items-center gap-2 font-ui text-[11px] text-text-secondary shrink-0">
          {unitsText && isRunning && (
            <span className="text-primary hidden sm:inline">{unitsText}</span>
          )}
          {percent != null && isRunning && (
            <span className="text-primary font-bold font-brand">{Math.round(percent)}%</span>
          )}
          {stageData.duration_seconds != null && (
            <span className="opacity-70">{Math.round(stageData.duration_seconds)}s</span>
          )}
        </div>
      </div>

      {/* Stage progress bar */}
      {!isSkipped && !isPending && (
        <div
          className="mt-2.5 mx-1 w-auto h-1.5 rounded-full bg-surface-elevated overflow-hidden"
          role="progressbar"
          aria-valuenow={isCompleted ? 100 : percent != null ? Math.round(percent) : 0}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Progreso de ${label}`}
        >
          {isCompleted ? (
            <div className="h-full bg-success rounded-full w-full transition-all duration-300" />
          ) : isFailed ? (
            <div className="h-full bg-error rounded-full w-full" />
          ) : percent != null && percent > 0 ? (
            <div
              className="h-full bg-primary rounded-full transition-all duration-300"
              style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
            />
          ) : (
            <div className="h-full w-1/3 bg-primary/50 rounded-full animate-indeterminate" />
          )}
        </div>
      )}

      {/* Skipped reason */}
      {isSkipped && stageData.skipped_reason && (
        <p className="text-[11px] text-text-secondary italic mt-1.5 px-1">
          {stageData.skipped_reason}
        </p>
      )}

      {/* Failed: error message + retry button */}
      {isFailed && (
        <div className="mt-2.5 pt-2 border-t border-error/20 mx-1 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <p className="text-xs text-error font-ui break-words leading-relaxed">
            {stageData.error || 'La etapa falló durante su ejecución.'}
          </p>
          {onRetryStage && (
            <button
              type="button"
              onClick={() => onRetryStage(stageKey)}
              disabled={isRetrying}
              className="inline-flex items-center justify-center gap-1.5 text-xs font-ui py-1.5 px-3 shrink-0
                bg-error/10 text-error border border-error rounded-btn
                hover:bg-error/20 transition-colors
                focus:outline-none focus:ring-2 focus:ring-error/50
                disabled:opacity-50 disabled:cursor-not-allowed"
              aria-label={`Reintentar desde la etapa ${label}`}
            >
              {isRetrying ? (
                <Loader2 size={12} className="animate-spin" aria-hidden="true" />
              ) : (
                <RotateCcw size={12} aria-hidden="true" />
              )}
              <span>Reintentar desde esta etapa</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
