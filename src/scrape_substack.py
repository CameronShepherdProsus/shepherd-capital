"""
Substack scraper for Rebound Capital.

Discovery order:
  1. RSS feed  (<substack_url>/feed)
  2. Sitemap   (<substack_url>/sitemap.xml)
  3. Archive   (<substack_url>/archive)
  4. Homepage link crawl

Only fetches publicly accessible content — no paywall bypass.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set
from urllib.parse import urljoin, urlparse

import feedparser
import trafilatura
from bs4 import BeautifulSoup
from tqdm import tqdm

from src.database import Source, get_session, init_db
from src.utils import (
    can_fetch, clean_text, content_hash, get_config_value, get_logger,
    normalise_url, parse_date, polite_get, save_raw_html,
)

logger = get_logger("scrape_substack")


# ---------------------------------------------------------------------------
# URL discovery
# ---------------------------------------------------------------------------

def discover_via_rss(base_url: str) -> List[dict]:
    feed_url = base_url.rstrip("/") + "/feed"
    logger.info(f"Trying RSS feed: {feed_url}")
    resp = polite_get(feed_url)
    if resp is None:
        return []
    feed = feedparser.parse(resp.text)
    entries = []
    for entry in feed.entries:
        url = getattr(entry, "link", None)
        if not url:
            continue
        entries.append({
            "url": normalise_url(url),
            "title": getattr(entry, "title", ""),
            "author": getattr(entry, "author", ""),
            "published": getattr(entry, "published", None),
            "summary": getattr(entry, "summary", ""),
        })
    logger.info(f"RSS: found {len(entries)} entries")
    return entries


def discover_via_sitemap(base_url: str) -> List[str]:
    sitemap_url = base_url.rstrip("/") + "/sitemap.xml"
    logger.info(f"Trying sitemap: {sitemap_url}")
    resp = polite_get(sitemap_url)
    if resp is None:
        return []
    soup = BeautifulSoup(resp.text, "xml")
    urls = [loc.get_text(strip=True) for loc in soup.find_all("loc")]
    # Keep only article-like URLs (contain /p/ which is Substack pattern)
    article_urls = [u for u in urls if "/p/" in u]
    logger.info(f"Sitemap: found {len(article_urls)} article URLs")
    return [normalise_url(u) for u in article_urls]


def discover_via_archive(base_url: str, max_pages: int = 100) -> List[str]:
    """Paginate through /archive to collect article links."""
    discovered: Set[str] = set()
    session = None
    for page in range(1, max_pages + 1):
        archive_url = f"{base_url.rstrip('/')}/archive?sort=new&page={page}"
        logger.info(f"Archive page {page}: {archive_url}")
        resp = polite_get(archive_url)
        if resp is None:
            break
        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.find_all("a", href=True)
        new_found = 0
        for a in links:
            href = urljoin(base_url, a["href"])
            if "/p/" in href and urlparse(href).netloc == urlparse(base_url).netloc:
                norm = normalise_url(href)
                if norm not in discovered:
                    discovered.add(norm)
                    new_found += 1
        logger.info(f"  → {new_found} new articles (total {len(discovered)})")
        if new_found == 0:
            break
    return list(discovered)


def discover_via_homepage(base_url: str) -> List[str]:
    resp = polite_get(base_url)
    if resp is None:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    urls = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if "/p/" in href and urlparse(href).netloc == urlparse(base_url).netloc:
            urls.add(normalise_url(href))
    logger.info(f"Homepage: found {len(urls)} article links")
    return list(urls)


# ---------------------------------------------------------------------------
# Article fetching
# ---------------------------------------------------------------------------

def _is_public(soup: BeautifulSoup) -> bool:
    """Heuristic: return False if page shows a paywall/subscribe prompt."""
    text = soup.get_text(" ", strip=True).lower()
    for marker in ["this post is for paid subscribers", "subscribe to read", "upgrade your subscription"]:
        if marker in text:
            return False
    return True


def fetch_article(url: str, meta: Optional[dict] = None) -> Optional[dict]:
    """Fetch and parse one Substack article. Returns None if inaccessible."""
    if not can_fetch(url):
        logger.info(f"robots.txt disallows: {url}")
        return None

    resp = polite_get(url)
    if resp is None:
        return None

    raw_html = resp.text
    soup = BeautifulSoup(raw_html, "html.parser")

    if not _is_public(soup):
        logger.info(f"Skipping paywalled/restricted content: {url}")
        return None

    # --- metadata ---
    title = ""
    title_el = soup.find("h1") or soup.find("meta", {"property": "og:title"})
    if title_el:
        title = title_el.get("content", "") or title_el.get_text(strip=True)

    author = ""
    author_el = soup.find("meta", {"name": "author"}) or soup.find("a", {"class": re.compile(r"author", re.I)})
    if author_el:
        author = author_el.get("content", "") or author_el.get_text(strip=True)

    pub_date = None
    date_el = soup.find("meta", {"property": "article:published_time"})
    if date_el:
        pub_date = parse_date(date_el.get("content", ""))
    if pub_date is None and meta and meta.get("published"):
        pub_date = parse_date(meta["published"])

    subtitle = ""
    sub_el = soup.find("h3") or soup.find("meta", {"property": "og:description"})
    if sub_el:
        subtitle = sub_el.get("content", "") or sub_el.get_text(strip=True)

    # --- body text via trafilatura (cleaner than BS4) ---
    body_text = trafilatura.extract(raw_html, include_comments=False, include_tables=True) or ""

    raw_path = save_raw_html(url, raw_html)
    h = content_hash(raw_html)

    return {
        "url": url,
        "title": clean_text(title),
        "author": clean_text(author),
        "subtitle": clean_text(subtitle),
        "published_date": pub_date,
        "body_text": body_text,
        "content_hash": h,
        "raw_html_path": str(raw_path),
    }


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

def scrape_substack(force_refresh: bool = False) -> int:
    """
    Full Substack scrape. Returns number of newly fetched articles.
    """
    init_db()
    base_url = get_config_value("sources", "substack_url", default="")
    if not base_url or "PASTE_" in base_url:
        logger.warning("Substack URL not configured in config.yaml — skipping.")
        return 0

    use_rss = get_config_value("sources", "use_rss", default=True)
    use_sitemap = get_config_value("sources", "use_sitemap", default=True)
    include_archived = get_config_value("sources", "include_archived_substack", default=True)
    max_pages = get_config_value("scraping", "max_pages", default=500)

    # --- discovery ---
    rss_meta: dict[str, dict] = {}
    discovered: Set[str] = set()

    if use_rss:
        for entry in discover_via_rss(base_url):
            u = entry["url"]
            discovered.add(u)
            rss_meta[u] = entry

    if use_sitemap:
        for u in discover_via_sitemap(base_url):
            discovered.add(u)

    if include_archived:
        for u in discover_via_archive(base_url, max_pages=50):
            discovered.add(u)

    for u in discover_via_homepage(base_url):
        discovered.add(u)

    logger.info(f"Total discovered URLs: {len(discovered)}")

    # --- store RSS-only entries first (free preview text available even for paid posts) ---
    session = get_session()
    fetched_count = 0
    import sqlalchemy as _sa

    def _upsert_source(url: str, **kwargs) -> Source:
        """Insert or update a Source row, avoiding UNIQUE errors on re-runs."""
        existing = session.query(Source).filter_by(url=url).first()
        if existing:
            for k, v in kwargs.items():
                if v is not None:
                    setattr(existing, k, v)
            session.commit()
            return existing
        src = Source(url=url, **kwargs)
        session.add(src)
        session.commit()
        return src

    # Store RSS entries with preview text so extraction can use them
    for url, meta in rss_meta.items():
        summary = clean_text(meta.get("summary", "") or "")
        if not summary:
            continue
        # Save preview text as a minimal "fetched" source so the extractor sees it
        preview_path = None
        if summary:
            preview_path = save_raw_html(url + "_rss_preview", f"<html><body><p>{summary}</p></body></html>")
        _upsert_source(
            url=url,
            source_type="substack",
            title=clean_text(meta.get("title", "")),
            author=clean_text(meta.get("author", "")),
            published_date=parse_date(meta.get("published")),
            fetched_at=datetime.utcnow(),
            raw_html_path=str(preview_path) if preview_path else None,
            status="fetched",  # preview text is valid for extraction
        )
        fetched_count += 1

    existing_urls = {row[0] for row in session.execute(
        _sa.text("SELECT url FROM sources WHERE source_type='substack'")
    )}

    # Only attempt full-page fetch for URLs not already stored (or force-refresh)
    to_fetch = [u for u in discovered if u not in existing_urls or force_refresh]
    logger.info(f"New URLs to fetch (full page): {len(to_fetch)}")

    for url in tqdm(to_fetch[:max_pages], desc="Substack articles"):
        meta = rss_meta.get(url, {})
        data = fetch_article(url, meta)
        if data is None:
            # Store skipped only if not already stored from RSS
            if url not in existing_urls:
                _upsert_source(
                    url=url,
                    source_type="substack",
                    status="skipped",
                    fetched_at=datetime.utcnow(),
                )
            continue

        _upsert_source(
            url=data["url"],
            source_type="substack",
            title=data["title"],
            author=data["author"],
            published_date=data["published_date"],
            fetched_at=datetime.utcnow(),
            content_hash=data["content_hash"],
            raw_html_path=data["raw_html_path"],
            status="fetched",
        )
        session.commit()
        fetched_count += 1

    logger.info(f"Substack scrape complete. New articles fetched: {fetched_count}")
    return fetched_count
