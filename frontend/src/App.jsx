import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  deleteVersion, fetchConfig, fetchHistory, fetchMe, fetchVersions,
  getAdminToken, login, logout, setAdminToken, summarize,
} from './api.js';
import { Markdown } from './markdown.jsx';

const LENGTHS = [
  { value: 'quick', label: 'Quick', hint: 'Under 150 words' },
  { value: 'medium', label: 'Mid-length', hint: '≈ 350 words' },
  { value: 'long', label: 'Long', hint: '≈ 800 words' },
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
      setLoginError('Enter the admin username and password.');
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
      setNotice('Logged in as admin — delete and full search are unlocked.');
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
    setNotice('Logged out. Showing the 5 most recent summaries.');
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
                <span className="admin-badge" title="Logged in as admin">admin{adminUser ? `: ${adminUser}` : ''}</span>
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
            <span className="login-title">Admin log in</span>
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
                  {isAdmin && active && (
                    <button className="btn danger-ghost" onClick={removeActive} title="Delete this version (admin only)">
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
            <h2>{isAdmin ? 'All summaries' : 'Recent'}</h2>
            <button className="link-btn" onClick={() => refreshHistory()}>Refresh</button>
          </div>
          {isAdmin ? (
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
              </select>
            </div>
          ) : (
            <p className="dim small guest-note">
              Showing the 5 most recent. <button className="link-btn" onClick={() => setShowLogin(true)}>Log in</button> as admin to search everything.
            </p>
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
