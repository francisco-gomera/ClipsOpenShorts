import React from 'react';
import { Film, CheckCircle2, Loader2, Sparkles, Scissors, Type } from 'lucide-react';

const SUBSTAGE_LABELS = {
  cut: { label: 'Recortando fragmento', icon: Scissors },
  reframe: { label: 'Reencuadrando 9:16', icon: Film },
  hook: { label: 'Hook visual', icon: Sparkles },
  subtitles: { label: 'Quemando subtítulos', icon: Type },
  done: { label: 'Completado', icon: CheckCircle2 },
};

export default function ClipProgressCard({ clip, clipNumber, onPreviewClip = null }) {
  const isReady = clip.ready || clip.status === 'completed';
  const substageKey = clip.substage || (isReady ? 'done' : 'reframe');
  const substageMeta = SUBSTAGE_LABELS[substageKey] || { label: 'Procesando', icon: Loader2 };
  const SubstageIcon = substageMeta.icon;

  return (
    <div
      className={`p-3 rounded-card border transition-all duration-300 ${
        isReady
          ? 'bg-paper border-emerald-500/30 shadow-sm shadow-emerald-500/5'
          : 'bg-paper/70 border-rule/60'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <div
            className={`p-1.5 rounded shrink-0 ${
              isReady ? 'bg-emerald-500/10 text-emerald-400' : 'bg-brass/10 text-brass'
            }`}
          >
            <SubstageIcon size={14} className={!isReady ? 'animate-pulse' : ''} />
          </div>
          <div className="min-w-0">
            <h5 className="text-xs font-semibold text-ink truncate">
              Clip {clipNumber || clip.index + 1}
            </h5>
            <p className="text-[11px] text-muted truncate">
              {substageMeta.label}
            </p>
          </div>
        </div>

        {/* Estado o Badge */}
        <div className="shrink-0 text-right">
          {isReady ? (
            <button
              type="button"
              onClick={() => onPreviewClip && onPreviewClip(clip)}
              className="inline-flex items-center gap-1 text-[11px] font-mono font-medium text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20 hover:bg-emerald-500/20 transition-colors"
            >
              <CheckCircle2 size={11} />
              Listo
            </button>
          ) : (
            <span className="text-xs font-mono text-brass font-bold">
              {clip.percent ? `${Math.round(clip.percent)}%` : '0%'}
            </span>
          )}
        </div>
      </div>

      {/* Mini barra de progreso */}
      <div
        className="mt-2 w-full h-1 rounded-full bg-black/20 border border-rule/30 overflow-hidden"
        role="progressbar"
        aria-valuenow={isReady ? 100 : Math.round(clip.percent || 0)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Progreso de clip ${clipNumber || clip.index + 1}`}
      >
        <div
          className={`h-full rounded-full transition-all duration-300 ${
            isReady ? 'bg-emerald-500 w-full' : 'bg-brass'
          }`}
          style={{ width: isReady ? '100%' : `${Math.min(100, clip.percent || 0)}%` }}
        />
      </div>
    </div>
  );
}
