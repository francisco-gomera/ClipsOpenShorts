import React, { useState } from 'react';
import { KeyRound, LogOut, Shield, UserRound } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';

export default function LocalProfileMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  if (!user) return null;
  return (
    <div className="relative">
      <button onClick={() => setOpen((v) => !v)} aria-label="Menú de cuenta" className="w-8 h-8 rounded-full bg-primary-soft border border-border text-primary flex items-center justify-center text-sm font-medium">{(user.username || '?').slice(0, 1).toUpperCase()}</button>
      {open && <div className="absolute right-0 top-full mt-2 w-56 z-30 overflow-hidden bg-surface-elevated border border-border rounded-input">
        <div className="px-4 py-3 border-b border-border"><p className="eyebrow">Sesión iniciada</p><p className="text-sm text-text-primary truncate">{user.username}</p><p className="text-[11px] text-text-secondary">{user.role === 'admin' ? 'Administrador' : 'Usuario'}</p></div>
        <a href="#/security" onClick={() => setOpen(false)} className="w-full flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-paper3"><KeyRound size={15} /> Seguridad</a>
        {user.role === 'admin' && <a href="#/admin/users" onClick={() => setOpen(false)} className="w-full flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-paper3"><Shield size={15} /> Administración de usuarios</a>}
        <button onClick={() => { setOpen(false); logout(); }} className="w-full flex items-center gap-3 px-4 py-2.5 text-sm border-t border-border hover:bg-paper3"><LogOut size={15} /> Cerrar sesión</button>
      </div>}
    </div>
  );
}
