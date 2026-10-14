"""FastAPI service: summarize YouTube videos, reuse stored versions, regenerate on demand."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Literal

logger = logging.getLogger("yt-summarizer")

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import auth, db
from .config import settings

GUEST_HISTORY_LIMIT = 5
from .llm import LLMError, complete_anthropic, complete_openai
from .prompts import build_prompt, normalize_length
from .transcripts import (
    canonical_url,
    extract_video_id,
    fetch_title,
    fetch_transcript,
    truncate_transcript,
)


class SummarizeRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    length: str = Field(default="medium", max_length=20)
    regenerate: bool = False


class SummarizeResponse(BaseModel):
    url: str
    video_id: str
    title: str
    length: str
    reused: bool
    summaries: list[dict[str, Any]]
    max_versions: int


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=500)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db(settings.database_path)
    if settings.admin_password == "changeme":
        logger.warning("ADMIN_PASSWORD is still the default — change it in .env")
    yield


app = FastAPI(title="YouTube Summarizer", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return {
        "provider": settings.llm_provider,
        "model": settings.active_model,
        "max_summaries": settings.max_summaries,
        "has_api_key": bool(settings.active_api_key),
    }


@app.get("/api/summaries")
def get_summaries(url: str = Query(min_length=8, max_length=2000), length: str = "medium") -> dict[str, Any]:
    try:
        video_id = extract_video_id(url)
        norm_length = normalize_length(length)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    canonical = canonical_url(video_id)
    return {
        "url": canonical,
        "video_id": video_id,
        "length": norm_length,
        "summaries": db.list_summaries(canonical, norm_length),
        "max_versions": settings.max_summaries,
    }


@app.post("/api/login")
def login(req: LoginRequest) -> dict[str, str]:
    if not auth.verify_credentials(req.username, req.password):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    return {"token": auth.issue_token(req.username), "username": req.username}


@app.post("/api/logout")
def logout(request: Request) -> dict[str, bool]:
    token = auth.bearer_token(request)
    if token:
        auth.revoke_token(token)
    return {"logged_out": True}


@app.get("/api/me")
def me(request: Request) -> dict[str, Any]:
    return {"is_admin": auth.is_admin_request(request)}


@app.get("/api/history")
def get_history(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=200),
    length: str | None = Query(default=None, max_length=20),
) -> dict[str, Any]:
    if auth.is_admin_request(request):
        norm_length: str | None = None
        if length:
            try:
                norm_length = normalize_length(length)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "items": db.recent_pairs(limit, query=(q or None), length=norm_length),
            "is_admin": True,
        }
    # Guests: most recent pairs only — search/filter params are ignored.
    return {"items": db.recent_pairs(min(limit, GUEST_HISTORY_LIMIT)), "is_admin": False}


@app.get("/api/admin/summaries")
def admin_summaries(
    request: Request,
    q: str | None = Query(default=None, max_length=200),
    length: str | None = Query(default=None, max_length=20),
    video_id: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    auth.require_admin(request)
    norm_length: str | None = None
    if length:
        try:
            norm_length = normalize_length(length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    items, total = db.list_all_summaries(
        query=(q or None), length=norm_length, video_id=(video_id or None),
        limit=limit, offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.delete("/api/summaries/{summary_id}")
def remove_summary(request: Request, summary_id: int) -> dict[str, bool]:
    auth.require_admin(request)
    if not db.delete_summary(summary_id):
        raise HTTPException(status_code=404, detail="Summary not found")
    return {"deleted": True}


@app.post("/api/summarize", response_model=SummarizeResponse)
async def summarize(req: SummarizeRequest) -> SummarizeResponse:
    try:
        video_id = extract_video_id(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        length = normalize_length(req.length)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    canonical = canonical_url(video_id)

    existing = db.list_summaries(canonical, length)
    if existing and not req.regenerate:
        title = existing[0].get("title", "") or await fetch_title(video_id)
        return SummarizeResponse(
            url=canonical, video_id=video_id, title=title, length=length,
            reused=True, summaries=existing, max_versions=settings.max_summaries,
        )

    try:
        transcript = await asyncio.to_thread(fetch_transcript, video_id)
    except RuntimeError as exc:
        logger.warning("Transcript fetch failed for %s: %s", video_id, exc)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    transcript = truncate_transcript(transcript)
    if len(transcript) < 200:
        raise HTTPException(status_code=422, detail="Transcript is too short to summarize reliably.")

    prompt = build_prompt(length, "", transcript)
    try:
        if settings.llm_provider == "anthropic":
            text = await complete_anthropic(
                api_url=settings.active_api_url, api_key=settings.active_api_key,
                model=settings.active_model, prompt=prompt, length=length,
                temperature=settings.llm_temperature,
            )
        else:
            text = await complete_openai(
                api_url=settings.active_api_url, api_key=settings.active_api_key,
                model=settings.active_model, prompt=prompt, length=length,
                temperature=settings.llm_temperature,
                reasoning_effort=settings.llm_reasoning_effort or None,
            )
    except LLMError as exc:
        logger.warning("LLM request failed (%s %s): %s", settings.llm_provider, settings.active_model, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not text:
        raise HTTPException(status_code=502, detail="The LLM returned an empty summary.")

    title = await fetch_title(video_id)
    summaries = db.add_summary(
        url=canonical, video_id=video_id, title=title, length=length,
        summary=text, model=f"{settings.llm_provider}:{settings.active_model}",
        transcript_chars=len(transcript), max_versions=settings.max_summaries,
    )
    return SummarizeResponse(
        url=canonical, video_id=video_id, title=title or video_id, length=length,
        reused=False, summaries=summaries, max_versions=settings.max_summaries,
    )


def main() -> None:
    import uvicorn

    db.init_db(settings.database_path)
    uvicorn.run("backend.app:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
