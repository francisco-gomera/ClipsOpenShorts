import React, { useState, useEffect } from 'react';
import { Key, Eye, EyeOff, Check } from 'lucide-react';

/**
 * API key input component – visual redesign only.
 * Props:
 *   - onKeySet(key: string) – callback when user saves a key
 *   - savedKey?: string – initial key value (may be empty)
 */
export default function KeyInput({ onKeySet, savedKey }) {
  const [key, setKey] = useState(savedKey || '');
  const [isVisible, setIsVisible] = useState(false);
  const [isSaved, setIsSaved] = useState(!!savedKey);

  useEffect(() => {
    if (savedKey) setKey(savedKey);
  }, [savedKey]);

  const handleSave = () => {
    if (key.trim().length > 0) {
      onKeySet(key);
      setIsSaved(true);
    }
  };

  return (
    <div className="card p-4 sm:p-6 mb-8 animate-fade">
      <div className="flex items-center gap-3 mb-4">
        <div className="p-2 bg-surface rounded-input text-primary">
          <Key size={18} />
        </div>
        <h2 className="font-display lowercase text-lg text-primary">Gemini API Key</h2>
      </div>

      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative sm:flex-1">
          <input
            type={isVisible ? 'text' : 'password'}
            value={key}
            onChange={(e) => {
              setKey(e.target.value);
              setIsSaved(false);
            }}
            placeholder="AIzaSy..."
            className="input-field pr-12 font-mono"
          />
          <button
            onClick={() => setIsVisible(!isVisible)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-text-secondary hover:text-primary transition-colors"
            aria-label={isVisible ? 'Hide key' : 'Show key'}
          >
            {isVisible ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>
        <button
          onClick={handleSave}
          disabled={!key || isSaved}
          className={isSaved ? 'badge-ok px-4 cursor-default' : 'btn-primary'}
        >
          {isSaved ? <><Check size={14} /> Ready</> : 'Set Key'}
        </button>
      </div>
      <p className="mt-3 text-xs text-text-secondary">
        Your key is stored locally in your browser for convenience.
        <br />
        <a
          href="https://aistudio.google.com/app/apikey"
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary hover:underline mt-1 inline-block"
        >
          Get your free Gemini API Key here →
        </a>
      </p>
    </div>
  );
}
