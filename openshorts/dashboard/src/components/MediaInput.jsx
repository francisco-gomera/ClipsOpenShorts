import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Link2, Upload, FileVideo, X, Info, Loader2, ChevronDown, CheckCircle2, Youtube, ExternalLink } from 'lucide-react';
import { track } from '../lib/analytics';
import { getApiUrl } from '../config';
import SourceCost from './SourceCost';

const SUPPORTED_PLATFORMS = [
    'YouTube', 'Vimeo', 'TikTok', 'X / Twitter', 'Twitch', 'Kick',
    'Facebook', 'Instagram', 'Dailymotion', 'Reddit', 'Streamable',
];

// Mirrors the server's MIN_SOURCE_SECONDS: shorter sources are rejected with a
// 400 after the whole file was uploaded. Checking the duration in the browser
// says so the moment the file is picked (a 27 s upload used to end in a bare
// "That run failed").
const MIN_SOURCE_SECONDS = 45;

// Duration of a local video file in seconds, or null when the browser cannot
// read it (unsupported codec): then the server stays the judge.
const readVideoDuration = (file) => new Promise((resolve) => {
    try {
        const url = URL.createObjectURL(file);
        const v = document.createElement('video');
        v.preload = 'metadata';
        const done = (d) => { URL.revokeObjectURL(url); resolve(d); };
        v.onloadedmetadata = () => done(Number.isFinite(v.duration) ? v.duration : null);
        v.onerror = () => done(null);
        setTimeout(() => done(null), 8000);
        v.src = url;
    } catch { resolve(null); }
});

export default function MediaInput({ onProcess, isProcessing }) {
    const [youtubeUrlEnabled, setYoutubeUrlEnabled] = useState(true);
    // File upload is the primary path; the link is secondary.
    const [mode, setMode] = useState('file'); // 'file' | 'url'
    const [url, setUrl] = useState('');
    const [file, setFile] = useState(null);
    const [fileSeconds, setFileSeconds] = useState(null);
    const fileTooShort = fileSeconds != null && fileSeconds < MIN_SOURCE_SECONDS;
    const [acknowledged, setAcknowledged] = useState(false);
    // {start, end} in seconds when the user picked a stretch under the cost line.
    const [range, setRange] = useState(null);
    const [outputFormat, setOutputFormat] = useState('vertical'); // vertical | horizontal | square
    const [showInfo, setShowInfo] = useState(false);
    // Advanced generation controls — empty string means "let the AI decide",
    // which keeps the default pipeline behavior untouched.
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [targetClips, setTargetClips] = useState('');
    const [clipMinSeconds, setClipMinSeconds] = useState('');
    const [clipMaxSeconds, setClipMaxSeconds] = useState('');
    const [generationMode, setGenerationMode] = useState('smart');
    const [sequentialCount, setSequentialCount] = useState('3');
    const [sequentialSeconds, setSequentialSeconds] = useState('60');
    const [manualSegments, setManualSegments] = useState([{ start: '0', end: '30' }]);
    const [manualSegmentIndex, setManualSegmentIndex] = useState(0);
    const [playheadSeconds, setPlayheadSeconds] = useState(0);
    // Auto-hook: burn the AI hook text into every clip. On by default; the
    // choice persists so turning it off sticks across sessions.
    const [autoHook, setAutoHook] = useState(() => {
        try { return localStorage.getItem('os_auto_hook') !== '0'; } catch { return true; }
    });
    const [autoHookStyle, setAutoHookStyle] = useState(() => {
        try { return localStorage.getItem('os_auto_hook_style_v2') || 'classic'; } catch { return 'classic'; }
    });
    // Layout: 'auto' lets the AI pick per video (server default); the others
    // force one on so a podcast host who knows what they uploaded doesn't
    // depend on the detector, and 'none' keeps the plain single crop.
    const [layout, setLayout] = useState(() => {
        try { return localStorage.getItem('os_layout') || 'auto'; } catch { return 'auto'; }
    });
    const [previewUrl, setPreviewUrl] = useState(null);

    useEffect(() => {
        if (!file) {
            setPreviewUrl(null);
            return;
        }
        const objUrl = URL.createObjectURL(file);
        setPreviewUrl(objUrl);
        return () => {
            URL.revokeObjectURL(objUrl);
        };
    }, [file]);

    const ytId = useMemo(() => {
        if (mode !== 'url' || !url) return null;
        const m = url.match(/(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))([\w-]{11})/);
        return m ? m[1] : null;
    }, [mode, url]);

    const infoRef = useRef(null);

    // Close the compatibility popover on any outside click.
    useEffect(() => {
        if (!showInfo) return;
        const onClick = (e) => {
            if (infoRef.current && !infoRef.current.contains(e.target)) setShowInfo(false);
        };
        document.addEventListener('mousedown', onClick);
        return () => document.removeEventListener('mousedown', onClick);
    }, [showInfo]);

    useEffect(() => {
        let cancelled = false;
        setFileSeconds(null);
        if (!file) return undefined;
        readVideoDuration(file).then((d) => {
            if (cancelled) return;
            setFileSeconds(d);
            if (d != null && d < MIN_SOURCE_SECONDS) {
                track('SourceTooShort', { props: { seconds: String(Math.round(d)) } });
            }
        });
        return () => { cancelled = true; };
    }, [file]);

    useEffect(() => {
        fetch(getApiUrl('/api/config'))
            .then((r) => r.ok ? r.json() : null)
            .then((cfg) => {
                if (cfg && cfg.youtubeUrlEnabled === false) {
                    setYoutubeUrlEnabled(false);
                    setMode('file');
                }
            })
            .catch(() => {});
    }, []);

    // A link pasted in the landing hero: preload it here so the user picks up
    // where they left off. Not auto-submitted — the rights attestation below
    // has to be ticked by the user.
    useEffect(() => {
        let pending = null;
        try {
            pending = localStorage.getItem('os_pending_url');
            if (pending) localStorage.removeItem('os_pending_url');
        } catch { /* ignore */ }
        if (pending) {
            setMode('url');
            setUrl(pending);
        }
    }, []);

    const handleSubmit = (e) => {
        e.preventDefault();
        if (!acknowledged) return;
        const advanced = {
            generationMode,
            sequentialCount: generationMode === 'sequential' ? sequentialCount : null,
            sequentialSeconds: generationMode === 'sequential' ? sequentialSeconds : null,
            manualSegments: generationMode === 'manual'
                ? manualSegments.map((s) => ({ start: Number(s.start), end: Number(s.end) })) : null,
            targetClips: targetClips || null,
            clipMinSeconds: clipMinSeconds || null,
            clipMaxSeconds: clipMaxSeconds || null,
            autoHook,
            autoHookStyle,
            layout,
            sourceStart: range ? Math.round(range.start) : null,
            sourceEnd: range ? Math.round(range.end) : null,
        };
        try {
            localStorage.setItem('os_auto_hook', autoHook ? '1' : '0');
            localStorage.setItem('os_auto_hook_style_v2', autoHookStyle);
            localStorage.setItem('os_layout', layout);
        } catch { /* ignore */ }
        if (mode === 'url' && url) {
            onProcess({ type: 'url', payload: url, acknowledged: true, outputFormat, ...advanced });
        } else if (mode === 'file' && file && !fileTooShort) {
            onProcess({ type: 'file', payload: file, acknowledged: true, outputFormat, ...advanced });
        }
    };

    const handleDrop = (e) => {
        e.preventDefault();
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            setFile(e.dataTransfer.files[0]);
            setMode('file');
        }
    };

    return (
        <div className="card p-4 sm:p-6 animate-fade">
            <div className="flex gap-4 sm:gap-6 mb-6 border-b border-border" data-tutorial="source-tabs">
                <button
                    onClick={() => setMode('file')}
                    className={`flex items-center gap-2 pb-3 px-1 -mb-px border-b-2 text-sm lowercase whitespace-nowrap transition-colors ${mode === 'file'
                        ? 'text-text-primary border-primary'
                        : 'text-text-secondary border-transparent hover:text-text-secondary'
                        }`}
                >
                    <Upload size={16} className={`hidden sm:block ${mode === 'file' ? 'text-text-primary' : ''}`} />
                    Subir archivo
                </button>
                {youtubeUrlEnabled && (
                    <button
                        onClick={() => setMode('url')}
                        className={`flex items-center gap-2 pb-3 px-1 -mb-px border-b-2 text-sm lowercase whitespace-nowrap transition-colors ${mode === 'url'
                            ? 'text-text-primary border-primary'
                            : 'text-text-secondary border-transparent hover:text-text-secondary'
                            }`}
                    >
                        <Link2 size={16} className={`hidden sm:block ${mode === 'url' ? 'text-text-primary' : ''}`} />
                        URL de vídeo
                    </button>
                )}
            </div>

            <form onSubmit={handleSubmit}>
                {mode === 'url' ? (
                    <div className="space-y-4" data-tutorial="drop-zone">
                        <div className="relative">
                            <input
                                type="url"
                                value={url}
                                onChange={(e) => setUrl(e.target.value)}
                                placeholder="https://... pega un enlace de vídeo"
                                className="input-field pr-11"
                                required
                            />
                            <div className="absolute inset-y-0 right-2 flex items-center" ref={infoRef}>
                                <button
                                    type="button"
                                    onClick={() => setShowInfo((v) => !v)}
                                    aria-label="Plataformas compatibles"
                                    className="p-1.5 text-text-secondary hover:text-text-primary transition-colors"
                                >
                                    <Info size={16} />
                                </button>
                                {showInfo && (
                                    <div className="absolute right-0 top-full mt-2 w-64 z-20 card p-4 text-left animate-fade">
                                        <p className="eyebrow mb-2">Pega un enlace de</p>
                                        <div className="flex flex-wrap gap-1.5">
                                            {SUPPORTED_PLATFORMS.map((p) => (
                                                <span key={p} className="text-xs px-2 py-0.5 rounded-full bg-primary-soft text-text-secondary">
                                                    {p}
                                                </span>
                                            ))}
                                        </div>
                                        <p className="text-xs text-text-secondary mt-2.5 leading-relaxed">
                                            …y más de 1.000 sitios. Si el enlace contiene un vídeo público, generalmente podemos procesarlo.
                                        </p>
                                    </div>
                                )}
                            </div>
                        </div>
                        {/* URL Media Preview */}
                        {ytId && (
                            <div className="rounded-card overflow-hidden bg-surface border border-border p-3 animate-fade flex flex-col sm:flex-row gap-3 items-center">
                                <div className="relative w-full sm:w-44 h-28 rounded-input overflow-hidden bg-black shrink-0">
                                    <iframe
                                        src={`https://www.youtube-nocookie.com/embed/${ytId}`}
                                        title="Vista previa del vídeo de YouTube"
                                        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                                        referrerPolicy="strict-origin-when-cross-origin"
                                        className="w-full h-full border-0"
                                    />
                                    <span className="absolute bottom-1 right-1 px-1.5 py-0.5 rounded bg-black/80 text-[10px] text-white flex items-center gap-1 font-mono">
                                        <Youtube size={11} className="text-danger" /> YouTube
                                    </span>
                                </div>
                                <div className="min-w-0 flex-1 text-left space-y-1">
                                    <p className="text-xs font-semibold text-ok flex items-center gap-1.5">
                                        <CheckCircle2 size={14} /> Vídeo identificado
                                    </p>
                                    <p className="text-xs text-text-secondary truncate">{url}</p>
                                    <a
                                        href={url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="text-xs text-text-primary hover:underline inline-flex items-center gap-1 pt-1"
                                    >
                                        Abrir enlace de origen <ExternalLink size={12} />
                                    </a>
                                </div>
                            </div>
                        )}
                    </div>
                ) : (
                    <div
                        data-tutorial="drop-zone"
                        className={`border-2 border-dashed rounded-card p-4 sm:p-6 text-center transition-colors ${file ? 'border-primary bg-surface' : 'border-border hover:border-primary'
                            }`}
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={handleDrop}
                    >
                        {file ? (
                            <div className="space-y-3">
                                <div className="flex flex-col sm:flex-row gap-3 items-center">
                                    {previewUrl && (
                                        <video
                                            src={previewUrl}
                                            controls
                                            onTimeUpdate={(e) => setPlayheadSeconds(e.currentTarget.currentTime)}
                                            className="w-full sm:w-44 h-28 object-contain rounded-input bg-black shrink-0"
                                            preload="metadata"
                                        />
                                    )}
                                    <div className="min-w-0 flex-1 text-left space-y-1">
                                        <div className="flex items-center gap-2">
                                            <FileVideo size={16} className="text-text-primary shrink-0" />
                                            <span className="font-medium text-sm text-text-primary truncate">{file.name}</span>
                                        </div>
                                        <p className="text-xs text-text-secondary">
                                            {(file.size / (1024 * 1024)).toFixed(1)} MB
                                            {fileSeconds != null ? ` · ${Math.round(fileSeconds)}s duration` : ''}
                                        </p>
                                        <button
                                            type="button"
                                            onClick={() => setFile(null)}
                                            className="text-xs text-danger hover:underline pt-1 flex items-center gap-1"
                                        >
                                            <X size={12} /> Eliminar y elegir otro
                                        </button>
                                    </div>
                                </div>
                            </div>
                        ) : null}
                        {file && fileTooShort ? (
                            <p className="text-danger text-sm mt-3" role="alert">
                                Este vídeo dura {Math.round(fileSeconds)}s. La generación de clips necesita al menos {MIN_SOURCE_SECONDS}s
                                de metraje para cortar: ya es un vídeo corto. Elige un vídeo más largo.
                            </p>
                        ) : null}
                        {!file && (
                            <label className="cursor-pointer block py-4">
                                <input
                                    type="file"
                                    accept="video/*"
                                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                                    className="hidden"
                                />
                                <Upload className="mx-auto mb-3 text-text-secondary" size={24} />
                                <p className="text-text-primary font-medium text-sm">Haz clic para subir o arrastra y suelta aquí</p>
                                <p className="readout mt-1.5 text-xs text-text-secondary">MP4, MOV hasta 500 MB · al menos {MIN_SOURCE_SECONDS}s de duración</p>
                            </label>
                        )}
                    </div>
                )}

                <SourceCost
                    mode={mode}
                    url={url}
                    fileSeconds={fileSeconds}
                    range={range}
                    onRangeChange={setRange}
                />

                {/* Output format selector */}
                <div className="mt-5" data-tutorial="output-format">
                    <p className="eyebrow mb-2">Formato de salida</p>
                    <div className="grid grid-cols-3 gap-2">
                        {[
                            { value: 'vertical', label: '9:16', hint: 'Shorts · Reels · TikTok', w: 18, h: 32 },
                            { value: 'square', label: '1:1', hint: 'Publicaciones feed', w: 28, h: 28 },
                            { value: 'horizontal', label: '16:9', hint: 'Horizontal · YouTube', w: 36, h: 20 },
                        ].map((f) => {
                            const active = outputFormat === f.value;
                            return (
                                <button
                                    key={f.value}
                                    type="button"
                                    onClick={() => setOutputFormat(f.value)}
                                    className={`py-3 px-2 rounded-input border flex flex-col items-center gap-2 transition-colors
                                        ${active ? 'border-[color:var(--color-accent)] text-text-primary' : 'border-border text-text-secondary hover:border-[color:var(--color-accent)]'}`}
                                >
                                    {/* Aspect-ratio glyph */}
                                    <span
                                        className="rounded-[3px] border-2 transition-colors"
                                        style={{
                                            width: `${f.w}px`,
                                            height: `${f.h}px`,
                                            borderColor: active ? 'var(--color-accent)' : 'var(--color-rule-2)',
                                            backgroundColor: active ? 'color-mix(in srgb, var(--color-accent) 22%, transparent)' : 'transparent',
                                        }}
                                    />
                                    <span className="block font-mono text-sm leading-none">{f.label}</span>
                                    <span className="block text-[11px] sm:text-[10px] leading-tight text-center text-text-secondary">{f.hint}</span>
                                </button>
                            );
                        })}
                    </div>
                </div>

                {/* Advanced generation controls — collapsed by default; blank = AI decides */}
                <div className="mt-5">
                    <p className="eyebrow mb-2">Modo de generación</p>
                    <div className="grid grid-cols-2 gap-2">
                        {[
                            ['smart', 'Inteligente', 'La IA encuentra los mejores momentos'],
                            ['sequential', 'Consecutivos', 'Divide el vídeo en partes iguales'],
                            ['full', 'Vídeo completo', 'Convierte todo el vídeo'],
                            ['manual', 'Selección manual', 'Elige los tiempos de cada clip'],
                        ].map(([value, label, hint]) => (
                            <button key={value} type="button" onClick={() => setGenerationMode(value)}
                                aria-pressed={generationMode === value}
                                className={`rounded-input border p-3 text-left transition-colors ${generationMode === value ? 'border-primary bg-surface' : 'border-border hover:border-primary'}`}>
                                <span className="block text-sm font-medium">{label}</span>
                                <span className="block text-[11px] text-text-secondary mt-1">{hint}</span>
                            </button>
                        ))}
                    </div>
                    {generationMode === 'sequential' && (
                        <div className="grid grid-cols-2 gap-3 mt-3">
                            <label className="text-xs text-text-secondary">Cantidad de clips<input type="number" min="1" max="15" step="1" value={sequentialCount} onChange={(e) => setSequentialCount(e.target.value)} className="input-field mt-1" /></label>
                            <label className="text-xs text-text-secondary">Duración de cada clip (s)<input type="number" min="5" max="240" value={sequentialSeconds} onChange={(e) => setSequentialSeconds(e.target.value)} className="input-field mt-1" /></label>
                        </div>
                    )}
                    {generationMode === 'manual' && (
                        <div className="mt-3 space-y-2">
                            <p className="text-xs text-text-secondary">Indica inicio y final en segundos (clips de 5 a 240 s, sin solaparse).</p>
                            {(previewUrl || ytId) && <p className="text-xs text-text-secondary">Reproduce o busca el vídeo arriba{previewUrl ? ` (${playheadSeconds.toFixed(1)} s)` : ''} y fija el inicio o final del clip seleccionado.</p>}
                            {manualSegments.map((segment, index) => (
                                <div onClick={() => setManualSegmentIndex(index)} className={`grid grid-cols-[1fr_1fr_auto] gap-2 items-end rounded-input p-1 ${manualSegmentIndex === index ? 'bg-surface' : ''}`} key={index}>
                                    <label className="text-xs text-text-secondary">Inicio (s)<input type="number" min="0" step="0.1" value={segment.start} onChange={(e) => setManualSegments((all) => all.map((s, i) => i === index ? { ...s, start: e.target.value } : s))} className="input-field mt-1" /></label>
                                    <label className="text-xs text-text-secondary">Final (s)<input type="number" min="0" step="0.1" value={segment.end} onChange={(e) => setManualSegments((all) => all.map((s, i) => i === index ? { ...s, end: e.target.value } : s))} className="input-field mt-1" /></label>
                                    <button type="button" aria-label="Eliminar segmento" disabled={manualSegments.length === 1} onClick={() => setManualSegments((all) => all.filter((_, i) => i !== index))} className="btn-secondary px-3 py-2">×</button>
                                </div>
                            ))}
                            {previewUrl && <div className="flex gap-2"><button type="button" onClick={() => setManualSegments((all) => all.map((s, i) => i === manualSegmentIndex ? { ...s, start: playheadSeconds.toFixed(1) } : s))} className="btn-secondary px-3 py-2 text-xs">Fijar inicio actual</button><button type="button" onClick={() => setManualSegments((all) => all.map((s, i) => i === manualSegmentIndex ? { ...s, end: playheadSeconds.toFixed(1) } : s))} className="btn-secondary px-3 py-2 text-xs">Fijar final actual</button></div>}
                            <button type="button" disabled={manualSegments.length >= 15} onClick={() => setManualSegments((all) => [...all, { start: '', end: '' }])} className="text-xs text-text-primary hover:underline">+ Añadir clip</button>
                        </div>
                    )}
                    {generationMode === 'smart' && <p className="text-[11px] text-text-secondary mt-2">El modo inteligente conserva los controles y resultados actuales.</p>}
                </div>

                {/* Advanced generation controls — collapsed by default; blank = AI decides */}
                <div className="mt-4">
                    <button
                        type="button"
                        onClick={() => setShowAdvanced((v) => !v)}
                        className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-secondary lowercase transition-colors"
                    >
                        <ChevronDown size={14} className={`transition-transform ${showAdvanced ? 'rotate-180' : ''}`} />
                        opciones avanzadas
                        {(targetClips || clipMinSeconds || clipMaxSeconds || !autoHook) && (
                            <span className="text-text-primary">·</span>
                        )}
                    </button>
                    {showAdvanced && generationMode === 'smart' && (
                        /* Stacked on a phone: three number fields side by side leaves
                           ~100px each, which crushes both label and value. */
                        <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-2 animate-fade">
                            <div>
                                <p className="eyebrow mb-1.5">clips objetivo</p>
                                <input
                                    type="number" min="1" max="15" step="1"
                                    value={targetClips}
                                    onChange={(e) => setTargetClips(e.target.value)}
                                    placeholder="auto"
                                    className="input-field"
                                />
                            </div>
                            <div>
                                <p className="eyebrow mb-1.5">duración mín. (s)</p>
                                <input
                                    type="number" min="5" max="235" step="1"
                                    value={clipMinSeconds}
                                    onChange={(e) => setClipMinSeconds(e.target.value)}
                                    placeholder="15"
                                    className="input-field"
                                />
                            </div>
                            <div>
                                <p className="eyebrow mb-1.5">duración máx. (s)</p>
                                <input
                                    type="number" min="10" max="240" step="1"
                                    value={clipMaxSeconds}
                                    onChange={(e) => setClipMaxSeconds(e.target.value)}
                                    placeholder="60"
                                    className="input-field"
                                />
                            </div>
                            <p className="col-span-1 sm:col-span-3 text-[11px] leading-relaxed text-text-secondary">
                                Objetivos, no garantías: la IA devuelve menos clips si el
                                material no los tiene. Deja en blanco para que decida automáticamente.
                            </p>
                            <div className="col-span-1 sm:col-span-3 flex flex-wrap items-center justify-between gap-3 pt-3 sm:pt-1 border-t border-border">
                                <span className="text-xs text-text-secondary">diseño vertical</span>
                                <select
                                    value={layout}
                                    onChange={(e) => setLayout(e.target.value)}
                                    className="input-field !w-auto text-xs py-1.5"
                                    aria-label="diseño vertical"
                                >
                                    <option value="auto">Auto (la IA elige por vídeo)</option>
                                    <option value="split">Dos personas apiladas</option>
                                    <option value="screencast">Pantalla sobre presentador</option>
                                    <option value="none">Recorte único</option>
                                </select>
                            </div>
                            <div className="col-span-1 sm:col-span-3 flex flex-wrap items-center justify-between gap-3 pt-3 sm:pt-1 border-t border-border">
                                <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer select-none">
                                    <input
                                        type="checkbox"
                                        checked={autoHook}
                                        onChange={(e) => setAutoHook(e.target.checked)}
                                        className="w-4 h-4 shrink-0 accent-[var(--color-accent)] cursor-pointer"
                                    />
                                    títulos de gancho automáticos en clips
                                </label>
                                {autoHook && (
                                    <select
                                        value={autoHookStyle}
                                        onChange={(e) => setAutoHookStyle(e.target.value)}
                                        className="input-field !w-auto text-xs py-1.5"
                                    >
                                        <option value="classic">Clásico</option>
                                        <option value="pill">Píldora</option>
                                        <option value="dark">Oscuro</option>
                                        <option value="yellow">Amarillo</option>
                                        <option value="red">Rojo</option>
                                        <option value="outline">Contorno</option>
                                        <option value="outline_yellow">Contorno amarillo</option>
                                    </select>
                                )}
                                {autoHook && (
                                    <p className="w-full text-[11px] leading-relaxed text-text-secondary">
                                        Puedes cambiar el texto, estilo, posición y tamaño del gancho de cada clip
                                        más tarde con su botón de gancho.
                                    </p>
                                )}
                            </div>
                        </div>
                    )}
                </div>

                <label className="flex items-start gap-2.5 mt-5 text-left text-[13px] sm:text-xs leading-relaxed text-text-secondary cursor-pointer select-none">
                    <input
                        type="checkbox"
                        checked={acknowledged}
                        onChange={(e) => setAcknowledged(e.target.checked)}
                        className="mt-0.5 w-4 h-4 shrink-0 accent-[var(--color-accent)] cursor-pointer"
                    />
                    <span>
                        Confirmo que soy el propietario de este contenido o tengo los derechos para procesarlo. Soy responsable de cualquier contenido que envíe. Consulta nuestros <a href="/terms" target="_blank" rel="noopener noreferrer" className="text-text-secondary underline underline-offset-2 hover:text-text-primary transition-colors" onClick={(e) => e.stopPropagation()}>Términos</a> y <a href="/privacy" target="_blank" rel="noopener noreferrer" className="text-text-secondary underline underline-offset-2 hover:text-text-primary transition-colors" onClick={(e) => e.stopPropagation()}>Política de Privacidad</a>.
                    </span>
                </label>

                <button
                    type="submit"
                    data-tutorial="generate"
                    disabled={isProcessing || !acknowledged || (mode === 'url' && !url) || (mode === 'file' && (!file || fileTooShort))}
                    className="w-full btn-primary mt-4"
                >
                    {isProcessing ? (
                        <>
                            <Loader2 size={16} className="animate-spin" />
                            Procesando vídeo...
                        </>
                    ) : (
                        <>
                            Generar clips
                        </>
                    )}
                </button>
            </form>
        </div>
    );
}
