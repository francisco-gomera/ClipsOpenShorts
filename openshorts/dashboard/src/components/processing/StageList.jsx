import React from 'react';
import StageRow from './StageRow';

const STAGE_KEYS = [
  'download',
  'transcription',
  'clip_selection',
  'cut_and_reframe',
  'hooks',
  'subtitles',
];

export default function StageList({
  stages = {},
  onRetryStage = null,
  isRetrying = false,
}) {
  return (
    <div
      className="divide-y divide-border"
      role="list"
      aria-label="Etapas de procesamiento"
    >
      {STAGE_KEYS.map((key) => {
        const stageData = stages[key] || { name: key, status: 'pending' };
        return (
          <StageRow
            key={key}
            stageKey={key}
            stageData={stageData}
            onRetryStage={onRetryStage}
            isRetrying={isRetrying}
          />
        );
      })}
    </div>
  );
}
