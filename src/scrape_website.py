"""
Official Rebound Capital website scraper.

Crawls within the same domain, prioritising investment/research content.
"""
from __future__ import annotations

import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional, Set
from urllib.parse import urljoin, urlparse

import trafilatura
from bs4 import BeautifulSoup
from tqdm import tqdm

from src.database import Source, get_session, init_db
from src.utils import (
    can_fetch, clean_text, content_hash, get_config_value, get_logger,
    normalise_url, parse_date, polite_get, same_domain, save_raw_html,
)

logger = get_logger("scrape_website")

# URL path segments that suggest investment writing
CONTENT_HINTS = re.compile(
    r"(blog|research|portfolio|update|thesis|essay|newsletter|insight|idea|"
    r"stock|invest|analys|report|pick|position|holding|watchlist)",
    re.I,
)

# Paths to skip
SKIP_PATTERNS = re.compile(
    r"(privacy|terms|cookie|contact|about|careers|legal|cdn-cgi|wp-login|"
    r"\.(jpg|jpeg|png|gif|svg|pdf|zip|css|js|ico|woff|ttf)(\?|$))",
    re.I,
)


def _should_follow(url: str, base_url: str) -> bool:
    if not same_domain(url, base_url):
        return False
    path = urlparse(url).path
    if SKIP_PATTERNS.search(path):
        return False
    return True


def _priority(url: str) -> int:
    """Lower = higher priority. Content hints get priority 0, others 1."""
    if CONTENT_HINTS.search(urlparse(url).path):
        return 0
    return 1


def fetch_page(url: str) -> Optional[dict]:
    if not can_fetch(url):
        logger.info(f"robots.txt disallows: {url}")
        return None

    resp = polite_get(url)
    if resp is None:
        return None

    content_type = resp.headers.get("Content-Type", "")
    if "text/html" not in content_type:
        return None

    raw_html = resp.text
    soup = BeautifulSoup(raw_html, "html.parser")

    # title
    title = ""
    t = soup.find("title") or soup.find("h1") or soup.find("meta", {"property": "og:title"})
    if t:
        title = t.get("content", "") or t.get_text(strip=True)

    # meta description
    meta_desc = ""
    m = soup.find("meta", {"name": "description"}) or soup.find("meta", {"property": "og:description"})
    if m:
        meta_desc = m.get("content", "")

    # date
    pub_date = None
    for sel in ['meta[property="article:published_time"]', 'time[datetime]']:
        el = soup.select_one(sel)
        if el:
            raw_date = el.get("content") or el.get("datetime") or ""
            pub_date = parse_date(raw_date)
            if pub_date:
                break

    # headings
    headings = [h.get_text(strip=True) for h in soup.find_all(["h2", "h3"])][:10]

    # body text
    body_text = trafilatura.extract(raw_html, include_comments=False, include_tables=True) or ""

    # outbound links on same domain
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        norm = normalise_url(href)
        if _should_follow(norm, url):
            links.append(norm)

    raw_path = save_raw_html(url, raw_html)
    h = content_hash(raw_html)

    return {
        "url": url,
        "title": clean_text(title),
        "meta_description": clean_text(meta_desc),
        "published_date": pub_date,
        "headings": headings,
        "body_text": body_text,
        "content_hash": h,
        "raw_html_path": str(raw_path),
        "links": links,
    }


def scrape_website(force_refresh: bool = False) -> int:
    init_db()
    base_url = get_config_value("sources", "website_url", default="")
    if not base_url or "PASTE_" in base_url:
        logger.warning("Website URL not configured in config.yaml — skipping.")
        return 0

    max_pages = get_config_value("scraping", "max_pages", default=500)

    session = get_session()
    existing_urls = {row[0] for row in session.execute(
        __import__("sqlalchemy").text("SELECT url FROM sources WHERE source_type='website'")
    )}

    queue: deque = deque()
    queue.append((normalise_url(base_url), 0))
    visited: Set[str] = set(existing_urls)
    fetched_count = 0

    with tqdm(desc="Website pages") as pbar:
        while queue and fetched_count < max_pages:
            url, priority = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            data = fetch_page(url)
            if data is None:
                src = Source(
                    source_type="website",
                    url=url,
                    status="skipped",
                    fetched_at=datetime.utcnow(),
                )
                session.add(src)
                session.commit()
                continue

            src = Source(
                source_type="website",
                url=data["url"],
                title=data["title"],
                published_date=data["published_date"],
                fetched_at=datetime.utcnow(),
                content_hash=data["content_hash"],
                raw_html_path=data["raw_html_path"],
                status="fetched",
            )
            session.add(src)
            session.commit()
            fetched_count += 1
            pbar.update(1)
            pbar.set_postfix(url=url[:60])

            for link in data.get("links", []):
                if link not in visited:
                    p = _priority(link)
                    queue.append((link, p))

            # sort queue by priority
            queue = deque(sorted(queue, key=lambda x: x[1]))

    logger.info(f"Website scrape complete. Pages fetched: {fetched_count}")
    return fetched_count
