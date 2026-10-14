"""Length-specific prompts and token budgets."""
from __future__ import annotations

LENGTHS = ("quick", "medium", "long")

ALIASES = {"mid": "medium", "middle": "medium", "short": "quick", "detailed": "long"}


def normalize_length(value: str) -> str:
    v = (value or "").strip().lower()
    v = ALIASES.get(v, v)
    if v not in LENGTHS:
        raise ValueError(f"Unknown length '{value}'. Choose quick, medium or long.")
    return v


MAX_TOKENS = {"quick": 600, "medium": 1400, "long": 2600}

SYSTEM = (
    "You summarize YouTube videos from their captions. Be faithful to the transcript: "
    "no invented facts, names, or numbers. Use clear Markdown."
)

PROMPTS = {
    "quick": (
        "Summarize this video in under 150 words.\n"
        "Format: one opening sentence with the core takeaway, then 3-5 tight bullet points "
        "with the key facts. No preamble, no section headers."
    ),
    "medium": (
        "Write a mid-length summary of about 300-400 words.\n"
        "Format: a 2-3 sentence overview, then sections with short bold headings covering "
        "the main points in order, ending with one line on who this video is most useful for."
    ),
    "long": (
        "Write a thorough long summary of about 700-900 words.\n"
        "Format: an overview paragraph, then detailed sections with bold headings following "
        "the video's structure, including key arguments, examples, data points, and nuance. "
        "Close with 'Key takeaways' as 4-6 bullets."
    ),
}


def build_prompt(length: str, title: str, transcript: str) -> str:
    header = PROMPTS[length]
    return (
        f"{header}\n\nVideo title: {title or 'Unknown'}\n\n"
        f"Transcript (may contain caption errors):\n{transcript}"
    )
