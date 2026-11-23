import React, { useCallback, useEffect, useState } from 'react';
import { Plus, RefreshCw, Search, Shield, UserRound, X } from 'lucide-react';
import { apiJson } from '../lib/api';

const localDateValue = (iso) => {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};

export default function AdminUsersPage() {
  const [users, setUsers] = useState([]);
  const [query, setQuery] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [activeFilter, setActiveFilter] = useState('');
  const [drafts, setDrafts] = useState({});
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState({ username: '', password: '', role: 'user', access_expires_at: '' });
  const [resetUser, setResetUser] = useState(null);
  const [resetPassword, setResetPassword] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);

  const loadUsers = useCallback(async () => {
    const params = new URLSearchParams();
    if (query) params.set('q', query);
    if (roleFilter) params.set('role', roleFilter);
    if (activeFilter) params.set('active', activeFilter);
    const data = await apiJson(`/api/admin/users?${params}`);
    setUsers(data.users || []);
    setDrafts(Object.fromEntries((data.users || []).map((u) => [u.id, {
      role: u.role, is_active: u.is_active, access_expires_at: localDateValue(u.access_expires_at),
    }])));
  }, [query, roleFilter, activeFilter]);

  useEffect(() => { loadUsers().catch((e) => setError(e?.detail || 'No se pudo cargar la lista de usuarios.')); }, [loadUsers]);

  const run = async (action, successMessage) => {
    setBusy(true); setError(''); setNotice('');
    try { await action(); await loadUsers(); setNotice(successMessage); }
    catch (e) { setError(e?.detail || e?.message || 'La operación no pudo completarse.'); }
    finally { setBusy(false); }
  };

  const updateDraft = (id, field, value) => setDrafts((old) => ({ ...old, [id]: { ...old[id], [field]: value } }));
  const saveUser = (user) => {
    const draft = drafts[user.id];
    const newRole = draft.role;
    const newActive = draft.is_active;
    if ((user.role !== newRole || user.is_active !== newActive)
        && !window.confirm(`¿Guardar los cambios de acceso para ${user.username}?`)) return;
    const expiry = draft.access_expires_at ? new Date(draft.access_expires_at).toISOString() : null;
    return run(() => apiJson(`/api/admin/users/${user.id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role: newRole, is_active: newActive, access_expires_at: expiry }),
    }), 'Usuario actualizado.');
  };

  const createUser = (event) => {
    event.preventDefault();
    if (!window.confirm(`¿Crear el usuario ${createForm.username}?`)) return;
    const expiry = createForm.access_expires_at ? new Date(createForm.access_expires_at).toISOString() : null;
    return run(async () => {
      await apiJson('/api/admin/users', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...createForm, access_expires_at: expiry }),
      });
      setCreateForm({ username: '', password: '', role: 'user', access_expires_at: '' });
      setShowCreate(false);
    }, 'Usuario creado. Deberá cambiar su contraseña al iniciar sesión.');
  };

  const resetUserPassword = (event) => {
    event.preventDefault();
    if (!window.confirm(`¿Restablecer la contraseña de ${resetUser.username}? Se cerrarán sus sesiones.`)) return;
    return run(async () => {
      await apiJson(`/api/admin/users/${resetUser.id}/reset-password`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: resetPassword }),
      });
      setResetUser(null); setResetPassword('');
    }, 'Contraseña restablecida; se exigirá el cambio al usuario.');
  };

  return (
    <main className="min-h-screen bg-background text-text-secondary p-4 sm:p-8">
      <section className="max-w-6xl mx-auto space-y-5">
        <div className="flex items-start justify-between gap-3">
          <div><a href="#app" className="text-xs hover:text-text-primary">← Volver a MyClipper</a><h1 className="text-2xl text-text-primary mt-3 flex items-center gap-2"><Shield size={20} /> Administración de usuarios</h1><p className="text-sm mt-1">Crea y gestiona cuentas. No se eliminan para conservar el historial.</p></div>
          <button onClick={() => setShowCreate((v) => !v)} className="btn-primary shrink-0"><Plus size={16} /> Crear usuario</button>
        </div>

        {error && <p role="alert" className="text-danger text-sm p-3 bg-danger/10 rounded-input">{error}</p>}
        {notice && <p role="status" className="text-ok text-sm p-3 bg-ok/10 rounded-input">{notice}</p>}

        {showCreate && <form onSubmit={createUser} className="card p-4 sm:p-5 grid sm:grid-cols-2 lg:grid-cols-5 gap-3 items-end">
          <label className="text-xs">Usuario<input required minLength="3" maxLength="32" pattern="[A-Za-z0-9_.-]+" value={createForm.username} onChange={(e) => setCreateForm({ ...createForm, username: e.target.value })} className="input-field mt-1" /></label>
          <label className="text-xs">Contraseña inicial (12+)<input required minLength="12" maxLength="128" type="password" value={createForm.password} onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })} className="input-field mt-1" /></label>
          <label className="text-xs">Rol<select value={createForm.role} onChange={(e) => setCreateForm({ ...createForm, role: e.target.value })} className="input-field mt-1"><option value="user">Usuario</option><option value="admin">Administrador</option></select></label>
          <label className="text-xs">Vencimiento (opcional)<input type="datetime-local" value={createForm.access_expires_at} onChange={(e) => setCreateForm({ ...createForm, access_expires_at: e.target.value })} className="input-field mt-1" /></label>
          <button disabled={busy} className="btn-primary">Crear</button>
          <p className="sm:col-span-2 lg:col-span-5 text-[11px]">La persona deberá cambiar esta contraseña al iniciar sesión.</p>
        </form>}

        <div className="card p-3 sm:p-4 flex flex-col sm:flex-row gap-2">
          <label className="relative flex-1"><Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2" /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar por usuario" className="input-field pl-9" /></label>
          <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)} className="input-field sm:w-44"><option value="">Todos los roles</option><option value="admin">Administradores</option><option value="user">Usuarios</option></select>
          <select value={activeFilter} onChange={(e) => setActiveFilter(e.target.value)} className="input-field sm:w-40"><option value="">Todos los estados</option><option value="true">Activos</option><option value="false">Inactivos</option></select>
          <button onClick={() => loadUsers().catch((e) => setError(e?.detail || e.message))} className="btn-ghost px-3" aria-label="Actualizar"><RefreshCw size={16} /></button>
        </div>

        <div className="space-y-3">
          {users.map((user) => {
            const draft = drafts[user.id] || {};
            const expired = user.access_expires_at && new Date(user.access_expires_at) <= new Date();
            return <article key={user.id} className="card p-4 grid gap-3 lg:grid-cols-[1.2fr_1fr_1fr_1.3fr_auto] lg:items-end">
              <div className="min-w-0"><p className="text-text-primary font-medium flex items-center gap-2"><UserRound size={15} />{user.username}</p><p className="text-[11px] mt-1">Creado: {new Date(user.created_at).toLocaleString()}</p><p className={`text-[11px] mt-1 ${!user.is_active || expired ? 'text-danger' : 'text-ok'}`}>{!user.is_active || expired ? 'Inactivo' : 'Activo'}{expired ? ' · vencido' : ''}</p></div>
              <label className="text-xs">Rol<select value={draft.role || user.role} onChange={(e) => updateDraft(user.id, 'role', e.target.value)} className="input-field mt-1"><option value="user">Usuario</option><option value="admin">Administrador</option></select></label>
              <label className="text-xs flex items-center gap-2 pb-2"><input type="checkbox" checked={!!draft.is_active} onChange={(e) => updateDraft(user.id, 'is_active', e.target.checked)} className="accent-[var(--color-accent)]" />Cuenta activa</label>
              <label className="text-xs">Vencimiento<input type="datetime-local" value={draft.access_expires_at || ''} onChange={(e) => updateDraft(user.id, 'access_expires_at', e.target.value)} className="input-field mt-1" /></label>
              <div className="flex gap-2"><button disabled={busy} onClick={() => saveUser(user)} className="btn-secondary px-3 py-2 text-xs">Guardar</button><button disabled={busy} onClick={() => { setResetUser(user); setResetPassword(''); }} className="btn-ghost px-3 py-2 text-xs">Restablecer clave</button></div>
            </article>;
          })}
          {!users.length && <div className="card p-8 text-center text-sm">No hay usuarios que coincidan con esos filtros.</div>}
        </div>
      </section>

      {resetUser && <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) setResetUser(null); }}>
        <form onSubmit={resetUserPassword} className="card p-5 w-full max-w-md space-y-3"><div className="flex justify-between"><h2 className="text-text-primary">Restablecer contraseña · {resetUser.username}</h2><button type="button" onClick={() => setResetUser(null)} aria-label="Cerrar"><X size={18} /></button></div><label className="text-xs">Nueva contraseña temporal<input autoFocus required minLength="12" maxLength="128" type="password" value={resetPassword} onChange={(e) => setResetPassword(e.target.value)} className="input-field mt-1" /></label><p className="text-xs">Se cerrarán las sesiones y el usuario deberá cambiarla en su próximo acceso.</p><button disabled={busy} className="btn-primary w-full">Restablecer</button></form>
      </div>}
    </main>
  );
}
