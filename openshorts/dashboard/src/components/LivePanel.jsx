import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity, AlertTriangle, Check, Circle, Clock3, Cpu, Download, Film, Loader2,
  Eye, EyeOff, Radio, Square, Wifi, WifiOff, X,
} from 'lucide-react';
import ResultCard from './ResultCard';
import YouTubeLivePreview from './YouTubeLivePreview';
import { apiFetch, apiJson } from '../lib/api';
import { buildLiveCreatePayload, validateLiveDuration } from '../lib/liveDuration';
import { captureElapsedSeconds, formatCaptureElapsed } from '../lib/liveCaptureTimer';
import {
  countLiveQueue, elapsedSince, formatLiveOffset, liveQueueStatus, liveWaitReason,
  LIVE_PHASE_LABELS, LIVE_STATUS_LABELS, orderLiveQueue,
} from '../lib/liveProgress';
import { useAuth } from '../contexts/AuthContext';

const LIVE_SESSION_KEY = 'os_live_session';
const ACTIVE_STATES = new Set(['iniciando', 'esperando', 'capturando', 'reconectando', 'deteniendo', 'finalizando']);
const TERMINAL_STATES = new Set(['detenido', 'error']);

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

function captureStatusStyle(status) {
  if (status === 'capturando') return 'border-success/40 bg-success/10 text-success';
  if (status === 'reconectando' || status === 'esperando' || status === 'iniciando') {
    return 'border-primary/40 bg-primary-soft text-primary';
  }
  if (status === 'error') return 'border-error/40 bg-error/10 text-error';
  if (TERMINAL_STATES.has(status)) return 'border-border bg-surface text-text-secondary';
  return 'border-warning/40 bg-warning/10 text-warning';
}

function Metric({ label, value, detail }) {
  return <div className="rounded-input border border-border bg-surface p-3">
    <div className="text-[11px] text-text-secondary">{label}</div>
    <div className="readout mt-1 text-xl tabular-nums text-text-primary">{value}</div>
    {detail && <div className="mt-1 text-[10px] text-text-secondary">{detail}</div>}
  </div>;
}

function clipNumber(item) {
  const match = String(item?.id || item?.source_window_id || '').match(/(\d+)$/);
  return match ? Number(match[1]) : null;
}

function LiveProgressCard({ item, order, now }) {
  const status = item.status || 'desconocido';
  const phaseHistory = Array.isArray(item.phase_history) ? item.phase_history : [];
  const phaseTime = elapsedSince(item.phase_started_at, now);
  const waitingTime = elapsedSince(item.queued_at, now);
  const isProcessing = status === 'renderizando';
  const isError = status === 'error';
  const isDone = status === 'completado';
  const displayStatus = status === 'en_cola' && item.wait_reason === 'prioridad_de_captura'
    ? 'En pausa por prioridad de captura' : liveQueueStatus(status);

  return <article className={`rounded-card border p-4 ${isError ? 'border-error/40 bg-error/5' : 'border-border bg-surface'}`}>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-medium text-text-primary">{clipNumber(item) ? `Clip ${clipNumber(item)}` : 'Momento destacado'}</h3>
          <span className={`rounded-full border px-2 py-0.5 text-[11px] ${isError ? 'border-error/40 text-error' : isDone ? 'border-success/40 text-success' : 'border-border text-text-secondary'}`}>
            {displayStatus}
          </span>
          {order && status === 'en_cola' && <span className="text-[11px] text-text-secondary">Turno {order}</span>}
        </div>
        <p className="mt-1 text-xs text-text-secondary">
          {item.start != null && item.end != null
            ? `Origen ${formatLiveOffset(item.start)}–${formatLiveOffset(item.end)} · ${Math.max(0, Math.round(item.end - item.start))} s`
            : 'Origen del directo no disponible'}
          {item.predicted_score != null && ` · Puntuación ${Math.round(Number(item.predicted_score))}/100`}
        </p>
      </div>
      {isProcessing && <div className="flex items-center gap-1.5 text-xs text-primary" aria-live="polite">
        <Loader2 size={14} className="animate-spin" />
        {item.phase_started_at ? <span>{formatCaptureElapsed(phaseTime)}</span> : <span>Procesándose</span>}
      </div>}
      {status === 'en_cola' && item.queued_at && <div className="flex items-center gap-1.5 text-xs text-text-secondary">
        <Clock3 size={14} /><span>{formatCaptureElapsed(waitingTime)} esperando</span>
      </div>}
      {status === 'evaluando' && item.evaluating_started_at && <div className="flex items-center gap-1.5 text-xs text-primary">
        <Loader2 size={14} className="animate-spin" /><span>{formatCaptureElapsed(elapsedSince(item.evaluating_started_at, now))} evaluando</span>
      </div>}
    </div>

    {item.why && <p className="mt-2 text-sm text-text-secondary">{item.why}</p>}
    {status === 'en_cola' && <p className="mt-2 text-xs text-text-secondary">{liveWaitReason(item.wait_reason)}</p>}

    {phaseHistory.length > 0 && <ol className="mt-4 grid gap-2 sm:grid-cols-2" aria-label="Fases de procesamiento">
      {phaseHistory.map((entry, index) => {
        const current = isProcessing && index === phaseHistory.length - 1;
        const failed = isError && entry.phase === item.failed_phase;
        const done = isDone || (isProcessing && !current) || (isError && !failed);
        return <li key={`${entry.phase}-${entry.started_at}-${index}`} className="flex min-w-0 items-center gap-2 text-xs">
          {failed ? <AlertTriangle size={14} className="shrink-0 text-error" />
            : done ? <Check size={14} className="shrink-0 text-success" />
              : current ? <Loader2 size={14} className="shrink-0 animate-spin text-primary" />
                : <Circle size={14} className="shrink-0 text-text-secondary" />}
          <span className={`${failed ? 'text-error' : current ? 'text-text-primary' : 'text-text-secondary'} truncate`}>
            {LIVE_PHASE_LABELS[entry.phase] || entry.phase?.replaceAll('_', ' ') || 'Procesando'}
          </span>
        </li>;
      })}
    </ol>}
    {isError && <p role="alert" className="mt-3 text-sm text-error">{item.error || 'No se pudo procesar este clip.'}</p>}
    {status === 'descartado_por_saturacion' && <p className="mt-3 text-sm text-warning">{item.reason || 'La cola alcanzó su límite.'}</p>}
    {status === 'cancelado' && <p className="mt-3 text-sm text-text-secondary">{item.reason || 'El procesamiento fue cancelado.'}</p>}
  </article>;
}

export default function LivePanel({ uploadPostKey, uploadUserId, geminiApiKey, isManaged, onActiveChange }) {
  const { billingEnabled, localAuthEnabled, isSignedIn, authExpired } = useAuth();
  const [url, setUrl] = useState('');
  const [minClipSeconds, setMinClipSeconds] = useState('30');
  const [maxClipSeconds, setMaxClipSeconds] = useState('60');
  const [sessionId, setSessionId] = useState(() => localStorage.getItem(LIVE_SESSION_KEY) || '');
  const [session, setSession] = useState(null);
  const [clockNow, setClockNow] = useState(() => Date.now());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [downloadError, setDownloadError] = useState('');
  const [editing, setEditing] = useState(null);
  const [savingEdit, setSavingEdit] = useState(false);
  const [previewVisible, setPreviewVisible] = useState(false);
  const sessionRef = useRef(session);
  const refreshRef = useRef(null);
  const describeErrorRef = useRef(null);
  sessionRef.current = session;

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
  describeErrorRef.current = describeError;

  const refresh = useCallback(async () => {
    if (!sessionId) {
      const data = await apiJson('/api/live');
      const sessions = data.sessions || [];
      const selected = sessions.find((item) => ACTIVE_STATES.has(item.status)) || sessions[0] || null;
      sessionRef.current = selected;
      setSession(selected);
      setSessionId(selected?.id || '');
      storeLiveSessionId(selected?.id || '');
      return selected;
    }
    const data = await apiJson(`/api/live/${encodeURIComponent(sessionId)}`);
    sessionRef.current = data;
    setSession(data);
    if (TERMINAL_STATES.has(data.status)) storeLiveSessionId(sessionId);
    return data;
  }, [sessionId]);
  refreshRef.current = refresh;

  useEffect(() => {
    let cancelled = false;
    let timer;
    const tick = async () => {
      let failed = false;
      try {
        await refreshRef.current?.();
        if (!cancelled) setError('');
      } catch (err) {
        failed = true;
        if (cancelled) return;
        if (err?.status === 404 && localStorage.getItem(LIVE_SESSION_KEY)) {
          storeLiveSessionId('');
          sessionRef.current = null;
          setSessionId('');
          setSession(null);
          setError('');
        } else {
          setError(describeErrorRef.current?.(err) || 'No se pudo actualizar el estado de Live.');
        }
      }
      if (cancelled) return;
      const current = sessionRef.current;
      const delay = failed ? 8000 : TERMINAL_STATES.has(current?.status) ? 15000 : 4500;
      timer = window.setTimeout(tick, delay);
    };
    tick();
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, []);

  const queue = useMemo(() => Array.isArray(session?.queue) ? session.queue : [], [session?.queue]);
  const candidates = useMemo(() => Array.isArray(session?.candidates) ? session.candidates : [], [session?.candidates]);
  const clips = useMemo(() => Array.isArray(session?.clips) ? session.clips : [], [session?.clips]);
  const queueCounts = useMemo(() => countLiveQueue(queue), [queue]);
  const pendingEvaluation = useMemo(() => candidates.filter((item) => ['detectado', 'evaluando'].includes(item.status)
    && !queue.some((entry) => String(entry.id) === String(item.id))), [candidates, queue]);
  const candidateIssues = useMemo(() => candidates.filter((item) => ['error', 'descartado_por_saturacion', 'cancelado'].includes(item.status)
    && !queue.some((entry) => String(entry.id) === String(item.id))), [candidates, queue]);
  const progressItems = useMemo(() => {
    const ordered = orderLiveQueue(queue);
    const processingOrQueued = ordered.filter((item) => ['renderizando', 'en_cola'].includes(item.status));
    const recentCompleted = ordered.filter((item) => item.status === 'completado')
      .slice(0, 3);
    const recentIssues = ordered.filter((item) => ['error', 'descartado_por_saturacion', 'cancelado'].includes(item.status))
      .slice(0, 5);
    return [...processingOrQueued, ...pendingEvaluation, ...recentCompleted, ...recentIssues, ...candidateIssues];
  }, [queue, pendingEvaluation, candidateIssues]);
  const hasActivePhase = queue.some((item) => item.status === 'renderizando' && item.phase_started_at);
  const hasTimedQueue = queue.some((item) => item.status === 'en_cola');
  const hasTimedEvaluation = pendingEvaluation.length > 0;
  const captureClockActive = session?.capture_started_at && session.capture_ended_at == null;
  useEffect(() => {
    if (!captureClockActive && !hasActivePhase && !hasTimedQueue && !hasTimedEvaluation) return undefined;
    setClockNow(Date.now());
    const timer = window.setInterval(() => setClockNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [captureClockActive, hasActivePhase, hasTimedQueue, hasTimedEvaluation]);

  const active = ACTIVE_STATES.has(session?.status);
  const captureTime = formatCaptureElapsed(captureElapsedSeconds(session, clockNow));
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
    try { payload = buildLiveCreatePayload(url, minClipSeconds, maxClipSeconds); }
    catch (err) { setError(err.message); return; }
    setBusy(true);
    setError('');
    try {
      const created = await apiJson('/api/live', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      sessionRef.current = created;
      setSession(created);
      setSessionId(created.id);
      storeLiveSessionId(created.id);
      setUrl('');
    } catch (err) {
      setError(describeError(err));
      if (err?.status === 409 && err?.detail?.session_id) {
        try {
          const existing = await apiJson(`/api/live/${encodeURIComponent(err.detail.session_id)}`);
          sessionRef.current = existing;
          setSession(existing);
          setSessionId(existing.id);
          storeLiveSessionId(existing.id);
        } catch (_) { /* never expose a conflicting session owned by someone else */ }
      }
    } finally { setBusy(false); }
  };

  const stop = async (mode) => {
    if (!sessionId) return;
    setBusy(true);
    setError('');
    try {
      const next = await apiJson(`/api/live/${encodeURIComponent(sessionId)}/stop`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ modo: mode }),
      });
      sessionRef.current = next;
      setSession(next);
    } catch (err) { setError(describeError(err)); }
    finally { setBusy(false); }
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
      sessionRef.current = next;
      setSession(next);
      setEditing(null);
    } catch (err) { setError(describeError(err)); }
    finally { setSavingEdit(false); }
  };

  const liveStatus = session?.status || 'iniciando';
  const connection = liveStatus === 'capturando' ? 'Conexión estable'
    : liveStatus === 'reconectando' ? 'Reconectando'
      : liveStatus === 'esperando' ? 'Esperando emisión'
        : ['deteniendo', 'finalizando'].includes(liveStatus) ? 'Cerrando captura'
          : liveStatus === 'iniciando' ? 'Preparando conexión'
        : TERMINAL_STATES.has(liveStatus) ? 'Desconectado' : 'Conexión pendiente';
  const momentsDetected = candidates.length;

  return <section className="space-y-5" aria-labelledby="live-heading">
    <header className="flex items-start gap-3">
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-btn border border-border bg-primary-soft text-primary">
        <Film size={21} />
      </div>
      <div>
        <p className="eyebrow">CLIPS OPEN SHORTS</p>
        <h1 id="live-heading" className="font-display text-2xl lowercase text-text-primary sm:text-3xl">En vivo</h1>
        <p className="mt-1 text-sm text-text-secondary">Centro de control de captura y procesamiento de clips.</p>
      </div>
    </header>

    {!active && <form onSubmit={start} className="card space-y-4 p-4 sm:p-5">
      <div>
        <h2 className="font-display text-lg lowercase text-text-primary">Iniciar captura</h2>
        <p className="mt-1 text-xs text-text-secondary">El procesamiento usa la CPU y conserva un buffer temporal de los últimos 20 minutos.</p>
      </div>
      <label className="block text-sm text-text-primary" htmlFor="live-url">Enlace de un directo de YouTube</label>
      <input id="live-url" type="url" required value={url} onChange={(event) => setUrl(event.target.value)}
        placeholder="https://www.youtube.com/live/..." className="input-field w-full" />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
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
      {durationError && <p role="alert" className="text-xs text-error">{durationError}</p>}
      <button className="btn-primary inline-flex items-center justify-center gap-2" disabled={busy || !authenticated || !url.trim() || !!durationError}>
        {busy ? <Loader2 size={16} className="animate-spin" /> : <Radio size={16} />}
        Iniciar captura
      </button>
    </form>}

    {session && <>
      <section className="card space-y-4 p-4 sm:p-5" aria-label="Estado de la captura">
        <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate font-display text-xl lowercase text-text-primary">{session.titulo || 'Sesión en vivo'}</h2>
              <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${captureStatusStyle(liveStatus)}`}>
                <span className={`h-2 w-2 rounded-full ${liveStatus === 'capturando' ? 'animate-pulse bg-current' : 'bg-current'}`} />
                {LIVE_STATUS_LABELS[liveStatus] || 'Estado no disponible'}
              </span>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-secondary">
              <span className="inline-flex items-center gap-1.5">
                {liveStatus === 'capturando' ? <Wifi size={14} className="text-success" />
                  : TERMINAL_STATES.has(liveStatus) ? <WifiOff size={14} /> : <Activity size={14} className="text-primary" />}
                {connection}
              </span>
              {session.mensaje && <span>{session.mensaje}</span>}
              <span>Duración de clip: {session.min_clip_seconds ?? 30}–{session.max_clip_seconds ?? 60} s</span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="min-w-32 rounded-input border border-border bg-surface px-3 py-2 text-center">
              <div className="text-[10px] uppercase tracking-wide text-text-secondary">Tiempo de captura</div>
              <div className="readout text-xl tabular-nums text-text-primary">{captureTime}</div>
            </div>
            {active && <>
              <button onClick={() => stop('terminar_pendientes')} disabled={busy} className="btn-ghost inline-flex items-center gap-2 text-xs">
                {busy ? <Loader2 size={14} className="animate-spin" /> : <Square size={13} />} Detener y terminar clips
              </button>
              <button onClick={() => stop('detener_ya')} disabled={busy} className="btn-ghost inline-flex items-center gap-2 text-xs text-error">
                Detener ya
              </button>
            </>}
          </div>
        </div>
        {liveStatus === 'reconectando' && <p role="status" className="rounded-input border border-warning/30 bg-warning/5 p-3 text-sm text-warning">
          La conexión con el directo se interrumpió. El sistema está intentando reconectar y el cronómetro conserva el tiempo acumulado.
        </p>}
      </section>

      {session.url && <section className="space-y-3" aria-label="Vista previa del directo">
        <button type="button" onClick={() => setPreviewVisible((visible) => !visible)}
          aria-expanded={previewVisible}
          className="btn-ghost inline-flex items-center gap-2 text-xs">
          {previewVisible ? <EyeOff size={14} /> : <Eye size={14} />}
          {previewVisible ? 'Ocultar vista previa' : 'Mostrar vista previa'}
        </button>
        {previewVisible && <YouTubeLivePreview key={sessionId || session.id} url={session.url} />}
      </section>}

      <section aria-label="Estadísticas de la sesión" className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <Metric label="Segmentos capturados" value={session.segments_total ?? session.segments ?? 0} />
        <Metric label="Momentos detectados" value={momentsDetected} />
        <Metric label="Clips terminados" value={clips.length} />
        <Metric label="Clips pendientes" value={queueCounts.pending + pendingEvaluation.length} />
        <Metric label="Clips procesándose" value={queueCounts.processing} />
        <Metric label="Reconexiones" value={session.reconnections ?? '—'} />
      </section>

      <section className="card space-y-3 p-4 sm:p-5" aria-labelledby="live-health-heading">
        <div className="flex items-center gap-2"><Cpu size={17} className="text-primary" />
          <h2 id="live-health-heading" className="font-display text-lg lowercase text-text-primary">Salud del motor</h2></div>
        {session.render_priority_paused && <p role="status" className="rounded-input border border-warning/30 bg-warning/5 p-3 text-sm text-warning">
          El inicio de nuevos renders está en pausa para dar prioridad a la captura y transcripción. Los clips pendientes continuarán cuando el RTF de Whisper vuelva a estar dentro del umbral.
        </p>}
        <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-input bg-primary-soft p-3"><span className="text-text-secondary">Whisper</span>
            <div className="mt-1 font-medium text-text-primary">{session.rtf == null ? 'Sin medición' : `${Number(session.rtf).toFixed(2)} RTF`}</div>
            <div className="mt-1 text-text-secondary">{{ esperando: 'Esperando audio', activo: 'Activo', degradado: 'Reducido por carga', detenido_por_carga: 'Pausado por carga', no_disponible: 'No disponible' }[session.asr_status] || 'Estado heredado / desconocido'}</div>
          </div>
          <div className="rounded-input bg-primary-soft p-3"><span className="text-text-secondary">Renderizador</span>
            <div className="mt-1 font-medium text-text-primary">{queueCounts.processing ? 'Procesando un clip' : session.render_priority_paused ? 'En pausa por prioridad' : queueCounts.pending ? 'Esperando turno' : 'Disponible'}</div>
          </div>
          <div className="rounded-input bg-primary-soft p-3"><span className="text-text-secondary">Cola de trabajo</span>
            <div className="mt-1 font-medium text-text-primary">{queueCounts.pending} pendientes · {queueCounts.processing} activos</div>
          </div>
          <div className="rounded-input bg-primary-soft p-3"><span className="text-text-secondary">Avisos recientes</span>
            <div className="mt-1 font-medium text-text-primary">{(session.notices || []).filter((item) => ['aviso', 'error', 'error_captura'].includes(item.tipo)).length}</div>
          </div>
        </div>
      </section>

      <section className="space-y-3" aria-labelledby="live-progress-heading">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div><p className="eyebrow">CAPTURA Y PROCESAMIENTO</p>
            <h2 id="live-progress-heading" className="font-display text-xl lowercase text-text-primary">Progreso de clips</h2></div>
          {clips.length > 0 && <button onClick={() => download(`/api/live/${sessionId}/download.zip`, 'clips_en_vivo.zip')}
            className="btn-primary inline-flex items-center gap-2 text-sm"><Download size={15} /> Descargar paquete</button>}
        </div>
        {progressItems.length > 0 ? <div className="grid gap-3 xl:grid-cols-2">
          {progressItems.map((item) => {
            const pendingOrder = item.status === 'en_cola'
              ? orderLiveQueue(queue).filter((entry) => entry.status === 'en_cola').findIndex((entry) => entry.id === item.id) + 1
              : null;
            return <LiveProgressCard key={`${item.id}-${item.status}`} item={item} order={pendingOrder} now={clockNow} />;
          })}
        </div> : <div className="rounded-card border border-dashed border-border bg-surface p-6 text-center">
          <Film size={23} className="mx-auto text-text-secondary" />
          <p className="mt-2 text-sm font-medium text-text-primary">Esperando momentos destacados</p>
          <p className="mt-1 text-xs text-text-secondary">Cuando el sistema detecte un momento interesante, aparecerá aquí su progreso.</p>
        </div>}
      </section>

      {!!session.notices?.length && <section className="card p-4 sm:p-5" aria-labelledby="live-activity-heading">
        <div className="mb-3 flex items-center gap-2"><Activity size={16} className="text-primary" />
          <h2 id="live-activity-heading" className="font-display text-lg lowercase text-text-primary">Actividad reciente</h2></div>
        <ol className="space-y-2" aria-live="polite">
          {session.notices.slice(-10).reverse().map((rawNotice, index) => {
            const notice = typeof rawNotice === 'string' ? { mensaje: rawNotice } : (rawNotice || {});
            return <li key={`${notice.at || index}-${index}`} className="flex gap-2 text-xs text-text-secondary">
              {notice.tipo?.includes('error') ? <AlertTriangle size={14} className="shrink-0 text-error" />
                : notice.tipo === 'clip_completado' ? <Check size={14} className="shrink-0 text-success" />
                  : <Clock3 size={14} className="shrink-0 text-primary" />}
              <span className="min-w-0 flex-1">{notice.mensaje || notice.error || notice.tipo || 'Actividad LIVE'}</span>
              {notice.at && <time className="shrink-0 tabular-nums">{new Date(notice.at * 1000).toLocaleTimeString()}</time>}
            </li>;
          })}
        </ol>
      </section>}

      {clips.length > 0 && <section className="space-y-4" aria-labelledby="live-clips-heading">
        <h2 id="live-clips-heading" className="font-display text-xl lowercase text-text-primary">Clips de esta sesión</h2>
        <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(min(100%,520px),1fr))]">
          {clips.map((clip, index) => <div key={`${clip.source_window_id}-${clip.file}`} className="space-y-2">
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
          </div>)}
        </div>
      </section>}
    </>}

    {error && <p role="alert" className="text-sm text-error">{error}</p>}
    {authExpired && <p role="status" className="text-sm text-primary">Tu sesión ha caducado. Inicia sesión nuevamente; el backend está deteniendo la captura asociada.</p>}
    {downloadError && <p role="alert" className="text-sm text-error">{downloadError}</p>}

    {editing && <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-labelledby="live-edit-title">
      <form onSubmit={saveMetadata} className="card max-h-[90vh] w-full max-w-xl space-y-4 overflow-y-auto p-5">
        <div className="flex items-center justify-between"><h2 id="live-edit-title" className="font-display text-xl lowercase text-text-primary">Editar textos del clip</h2>
          <button type="button" onClick={() => setEditing(null)} aria-label="Cerrar" className="p-2 text-text-secondary"><X size={18} /></button></div>
        {[
          ['video_title_for_youtube_short', 'Título'], ['viral_hook_text', 'Hook'],
          ['video_description_for_tiktok', 'Descripción TikTok'], ['video_description_for_instagram', 'Descripción Instagram'],
        ].map(([key, label]) => <label key={key} className="block space-y-1 text-xs text-text-secondary">{label}
          <textarea rows={key.includes('description') ? 3 : 2} value={editing.values[key]}
            onChange={(event) => setEditing((current) => ({ ...current, values: { ...current.values, [key]: event.target.value } }))}
            className="input-field w-full resize-y text-sm text-text-primary" /></label>)}
        <div className="flex justify-end gap-2"><button type="button" className="btn-ghost" onClick={() => setEditing(null)}>Cancelar</button>
          <button disabled={savingEdit} className="btn-primary inline-flex items-center gap-2">{savingEdit && <Loader2 size={14} className="animate-spin" />} Guardar</button></div>
      </form>
    </div>}
  </section>;
}
