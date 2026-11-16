import React, { useState, useRef, useEffect } from 'react';
import { Terminal, ChevronDown, ChevronUp, Copy, Check } from 'lucide-react';

export default function CollapsibleLogs({ logs = [], defaultOpen = false }) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  const [copied, setCopied] = useState(false);
  const logContainerRef = useRef(null);

  // Auto-scroll to bottom when new logs arrive while open
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
    <div className="rounded-card border border-border bg-surface overflow-hidden">
      {/* Collapsible header */}
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
        className="w-full px-4 py-3 flex items-center justify-between text-left
          hover:bg-surface-elevated cursor-pointer transition-colors duration-150
          focus:outline-none focus:ring-2 focus:ring-primary/40 focus:ring-inset"
        aria-expanded={isOpen}
        aria-controls="system-logs-panel"
      >
        <div className="flex items-center gap-2">
          <Terminal size={14} className="text-text-secondary" aria-hidden="true" />
          <span className="text-xs font-brand font-semibold text-text-secondary uppercase tracking-widest">
            System Logs
          </span>
          <span className="text-[10px] font-ui px-1.5 py-0.5 rounded bg-surface-elevated text-text-secondary border border-border">
            {lineCount} {lineCount === 1 ? 'line' : 'lines'}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {isOpen && lineCount > 0 && (
            <button
              type="button"
              onClick={handleCopy}
              className="text-[11px] font-ui flex items-center gap-1 text-text-secondary
                hover:text-text-primary px-2 py-0.5 rounded border border-border
                hover:bg-surface-elevated transition-colors focus:outline-none focus:ring-2 focus:ring-primary/40"
              title="Copy full log"
              aria-label="Copy full log"
            >
              {copied
                ? <Check size={11} className="text-success" aria-hidden="true" />
                : <Copy size={11} aria-hidden="true" />}
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
          )}
          {isOpen
            ? <ChevronUp size={15} className="text-text-secondary" aria-hidden="true" />
            : <ChevronDown size={15} className="text-text-secondary" aria-hidden="true" />
          }
        </div>
      </div>

      {/* Log content — smooth height transition */}
      <div
        id="system-logs-panel"
        className={`transition-all duration-200 ${isOpen ? 'block' : 'hidden'}`}
      >
        <div
          ref={logContainerRef}
          className="p-3 bg-background border-t border-border max-h-[300px] overflow-y-auto
            font-mono text-[11px] leading-relaxed text-text-secondary space-y-1 select-text
            scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent"
          role="log"
          aria-live="polite"
          aria-label="Registro técnico del sistema"
        >
          {logs && logs.length > 0 ? (
            logs.map((log, index) => (
              <div key={index} className="break-all whitespace-pre-wrap">
                <span className="text-text-secondary/40 select-none mr-2" aria-hidden="true">
                  {String(index + 1).padStart(3, '0')}
                </span>
                <span>{log}</span>
              </div>
            ))
          ) : (
            <div className="text-text-secondary/60 italic py-2 text-center">
              No logs yet.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
