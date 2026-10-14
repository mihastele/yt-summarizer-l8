const TOKEN_KEY = 'recap-admin-token';

export function getAdminToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setAdminToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable — session-only */
  }
}

function authHeaders() {
  const token = getAdminToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...(options.headers || {}) },
    ...options,
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    const message = (data && (data.detail || data.message)) || `Request failed (${res.status})`;
    throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
  }
  return data;
}

export const summarize = (url, length, regenerate) =>
  api('/api/summarize', { method: 'POST', body: JSON.stringify({ url, length, regenerate }) });

export const fetchVersions = (url, length) =>
  api(`/api/summaries?url=${encodeURIComponent(url)}&length=${encodeURIComponent(length)}`);

export function fetchHistory({ limit = 20, q = '', length = '' } = {}) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (q) params.set('q', q);
  if (length) params.set('length', length);
  return api(`/api/history?${params.toString()}`);
}

export const fetchConfig = () => api('/api/config');

export const deleteVersion = (id) => api(`/api/summaries/${id}`, { method: 'DELETE' });

export const login = (username, password) =>
  api('/api/login', { method: 'POST', body: JSON.stringify({ username, password }) });

export const logout = () => api('/api/logout', { method: 'POST' });

export const fetchMe = () => api('/api/me');
