from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator


class SourceType(StrEnum):
    RSS = "rss"
    API = "api"
    HTML_SEARCH = "html_search"
    HTML_DETAIL = "html_detail"


class ItemType(StrEnum):
    ARTICLE = "article"
    LISTING = "listing"
    EVENT = "event"
    OFFER = "offer"
    PARLIAMENT_VOTE = "parliament_vote"
    SYSTEM_EVENT = "system_event"


class SourceConfig(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    name: str
    source_type: SourceType = Field(alias="type")
    category: str
    url: HttpUrl
    enabled: bool = True
    interval_minutes: int = Field(default=60, gt=0)
    parser: str = "rss_article"
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("category", "parser")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class NormalizedItem(BaseModel):
    source_id: str
    item_type: ItemType
    title: str
    canonical_url: HttpUrl
    external_id: str | None = None
    description: str | None = None
    content_text: str | None = None
    published_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def title_must_have_text(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("title must not be empty")
        return value

    @field_validator("published_at")
    @classmethod
    def ensure_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class FetchResult(BaseModel):
    source_id: str
    status: str
    http_status: int | None = None
    items_found: int = 0
    items_new: int = 0
    items_changed: int = 0
    bytes_downloaded: int = 0
    error: str | None = None


class QuarantineCandidate(BaseModel):
    reason: str
    payload: dict[str, Any] = Field(default_factory=dict)
