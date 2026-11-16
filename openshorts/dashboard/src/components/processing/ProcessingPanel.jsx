import React from 'react';
import GlobalProgress from './GlobalProgress';
import StageList from './StageList';
import ClipProgressCard from './ClipProgressCard';
import RecoveryBanner from './RecoveryBanner';
import CollapsibleLogs from './CollapsibleLogs';

export default function ProcessingPanel({
  stagesData = {},
  logs = [],
  onRetryStage = null,
  isRetrying = false,
  status = 'processing',
}) {
  const stages = stagesData.stages || {};
  const currentStage = stagesData.current_stage || '';
  const currentStageLabel = stages[currentStage]?.label || currentStage;
  const clips = stagesData.clips || [];
  const counters = stagesData.counters || { total: 0, ready: 0, failed: 0 };
  const recovery = stagesData.recovery || { state: 'normal' };

  return (
    <div className="w-full space-y-4 font-sans animate-fade-in" aria-live="polite">
      {/* Banner de recuperación si hay rate limits u operaciones de retry */}
      {recovery && recovery.state !== 'normal' && (
        <RecoveryBanner recovery={recovery} />
      )}

      {/* Progreso Global de la canalización */}
      <GlobalProgress
        percent={stagesData.percent}
        mode={stagesData.mode || 'indeterminate'}
        etaSeconds={stagesData.eta_seconds}
        etaConfidence={stagesData.eta_confidence || 'none'}
        stageIndex={stagesData.stage_index || 1}
        stageTotal={stagesData.stage_total || 6}
        currentStageName={currentStageLabel}
        status={stagesData.status || status}
      />

      {/* Lista ordenada de las 6 etapas con barras individuales y check verde */}
      <div className="p-4 rounded-card bg-paper border border-rule space-y-3">
        <h4 className="text-xs font-mono uppercase tracking-wider text-muted">
          Etapas del Proceso
        </h4>
        <StageList
          stages={stages}
          onRetryStage={onRetryStage}
          isRetrying={isRetrying}
        />
      </div>

      {/* Progreso incremental de clips si están en curso */}
      {clips.length > 0 && (
        <div className="p-4 rounded-card bg-paper border border-rule space-y-3">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-mono uppercase tracking-wider text-muted">
              Generación de Clips
            </h4>
            <span className="text-xs font-mono text-ink2">
              <strong className="text-emerald-400">{counters.ready || 0}</strong> de {counters.total || clips.length} listos
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
            {clips.map((clip, idx) => (
              <ClipProgressCard
                key={clip.index != null ? clip.index : idx}
                clip={clip}
                clipNumber={idx + 1}
              />
            ))}
          </div>
        </div>
      )}

      {/* Terminal secundario plegable de logs técnicos */}
      <CollapsibleLogs logs={logs} defaultOpen={false} />
    </div>
  );
}
