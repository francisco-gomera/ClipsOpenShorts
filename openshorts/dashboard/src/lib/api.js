// Centralized API client for cloud mode.
// Adds the Authorization: Bearer header from the stored session token, and turns
// a 402 (quota exceeded) into a typed QuotaError the UI can catch to prompt a top-up.
import { getApiUrl } from '../config.js';

export const AUTH_TOKEN_KEY = 'openshorts_auth';
export const AUTH_EXPIRED_EVENT = 'os:auth-expired';

export const getToken = () => localStorage.getItem(AUTH_TOKEN_KEY) || '';
let expirationNotified = false;
export const setToken = (t) => {
  expirationNotified = false;
  localStorage.setItem(AUTH_TOKEN_KEY, t);
};
export const clearToken = () => localStorage.removeItem(AUTH_TOKEN_KEY);

let localAuthEnabled = false;
let managedAuthEnabled = false;
let refreshingAccess = null;
export const setLocalAuthEnabled = (enabled) => { localAuthEnabled = !!enabled; };
export const setManagedAuthEnabled = (enabled) => { managedAuthEnabled = !!enabled; };

function notifyAuthExpired() {
  clearToken();
  if (expirationNotified) return;
  expirationNotified = true;
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT, {
      detail: { message: 'Tu sesión ha caducado. Inicia sesión nuevamente.' },
    }));
  }
}

export function refreshLocalAccessResult() {
  if (!localAuthEnabled) return Promise.resolve({ status: 'unavailable' });
  if (!refreshingAccess) {
    const pending = fetch(getApiUrl('/api/auth/refresh'), {
      method: 'POST', credentials: 'include',
    }).then(async (res) => {
      if (res.status === 401) return { status: 'expired' };
      if (!res.ok) return { status: 'unavailable' };
      const data = await res.json();
      if (!data.access_token) return { status: 'expired' };
      setToken(data.access_token);
      return { status: 'ok' };
    }).catch(() => ({ status: 'unavailable' })).finally(() => {
      if (refreshingAccess === pending) refreshingAccess = null;
    });
    refreshingAccess = pending;
  }
  return refreshingAccess;
}

export async function refreshLocalAccess() {
  return (await refreshLocalAccessResult()).status === 'ok';
}

export class QuotaError extends Error {
  constructor(detail) {
    super('quota_exceeded');
    this.name = 'QuotaError';
    this.minutesRequired = detail?.minutes_required;
    this.minutesRemaining = detail?.minutes_remaining;
    // Minutes of the source the server offers to clip instead (0 = no offer).
    this.partialMinutes = Number(detail?.partial_minutes) || 0;
  }
}

// A 402 caught outside the main clip flow (thumbnails, clip editor, autopilot):
// ask the app shell to open the quota wall instead of a dead-end error. `source`
// tags CheckoutStarted so each surface can be measured.
export const QUOTA_WALL_EVENT = 'os:quota-wall';
export function openQuotaWall(err, source) {
  try {
    window.dispatchEvent(new CustomEvent(QUOTA_WALL_EVENT, {
      detail: { required: err?.minutesRequired, remaining: err?.minutesRemaining, source },
    }));
  } catch (_) { /* ignore */ }
}

// Drop-in fetch wrapper. Always attaches the bearer token when present.
export async function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const fetchOptions = { ...options, headers };
  if (localAuthEnabled && fetchOptions.credentials == null) fetchOptions.credentials = 'include';
  let res = await fetch(getApiUrl(path), fetchOptions);

  const authEndpoint = ['/api/auth/login', '/api/auth/refresh', '/api/auth/logout',
    '/api/auth/review-login', '/api/auth/magic-link', '/api/auth/magic-link/verify',
    '/api/auth/google', '/api/auth/exchange'].some((item) => path.split('?')[0] === item);
  if (res.status === 401 && !authEndpoint && localAuthEnabled) {
    const refresh = await refreshLocalAccessResult();
    if (refresh.status === 'ok') {
      headers.set('Authorization', `Bearer ${getToken()}`);
      res = await fetch(getApiUrl(path), fetchOptions);
      if (res.status === 401) notifyAuthExpired();
    } else if (refresh.status === 'expired') {
      notifyAuthExpired();
    }
  } else if (res.status === 401 && !authEndpoint && managedAuthEnabled) {
    notifyAuthExpired();
  }

  if (res.status === 402) {
    let detail = {};
    try {
      const body = await res.clone().json();
      detail = body.detail || body;
    } catch (_) { /* ignore */ }
    throw new QuotaError(detail);
  }
  return res;
}

// Upload files with real XMLHttpRequest upload.onprogress tracking
export function apiUpload(path, body, options = {}, onProgress = null, retryAuth = true) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const url = getApiUrl(path);

    xhr.open(options.method || 'POST', url);
    if (localAuthEnabled) xhr.withCredentials = true;

    const token = getToken();
    if (token) {
      xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    }

    if (options.headers) {
      for (const [key, value] of Object.entries(options.headers)) {
        if (key.toLowerCase() !== 'content-type') {
          xhr.setRequestHeader(key, value);
        }
      }
    }

    if (xhr.upload && onProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          const percent = (event.loaded / event.total) * 100;
          onProgress({
            percent: Math.round(percent * 10) / 10,
            loaded: event.loaded,
            total: event.total,
          });
        }
      };
    }

    xhr.onload = () => {
      const status = xhr.status;
      const resText = xhr.responseText;
      let data = null;
      try {
        data = JSON.parse(resText);
      } catch (_) {
        data = resText;
      }

      if (status === 402) {
        reject(new QuotaError(typeof data === 'object' ? data?.detail || data : {}));
        return;
      }

      if (status === 401 && retryAuth && localAuthEnabled) {
        refreshLocalAccessResult().then((refresh) => {
          if (refresh.status === 'ok') apiUpload(path, body, options, onProgress, false).then(resolve, reject);
          else {
            if (refresh.status === 'expired') notifyAuthExpired();
            reject(new ApiError(401, refresh.status === 'expired'
              ? 'Tu sesión ha caducado. Inicia sesión nuevamente.'
              : 'No se pudo verificar tu sesión. Comprueba la conexión e inténtalo de nuevo.', resText));
          }
        });
        return;
      }

      if (status === 401 && !retryAuth && (localAuthEnabled || managedAuthEnabled)) {
        notifyAuthExpired();
      } else if (status === 401 && managedAuthEnabled) {
        notifyAuthExpired();
      }

      if (status >= 200 && status < 300) {
        resolve({
          ok: true,
          status,
          json: async () => (typeof data === 'object' ? data : JSON.parse(resText)),
          text: async () => resText,
        });
      } else {
        const detail = (typeof data === 'object' && data?.detail) ? data.detail : resText;
        reject(new ApiError(status, detail, resText));
      }
    };

    xhr.onerror = () => {
      reject(new Error('Network error during file upload'));
    };

    xhr.onabort = () => {
      reject(new Error('Upload aborted'));
    };

    xhr.send(body);
  });
}

// A failed request, carrying the server's own explanation. Callers that show an
// alert should prefer `detail` — the generic "something went wrong" strings hid
// real, actionable messages (e.g. a declined card blocking checkout).
export class ApiError extends Error {
  constructor(status, detail, raw) {
    super(`${status}: ${raw}`);   // message kept verbatim for existing callers
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

// Convenience JSON helper.
export async function apiJson(path, options = {}) {
  const res = await apiFetch(path, options);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    let detail = '';
    try {
      const d = JSON.parse(text).detail;
      if (d !== undefined) detail = d;
    } catch (_) { /* not JSON — leave detail empty and fall back to the caller's copy */ }
    throw new ApiError(res.status, detail, text);
  }
  return res.json();
}
