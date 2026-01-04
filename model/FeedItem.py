from dataclasses import dataclass
from typing import Optional


@dataclass
class FeedItem:
    guid: Optional[str]
    fingerprint: str
    title: str
    link: str
    content: str
    published_iso: str
    published_date_str: str
    enclosures: List[dict]