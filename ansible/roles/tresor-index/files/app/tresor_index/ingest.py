from __future__ import annotations

from requests import HTTPError, RequestException

from . import db
from .collectors.cdep import fetch_cdep_final_votes
from .collectors.olx import fetch_olx_real_estate_search
from .collectors.rss import fetch_rss
from .collectors.senat import fetch_senat_final_votes
from .models import FetchResult, ItemType, NormalizedItem, SourceConfig, SourceType


def _num(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _record_listing_observations(item_id: int, item: NormalizedItem) -> None:
    if item.item_type != ItemType.LISTING:
        return

    metadata = item.metadata
    price = metadata.get("price") or {}
    location = metadata.get("location") or {}
    seller = metadata.get("seller") or {}

    price_value = _num(price.get("value"))
    if price_value is not None and price.get("currency") == "EUR":
        db.record_observation_if_changed(
            item_id,
            "price_eur",
            value_num=price_value,
            metadata={"source_id": item.source_id, "display": price.get("display")},
        )

    area = _num(metadata.get("area_sqm"))
    if area is not None:
        db.record_observation_if_changed(item_id, "area_sqm", value_num=area, metadata={"source_id": item.source_id})

    rooms = metadata.get("rooms")
    if rooms:
        db.record_observation_if_changed(item_id, "rooms", value_text=str(rooms), metadata={"source_id": item.source_id})

    area = metadata.get("area_label") or location.get("district") or location.get("city")
    if area:
        db.record_observation_if_changed(item_id, "district", value_text=str(area), metadata={"source_id": item.source_id})

    status = metadata.get("status")
    if status:
        db.record_observation_if_changed(item_id, "listing_status", value_text=str(status), metadata={"source_id": item.source_id})

    if "business" in seller:
        db.record_observation_if_changed(
            item_id,
            "seller_business",
            value_text=str(bool(seller.get("business"))).lower(),
            metadata={"source_id": item.source_id},
        )


def _record_parliament_vote(item_id: int, item: NormalizedItem, positions: list[dict]) -> None:
    if item.item_type != ItemType.PARLIAMENT_VOTE:
        return
    db.upsert_parliament_vote(item_id, item, positions)


def fetch_source(source: SourceConfig) -> FetchResult:
    run_id = db.begin_fetch_run(source.id)
    items_new = 0
    items_changed = 0
    try:
        if source.source_type == SourceType.RSS:
            items, rejected, http_status, bytes_downloaded = fetch_rss(source)
        elif source.source_type == SourceType.HTML_SEARCH and source.parser == "olx_real_estate_search":
            items, rejected, http_status, bytes_downloaded = fetch_olx_real_estate_search(source)
        elif source.source_type == SourceType.API and source.parser == "cdep_final_votes":
            items, rejected, http_status, bytes_downloaded = fetch_cdep_final_votes(source)
        elif source.source_type == SourceType.HTML_SEARCH and source.parser == "senat_final_votes":
            items, rejected, http_status, bytes_downloaded = fetch_senat_final_votes(source)
        else:
            raise NotImplementedError(f"collector not implemented yet: {source.source_type.value}")

        for candidate in rejected:
            db.quarantine(source.id, run_id, candidate.reason, candidate.payload)

        for item in items:
            parliament_positions = item.metadata.pop("positions", [])
            state, item_id = db.upsert_item_with_id(item)
            _record_listing_observations(item_id, item)
            _record_parliament_vote(item_id, item, parliament_positions)
            if state == "new":
                items_new += 1
            elif state == "changed":
                items_changed += 1

        db.finish_fetch_run(
            run_id,
            status="success",
            http_status=http_status,
            items_found=len(items),
            items_new=items_new,
            items_changed=items_changed,
            bytes_downloaded=bytes_downloaded,
        )
        return FetchResult(
            source_id=source.id,
            status="success",
            http_status=http_status,
            items_found=len(items),
            items_new=items_new,
            items_changed=items_changed,
            bytes_downloaded=bytes_downloaded,
        )
    except HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        db.finish_fetch_run(run_id, status="error", http_status=status_code, error=str(exc))
        return FetchResult(source_id=source.id, status="error", http_status=status_code, error=str(exc))
    except (RequestException, Exception) as exc:
        db.finish_fetch_run(run_id, status="error", error=str(exc))
        return FetchResult(source_id=source.id, status="error", error=str(exc))
