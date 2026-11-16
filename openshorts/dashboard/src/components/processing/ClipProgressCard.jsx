import React from 'react';
import { Film, CheckCircle2, Loader2, Sparkles, Scissors, Type } from 'lucide-react';

const SUBSTAGE_LABELS = {
  cut:       { label: 'Trimming',   icon: Scissors },
  reframe:   { label: 'Reframing',  icon: Film },
  hook:      { label: 'Hook visual', icon: Sparkles },
  subtitles: { label: 'Subtitles',  icon: Type },
  done:      { label: 'Completed',  icon: CheckCircle2 },
};

export default function ClipProgressCard({ clip, clipNumber, onPreviewClip = null }) {
  const isReady = clip.ready || clip.status === 'completed';
  const substageKey = clip.substage || (isReady ? 'done' : 'reframe');
  const substageMeta = SUBSTAGE_LABELS[substageKey] || { label: 'Processing', icon: Loader2 };
  const SubstageIcon = substageMeta.icon;

  return (
    <div
      className={`p-3 rounded-card border transition-all duration-300 ${
        isReady
          ? 'bg-primary-soft/40 border-success/30'
          : 'bg-surface border-border'
      }`}
      role="article"
      aria-label={`Clip ${clipNumber || (clip.index ?? 0) + 1}: ${substageMeta.label}`}
    >
      <div className="flex items-center justify-between gap-2">
        {/* Left: substage icon + label */}
        <div className="flex items-center gap-2 min-w-0">
          <div
            className={`p-1.5 rounded shrink-0 ${
              isReady
                ? 'bg-success/10 text-success'
                : 'bg-surface-elevated text-primary'
            }`}
            aria-hidden="true"
          >
            {isReady ? (
              <SubstageIcon size={14} />
            ) : (
              /* Skeleton pulse icon for in-progress */
              <SubstageIcon size={14} className="animate-pulse" />
            )}
          </div>
          <div className="min-w-0">
            <h5 className="text-xs font-brand font-semibold text-text-primary truncate">
              Clip {clipNumber || (clip.index ?? 0) + 1}
            </h5>
            <p className="text-[11px] text-text-secondary truncate font-ui">
              {substageMeta.label}
            </p>
          </div>
        </div>

        {/* Right: ready badge or percentage */}
        <div className="shrink-0 text-right">
          {isReady ? (
            <button
              type="button"
              onClick={() => onPreviewClip && onPreviewClip(clip)}
              className="inline-flex items-center gap-1 text-[11px] font-ui font-medium
                text-success bg-success/10 px-2 py-0.5 rounded-full border border-success/20
                hover:bg-success/20 transition-colors focus:outline-none focus:ring-2 focus:ring-success/40"
              aria-label={`Preview clip ${clipNumber || (clip.index ?? 0) + 1}`}
            >
              <CheckCircle2 size={11} aria-hidden="true" />
              Listo
            </button>
          ) : (
            <span className="text-xs font-brand font-bold text-primary" aria-label="Progreso">
              {clip.percent != null ? `${Math.round(clip.percent)}%` : '0%'}
            </span>
          )}
        </div>
      </div>

      {/* Mini progress bar */}
      <div
        className="mt-2 w-full h-1 rounded-full bg-surface-elevated overflow-hidden"
        role="progressbar"
        aria-valuenow={isReady ? 100 : Math.round(clip.percent || 0)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Progreso de clip ${clipNumber || (clip.index ?? 0) + 1}`}
      >
        <div
          className={`h-full rounded-full transition-all duration-300 ${
            isReady ? 'bg-success' : 'bg-primary'
          }`}
          style={{ width: isReady ? '100%' : `${Math.min(100, clip.percent || 0)}%` }}
        />
      </div>
    </div>
  );
}
