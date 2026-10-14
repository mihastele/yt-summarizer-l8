# Production image for the FastAPI backend.
# Build context is the repo root:  docker build -f backend/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/

# Container defaults; docker-compose.yml overrides these explicitly.
# HOST must be 0.0.0.0 inside the container — never 127.0.0.1.
ENV HOST=0.0.0.0 \
    PORT=8000 \
    DATABASE_PATH=/data/summaries.db

VOLUME /data
EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn backend.app:app --host ${HOST:-0.0.0.0} --port ${PORT:-8000}"]
