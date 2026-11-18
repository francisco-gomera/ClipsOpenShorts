import React from 'react';
import ProcessingPanel from './processing/ProcessingPanel';

export default function StageProgress({
  stagesData,
  logs = [],
  onRetry = null,
  onRetryStage = null,
  onCancelJob = null,
  isRetrying = false,
  isCancelling = false,
  status = 'processing',
}) {
  if (!stagesData || !stagesData.stages) return null;

  return (
    <ProcessingPanel
      stagesData={stagesData}
      logs={logs}
      onRetryStage={onRetryStage || onRetry}
      onCancelJob={onCancelJob}
      isRetrying={isRetrying}
      isCancelling={isCancelling}
      status={status}
    />
  );
}
