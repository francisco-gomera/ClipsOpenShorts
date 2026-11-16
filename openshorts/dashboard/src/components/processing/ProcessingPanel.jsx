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
    <div
      className="w-full space-y-4 animate-fade font-ui"
      aria-live="polite"
      aria-label="Panel de procesamiento"
    >
      {/* Recovery banner — rate limit or Gemini wait */}
      {recovery && recovery.state !== 'normal' && (
        <RecoveryBanner recovery={recovery} />
      )}

      {/* Global progress */}
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

      {/* Stage list */}
      <div
        className="p-4 rounded-card bg-surface border border-border space-y-3"
        role="region"
        aria-label="Etapas del proceso"
      >
        <h4 className="text-xs font-brand font-semibold uppercase tracking-widest text-text-secondary">
          Etapas del Proceso
        </h4>
        <StageList
          stages={stages}
          onRetryStage={onRetryStage}
          isRetrying={isRetrying}
        />
      </div>

      {/* Clip progress cards */}
      {clips.length > 0 && (
        <div
          className="p-4 rounded-card bg-surface border border-border space-y-3"
          role="region"
          aria-label="Generación de clips"
        >
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-brand font-semibold uppercase tracking-widest text-text-secondary">
              Generación de Clips
            </h4>
            <span className="text-xs font-ui text-text-secondary">
              <strong className="text-success">{counters.ready || 0}</strong>
              {' '}de {counters.total || clips.length} listos
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

      {/* Collapsible technical logs */}
      <CollapsibleLogs logs={logs} defaultOpen={false} />
    </div>
  );
}
