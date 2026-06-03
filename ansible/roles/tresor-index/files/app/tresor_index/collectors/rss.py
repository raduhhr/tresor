from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
from pydantic import ValidationError
import requests

from ..models import ItemType, NormalizedItem, QuarantineCandidate, SourceConfig


def _parse_datetime(entry: dict[str, Any]) -> datetime | None:
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if not value:
            continue
        try:
            parsed = parsedate_to_datetime(value)
        except Exception:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def fetch_rss(source: SourceConfig) -> tuple[list[NormalizedItem], list[QuarantineCandidate], int, int]:
    response = requests.get(str(source.url), timeout=20, headers={"User-Agent": "tresor-index/0.1"})
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    items: list[NormalizedItem] = []
    rejected: list[QuarantineCandidate] = []
    for entry in parsed.entries:
        url = entry.get("link") or entry.get("id")
        title = entry.get("title")
        if not url or not title:
            rejected.append(
                QuarantineCandidate(
                    reason="rss entry missing required link or title",
                    payload=dict(entry),
                )
            )
            continue
        summary = entry.get("summary") or entry.get("description")
        metadata = {
            "feed_title": parsed.feed.get("title"),
            "author": entry.get("author"),
            "tags": [tag.get("term") for tag in entry.get("tags", []) if tag.get("term")],
        }
        try:
            items.append(
                NormalizedItem(
                    source_id=source.id,
                    item_type=ItemType.ARTICLE,
                    title=title,
                    canonical_url=url,
                    external_id=entry.get("id"),
                    description=summary,
                    content_text=summary,
                    published_at=_parse_datetime(entry),
                    metadata={k: v for k, v in metadata.items() if v},
                )
            )
        except ValidationError as exc:
            rejected.append(
                QuarantineCandidate(
                    reason=str(exc),
                    payload=dict(entry),
                )
            )
    return items, rejected, response.status_code, len(response.content)
