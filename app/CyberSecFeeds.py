#!/usr/bin/env python3
"""
rss_to_md_oop_safe.py
OOP RSS -> Markdown with idempotent, concurrency-safe insertion.

Requirements:
    pip install feedparser requests python-slugify

Features:
- Multiple feeds
- Deduplication by GUID (preferred) or fingerprint fallback
- UNIQUE constraints on guid and fingerprint
- Atomic file moves for markdown and assets
- DB transactions and IntegrityError handling
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import traceback
from pathlib import Path
from typing import List
from urllib.parse import urlparse
from slugify import slugify
from services.AssetManager import AssetManager
from services.FeedFetcher import FeedFetcher
from services.MarkdownStore import MarkdownStore
import logging
import threading
import time
import schedule

# CONFIG
FEEDS = [
    "https://feeds.feedburner.com/TheHackersNews",
    "https://www.bleepingcomputer.com/feed/",
    "https://cvefeed.io/rssfeed/latest.xml",
    "https://cvefeed.io/rssfeed/newsroom.xml"
]
OUTPUT_DIR = Path("content")
ASSETS_DIR = OUTPUT_DIR / "assets"
DB_PATH = Path("db/posts.db")

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

# your job
def job():
    print("job start", time.time())
    print("scheduled job running")
    # call whatever method you need, e.g. app.do_something()

def run_scheduler():
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            print("Scheduler error:", e)
        time.sleep(1)

class RssToMdApp:
    def __init__(self, feeds: List[str]):
        self.feeds = feeds
        self.fetcher = FeedFetcher()
        self.asset_mgr = AssetManager()
        self.store = MarkdownStore()

    def feed_slug(self, feed_title: str) -> str:
        return safe_slug(feed_title or "feed")

    def process_feed(self, feed_url: str):
        parsed = self.fetcher.fetch(feed_url)
        feed_title = parsed.feed.get("title", feed_url)
        feed_slug = self.feed_slug(feed_title)
        entries = parsed.entries or []
        try:
            for entry in entries:
                try:
                    item = self.fetcher.parse_item(entry)
                    # quick existence check to avoid downloads
                    if self.store.exists_guid_or_fp(item.guid, item.fingerprint):
                        print("Skipping existing (guid/fp):", item.guid or item.fingerprint[:8])
                        continue

                    # Download enclosures to temp, then move into final after DB insertion
                    temp_assets = []
                    final_asset_paths: List[Path] = []
                    for enc in item.enclosures:
                        url = enc.get("href") or enc.get("url")
                        if not url:
                            continue
                        tf = self.asset_mgr.download_to_temp(feed_slug, item.published_date_str, safe_slug(item.title), url)
                        if tf:
                            temp_assets.append((tf, url))

                    # determine final asset destinations and move atomically after DB insert success
                    for tf, url in temp_assets:
                        filename = os.path.basename(urlparse(url).path) or tf.name
                        final = self.asset_mgr.final_asset_path(feed_slug, item.published_date_str, safe_slug(item.title), filename)
                        final_asset_paths.append((tf, final))

                    # Attempt to write markdown and insert DB row; if duplicate, cleanup temp assets
                    # But we need asset final paths (only move them if DB insert succeeded)
                    # Call store.atomic_write_post with placeholder final asset paths (we'll move assets after success)
                    # Note: atomic_write_post expects final asset paths for markdown linking; we will compute them now
                    final_paths_only = [f for (_, f) in final_asset_paths]

                    written = self.store.atomic_write_post(feed_title, item, final_paths_only)
                    if not written:
                        # duplicate detected during insert; remove temp assets
                        for tf, _ in temp_assets:
                            try:
                                tf.unlink()
                            except Exception:
                                pass
                        print("Skipped (insert race):", item.guid or item.fingerprint[:8])
                        continue

                    # move temp assets into final locations (atomic)
                    for tf, final in final_asset_paths:
                        try:
                            # if final already exists (very unlikely because we ensured uniqueness), skip
                            if final.exists():
                                try:
                                    tf.unlink()
                                except Exception:
                                    pass
                                continue
                            os.replace(str(tf), str(final))
                        except Exception:
                            # best-effort: if move fails, remove temp
                            try:
                                tf.unlink()
                            except Exception:
                                pass

                    print("Wrote:", written)
                except Exception as e:
                    print("Error processing entry:", e)
                    print(e.args)
        except Exception as e:
            print("Error processing feed entries:", e)

    def run(self):
        for f in self.feeds:
            try:
                print("Processing feed:", f)
                self.process_feed(f)
            except Exception as e:
                print("Feed error:", f, e)
                traceback.print_exc()

if __name__ == "__main__":
    # schedule jobs
    schedule.every(1).minutes.do(job)

    # start scheduler thread
    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()

    # start main app
    app = RssToMdApp(FEEDS if len(sys.argv) == 1 else sys.argv[1:])
    try:
        print("run")
        app.run()
    except KeyboardInterrupt:
        pass

    # app = RssToMdApp(FEEDS)
    #
    #
    # def job():
    #     for f in app.feeds:
    #         threading.Thread(target=app.process_feed, args=(f,), daemon=True).start()
    #
    #
    # schedule.every(16).minutes.do(job)
    #
    # t = threading.Thread(target=run_scheduler, daemon=True)
    # t.start()
    #
    # # Optionally run job once at startup:
    # job()
    #
    # # Keep main alive (or handle signals)
    # try:
    #     while True:
    #         time.sleep(1)
    # except KeyboardInterrupt:
    #     pass
