"""
Shared utilities: config loading, logging, HTTP helpers, text cleaning.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse

import yaml
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


@lru_cache(maxsize=1)
def load_config() -> Dict[str, Any]:
    with open(_CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def get_config_value(*keys: str, default=None):
    cfg = load_config()
    val = cfg
    for k in keys:
        if not isinstance(val, dict):
            return default
        val = val.get(k, default)
    return val


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def build_session() -> requests.Session:
    cfg = load_config()
    ua = cfg.get("scraping", {}).get("user_agent", "ReboundCapitalTracker/1.0")
    retries = Retry(
        total=cfg.get("scraping", {}).get("max_retries", 3),
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    session = requests.Session()
    session.headers.update({"User-Agent": ua})
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def polite_get(
    url: str,
    session: Optional[requests.Session] = None,
    delay: Optional[float] = None,
    timeout: int = 30,
) -> Optional[requests.Response]:
    """GET with rate-limiting and error handling. Returns None on failure."""
    logger = get_logger("http")
    if delay is None:
        delay = get_config_value("scraping", "request_delay_seconds", default=2.0)
    if session is None:
        session = build_session()
    time.sleep(delay)
    try:
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        logger.warning(f"GET {url} failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Robots.txt check
# Python 3.9's RobotFileParser mishandles wildcards in patterns like
# /p/*/comment/* and incorrectly blocks all /p/ paths. We implement our own
# parser that correctly converts robots.txt glob patterns to regex.
# ---------------------------------------------------------------------------

_robots_cache: Dict[str, List[re.Pattern]] = {}   # domain → list of disallowed patterns


def _robots_pattern_to_regex(pattern: str) -> re.Pattern:
    """Convert a robots.txt Disallow path (with * and $ wildcards) to a compiled regex."""
    # Escape everything except * and $
    escaped = re.escape(pattern)
    # Restore * as .* (match any sequence)
    escaped = escaped.replace(r"\*", ".*")
    # $ as end-of-string anchor (already escaped above, but * replacement may change things)
    escaped = escaped.rstrip("$") + ("$" if pattern.endswith("$") else "")
    return re.compile("^" + escaped)


def _load_robots(base: str) -> List[re.Pattern]:
    """Fetch and parse robots.txt for base URL. Returns list of disallowed path patterns."""
    robots_url = urljoin(base, "/robots.txt")
    disallowed: List[re.Pattern] = []
    try:
        resp = requests.get(robots_url, timeout=10, headers={"User-Agent": "ReboundCapitalTracker/1.0"})
        if resp.status_code != 200:
            return disallowed
        current_agents: List[str] = []
        applies = False
        for line in resp.text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                current_agents = []
                applies = False
                continue
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip().lower()
            val = val.strip()
            if key == "user-agent":
                current_agents.append(val.lower())
                # applies to us if wildcard or our bot name
                if val == "*" or "reboundcapitaltracker" in val.lower():
                    applies = True
            elif key == "disallow" and applies and val:
                disallowed.append(_robots_pattern_to_regex(val))
    except Exception:
        pass
    return disallowed


def can_fetch(url: str, ua: Optional[str] = None) -> bool:
    """Return True if robots.txt allows fetching the URL."""
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    if base not in _robots_cache:
        _robots_cache[base] = _load_robots(base)
    path = parsed.path or "/"
    for pattern in _robots_cache[base]:
        if pattern.match(path):
            return False
    return True


# ---------------------------------------------------------------------------
# Content hashing / caching
# ---------------------------------------------------------------------------

def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def save_raw_html(url: str, html: str, raw_dir: Optional[Path] = None) -> Path:
    if raw_dir is None:
        raw_dir = Path(get_config_value("output", "raw_html_dir", default="data/raw_html"))
    raw_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w\-_]", "_", url)[:120]
    h = content_hash(url)[:8]
    path = raw_dir / f"{safe}_{h}.html"
    path.write_text(html, encoding="utf-8", errors="replace")
    return path


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

def clean_text(text: str) -> str:
    """Remove excessive whitespace and normalize."""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def truncate(text: str, max_chars: int = 500) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def same_domain(url: str, base: str) -> bool:
    return urlparse(url).netloc == urlparse(base).netloc


def normalise_url(url: str) -> str:
    """Strip fragments and trailing slashes for deduplication."""
    p = urlparse(url)
    return p._replace(fragment="").geturl().rstrip("/")


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

import dateparser
from datetime import datetime


def parse_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return dateparser.parse(raw, settings={"RETURN_AS_TIMEZONE_AWARE": False})
    except Exception:
        return None
