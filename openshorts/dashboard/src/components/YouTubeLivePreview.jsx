import React, { useMemo } from 'react';
import { ExternalLink, Radio } from 'lucide-react';
import { buildYouTubeEmbedUrl, getYouTubeVideoId } from '../lib/youtubeLivePreview';
import { previewStatus } from '../lib/livePreviewStatus';

export default function YouTubeLivePreview({ url, status }) {
  const videoId = useMemo(() => getYouTubeVideoId(url), [url]);
  const canonicalUrl = videoId ? `https://www.youtube.com/watch?v=${videoId}` : null;
  const embedUrl = buildYouTubeEmbedUrl(videoId);
  const liveStatus = previewStatus(status);

  return (
    <section className="rounded-input border border-border bg-primary-soft/40 p-3 sm:p-4 space-y-3" aria-label="Vista previa del directo">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
          <Radio size={16} className={liveStatus.tone === 'active' ? 'text-error' : 'text-text-secondary'} />
          <span>Vista previa de YouTube LIVE</span>
          <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide ${liveStatus.tone === 'active' ? 'bg-error/15 text-error' : 'bg-surface text-text-secondary'}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${liveStatus.tone === 'active' ? 'animate-pulse bg-error' : 'bg-text-secondary'}`} />
            {liveStatus.label}
          </span>
        </div>
        <span className="text-xs text-text-secondary">La calidad de la vista previa la decide YouTube</span>
      </div>

      {embedUrl ? (
        <div className="relative w-full overflow-hidden rounded-input bg-black" style={{ aspectRatio: '16 / 9' }}>
          <iframe
            title="Vista previa del directo de YouTube"
            src={embedUrl}
            loading="lazy"
            referrerPolicy="strict-origin-when-cross-origin"
            allow="fullscreen; picture-in-picture"
            allowFullScreen
            className="absolute inset-0 h-full w-full border-0"
          />
        </div>
      ) : (
        <p className="text-sm text-text-secondary">No se pudo validar el enlace de esta sesión como un video de YouTube.</p>
      )}

      <div className="flex flex-col gap-2 text-xs text-text-secondary sm:flex-row sm:items-center sm:justify-between">
        <p>La vista previa es del navegador; la captura del servidor tiene su propio estado. La calidad la decide YouTube. Si el directo no permite reproducción incrustada, ábrelo en YouTube.</p>
        {canonicalUrl && (
          <a href={canonicalUrl} target="_blank" rel="noopener noreferrer" className="inline-flex shrink-0 items-center gap-1 text-primary hover:underline">
            Abrir en YouTube <ExternalLink size={13} />
          </a>
        )}
      </div>
    </section>
  );
}
