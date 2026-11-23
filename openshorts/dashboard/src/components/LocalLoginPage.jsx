import React, { useState } from 'react';
import { Lock, UserRound, Loader2 } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { brandConfig } from '../brand.config.js';

export default function LocalLoginPage() {
  const { loginLocal, authExpired } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await loginLocal(username.trim(), password);
      window.location.hash = '#app';
    } catch (err) {
      setError(err?.detail || err?.message || 'No se pudo iniciar sesión.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="min-h-screen bg-background text-text-secondary flex items-center justify-center p-5">
      <form onSubmit={submit} className="card w-full max-w-sm p-6 sm:p-8 space-y-4">
        <h1 className="font-brand text-2xl text-text-primary text-center" style={{ fontFamily: 'var(--font-brand)' }}>{brandConfig.name}</h1>
        {authExpired && <p role="status" className="text-sm text-center text-primary">Tu sesión ha caducado. Inicia sesión nuevamente.</p>}
        <p className="text-sm text-center">Inicia sesión para continuar</p>
        <label className="block text-xs text-text-secondary">Usuario
          <span className="relative block mt-1"><UserRound size={16} className="absolute left-3 top-1/2 -translate-y-1/2" /><input autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} className="input-field pl-9" required /></span>
        </label>
        <label className="block text-xs text-text-secondary">Contraseña
          <span className="relative block mt-1"><Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2" /><input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className="input-field pl-9" required /></span>
        </label>
        {error && <p role="alert" className="text-danger text-sm">{error}</p>}
        <button type="submit" disabled={busy || !username || !password} className="btn-primary w-full">
          {busy ? <><Loader2 size={16} className="animate-spin" /> Iniciando sesión…</> : 'Iniciar sesión'}
        </button>
      </form>
    </main>
  );
}
