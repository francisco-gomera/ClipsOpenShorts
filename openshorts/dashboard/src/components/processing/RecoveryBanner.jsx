import React, { useState, useEffect } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

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
      className="p-3.5 rounded-card border-l-[3px] border border-warning/30 border-l-warning
        bg-warning/10 flex items-start gap-3 transition-colors"
      role="status"
      aria-live="polite"
      aria-label={isRateLimit ? 'AI rate limit — esperando' : 'Reintentando procesamiento'}
    >
      {/* Icon */}
      <div className="shrink-0 mt-0.5" aria-hidden="true">
        {isRateLimit ? (
          <AlertTriangle size={16} className="text-warning" />
        ) : (
          <RefreshCw size={16} className="text-warning animate-spin" />
        )}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <h4 className="text-xs font-brand font-semibold uppercase tracking-wide text-warning">
            {isRateLimit ? 'AI quota window in progress' : 'Retrying processing'}
          </h4>
          {secondsLeft > 0 && (
            <span
              className="text-xs font-brand font-bold text-warning bg-warning/10
                px-2 py-0.5 rounded border border-warning/30"
              aria-label={`${secondsLeft} segundos restantes`}
            >
              {secondsLeft}s
            </span>
          )}
        </div>
        <p className="text-xs text-warning/90 font-ui mt-1 leading-relaxed">
          {recovery.message ||
            (isRateLimit
              ? `Pacing with the AI service to avoid request saturation. Will resume automatically in ${secondsLeft}s.`
              : 'Recovering pipeline state...')}
        </p>
      </div>
    </div>
  );
}
