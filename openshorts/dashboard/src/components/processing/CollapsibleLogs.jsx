import React, { useState, useRef, useEffect } from 'react';
import { Terminal, ChevronDown, ChevronUp, Copy, Check } from 'lucide-react';

export default function CollapsibleLogs({ logs = [], defaultOpen = false }) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [copied, setCopied] = useState(false);
  const logContainerRef = useRef(null);

  useEffect(() => {
    if (isOpen && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs, isOpen]);

  const handleCopy = (e) => {
    e.stopPropagation();
    if (!logs || logs.length === 0) return;
    navigator.clipboard.writeText(logs.join('\n'));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const lineCount = logs ? logs.length : 0;

  return (
    <div className="rounded-card border border-rule/70 bg-paper/60 overflow-hidden">
      {/* Cabecera interactiva */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => setIsOpen(!isOpen)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setIsOpen(!isOpen);
          }
        }}
        className="w-full px-3.5 py-2.5 flex items-center justify-between text-left hover:bg-black/5 cursor-pointer focus:outline-none focus:ring-1 focus:ring-brass transition-colors"
        aria-expanded={isOpen}
      >
        <div className="flex items-center gap-2">
          <Terminal size={14} className="text-muted" />
          <span className="text-xs font-mono font-medium text-ink2">
            Registro de ejecución técnica
          </span>
          <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-black/20 text-muted border border-rule/30">
            {lineCount} {lineCount === 1 ? 'línea' : 'líneas'}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {isOpen && lineCount > 0 && (
            <button
              type="button"
              onClick={handleCopy}
              className="text-[11px] font-mono flex items-center gap-1 text-muted hover:text-ink px-2 py-0.5 rounded border border-rule/40 hover:bg-black/10 transition-colors"
              title="Copiar registro completo"
            >
              {copied ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
              <span>{copied ? 'Copiado' : 'Copiar'}</span>
            </button>
          )}
          {isOpen ? <ChevronUp size={15} className="text-muted" /> : <ChevronDown size={15} />}
        </div>
      </div>

      {/* Contenido desplegable */}
      {isOpen && (
        <div
          ref={logContainerRef}
          className="p-3 bg-black/30 border-t border-rule/40 max-h-56 overflow-y-auto font-mono text-[11px] leading-relaxed text-ink2 space-y-1 select-text scrollbar-thin"
        >
          {logs && logs.length > 0 ? (
            logs.map((log, index) => (
              <div key={index} className="break-all whitespace-pre-wrap">
                <span className="text-muted/50 select-none mr-2">
                  {String(index + 1).padStart(3, '0')}
                </span>
                <span>{log}</span>
              </div>
            ))
          ) : (
            <div className="text-muted/60 italic py-2 text-center">
              Sin registros adicionales por el momento.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
