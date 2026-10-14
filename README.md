# Recap — YouTube Summarizer

Paste a YouTube link, pick Quick / Mid-length / Long, get a faithful Markdown summary.
Summaries are stored in SQLite keyed by **canonical URL + length**, reused instantly on
repeat requests, and versioned (up to a configurable limit) when you hit **Regenerate**.

## Stack

- Backend: Python + FastAPI, SQLite (WAL), `httpx`, `youtube-transcript-api`
- Frontend: React 18 + Vite, dependency-free Markdown renderer
- LLMs: OpenAI-compatible (`/chat/completions`) or Anthropic-compatible (`/v1/messages`) —
  point at OpenAI/Anthropic or any compatible gateway via `.env`

## Setup

```bash
cp .env.example .env
# edit .env: set LLM_PROVIDER and the matching API URL / key / model
```

### Backend

```bash
uv venv
uv pip install -r backend/requirements.txt
uv run uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Health check: `GET http://127.0.0.1:8000/api/health`
Config (no secrets): `GET http://127.0.0.1:8000/api/config`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 in a browser. The Vite dev server proxies `/api` to the backend.

## Production (Docker Compose)

```bash
cp .env.example .env
# edit .env: set LLM_PROVIDER and the matching API URL / key / model
docker compose up --build -d
```

Open http://localhost:8080 in a browser (or your `FRONTEND_PORT`). nginx serves the
built frontend and proxies `/api` to the backend, so the app is same-origin with no
CORS involved. SQLite lives on the `yt-data` volume and survives restarts/upgrades.

```bash
docker compose logs -f        # follow logs
docker compose down           # stop (data kept in yt-data volume)
docker compose down -v        # stop AND delete stored summaries
```

The backend is also reachable directly at http://127.0.0.1:8000 (loopback only,
`BACKEND_PORT` in `.env` if you changed it) for debugging, e.g. `GET /api/health`.

## Using a local Ollama server

The backend speaks plain OpenAI-compatible chat completions, so Ollama works with
`LLM_PROVIDER=openai`. Three things must be right, or `/api/summarize` answers 502
(the exact cause is in the response detail and in `docker compose logs`):

1. **Ollama must listen on all interfaces.** By default it binds to localhost only,
   which containers can't reach. Start it with `OLLAMA_HOST=0.0.0.0 ollama serve`
   (or set `OLLAMA_HOST=0.0.0.0` persistently) and restart it.
2. **The URL must resolve from inside the container.** `localhost` inside the
   backend container means the container itself, not your machine. Use:
   - compose: `OPENAI_API_URL=http://host.docker.internal:11434/v1`
     (the compose file maps this to your host automatically)
   - local dev: `OPENAI_API_URL=http://localhost:11434/v1`
3. **The model must be pulled.** `ollama pull gemma3:12b`, and set `OPENAI_MODEL`
   to exactly what `ollama list` shows. Leave `OPENAI_API_KEY` empty — no key needed.

### Ollama Cloud (hosted, no local server)

Point at the hosted endpoint instead — this works the same from compose and local dev:

```bash
LLM_PROVIDER=openai
OPENAI_API_URL=https://ollama.com/v1
OPENAI_API_KEY=<key from your ollama.com account>
OPENAI_MODEL=gpt-oss:120b   # any cloud model id
```

Transient hiccups (empty or cut-off completions) are retried automatically, up to
3 attempts per summary; persistent failures return a 502 whose detail names the
cause — also visible in `docker compose logs`.

## How reuse works

1. The backend canonicalizes any YouTube URL (`watch?v=`, `youtu.be`, `/shorts/`, `/embed/`, `/live/`)
   to `https://www.youtube.com/watch?v={id}`.
2. `POST /api/summarize` with `{"url", "length", "regenerate": false}` returns the stored
   version list for that (URL, length) pair without calling the LLM.
3. With `"regenerate": true` (or no stored versions) it fetches captions, calls the LLM,
   appends a new version, and evicts the oldest past `MAX_SUMMARIES_PER_URL_LENGTH`.
4. `GET /api/summaries?url=…&length=…` lists versions; `GET /api/history` lists recent
   pairs (guests: 5 most recent; admin: searchable/filterable); `DELETE
   /api/summaries/{id}` drops one version (admin only, enforced by the backend).

## Admin access

One admin user is defined in-memory via `ADMIN_USERNAME` / `ADMIN_PASSWORD` in
`.env` — there is no users table. Guests can summarize and view, but only the
admin can delete summaries or browse/search/filter beyond the 5 most recent.

- In the UI, click **Log in** (top right) and enter the admin credentials.
  The Delete button and the history search/filter appear only for the admin.
- API clients can either send HTTP Basic auth (`Authorization: Basic
  base64(user:pass)`) or log in once and reuse the token:
  `POST /api/login {"username","password"}` → `{"token",…}`, then
  `Authorization: Bearer <token>`. Tokens live in backend memory only and
  expire after 12 hours; `POST /api/logout` revokes the current one.
- Admin-only endpoints: `DELETE /api/summaries/{id}` and
  `GET /api/admin/summaries?q=…&length=…&video_id=…&limit=…&offset=…`
  (every stored version, newest first, with a `total` count for paging).
  Both answer `401` without valid admin credentials, so rogue delete
  requests from non-admin clients are rejected.

Change `ADMIN_PASSWORD` from the `changeme` default before exposing the app;
the backend logs a warning on startup while the default is in place.

Lengths: `quick` (<150 words), `medium`/`mid` (≈350 words), `long` (≈800 words).

## Configuration (`.env`)

| Variable | Purpose | Default |
|---|---|---|
| `LLM_PROVIDER` | `openai` or `anthropic` | `openai` |
| `OPENAI_API_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL` | OpenAI-compatible endpoint | `https://api.openai.com/v1` / — / `gpt-4o-mini` |
| `ANTHROPIC_API_URL` / `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | Anthropic-compatible endpoint | `https://api.anthropic.com` / — / `claude-sonnet-4-20250514` |
| `MAX_SUMMARIES_PER_URL_LENGTH` | Stored versions per (URL, length) | `5` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | In-memory admin user (delete + full search) | `admin` / `changeme` |
| `DATABASE_PATH` | SQLite file | `backend/data/summaries.db` |
| `HOST` / `PORT` | Backend bind (local dev; overridden in compose) | `127.0.0.1` / `8000` |
| `FRONTEND_PORT` | Host port for the web UI (compose only) | `8080` |
| `BACKEND_PORT` | Host port for direct backend access (compose only) | `8000` |

Settings are read once on backend startup — restart after editing `.env`.
Full endpoint URLs also work for the `*_API_URL` values (e.g. ending in
`/chat/completions` or `/v1/messages` are used as-is).

## Notes

- Caption fetching needs public captions on the video; private, captionless, or
  region-blocked videos return a clear 422 error.
- Transcripts are truncated to ~30k characters before being sent to the LLM.
- Summaries may contain model errors — the footer says so in the UI too.
