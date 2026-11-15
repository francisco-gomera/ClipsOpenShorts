import React from 'react';
import { CheckCircle2, Loader2, AlertTriangle, Clock, FastForward } from 'lucide-react';

const STAGE_ORDER = [
  { key: 'download', label: 'Source' },
  { key: 'transcription', label: 'Transcript' },
  { key: 'clip_selection', label: 'AI Selection' },
  { key: 'cut_and_reframe', label: 'Reframe' },
  { key: 'hooks', label: 'Hooks' },
  { key: 'subtitles', label: 'Subtitles' },
];

export default function StageProgress({ stagesData, onRetry, isRetrying }) {
  if (!stagesData || !stagesData.stages) return null;
  const stages = stagesData.stages;

  return (
    <div className="my-3 p-3.5 rounded-card bg-paper border border-rule space-y-2.5">
      <div className="flex items-center justify-between">
        <span className="text-micro font-mono uppercase tracking-wider text-muted">Pipeline Progress</span>
        {stagesData.current_stage && stagesData.status === 'processing' && (
          <span className="text-micro font-mono text-brass flex items-center gap-1">
            <Loader2 size={11} className="animate-spin" />
            {stages[stagesData.current_stage]?.label || stagesData.current_stage}
          </span>
        )}
      </div>

      {/* Grid of stages */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {STAGE_ORDER.map(({ key, label }) => {
          const st = stages[key] || { status: 'pending' };
          const status = st.status;

          let badgeColor = 'text-muted/60 border-rule/50 bg-black/10';
          let icon = <Clock size={12} className="opacity-40" />;

          if (status === 'completed') {
            badgeColor = 'text-emerald-400 border-emerald-500/20 bg-emerald-500/5';
            icon = <CheckCircle2 size={12} className="text-emerald-400 shrink-0" />;
          } else if (status === 'running') {
            badgeColor = 'text-sky-400 border-sky-500/30 bg-sky-500/10 shadow-sm shadow-sky-500/10';
            icon = <Loader2 size={12} className="animate-spin text-sky-400 shrink-0" />;
          } else if (status === 'failed') {
            badgeColor = 'text-rose-400 border-rose-500/30 bg-rose-500/10';
            icon = <AlertTriangle size={12} className="text-rose-400 shrink-0" />;
          } else if (status === 'skipped') {
            badgeColor = 'text-muted/40 border-rule/30 bg-transparent';
            icon = <FastForward size={12} className="opacity-40 shrink-0" />;
          }

          return (
            <div
              key={key}
              className={`flex items-center justify-between px-2.5 py-1.5 rounded border text-xs transition-colors ${badgeColor}`}
            >
              <div className="flex items-center gap-1.5 min-w-0">
                {icon}
                <span className="truncate font-medium">{label}</span>
              </div>
              {st.duration_seconds ? (
                <span className="text-[10px] font-mono opacity-70 ml-1">
                  {Math.round(st.duration_seconds)}s
                </span>
              ) : null}
            </div>
          );
        })}
      </div>

      {/* Retry action if failed */}
      {stagesData.status === 'failed' && onRetry && (
        <div className="pt-2 border-t border-rule flex items-center justify-between gap-2">
          <p className="text-xs text-rose-400 truncate">
            {stagesData.error || 'Pipeline halted at current stage.'}
          </p>
          <button
            onClick={onRetry}
            disabled={isRetrying}
            className="btn-primary text-xs py-1 px-2.5 shrink-0 flex items-center gap-1.5"
          >
            {isRetrying ? <Loader2 size={12} className="animate-spin" /> : null}
            Resume / Retry
          </button>
        </div>
      )}
    </div>
  );
}
