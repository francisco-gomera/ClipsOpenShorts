import React, { useState } from 'react';
import { Eye, EyeOff, KeyRound } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { apiJson, setToken } from '../lib/api';

export default function LocalSecurityPage({ forced = false }) {
  const { user, refreshMe } = useAuth();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [visible, setVisible] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setError('');
    setMessage('');
    if (newPassword !== confirmPassword) { setError('Las contraseñas nuevas no coinciden.'); return; }
    if (newPassword.length < 12) { setError('La nueva contraseña debe tener al menos 12 caracteres.'); return; }
    setBusy(true);
    try {
      const data = await apiJson('/api/auth/change-password', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      if (data.access_token) setToken(data.access_token);
      await refreshMe();
      setCurrentPassword(''); setNewPassword(''); setConfirmPassword('');
      setMessage('Contraseña actualizada. Las demás sesiones se cerraron.');
      if (forced) window.location.hash = '#app';
    } catch (err) {
      setError(err?.detail || err?.message || 'No se pudo cambiar la contraseña.');
    } finally { setBusy(false); }
  };

  const inputType = visible ? 'text' : 'password';
  return (
    <main className="min-h-screen bg-background text-text-secondary p-4 sm:p-8">
      <section className="card max-w-lg mx-auto p-5 sm:p-7">
        <a href="#app" className="text-xs text-text-secondary hover:text-text-primary">← Volver a MyClipper</a>
        <div className="flex items-center gap-2 mt-5"><KeyRound size={18} className="text-primary" /><h1 className="text-xl text-text-primary">{forced ? 'Cambia tu contraseña inicial' : 'Mi cuenta · Seguridad'}</h1></div>
        <p className="text-sm mt-2">Usuario: <b className="text-text-primary">{user?.username}</b></p>
        {forced && <p className="text-sm mt-4 p-3 rounded-input bg-primary-soft">Debes cambiar la contraseña temporal antes de usar la aplicación.</p>}
        <form onSubmit={submit} className="space-y-3 mt-5">
          {[['Contraseña actual', currentPassword, setCurrentPassword], ['Nueva contraseña', newPassword, setNewPassword], ['Confirmar nueva contraseña', confirmPassword, setConfirmPassword]].map(([label, value, setter]) => (
            <label key={label} className="block text-xs text-text-secondary">{label}
              <span className="relative block mt-1"><input type={inputType} autoComplete={label === 'Contraseña actual' ? 'current-password' : 'new-password'} minLength={label === 'Contraseña actual' ? 1 : 12} maxLength={128} value={value} onChange={(e) => setter(e.target.value)} className="input-field pr-10" required /><button type="button" onClick={() => setVisible((v) => !v)} aria-label={visible ? 'Ocultar contraseñas' : 'Mostrar contraseñas'} className="absolute right-3 top-1/2 -translate-y-1/2">{visible ? <EyeOff size={16} /> : <Eye size={16} />}</button></span>
            </label>
          ))}
          <p className="text-[11px] text-text-secondary">Usa al menos 12 caracteres. Cambiarla cerrará tus otras sesiones.</p>
          {error && <p role="alert" className="text-danger text-sm">{error}</p>}
          {message && <p role="status" className="text-ok text-sm">{message}</p>}
          <button disabled={busy} className="btn-primary w-full">{busy ? 'Guardando…' : 'Cambiar contraseña'}</button>
        </form>
      </section>
    </main>
  );
}
