from __future__ import annotations

import json
import time

from . import db
from .config import load_sources, scheduler_interval_seconds
from .civic_cache import civic_cache_keys, refresh_civic_caches
from .digest import run_due_digests
from .ingest import fetch_source
from .models import SourceConfig

CIVIC_PARSERS = {"cdep_final_votes", "senat_final_votes"}


def _refresh_civic_cache(reason: str) -> dict:
    try:
        results = refresh_civic_caches()
        return {"status": "success", "reason": reason, "results": results}
    except Exception as exc:
        return {"status": "error", "reason": reason, "error": str(exc)}


def _civic_cache_needs_refresh() -> bool:
    rows = db.api_cache_status()
    by_key = {row.get("key"): row for row in rows}
    for key in civic_cache_keys():
        row = by_key.get(key)
        if row is None or bool(row.get("expired")):
            return True
    return False


def source_from_row(row: dict) -> SourceConfig:
    return SourceConfig.model_validate(
        {
            "id": row["id"],
            "name": row["name"],
            "type": row["source_type"],
            "category": row["category"],
            "url": row["url"],
            "enabled": row["enabled"],
            "interval_minutes": row["interval_minutes"],
            "parser": row["parser"],
            "config": row["config"] or {},
        }
    )


def run_once(*, all_enabled: bool = False) -> list[dict]:
    db.migrate()
    sources = load_sources()
    db.sync_sources(sources)
    configured = {source.id: source for source in sources}

    if all_enabled:
        targets = [source for source in sources if source.enabled]
    else:
        targets = [source_from_row(row) for row in db.due_sources()]

    results: list[dict] = []
    for source in targets:
        result = fetch_source(source)
        results.append(result.model_dump())
    if any(source.parser in CIVIC_PARSERS for source in targets):
        results.append({"api_cache": _refresh_civic_cache("run_once_civic_fetch")})

    return [
        {
            "sources_configured": len(sources),
            "sources_selected": len(targets),
            "mode": "all_enabled" if all_enabled else "due",
        },
        *results,
    ]


def run_forever() -> None:
    db.migrate()
    db.sync_sources(load_sources())
    interval = scheduler_interval_seconds()
    print(f"tresor-index scheduler running; tick={interval}s", flush=True)
    if _civic_cache_needs_refresh():
        print(json.dumps({"api_cache": _refresh_civic_cache("scheduler_start")}, default=str), flush=True)
    while True:
        due = db.due_sources()
        if due:
            print(f"due sources: {', '.join(row['id'] for row in due)}", flush=True)
        saw_civic = False
        for row in due:
            source = source_from_row(row)
            result = fetch_source(source)
            saw_civic = saw_civic or source.parser in CIVIC_PARSERS
            print(json.dumps(result.model_dump(), default=str), flush=True)
        if saw_civic or _civic_cache_needs_refresh():
            reason = "scheduler_civic_fetch" if saw_civic else "scheduler_cache_expired"
            print(json.dumps({"api_cache": _refresh_civic_cache(reason)}, default=str), flush=True)
        digest_results = run_due_digests()
        for result in digest_results:
            print(json.dumps(result, default=str), flush=True)
        time.sleep(interval)
