from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from . import db
from .api import (
    CIVIC_BILLS_CACHE_PREFIX,
    CIVIC_PARTIES_CACHE_PREFIX,
    CIVIC_OVERVIEW_CACHE_KEY,
    PARTY_LINE_CACHE_LIMIT,
    build_civic_bills_payload,
    build_civic_parties_payload,
    build_civic_overview_payload,
    build_civic_party_line_discipline_payload,
    civic_bills_cache_key,
    civic_parties_cache_key,
    party_line_cache_key,
)


DEFAULT_TTL_SECONDS = 12 * 60 * 60
PARTY_LINE_CACHE_VARIANTS = (
    ("party", "asc"),
    ("party", "desc"),
    ("politician", "asc"),
    ("politician", "desc"),
)
CIVIC_PARTIES_CACHE_VARIANTS = (None, "Camera Deputatilor", "Senat")
CIVIC_BILLS_CACHE_LIMITS = (50, 100)


def civic_cache_keys() -> list[str]:
    return [
        CIVIC_OVERVIEW_CACHE_KEY,
        *[
            civic_parties_cache_key(chamber=chamber)
            for chamber in CIVIC_PARTIES_CACHE_VARIANTS
        ],
        *[
            civic_bills_cache_key(limit=limit)
            for limit in CIVIC_BILLS_CACHE_LIMITS
        ],
        *[
            party_line_cache_key(group_by=group_by, order=order)
            for group_by, order in PARTY_LINE_CACHE_VARIANTS
        ],
    ]


def refresh_civic_overview_cache(*, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict[str, Any]:
    payload = build_civic_overview_payload()
    db.set_api_cache(
        CIVIC_OVERVIEW_CACHE_KEY,
        payload,
        ttl_seconds=ttl_seconds,
        metadata={
            "kind": "civic_overview",
            "refreshed_by": "tresor_index",
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {
        "key": CIVIC_OVERVIEW_CACHE_KEY,
        "status": "refreshed",
        "ttl_seconds": ttl_seconds,
        "votes": (payload.get("totals") or {}).get("votes"),
        "latest_vote_time": (payload.get("coverage") or {}).get("latest_vote_time"),
    }


def refresh_civic_party_line_cache(
    *,
    group_by: str,
    order: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    payload = build_civic_party_line_discipline_payload(
        group_by=group_by,
        order=order,
        limit=PARTY_LINE_CACHE_LIMIT,
        offset=0,
    )
    key = party_line_cache_key(group_by=group_by, order=order)
    db.set_api_cache(
        key,
        payload,
        ttl_seconds=ttl_seconds,
        metadata={
            "kind": "civic_party_line",
            "group_by": group_by,
            "order": order,
            "limit": PARTY_LINE_CACHE_LIMIT,
            "refreshed_by": "tresor_index",
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {
        "key": key,
        "status": "refreshed",
        "ttl_seconds": ttl_seconds,
        "items": len(payload.get("items") or []),
    }


def refresh_civic_parties_cache(
    *,
    chamber: str | None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    payload = build_civic_parties_payload(chamber=chamber)
    key = civic_parties_cache_key(chamber=chamber)
    db.set_api_cache(
        key,
        payload,
        ttl_seconds=ttl_seconds,
        metadata={
            "kind": CIVIC_PARTIES_CACHE_PREFIX,
            "chamber": chamber,
            "refreshed_by": "tresor_index",
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {
        "key": key,
        "status": "refreshed",
        "ttl_seconds": ttl_seconds,
        "items": len(payload.get("items") or []),
    }


def refresh_civic_bills_cache(
    *,
    limit: int,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    payload = build_civic_bills_payload(limit=limit, offset=0)
    key = civic_bills_cache_key(limit=limit)
    db.set_api_cache(
        key,
        payload,
        ttl_seconds=ttl_seconds,
        metadata={
            "kind": CIVIC_BILLS_CACHE_PREFIX,
            "limit": limit,
            "refreshed_by": "tresor_index",
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {
        "key": key,
        "status": "refreshed",
        "ttl_seconds": ttl_seconds,
        "items": len(payload.get("items") or []),
        "total": payload.get("total"),
    }


def refresh_civic_caches(*, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> list[dict[str, Any]]:
    return [
        {"key": "parliament_politician_summaries", **db.refresh_parliament_politician_summaries()},
        refresh_civic_overview_cache(ttl_seconds=ttl_seconds),
        *[
            refresh_civic_parties_cache(chamber=chamber, ttl_seconds=ttl_seconds)
            for chamber in CIVIC_PARTIES_CACHE_VARIANTS
        ],
        *[
            refresh_civic_bills_cache(limit=limit, ttl_seconds=ttl_seconds)
            for limit in CIVIC_BILLS_CACHE_LIMITS
        ],
        *[
            refresh_civic_party_line_cache(group_by=group_by, order=order, ttl_seconds=ttl_seconds)
            for group_by, order in PARTY_LINE_CACHE_VARIANTS
        ],
    ]
