import React from 'react';
import ProcessingPanel from './processing/ProcessingPanel';

export default function StageProgress({
  stagesData,
  logs = [],
  onRetry = null,
  onRetryStage = null,
  isRetrying = false,
  status = 'processing',
}) {
  if (!stagesData || !stagesData.stages) return null;

  return (
    <ProcessingPanel
      stagesData={stagesData}
      logs={logs}
      onRetryStage={onRetryStage || onRetry}
      isRetrying={isRetrying}
      status={status}
    />
  );
}
