export async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
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

export const fetchHistory = (limit = 20) => api(`/api/history?limit=${limit}`);

export const fetchConfig = () => api('/api/config');

export const deleteVersion = (id) => api(`/api/summaries/${id}`, { method: 'DELETE' });
