"""Environment, limits, AI-bot list and thresholds. No secrets are logged."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# Bots checked against robots.txt. kind: "search" = surfaces the page in AI answers
# or search results; "training" = model training crawl (blocking is a valid policy choice).
AI_BOTS: list[dict] = [
    {"name": "GPTBot", "kind": "training", "owner": "OpenAI"},
    {"name": "OAI-SearchBot", "kind": "search", "owner": "OpenAI"},
    {"name": "ChatGPT-User", "kind": "search", "owner": "OpenAI"},
    {"name": "ClaudeBot", "kind": "training", "owner": "Anthropic"},
    {"name": "Claude-SearchBot", "kind": "search", "owner": "Anthropic"},
    {"name": "PerplexityBot", "kind": "search", "owner": "Perplexity"},
    {"name": "Google-Extended", "kind": "training", "owner": "Google"},
    {"name": "Applebot-Extended", "kind": "training", "owner": "Apple"},
    {"name": "CCBot", "kind": "training", "owner": "Common Crawl"},
    {"name": "Bingbot", "kind": "search", "owner": "Microsoft"},
    {"name": "Googlebot", "kind": "search", "owner": "Google"},
]


@dataclass
class Settings:
    tinyfish_api_key: str = ""
    anthropic_api_key: str = ""
    search_url: str = "https://api.search.tinyfish.ai"
    fetch_url: str = "https://api.fetch.tinyfish.ai"
    # Docs say 30/min default; plan conservatively for the 5/min free tier. Configurable.
    search_rpm: int = 5
    fetch_upm: int = 150
    fetch_client_timeout_s: float = 150.0
    search_client_timeout_s: float = 30.0
    max_retries: int = 3
    audits_per_hour: int = 10
    audits_per_minute: int = 3
    db_path: str = "citegap.db"
    llm_model: str = "claude-haiku-5-5"
    # analysis thresholds
    js_gap_ratio: float = 0.40
    thin_words: int = 300
    title_max: int = 60
    desc_min: int = 70
    desc_max: int = 160
    title_rewrite_ratio: float = 60.0
    boilerplate_ratio: float = 0.50
    max_search_calls: int = 6
    competitors: int = 3
    raw_max_bytes: int = 3 * 1024 * 1024
    raw_timeout_s: float = 10.0
    raw_user_agent: str = "CiteGapAuditor/1.0"
    ai_bots: list[dict] = field(default_factory=lambda: list(AI_BOTS))


def load_settings() -> Settings:
    return Settings(
        tinyfish_api_key=os.environ.get("TINYFISH_API_KEY", "").strip(),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        search_rpm=max(1, _int("CITEGAP_SEARCH_RPM", 5)),
        fetch_upm=max(1, _int("CITEGAP_FETCH_UPM", 150)),
        audits_per_hour=max(1, _int("CITEGAP_AUDITS_PER_HOUR", 10)),
        db_path=os.environ.get("CITEGAP_DB", "citegap.db"),
    )


def load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (no dependency). Existing env vars win."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def mask_key(key: str) -> str:
    if not key:
        return "<unset>"
    return key[:4] + "…" + key[-2:] if len(key) > 8 else "****"
