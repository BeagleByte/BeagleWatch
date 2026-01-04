from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests

from model.FeedItem import FeedItem


USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
REQUEST_TIMEOUT = 30
now = datetime.now(timezone.utc)

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

class FeedFetcher:
    def __init__(self, user_agent: str = USER_AGENT, timeout: int = REQUEST_TIMEOUT):
        self.user_agent = user_agent
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

    def fetch(self, url: str) -> feedparser.FeedParserDict:
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return feedparser.parse(resp.content)
        except Exception as e:
            print(e)

    def parse_item(self, entry: feedparser.FeedParserDict) -> FeedItem:
        title = (entry.get("title") or "").strip()
        guid = entry.get("guid") or entry.get("id") or entry.get("link")
        link = entry.get("link", "") or ""
        # content fallback
        content = ""
        if entry.get("content"):
            content = entry.content[0].value
        else:
            content = entry.get("description", "") or entry.get("summary", "")
        content = content.strip()
        # published
        pub_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if pub_parsed:
            published_dt = datetime(*pub_parsed[:6])
        else:
            published_dt = now
        published_iso = published_dt.isoformat() + "Z"
        published_date_str = published_dt.strftime("%Y-%m-%d")
        # fingerprint fallback: title + link + normalized content
        fingerprint = sha256_hex((title or "") + "|" + (link or "") + "|" + re.sub(r'\s+', ' ', content or "")[:2000])
        enclosures = entry.get("enclosures", []) or []
        return FeedItem(
            guid=str(guid) if guid else None,
            fingerprint=fingerprint,
            title=title or "untitled",
            link=link,
            content=content,
            published_iso=published_iso,
            published_date_str=published_date_str,
            enclosures=enclosures,
        )