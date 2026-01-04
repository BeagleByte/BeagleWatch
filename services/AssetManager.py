from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

OUTPUT_DIR = Path("content")
ASSETS_DIR = OUTPUT_DIR / "assets"
DB_PATH = Path("db/posts.db")
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
REQUEST_TIMEOUT = 30
now = datetime.now(timezone.utc)

class AssetManager:
    def __init__(self, base_dir: Path = ASSETS_DIR):
        self.base_dir = base_dir
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def download_to_temp(self, feed_slug: str, date_str: str, post_slug: str, url: str) -> Optional[Path]:
        """
        Download into a temporary file and return its Path (temp file).
        Caller will move atomically into final location.
        """
        try:
            parsed = urlparse(url)
            fname = os.path.basename(parsed.path) or "file"
            # temp file
            tf = Path(tempfile.mkstemp(prefix="asset_", suffix=f"_{fname}")[1])
            with self.session.get(url, stream=True, timeout=REQUEST_TIMEOUT) as r:
                r.raise_for_status()
                with open(tf, "wb",encoding="utf-8") as fh:
                    for chunk in r.iter_content(8192):
                        if chunk:
                            fh.write(chunk)
            return tf
        except Exception:
            return None

    def final_asset_path(self, feed_slug: str, date_str: str, post_slug: str, filename: str) -> Path:
        dest_dir = self.base_dir / feed_slug / date_str / post_slug
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename
        # ensure unique
        i = 1
        while dest.exists():
            dest = dest_dir / f"{dest.stem}-{i}{dest.suffix}"
            i += 1
        return dest