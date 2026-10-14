"""YouTube helpers: URL parsing, title lookup, caption fetching."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import httpx

_VIDEO_PATTERNS = [
    re.compile(r"[?&]v=([A-Za-z0-9_-]{11})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"youtube\.com/(?:shorts|embed|live)/([A-Za-z0-9_-]{11})"),
]


def extract_video_id(url: str) -> str:
    url = (url or "").strip()
    for pattern in _VIDEO_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    # Fallback: strict query parse
    try:
        query = parse_qs(urlparse(url).query)
        candidate = (query.get("v") or [""])[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
            return candidate
    except Exception:
        pass
    raise ValueError("That doesn't look like a YouTube URL (expected watch?v=, youtu.be, shorts, embed or live link).")


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


async def fetch_title(video_id: str) -> str:
    """Best-effort title via YouTube oEmbed (no API key needed)."""
    url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers={"User-Agent": "yt-summarizer/1.0"})
            if response.status_code == 200:
                return str(response.json().get("title", "") or "")
    except Exception:
        pass
    return ""


def fetch_transcript(video_id: str, languages: tuple[str, ...] = ("en",)) -> str:
    """Return plain-text captions. Supports old and new youtube-transcript-api versions."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"Transcript library missing: {exc}") from exc

    last_error: Exception | None = None

    # New API (>=1.0): YouTubeTranscriptApi().fetch(video_id, languages=[...])
    try:
        api = YouTubeTranscriptApi()
        if hasattr(api, "fetch"):
            fetched = api.fetch(video_id, languages=list(languages))
            chunks = getattr(fetched, "snippets", None) or fetched
            texts: list[str] = []
            for item in chunks:  # type: ignore[union-attr]
                if isinstance(item, dict):
                    texts.append(item.get("text", ""))
                else:
                    texts.append(getattr(item, "text", "") or "")
            text = " ".join(t.strip() for t in texts if t and t.strip())
            if text:
                return text
    except Exception as exc:  # noqa: BLE001 - fall through to legacy API
        last_error = exc

    # Legacy API: YouTubeTranscriptApi.get_transcript(video_id, languages=[...])
    try:
        get_transcript = getattr(YouTubeTranscriptApi, "get_transcript", None)
        if callable(get_transcript):
            items = get_transcript(video_id, languages=list(languages))
            text = " ".join(i.get("text", "").strip() for i in items if i.get("text", "").strip())
            if text:
                return text
    except Exception as exc:  # noqa: BLE001
        last_error = exc

    # Final attempt: list_transcripts + find first English-ish track
    try:
        lister = getattr(YouTubeTranscriptApi, "list_transcripts", None)
        lister_fn = lister() if callable(lister) and not hasattr(YouTubeTranscriptApi, "get_transcript") else lister
        transcripts = None
        if callable(getattr(YouTubeTranscriptApi(), "list", None)):
            transcripts = YouTubeTranscriptApi().list(video_id)  # type: ignore[attr-defined]
        elif callable(lister_fn):
            transcripts = lister_fn(video_id)
        if transcripts is not None:
            for track in transcripts:
                try:
                    data = track.fetch()
                except TypeError:
                    data = track.fetch(languages=list(languages))
                items = data.to_raw_data() if hasattr(data, "to_raw_data") else data
                texts = [
                    (i.get("text", "") if isinstance(i, dict) else getattr(i, "text", "") or "")
                    for i in items  # type: ignore[union-attr]
                ]
                text = " ".join(t.strip() for t in texts if t and t.strip())
                if text:
                    return text
    except Exception as exc:  # noqa: BLE001
        last_error = exc

    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(
        "Could not fetch captions for this video. It may have captions disabled, "
        f"be private/age-restricted, or region-blocked{detail}"
    )


def truncate_transcript(text: str, max_chars: int = 30000) -> str:
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[transcript truncated for length]"
