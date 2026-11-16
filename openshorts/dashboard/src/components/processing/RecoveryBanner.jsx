import React, { useState, useEffect } from 'react';
import { Clock, RefreshCw, AlertCircle } from 'lucide-react';

export default function RecoveryBanner({ recovery }) {
  const isRateLimit = recovery?.state === 'waiting_rate_limit';
  const retryAt = recovery?.retry_at;

  const [secondsLeft, setSecondsLeft] = useState(() => {
    if (retryAt) {
      const diff = Math.ceil(retryAt - Date.now() / 1000);
      return Math.max(0, diff);
    }
    return 0;
  });

  useEffect(() => {
    if (!retryAt) return;
    const interval = setInterval(() => {
      const diff = Math.ceil(retryAt - Date.now() / 1000);
      setSecondsLeft(Math.max(0, diff));
    }, 500);
    return () => clearInterval(interval);
  }, [retryAt]);

  if (!recovery || recovery.state === 'normal') return null;

  return (
    <div
      className={`p-3.5 rounded-card border flex items-start gap-3 transition-colors ${
        isRateLimit
          ? 'bg-amber-500/10 border-amber-500/30 text-amber-200'
          : 'bg-sky-500/10 border-sky-500/30 text-sky-200'
      }`}
      role="status"
      aria-live="polite"
    >
      <div className="p-1 rounded bg-black/20 shrink-0 mt-0.5">
        {isRateLimit ? (
          <Clock size={16} className="text-amber-400 animate-pulse" />
        ) : (
          <RefreshCw size={16} className="text-sky-400 animate-spin" />
        )}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <h4 className="text-xs font-semibold tracking-wide uppercase font-mono">
            {isRateLimit ? 'Ventana de cuota de IA en curso' : 'Reintentando procesamiento'}
          </h4>
          {secondsLeft > 0 && (
            <span className="text-xs font-mono font-bold bg-amber-500/20 px-2 py-0.5 rounded border border-amber-500/30">
              {secondsLeft}s
            </span>
          )}
        </div>
        <p className="text-xs opacity-90 mt-1">
          {recovery.message ||
            (isRateLimit
              ? `Ajustando ritmo con el servicio de IA para evitar saturación de solicitudes. El proceso se reanudará automáticamente en ${secondsLeft}s.`
              : 'Recuperando estado de la canalización...')}
        </p>
      </div>
    </div>
  );
}
