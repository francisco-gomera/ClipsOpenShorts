import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Download, Film, Loader2, Radio, Square, X } from 'lucide-react';
import ResultCard from './ResultCard';
import { apiFetch, apiJson } from '../lib/api';
import { buildLiveCreatePayload, validateLiveDuration } from '../lib/liveDuration';
import { captureElapsedSeconds, captureTimerStatus, formatCaptureElapsed } from '../lib/liveCaptureTimer';
import { useAuth } from '../contexts/AuthContext';

const LIVE_SESSION_KEY = 'os_live_session';
const ACTIVE_STATES = new Set(['iniciando', 'esperando', 'capturando', 'reconectando', 'deteniendo', 'finalizando']);

function storeLiveSessionId(sessionId) {
  try {
    if (sessionId) localStorage.setItem(LIVE_SESSION_KEY, sessionId);
    else localStorage.removeItem(LIVE_SESSION_KEY);
  } catch (_) { /* private mode */ }
}

async function downloadWithAuth(path, filename) {
  const response = await apiFetch(path);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || 'No se pudo descargar el archivo.');
  }
  const blobUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = blobUrl;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(blobUrl);
}

export default function LivePanel({ uploadPostKey, uploadUserId, geminiApiKey, isManaged, onActiveChange }) {
  const { billingEnabled, localAuthEnabled, isSignedIn, authExpired } = useAuth();
  const [url, setUrl] = useState('');
  const [minClipSeconds, setMinClipSeconds] = useState('30');
  const [maxClipSeconds, setMaxClipSeconds] = useState('60');
  const [sessionId, setSessionId] = useState(() => localStorage.getItem(LIVE_SESSION_KEY) || '');
  const [session, setSession] = useState(null);
  const [captureClockNow, setCaptureClockNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [downloadError, setDownloadError] = useState('');
  const [editing, setEditing] = useState(null);
  const [savingEdit, setSavingEdit] = useState(false);

  const describeError = useCallback((err) => {
    if (err?.status === 401) return authExpired
      ? 'Tu sesión ha caducado. Inicia sesión nuevamente.'
      : 'No se pudo validar tu sesión. Comprueba la conexión e inténtalo de nuevo.';
    if (err?.status === 409 && err?.detail?.reason === 'live_session_active') {
      return err.detail.stopping
        ? 'La sesión LIVE anterior todavía se está deteniendo.'
        : 'Ya hay una sesión LIVE activa. Se está cargando su estado para que puedas gestionarla.';
    }
    return (typeof err?.detail === 'string' && err.detail) || err?.message || 'No se pudo completar la operación LIVE.';
  }, [authExpired]);

  const refresh = useCallback(async () => {
    if (!sessionId) {
      const data = await apiJson('/api/live');
      const sessions = data.sessions || [];
      const selected = sessions.find((item) => ACTIVE_STATES.has(item.status)) || sessions[0] || null;
      setSession(selected);
      setSessionId(selected?.id || '');
      storeLiveSessionId(selected?.id || '');
      return;
    }
    const data = await apiJson(`/api/live/${encodeURIComponent(sessionId)}`);
    setSession(data);
    if (data.status === 'detenido' || data.status === 'error') {
      storeLiveSessionId(sessionId);
    }
  }, [sessionId]);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        if (!cancelled) await refresh();
      } catch (err) {
        if (cancelled) return;
        if (err?.status === 404 && sessionId) {
          // The browser may retain an old session id that is no longer
          // accessible (for example, a session created before ownership was
          // enforced). Drop it and reload the caller's own session list.
          storeLiveSessionId('');
          setSessionId('');
          setSession(null);
          setError('');
        } else if (sessionId) {
          setError(describeError(err));
        }
      }
    };
    tick();
    const timer = window.setInterval(tick, 2500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [refresh, sessionId, describeError]);

  useEffect(() => {
    if (!session?.capture_started_at || session.capture_ended_at != null) return undefined;
    setCaptureClockNow(Date.now());
    const timer = window.setInterval(() => setCaptureClockNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [session?.capture_started_at, session?.capture_ended_at]);

  const active = ACTIVE_STATES.has(session?.status);
  const clips = useMemo(() => session?.clips || [], [session?.clips]);
  const captureTime = formatCaptureElapsed(captureElapsedSeconds(session, captureClockNow));
  const captureStatus = captureTimerStatus(session);
  const durationError = useMemo(() => validateLiveDuration(minClipSeconds, maxClipSeconds).error,
    [minClipSeconds, maxClipSeconds]);
  const authRequired = billingEnabled || localAuthEnabled;
  const authenticated = !authRequired || isSignedIn;

  useEffect(() => {
    if (session) onActiveChange?.(active);
  }, [active, onActiveChange, session]);

  const start = async (event) => {
    event.preventDefault();
    let payload;
    try {
      payload = buildLiveCreatePayload(url, minClipSeconds, maxClipSeconds);
    } catch (err) {
      setError(err.message);
      return;
    }
    setBusy(true);
    setError('');
    try {
      const created = await apiJson('/api/live', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setSession(created);
      setSessionId(created.id);
      storeLiveSessionId(created.id);
      setUrl('');
    } catch (err) {
      setError(describeError(err));
      if (err?.status === 409 && err?.detail?.session_id) {
        try {
          const existing = await apiJson(`/api/live/${encodeURIComponent(err.detail.session_id)}`);
          setSession(existing);
          setSessionId(existing.id);
          storeLiveSessionId(existing.id);
        } catch (_) { /* never expose a conflicting session owned by someone else */ }
      }
    } finally {
      setBusy(false);
    }
  };

  const stop = async (modo) => {
    if (!sessionId) return;
    setBusy(true);
    setError('');
    try {
      const next = await apiJson(`/api/live/${encodeURIComponent(sessionId)}/stop`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ modo }),
      });
      setSession(next);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  const download = async (path, filename) => {
    setDownloadError('');
    try { await downloadWithAuth(path, filename); }
    catch (err) { setDownloadError(err.message || 'No se pudo descargar el archivo.'); }
  };

  const saveMetadata = async (event) => {
    event.preventDefault();
    if (!editing || !sessionId) return;
    setSavingEdit(true);
    try {
      const next = await apiJson(`/api/live/${encodeURIComponent(sessionId)}/clips/${editing.index}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editing.values),
      });
      setSession(next);
      setEditing(null);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSavingEdit(false);
    }
  };

  return (
    <section className="space-y-6" aria-labelledby="live-heading">
      <header className="flex items-start gap-3">
        <div className="w-11 h-11 rounded-btn bg-primary-soft border border-border flex items-center justify-center text-primary shrink-0">
          <Film size={21} />
        </div>
        <div>
          <p className="eyebrow">CLIPS OPEN SHORTS</p>
          <h1 id="live-heading" className="font-display lowercase text-2xl sm:text-3xl text-text-primary">En vivo</h1>
          <p className="text-sm text-text-secondary mt-1">Detecta momentos destacados y genera clips verticales mientras el directo continúa.</p>
        </div>
      </header>

      {!active && (
        <form onSubmit={start} className="card p-4 sm:p-5 space-y-4">
          <label className="block text-sm text-text-primary" htmlFor="live-url">Enlace de un directo de YouTube</label>
          <div className="flex flex-col sm:flex-row gap-3">
            <input id="live-url" type="url" required value={url} onChange={(event) => setUrl(event.target.value)}
              placeholder="https://www.youtube.com/live/..." className="input-field flex-1 min-w-0" />
          </div>
          <p className="text-xs text-text-secondary">El procesamiento usa la CPU y conserva un buffer temporal de los últimos 20 minutos.</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label htmlFor="live-min-clip" className="block text-sm text-text-primary">Duración mínima del clip
              <div className="relative mt-1"><input id="live-min-clip" type="number" min="10" max="240" step="1"
                value={minClipSeconds} onChange={(event) => setMinClipSeconds(event.target.value)}
                className="input-field w-full pr-16" /><span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-text-secondary">segundos</span></div>
            </label>
            <label htmlFor="live-max-clip" className="block text-sm text-text-primary">Duración máxima del clip
              <div className="relative mt-1"><input id="live-max-clip" type="number" min="10" max="240" step="1"
                value={maxClipSeconds} onChange={(event) => setMaxClipSeconds(event.target.value)}
                className="input-field w-full pr-16" /><span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-text-secondary">segundos</span></div>
            </label>
          </div>
          {durationError && <p role="alert" className="text-xs text-danger">{durationError}</p>}
          <button className="btn-primary inline-flex items-center justify-center gap-2" disabled={busy || !authenticated || !url.trim() || !!durationError}>
            {busy ? <Loader2 size={16} className="animate-spin" /> : <Radio size={16} />}
            Iniciar
          </button>
        </form>
      )}

      {session && (
        <div className="card p-4 sm:p-5 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span className={`w-2.5 h-2.5 rounded-full ${active ? 'bg-primary animate-pulse' : session.status === 'error' ? 'bg-danger' : 'bg-text-secondary'}`} />
              <div>
                <div className="text-sm font-medium text-text-primary">{session.titulo || 'Sesión en vivo'}</div>
                <div className="text-xs text-text-secondary">Estado: {session.status || 'iniciando'}</div>
              </div>
            </div>
            {active && <div className="flex flex-wrap gap-2">
              <button onClick={() => stop('terminar_pendientes')} disabled={busy} className="btn-ghost inline-flex items-center gap-2 text-xs">
                {busy ? <Loader2 size={14} className="animate-spin" /> : <Square size={13} />} Detener y terminar clips
              </button>
              <button onClick={() => stop('detener_ya')} disabled={busy} className="btn-ghost inline-flex items-center gap-2 text-xs text-danger">
                Detener ya
              </button>
            </div>}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-xs">
            <div className="rounded-input bg-primary-soft p-3"><div className="text-text-secondary">Tiempo de captura</div><div className="readout mt-1 tabular-nums">{captureTime}</div><div className="mt-1 text-[10px] text-text-secondary">{captureStatus}</div></div>
            <div className="rounded-input bg-primary-soft p-3"><div className="text-text-secondary">Segmentos</div><div className="readout mt-1">{session.segments || 0}</div></div>
            <div className="rounded-input bg-primary-soft p-3"><div className="text-text-secondary">Clips listos</div><div className="readout mt-1">{clips.length}</div></div>
            <div className="rounded-input bg-primary-soft p-3"><div className="text-text-secondary">RTF Whisper</div><div className="readout mt-1">{session.rtf == null ? '—' : Number(session.rtf).toFixed(2)}</div></div>
            <div className="rounded-input bg-primary-soft p-3"><div className="text-text-secondary">En cola</div><div className="readout mt-1">{(session.queue || []).filter((item) => item.status === 'en_cola').length}</div></div>
          </div>
          <p className="text-xs text-text-secondary">Duración configurada: {session.min_clip_seconds ?? 30}–{session.max_clip_seconds ?? 60} segundos</p>
          {session.mensaje && <p className="text-sm text-text-secondary">{session.mensaje}</p>}
          {!!session.notices?.length && <div className="space-y-2" aria-live="polite">
            {session.notices.slice(-5).map((notice, index) => (
              <div key={`${notice.at || index}-${index}`} className="flex gap-2 text-xs text-text-secondary">
                <AlertTriangle size={14} className="shrink-0 text-primary" />
                <span>{notice.mensaje || notice.error || notice.tipo}</span>
              </div>
            ))}
          </div>}
          {(session.queue || []).some((item) => item.status === 'descartado_por_saturacion') && (
            <p className="text-xs text-text-secondary">Uno o más clips se descartaron porque la cola de render estaba llena.</p>
          )}
          {clips.length > 0 && <button onClick={() => download(`/api/live/${sessionId}/download.zip`, 'clips_en_vivo.zip')}
            className="btn-primary inline-flex items-center gap-2 text-sm"><Download size={15} /> Descargar paquete</button>}
        </div>
      )}

      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {authExpired && <p role="status" className="text-sm text-primary">Tu sesión ha caducado. Inicia sesión nuevamente; el backend está deteniendo la captura asociada.</p>}
      {downloadError && <p role="alert" className="text-sm text-danger">{downloadError}</p>}

      {clips.length > 0 && (
        <div className="space-y-4">
          <h2 className="font-display lowercase text-xl text-text-primary">Clips de esta sesión</h2>
          <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(min(100%,520px),1fr))]">
            {clips.map((clip, index) => (
              <div key={`${clip.source_window_id}-${clip.file}`} className="space-y-2">
                <ResultCard clip={clip} index={index} jobId={sessionId} isManaged={isManaged}
                  uploadPostKey={uploadPostKey} uploadUserId={uploadUserId} geminiApiKey={geminiApiKey}
                  liveMode onEditMetadata={() => setEditing({ index, values: {
                    video_title_for_youtube_short: clip.video_title_for_youtube_short || '',
                    video_description_for_tiktok: clip.video_description_for_tiktok || '',
                    video_description_for_instagram: clip.video_description_for_instagram || '',
                    viral_hook_text: clip.viral_hook_text || '',
                  } })} />
                <button onClick={() => download(`/api/live/${sessionId}/download/${index}`, `clip_${index + 1}.mp4`)}
                  className="btn-ghost inline-flex items-center gap-2 text-xs"><Download size={14} /> Descargar MP4</button>
              </div>
            ))}
          </div>
        </div>
      )}

      {editing && <div className="fixed inset-0 z-[120] bg-black/70 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="live-edit-title">
        <form onSubmit={saveMetadata} className="card w-full max-w-xl p-5 space-y-4 max-h-[90vh] overflow-y-auto">
          <div className="flex items-center justify-between"><h2 id="live-edit-title" className="font-display text-xl lowercase text-text-primary">Editar textos del clip</h2>
            <button type="button" onClick={() => setEditing(null)} aria-label="Cerrar" className="p-2 text-text-secondary"><X size={18} /></button></div>
          {[
            ['video_title_for_youtube_short', 'Título'],
            ['viral_hook_text', 'Hook'],
            ['video_description_for_tiktok', 'Descripción TikTok'],
            ['video_description_for_instagram', 'Descripción Instagram'],
          ].map(([key, label]) => <label key={key} className="block space-y-1 text-xs text-text-secondary">{label}
            <textarea rows={key.includes('description') ? 3 : 2} value={editing.values[key]}
              onChange={(event) => setEditing((current) => ({ ...current, values: { ...current.values, [key]: event.target.value } }))}
              className="input-field w-full resize-y text-sm text-text-primary" /></label>)}
          <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={() => setEditing(null)}>Cancelar</button>
            <button disabled={savingEdit} className="btn-primary inline-flex items-center gap-2">{savingEdit && <Loader2 size={14} className="animate-spin" />} Guardar</button></div>
        </form>
      </div>}
    </section>
  );
}
