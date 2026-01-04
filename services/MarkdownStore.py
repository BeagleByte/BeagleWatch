from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from slugify import slugify


FEEDS = [
    "https://feeds.feedburner.com/TheHackersNews",
    "https://www.bleepingcomputer.com/feed/"
]
OUTPUT_DIR = Path("content")
ASSETS_DIR = OUTPUT_DIR / "assets"
DB_PATH = Path("db/posts.db")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
REQUEST_TIMEOUT = 30
now = datetime.now(timezone.utc)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

# SQLite setup (enable WAL for concurrency)
_conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)  # autocommit off; we'll use explicit transactions
_conn.execute("PRAGMA journal_mode=WAL;")
_cur = _conn.cursor()
_cur.execute(
    """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    guid TEXT UNIQUE,
    fingerprint TEXT UNIQUE,
    title TEXT,
    path TEXT,
    date TEXT,
    fetched_at TEXT,
    source_url TEXT,
    feed_title TEXT
)
"""
)
_conn.commit()

def safe_slug(s: str) -> str:
    s = slugify(s or "post")
    return re.sub(r'[^a-z0-9\-]+', '', s)[:200] or "post"

def now_iso() -> str:
    return now.isoformat() + "Z"

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

class MarkdownStore:
    def __init__(self, output_dir: Path = OUTPUT_DIR, db_conn: sqlite3.Connection = _conn):
        self.output_dir = output_dir
        self.db = db_conn
        self.cur = self.db.cursor()

    def exists_guid_or_fp(self, guid: Optional[str], fingerprint: str) -> bool:
        if guid:
            self.cur.execute("SELECT 1 FROM posts WHERE guid = ? LIMIT 1", (guid,))
            if self.cur.fetchone():
                return True
        self.cur.execute("SELECT 1 FROM posts WHERE fingerprint = ? LIMIT 1", (fingerprint,))
        return self.cur.fetchone() is not None

    def atomic_write_post(self, feed_title: str, item: FeedItem, asset_final_paths: List[Path]) -> Optional[Path]:
        """
        Atomically write markdown (via temp file -> os.replace) and insert DB row in a transaction.
        If insertion fails due to duplicate GUID/fingerprint, cleanup and return None.
        """
        post_slug = safe_slug(item.title)
        filename = f"{item.published_date_str}-{post_slug}.md"
        final_path = self.output_dir / filename

        # prepare frontmatter and body
        frontmatter = [
            "---",
            f'title: "{item.title.replace('"', "'")}"',
            f'date: "{item.published_iso}"',
            f'source_url: "{item.link}"',
            f'guid: "{item.guid or ""}"',
            f'fingerprint: "{item.fingerprint}"',
            f'original_feed: "{feed_title}"',
            f'fetched_at: "{now_iso()}"',
            "---",
            "",
        ]

        asset_md = []
        for p in asset_final_paths:
            if p:
                # compute relative path from markdown file
                try:
                    rel = p.relative_to(final_path.parent)
                except Exception:
                    rel = Path(os.path.relpath(str(p), start=str(final_path.parent)))
                asset_md.append(f"![{item.title}]({rel.as_posix()})")

        body = "\n\n".join(filter(None, [item.content] + asset_md))
        content = "\n".join(frontmatter) + body

        # write to temp file in same dir to ensure atomic replace works across filesystems
        tmp_fd, tmp_path = tempfile.mkstemp(prefix="mdtmp_", dir=str(self.output_dir))
        os.close(tmp_fd)
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                fh.write(content)

            # DB transaction: attempt to insert row; if duplicate, abort and remove temp file
            try:
                self.db.execute("BEGIN")
                # double-check to avoid unnecessary work in races
                if item.guid:
                    self.cur.execute("SELECT 1 FROM posts WHERE guid = ? LIMIT 1", (item.guid,))
                    if self.cur.fetchone():
                        self.db.execute("ROLLBACK")
                        os.remove(tmp_path)
                        return None
                self.cur.execute("SELECT 1 FROM posts WHERE fingerprint = ? LIMIT 1", (item.fingerprint,))
                if self.cur.fetchone():
                    self.db.execute("ROLLBACK")
                    os.remove(tmp_path)
                    return None

                # insert row
                self.cur.execute(
                    "INSERT INTO posts (guid, fingerprint, title, path, date, fetched_at, source_url, feed_title) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (item.guid, item.fingerprint, item.title, str(final_path), item.published_iso, now_iso(), item.link, feed_title),
                )
                self.db.execute("COMMIT")
            except sqlite3.IntegrityError:
                # concurrent insert happened
                self.db.execute("ROLLBACK")
                os.remove(tmp_path)
                return None

            # atomic move temp md file to final
            os.replace(tmp_path, str(final_path))
            return final_path
        except Exception:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            raise