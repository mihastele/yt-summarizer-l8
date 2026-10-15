import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  deleteVersion, exportSummariesBlob, fetchAdminSummaries, fetchConfig, fetchHistory,
  fetchMe, fetchVersions, getAdminToken, login, logout, setAdminToken, summarize,
} from './api.js';
import { Markdown } from './markdown.jsx';

const LENGTHS = [
  { value: 'quick', label: 'Quick', hint: 'Under 150 words' },
  { value: 'medium', label: 'Mid-length', hint: '≈ 350 words' },
  { value: 'long', label: 'Long', hint: '≈ 800 words' },
  { value: 'extended', label: 'Extended', hint: '≈ 1400 words' },
];

function lengthLabel(value) {
  return LENGTHS.find((l) => l.value === value)?.label || value;
}

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso || '';
  }
}

function videoIdFromUrl(url) {
  const m = String(url || '').match(/(?:v=|youtu\.be\/|shorts\/|embed\/|live\/)([A-Za-z0-9_-]{11})/);
  return m ? m[1] : null;
}

function summaryMarkdown(result, active) {
  const title = result.title || result.video_id || 'Summary';
  return `# ${title}\n\nSource: ${result.url}\n\n${(active.summary || '').trim()}\n`;
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand('copy');
  } finally {
    ta.remove();
  }
}

function Dashboard() {
  const [q, setQ] = useState('');
  const [length, setLength] = useState('');
  const [videoId, setVideoId] = useState('');
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [selected, setSelected] = useState(() => new Set());

  const runSearch = useCallback(async (offset, append) => {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const data = await fetchAdminSummaries({
        q: q.trim(), length, video_id: videoId.trim(), limit: 50, offset,
      });
      setItems((prev) => (append ? [...prev, ...(data.items || [])] : data.items || []));
      setTotal(data.total || 0);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }, [q, length, videoId]);

  useEffect(() => {
    runSearch(0, false);
  }, []); // eslint-disable-line — initial load only; later searches run on submit

  const toggle = useCallback((id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const allShown = items.length > 0 && items.every((item) => selected.has(item.id));
  const toggleShown = useCallback(() => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allShown) items.forEach((item) => next.delete(item.id));
      else items.forEach((item) => next.add(item.id));
      return next;
    });
  }, [allShown, items]);

  const doExport = useCallback(async (mode) => {
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const blob = mode === 'selected'
        ? await exportSummariesBlob({ ids: [...selected].join(',') })
        : await exportSummariesBlob({ q: q.trim(), length, video_id: videoId.trim() });
      const count = mode === 'selected' ? selected.size : total;
      const stamp = new Date().toISOString().slice(0, 10);
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `recap-export-${stamp}-${count}.md`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      setMessage(`Exported ${count} ${count === 1 ? 'summary' : 'summaries'} to a Markdown file.`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }, [length, q, selected, total, videoId]);

  return (
    <section className="primary">
      <h1 className="display">Dashboard.</h1>
      <p className="lede">
        Search every stored summary and export all or a subset into one delimited Markdown file.
      </p>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          runSearch(0, false);
        }}
      >
        <div className="dash-fields">
          <input
            className="url-input"
            type="search"
            placeholder="Search title, link, video id, text…"
            aria-label="Search summaries"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <select
            className="history-filter dash-select"
            aria-label="Filter by depth"
            value={length}
            onChange={(e) => setLength(e.target.value)}
          >
            <option value="">All depths</option>
            <option value="quick">Quick</option>
            <option value="medium">Mid-length</option>
            <option value="long">Long</option>
            <option value="extended">Extended</option>
          </select>
          <input
            className="url-input"
            placeholder="Video id (optional)"
            aria-label="Filter by video id"
            value={videoId}
            onChange={(e) => setVideoId(e.target.value)}
            spellCheck={false}
          />
        </div>
        <div className="dash-actions">
          <button type="submit" className="btn primary" disabled={busy}>
            {busy ? 'Searching…' : 'Search'}
          </button>
          <button
            type="button"
            className="btn ghost"
            disabled={busy}
            onClick={() => {
              setQ('');
              setLength('');
              setVideoId('');
            }}
          >
            Clear
          </button>
        </div>
      </form>

      {error && (
        <div className="alert error" role="alert">
          <span className="alert-title">Something went wrong</span>
          <span>{error}</span>
        </div>
      )}
      {message && !error && <div className="alert info" role="status">{message}</div>}

      <div className="sheet dash-results">
        <div className="dash-bar">
          <label className="dash-select-all">
            <input type="checkbox" checked={allShown} onChange={toggleShown} />
            Select shown
          </label>
          <span className="dash-counts">
            {selected.size} selected · {items.length} of {total} shown
          </span>
        </div>
        {items.length === 0 ? (
          <p className="dim small">{busy ? 'Searching…' : 'No summaries match this search.'}</p>
        ) : (
          <ol className="dash-list">
            {items.map((item) => (
              <li key={item.id}>
                <label className="dash-row">
                  <input
                    type="checkbox"
                    checked={selected.has(item.id)}
                    onChange={() => toggle(item.id)}
                  />
                  <span className="dash-row-text">
                    <span className="dash-row-title">{item.title || item.video_id || item.url}</span>
                    <span className="dash-row-meta">
                      {lengthLabel(item.length)} · {formatDate(item.created_at)} · {item.video_id}
                    </span>
                  </span>
                </label>
              </li>
            ))}
          </ol>
        )}
        {items.length < total && (
          <button
            type="button"
            className="btn ghost dash-load"
            disabled={busy}
            onClick={() => runSearch(items.length, true)}
          >
            {busy ? 'Loading…' : `Load more (${total - items.length} remaining)`}
          </button>
        )}
      </div>

      <div className="dash-export">
        <button
          type="button"
          className="btn primary"
          disabled={busy || selected.size === 0}
          onClick={() => doExport('selected')}
        >
          Export selected ({selected.size})
        </button>
        <button
          type="button"
          className="btn ghost"
          disabled={busy || total === 0}
          onClick={() => doExport('all')}
        >
          Export all matching ({total})
        </button>
      </div>
    </section>
  );
}

export default function App() {
  const [url, setUrl] = useState('');
  const [length, setLength] = useState('medium');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [activeId, setActiveId] = useState(null);
  const [error, setError] = useState('');
  const [history, setHistory] = useState([]);
  const [config, setConfig] = useState(null);
  const [notice, setNotice] = useState('');
  const [isAdmin, setIsAdmin] = useState(false);
  const [adminUser, setAdminUser] = useState('');
  const [showLogin, setShowLogin] = useState(false);
  const [loginName, setLoginName] = useState('');
  const [loginPass, setLoginPass] = useState('');
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState('');
  const [histQuery, setHistQuery] = useState('');
  const [histLength, setHistLength] = useState('');
  const [view, setView] = useState('home');

  const isAdminRef = useRef(isAdmin);
  isAdminRef.current = isAdmin;
  const histQueryRef = useRef(histQuery);
  histQueryRef.current = histQuery;
  const histLengthRef = useRef(histLength);
  histLengthRef.current = histLength;

  const refreshHistory = useCallback(async (overrides = {}) => {
    const admin = overrides.isAdmin ?? isAdminRef.current;
    const q = overrides.q ?? histQueryRef.current;
    const len = overrides.len ?? histLengthRef.current;
    try {
      const data = admin
        ? await fetchHistory({ limit: 50, q: q.trim(), length: len })
        : await fetchHistory({ limit: 5 });
      setHistory(data.items || []);
      if (typeof data.is_admin === 'boolean') setIsAdmin(data.is_admin);
    } catch {
      /* history is best-effort */
    }
  }, []);

  useEffect(() => {
    fetchConfig().then(setConfig).catch(() => setConfig(null));
    // Restore an admin session from a stored token, then load history.
    if (getAdminToken()) {
      fetchMe()
        .then((me) => {
          setIsAdmin(!!me.is_admin);
          if (!me.is_admin) setAdminToken(null);
          refreshHistory({ isAdmin: !!me.is_admin });
        })
        .catch(() => {
          setAdminToken(null);
          setIsAdmin(false);
          refreshHistory({ isAdmin: false });
        });
    } else {
      refreshHistory({ isAdmin: false });
    }
  }, [refreshHistory]);

  // Debounced re-query while the admin types in the history search box.
  useEffect(() => {
    if (!isAdmin) return;
    const t = setTimeout(() => refreshHistory(), 350);
    return () => clearTimeout(t);
  }, [histQuery, histLength, isAdmin, refreshHistory]);

  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(''), 4500);
    return () => clearTimeout(t);
  }, [notice]);

  const run = useCallback(
    async ({ regenerate = false, overrideUrl, overrideLength } = {}) => {
      const targetUrl = (overrideUrl ?? url).trim();
      const targetLength = overrideLength ?? length;
      if (!targetUrl) {
        setError('Paste a YouTube link first.');
        return;
      }
      setLoading(true);
      setError('');
      setNotice('');
      try {
        const data = await summarize(targetUrl, targetLength, regenerate);
        setResult(data);
        setActiveId(data.summaries?.[0]?.id ?? null);
        if (data.reused) {
          setNotice(`Found ${data.summaries.length} saved ${lengthLabel(data.length).toLowerCase()} version${data.summaries.length === 1 ? '' : 's'} — no new generation needed.`);
        } else if (regenerate) {
          setNotice('Fresh summary generated and added to the version list.');
        }
        refreshHistory();
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    },
    [url, length, refreshHistory]
  );

  const openHistory = useCallback(
    async (item) => {
      setUrl(item.url);
      setLength(item.length);
      setLoading(true);
      setError('');
      try {
        const data = await fetchVersions(item.url, item.length);
        setResult({ ...data, title: item.title || data.video_id });
        setActiveId(data.summaries?.[0]?.id ?? null);
        setNotice(`Loaded ${data.summaries.length} saved version${data.summaries.length === 1 ? '' : 's'}.`);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const doLogin = useCallback(async (e) => {
    e?.preventDefault();
    if (!loginName.trim() || !loginPass) {
      setLoginError('Enter your username and password.');
      return;
    }
    setLoginBusy(true);
    setLoginError('');
    try {
      const data = await login(loginName.trim(), loginPass);
      setAdminToken(data.token);
      setIsAdmin(true);
      setAdminUser(data.username || loginName.trim());
      setShowLogin(false);
      setLoginPass('');
      setNotice('Logged in.');
      refreshHistory({ isAdmin: true });
    } catch (err) {
      setLoginError(err.message);
    } finally {
      setLoginBusy(false);
    }
  }, [loginName, loginPass, refreshHistory]);

  const doLogout = useCallback(async () => {
    try {
      await logout();
    } catch {
      /* token may already be expired — still clear it locally */
    }
    setAdminToken(null);
    setIsAdmin(false);
    setAdminUser('');
    setHistQuery('');
    setHistLength('');
    setView('home');
    setNotice('Logged out.');
    refreshHistory({ isAdmin: false, q: '', len: '' });
  }, [refreshHistory]);

  const removeActive = useCallback(async () => {
    if (!active) return;
    try {
      await deleteVersion(active.id);
      const remaining = result.summaries.filter((s) => s.id !== active.id);
      setResult({ ...result, summaries: remaining });
      setActiveId(remaining[0]?.id ?? null);
      setNotice('Version deleted.');
      refreshHistory();
    } catch (err) {
      setError(err.message);
    }
  }, [result]); // eslint-disable-line

  const active = result?.summaries?.find((s) => s.id === activeId) || result?.summaries?.[0] || null;
  const thumb = result?.video_id ? `https://i.ytimg.com/vi/${result.video_id}/hqdefault.jpg` : null;

  const copyActive = useCallback(async () => {
    if (!active) return;
    try {
      await copyText(summaryMarkdown(result, active));
      setNotice('Summary copied to clipboard.');
    } catch {
      setError('Could not copy to clipboard in this browser.');
    }
  }, [result, active]);

  const downloadActive = useCallback(() => {
    if (!active) return;
    const blob = new Blob([summaryMarkdown(result, active)], { type: 'text/markdown' });
    const idx = result.summaries.findIndex((s) => s.id === active.id);
    const ver = idx >= 0 ? result.summaries.length - idx : 1;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `recap-${result.video_id}-${result.length}-v${ver}.md`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    setNotice('Summary downloaded as Markdown.');
  }, [result, active]);

  return (
    <div className="page">
      <header className="masthead">
        <div className="masthead-inner">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                <rect x="1.5" y="4" width="21" height="16" rx="4.5" fill="#D9261C" />
                <path d="M10.2 9.1v5.8L15.4 12l-5.2-2.9z" fill="#fff" />
              </svg>
            </span>
            <span className="brand-name">Recap</span>
            <span className="brand-sub">YouTube Summarizer</span>
          </div>
          <div className="masthead-meta">
            {config ? (
              <>
                <span className={`provider-dot ${config.has_api_key ? 'on' : 'off'}`} title={config.has_api_key ? 'API key configured' : 'No API key configured'} />
                <span className="meta-text">
                  {config.provider} · {config.model}
                </span>
                <span className="meta-sep">·</span>
                <span className="meta-text">keeps {config.max_summaries} versions</span>
              </>
            ) : (
              <span className="meta-text dim">connecting to backend…</span>
            )}
            <span className="meta-sep">·</span>
            {isAdmin ? (
              <>
                <span className="admin-badge" title="Logged in">{adminUser || 'Logged in'}</span>
                <button className="link-btn" onClick={() => setView((v) => (v === 'dash' ? 'home' : 'dash'))}>
                  {view === 'dash' ? 'Summaries' : 'Dashboard'}
                </button>
                <button className="link-btn" onClick={doLogout}>Log out</button>
              </>
            ) : (
              <button className="link-btn" onClick={() => { setShowLogin((v) => !v); setLoginError(''); }}>
                {showLogin ? 'Close' : 'Log in'}
              </button>
            )}
          </div>
        </div>
      </header>

      {showLogin && !isAdmin && (
        <div className="login-strip">
          <form className="login-form" onSubmit={doLogin}>
            <span className="login-title">Log in</span>
            <label className="sr-only" htmlFor="login-user">Username</label>
            <input
              id="login-user"
              className="login-input"
              placeholder="Username"
              autoComplete="username"
              value={loginName}
              onChange={(e) => setLoginName(e.target.value)}
            />
            <label className="sr-only" htmlFor="login-pass">Password</label>
            <input
              id="login-pass"
              className="login-input"
              type="password"
              placeholder="Password"
              autoComplete="current-password"
              value={loginPass}
              onChange={(e) => setLoginPass(e.target.value)}
            />
            <button type="submit" className="btn primary login-btn" disabled={loginBusy}>
              {loginBusy ? 'Checking…' : 'Log in'}
            </button>
            {loginError && <span className="login-error" role="alert">{loginError}</span>}
          </form>
        </div>
      )}

      {view === 'dash' && isAdmin ? (
        <main className="layout dashboard-layout">
          <Dashboard />
        </main>
      ) : (
      <main className="layout">
        <section className="primary">
          <h1 className="display">Turn any video into a readable summary.</h1>
          <p className="lede">
            Paste a link, choose a depth, and Recap pulls the captions and distills them.
            Past summaries are reused instantly — regenerate only when you want a fresh take.
          </p>

          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              run({ regenerate: false });
            }}
          >
            <label className="field-label" htmlFor="yt-url">YouTube link</label>
            <div className="url-row">
              <input
                id="yt-url"
                className="url-input"
                type="url"
                inputMode="url"
                placeholder="https://www.youtube.com/watch?v=…"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                spellCheck={false}
              />
              <button type="submit" className="btn primary" disabled={loading}>
                {loading ? 'Working…' : 'Summarize'}
              </button>
            </div>

            <div className="length-row" role="radiogroup" aria-label="Summary length">
              {LENGTHS.map((l) => (
                <button
                  key={l.value}
                  type="button"
                  role="radio"
                  aria-checked={length === l.value}
                  className={`length-card ${length === l.value ? 'selected' : ''}`}
                  onClick={() => setLength(l.value)}
                >
                  <span className="length-name">{l.label}</span>
                  <span className="length-hint">{l.hint}</span>
                </button>
              ))}
              <p className="length-note">
                Saved summaries are matched by link + depth. Switching depth starts its own version list.
              </p>
            </div>
          </form>

          {error && (
            <div className="alert error" role="alert">
              <span className="alert-title">Something went wrong</span>
              <span>{error}</span>
            </div>
          )}
          {notice && !error && <div className="alert info" role="status">{notice}</div>}
          {config && !config.has_api_key && (
            <div className="alert warn" role="status">
              No LLM API key configured — cloud providers need one in <code>.env</code> (keyless local
              servers like Ollama work without). Saved summaries still load.
            </div>
          )}

          {loading && !result && (
            <div className="sheet skeleton" aria-hidden="true">
              <div className="sk-line w40" />
              <div className="sk-line" />
              <div className="sk-line" />
              <div className="sk-line w70" />
            </div>
          )}

          {result && (
            <article className="sheet">
              <div className="result-head">
                {thumb && <img className="thumb" src={thumb} alt="" loading="lazy" />}
                <div className="result-titles">
                  <h2 className="video-title">{result.title || result.video_id}</h2>
                  <div className="result-sub">
                    <span>{lengthLabel(result.length)} summary</span>
                    <span className="dot">·</span>
                    <a href={result.url} target="_blank" rel="noreferrer">watch on YouTube</a>
                    <span className="dot">·</span>
                    <span>
                      {result.summaries.length}/{result.max_versions} versions
                    </span>
                  </div>
                </div>
              </div>

              <div className="version-bar">
                <div className="versions" role="tablist" aria-label="Saved versions">
                  {result.summaries.map((s, i) => (
                    <button
                      key={s.id}
                      role="tab"
                      aria-selected={active && s.id === active.id}
                      className={`version-tab ${active && s.id === active.id ? 'active' : ''}`}
                      onClick={() => setActiveId(s.id)}
                      title={`${formatDate(s.created_at)} — ${s.model || 'unknown model'}`}
                    >
                      v{result.summaries.length - i}
                      {i === 0 && <span className="latest-pill">latest</span>}
                    </button>
                  ))}
                </div>
                <div className="version-actions">
                  <button
                    className="btn ghost"
                    disabled={loading}
                    onClick={() => run({ regenerate: true })}
                    title="Generate a new version (keeps the old ones, up to the limit)"
                  >
                    {loading ? 'Regenerating…' : 'Regenerate'}
                  </button>
                  {active && (
                    <button className="btn ghost" onClick={copyActive} title="Copy this summary as Markdown">
                      Copy
                    </button>
                  )}
                  {active && (
                    <button className="btn ghost" onClick={downloadActive} title="Download this summary as a Markdown file">
                      Download
                    </button>
                  )}
                  {isAdmin && active && (
                    <button className="btn danger-ghost" onClick={removeActive} title="Delete this version">
                      Delete
                    </button>
                  )}
                </div>
              </div>

              {active ? (
                <div className="summary-body">
                  <div className="summary-meta">
                    <span>{formatDate(active.created_at)}</span>
                    {active.model && (
                      <>
                        <span className="dot">·</span>
                        <span>{active.model}</span>
                      </>
                    )}
                  </div>
                  <Markdown text={active.summary} />
                </div>
              ) : (
                <p className="dim">All versions were deleted. Regenerate to create a new one.</p>
              )}
            </article>
          )}

          {!result && !loading && (
            <div className="samples">
              <p className="samples-title">Try it — paste any of these formats:</p>
              <ul>
                <li><code>https://www.youtube.com/watch?v=dQw4w9WgXcQ</code></li>
                <li><code>https://youtu.be/dQw4w9WgXcQ</code></li>
                <li><code>https://www.youtube.com/shorts/dQw4w9WgXcQ</code></li>
              </ul>
            </div>
          )}
        </section>

        <aside className="rail">
          <div className="rail-head">
            <h2>Recent</h2>
            <button className="link-btn" onClick={() => refreshHistory()}>Refresh</button>
          </div>
          {isAdmin && (
            <div className="history-tools">
              <input
                className="history-search"
                type="search"
                placeholder="Search title, link, video id…"
                aria-label="Search summaries"
                value={histQuery}
                onChange={(e) => setHistQuery(e.target.value)}
              />
              <select
                className="history-filter"
                aria-label="Filter by depth"
                value={histLength}
                onChange={(e) => setHistLength(e.target.value)}
              >
                <option value="">All depths</option>
                <option value="quick">Quick</option>
                <option value="medium">Mid-length</option>
                <option value="long">Long</option>
                <option value="extended">Extended</option>
              </select>
            </div>
          )}
          {isAdmin && (
            <button
              type="button"
              className="btn ghost dash-toggle"
              onClick={() => setView((v) => (v === 'dash' ? 'home' : 'dash'))}
            >
              {view === 'dash' ? 'Back to summaries' : 'Open dashboard'}
            </button>
          )}
          {history.length === 0 ? (
            <p className="dim small">
              {isAdmin && (histQuery || histLength)
                ? 'No summaries match this search.'
                : 'Nothing summarized yet. Your recent videos will appear here.'}
            </p>
          ) : (
            <ol className="history-list">
              {history.map((h) => (
                <li key={`${h.url}-${h.length}`}>
                  <button className="history-item" onClick={() => openHistory(h)}>
                    <span className="history-title">{h.title || h.video_id || h.url}</span>
                    <span className="history-sub">
                      {lengthLabel(h.length)} · v{h.version_count} · {formatDate(h.created_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          )}
          <div className="rail-foot">
            <p className="small dim">
              Storage key is the canonical video link plus depth, capped at {config?.max_summaries ?? 5}{' '}
              versions — oldest drops off first. Change it with{' '}
              <code>MAX_SUMMARIES_PER_URL_LENGTH</code> in <code>.env</code>.
            </p>
          </div>
        </aside>
      </main>
      )}

      <div className="support-banner">
        <span className="support-text">
          Recap is free to run — if it saves you time, consider supporting it.
        </span>
        <a
          className="btn coffee"
          href="https://www.buymeacoffee.com/mihastele"
          target="_blank"
          rel="noreferrer"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M4 9h12v6a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5V9z"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinejoin="round"
            />
            <path
              d="M16 10h1.5a2.5 2.5 0 0 1 0 5H16M7 4.5c0 1 .8 1.2.8 2.2M11 4.5c0 1 .8 1.2.8 2.2"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </svg>
          Support us
        </a>
      </div>

      <footer className="footer">
        <span>Recap fetches public captions and summarizes them with your configured LLM. Summaries may contain errors — check the video for anything important.</span>
      </footer>
    </div>
  );
}
