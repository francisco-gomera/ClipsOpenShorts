import assert from 'node:assert/strict';
import test from 'node:test';

const storage = new Map();
globalThis.localStorage = {
  getItem: (key) => storage.get(key) || null,
  setItem: (key, value) => storage.set(key, String(value)),
  removeItem: (key) => storage.delete(key),
};
const authEvents = [];
globalThis.window = { dispatchEvent: (event) => authEvents.push(event) };
globalThis.CustomEvent = class CustomEvent {
  constructor(type, options) { this.type = type; this.detail = options?.detail; }
};

const api = await import('../src/lib/api.js?auth-tests');

function response(status, body = {}) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

test('coalesces simultaneous 401 refreshes and retries each original request once', async () => {
  storage.clear();
  authEvents.length = 0;
  api.setLocalAuthEnabled(true);
  api.setManagedAuthEnabled(false);
  api.setToken('old-access');
  let refreshCount = 0;
  const attempts = new Map();
  globalThis.fetch = async (url, options) => {
    if (url.endsWith('/api/auth/refresh')) {
      refreshCount += 1;
      await new Promise((resolve) => setTimeout(resolve, 10));
      return response(200, { access_token: 'new-access' });
    }
    const path = new URL(url, 'http://localhost').pathname;
    attempts.set(path, (attempts.get(path) || 0) + 1);
    return options.headers.get('Authorization') === 'Bearer new-access'
      ? response(200, { ok: true }) : response(401, { detail: 'expired' });
  };

  const results = await Promise.all(Array.from({ length: 5 }, (_, index) => api.apiFetch(`/api/private/${index}`)));
  assert.equal(refreshCount, 1);
  assert.deepEqual(results.map((result) => result.status), [200, 200, 200, 200, 200]);
  assert.deepEqual([...attempts.values()], [2, 2, 2, 2, 2]);
  assert.equal(api.getToken(), 'new-access');
  assert.equal(authEvents.length, 0);
});

test('definitive refresh expiry clears access and announces auth expiration', async () => {
  storage.clear();
  authEvents.length = 0;
  api.setLocalAuthEnabled(true);
  api.setToken('old-access');
  globalThis.fetch = async (url) => url.endsWith('/api/auth/refresh')
    ? response(401, { detail: 'expired' }) : response(401, { detail: 'expired' });

  const result = await api.apiFetch('/api/live');
  assert.equal(result.status, 401);
  assert.equal(api.getToken(), '');
  assert.equal(authEvents.length, 1);
  assert.match(authEvents[0].detail.message, /caducado/i);
});

test('temporary refresh outage preserves token and does not sign the user out', async () => {
  storage.clear();
  authEvents.length = 0;
  api.setLocalAuthEnabled(true);
  api.setToken('old-access');
  globalThis.fetch = async (url) => url.endsWith('/api/auth/refresh')
    ? response(503, {}) : response(401, {});

  const result = await api.apiFetch('/api/live');
  assert.equal(result.status, 401);
  assert.equal(api.getToken(), 'old-access');
  assert.equal(authEvents.length, 0);
  api.setLocalAuthEnabled(false);
});
