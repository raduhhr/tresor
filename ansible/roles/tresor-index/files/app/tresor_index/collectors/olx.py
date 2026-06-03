from __future__ import annotations

import json
import re
import time
import unicodedata
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import ValidationError
import requests

from ..models import ItemType, NormalizedItem, QuarantineCandidate, SourceConfig


_STATE_MARKER = "window.__PRERENDERED_STATE__="


_AREA_KEYWORDS = {
    "cluj": [
        ("Manastur", ["manastur"]),
        ("Marasti", ["marasti"]),
        ("Gheorgheni", ["gheorgheni", "iulius mall"]),
        ("Zorilor", ["zorilor"]),
        ("Grigorescu", ["grigorescu"]),
        ("Buna Ziua", ["buna ziua"]),
        ("Iris", ["iris"]),
        ("Dambul Rotund", ["dambul rotund"]),
        ("Centru", ["central", "centru", "ultracentral"]),
        ("Andrei Muresanu", ["andrei muresanu"]),
        ("Borhanci", ["borhanci"]),
        ("Europa", ["europa"]),
        ("Plopilor", ["plopilor"]),
        ("Intre Lacuri", ["intre lacuri"]),
        ("Sopor", ["sopor", "soporului"]),
        ("Platinia", ["platinia"]),
        ("Piata Flora", ["piata flora"]),
    ],
    "brasov": [
        ("Astra", ["astra"]),
        ("Bartolomeu", ["bartolomeu", "avantgarden"]),
        ("Centrul Civic", ["centrul civic"]),
        ("Tractorul", ["tractorul", "coresi", "qualis"]),
        ("Racadau", ["racadau"]),
        ("Schei", ["schei"]),
        ("Grivitei", ["grivitei"]),
        ("Noua", ["noua"]),
        ("Stupini", ["stupini"]),
        ("Calea Bucuresti", ["calea bucuresti"]),
        ("Mihai Viteazul", ["mihai viteazul", "mihai vitezul"]),
        ("Ultracentral", ["ultracentral", "nicolae iorga"]),
    ],
    "timisoara": [
        ("Braytim", ["braytim"]),
        ("Lipovei", ["lipovei"]),
        ("Blascovici", ["blascovici"]),
        ("Circumvalatiunii", ["circumvalatiunii"]),
        ("Dacia", ["dacia"]),
        ("Girocului", ["girocului"]),
        ("Sagului", ["sagului", "calea sagului"]),
        ("Neptun", ["neptun"]),
        ("Spitalul Judetean", ["spitalul judetean"]),
        ("Cetatii", ["cetatii"]),
        ("Complex Studentesc", ["complex studentesc"]),
        ("Buziasului", ["buziasului"]),
        ("Aradului", ["aradului"]),
        ("Mehala", ["mehala"]),
        ("Fabric", ["fabric"]),
        ("Iosefin", ["iosefin"]),
        ("Freidorf", ["freidorf"]),
        ("Torontalului", ["torontalului"]),
    ],
    "bacau": [
        ("Gheraiesti", ["gheraiesti"]),
        ("CFR", ["cfr"]),
        ("Margineni", ["margineni"]),
        ("Centru", ["centru", "centrala", "ultracentrala"]),
        ("Serbanesti", ["serbanesti"]),
        ("Republicii", ["republicii"]),
        ("Aeroportului", ["aeroportului"]),
        ("Mioritei", ["mioritei"]),
        ("Narcisa", ["narcisa"]),
        ("Milcov", ["milcov"]),
        ("Bucegi", ["bucegi"]),
        ("Soimului", ["soimului"]),
    ],
    "sibiu": [
        ("Trei Stejari", ["trei stejari"]),
        ("Terezian", ["terezian"]),
        ("Piata Cluj", ["piata cluj"]),
        ("Turnisor", ["turnisor"]),
        ("Centru", ["centru", "centrala", "centru istoric"]),
        ("Orasul de Jos", ["orasul de jos"]),
        ("Piata Cibin", ["piata cibin"]),
        ("Calea Poplacii", ["calea poplacii", "poplacii"]),
        ("Hipodrom", ["hipodrom"]),
        ("Bulevardul Victoriei", ["victoriei"]),
        ("Garii", ["garii"]),
        ("Calea Cisnadiei", ["calea cisnadiei", "cisnadiei"]),
        ("Valea Aurie", ["valea aurie"]),
        ("Strand", ["strand"]),
        ("Lazaret", ["lazaret"]),
        ("Gusterita", ["gusterita"]),
        ("Selimbar", ["selimbar"]),
        ("Arhitectilor", ["arhitectilor"]),
    ],
    "iasi": [
        ("Copou", ["copou"]),
        ("Tatarasi", ["tatarasi"]),
        ("Nicolina", ["nicolina"]),
        ("Pacurari", ["pacurari"]),
        ("Podu Ros", ["podu ros"]),
        ("Alexandru", ["alexandru"]),
        ("Dacia", ["dacia"]),
        ("Mircea", ["mircea"]),
        ("Bucium", ["bucium"]),
        ("Galata", ["galata"]),
        ("CUG", ["cug"]),
        ("Centru", ["centru", "ultracentral"]),
        ("Frumoasa", ["frumoasa"]),
        ("Moara de Vant", ["moara de vant"]),
        ("Zimbru", ["zimbru"]),
    ],
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return " ".join(self.parts)


def _strip_html(value: str | None) -> str | None:
    if not value:
        return None
    parser = _TextExtractor()
    parser.feed(value)
    text = parser.text()
    return text or None


def _normalized_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


def _city_key(source_id: str, city: str | None) -> str | None:
    text = _normalized_text(f"{source_id} {city or ''}")
    for key in _AREA_KEYWORDS:
        if key in text:
            return key
    return None


def infer_area_label(
    *,
    source_id: str,
    title: str | None,
    description: str | None,
    city: str | None,
    district: str | None,
) -> tuple[str | None, str | None]:
    if district:
        return district, "olx_district"

    key = _city_key(source_id, city)
    haystack = f" {_normalized_text(title)} {_normalized_text(description)} "
    if key:
        for label, aliases in _AREA_KEYWORDS[key]:
            for alias in aliases:
                needle = f" {_normalized_text(alias)} "
                if needle in haystack:
                    return label, "title_keyword"

    if city:
        return "Unspecified", "fallback"
    return None, None


def _page_url(base_url: str, page: int) -> str:
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if page > 1:
        query["page"] = str(page)
    else:
        query.pop("page", None)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _load_state(body: str) -> dict[str, Any]:
    marker_index = body.find(_STATE_MARKER)
    if marker_index < 0:
        raise ValueError("OLX prerendered state not found")
    payload_text = body[marker_index + len(_STATE_MARKER) :].lstrip()
    payload, _ = json.JSONDecoder().raw_decode(payload_text)
    if isinstance(payload, str):
        return json.loads(payload)
    if isinstance(payload, dict):
        return payload
    raise ValueError("OLX prerendered state has unexpected shape")


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _param_map(ad: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for param in ad.get("params") or []:
        key = param.get("key")
        if not key:
            continue
        params[key] = {
            "name": param.get("name"),
            "value": param.get("value"),
            "normalized_value": param.get("normalizedValue"),
        }
    return params


def _price(ad: dict[str, Any]) -> dict[str, Any]:
    price = ad.get("price") or {}
    regular = price.get("regularPrice") or {}
    return {
        "display": price.get("displayValue"),
        "value": regular.get("value"),
        "currency": regular.get("currencyCode"),
        "negotiable": regular.get("negotiable"),
    }


def _int_config(source: SourceConfig, key: str, default: int) -> int:
    value = source.config.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_config(source: SourceConfig, key: str, default: float) -> float:
    value = source.config.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _within_price_bounds(source: SourceConfig, price_value: Any, currency: str | None) -> bool:
    if price_value is None:
        return True
    if currency and currency != source.config.get("currency", "EUR"):
        return False
    minimum = source.config.get("min_price")
    maximum = source.config.get("max_price")
    if minimum is not None and price_value < int(minimum):
        return False
    if maximum is not None and price_value > int(maximum):
        return False
    return True


def _within_location_bounds(source: SourceConfig, location: dict[str, Any]) -> bool:
    city_ids = source.config.get("city_ids")
    if not city_ids:
        return True
    try:
        allowed_city_ids = {int(city_id) for city_id in city_ids}
        city_id = int(location.get("cityId"))
    except (TypeError, ValueError):
        return False
    return city_id in allowed_city_ids


def _normalize_ad(
    source: SourceConfig,
    ad: dict[str, Any],
    *,
    total_pages: int | None,
) -> NormalizedItem | None:
    listing_id = ad.get("id")
    title = ad.get("title")
    url = ad.get("url")
    price = _price(ad)
    if not _within_price_bounds(source, price.get("value"), price.get("currency")):
        return None

    params = _param_map(ad)
    location = ad.get("location") or {}
    if not _within_location_bounds(source, location):
        return None
    map_data = ad.get("map") or {}
    description = _strip_html(ad.get("description"))
    area_label, area_source = infer_area_label(
        source_id=source.id,
        title=title,
        description=description,
        city=location.get("cityName"),
        district=location.get("districtName"),
    )
    metadata = {
        "site": "olx",
        "listing_id": listing_id,
        "external_url": ad.get("externalUrl"),
        "price": price,
        "location": {
            "city": location.get("cityName"),
            "district": location.get("districtName"),
            "region": location.get("regionName"),
            "path": location.get("pathName"),
        },
        "geo": {
            "lat": map_data.get("lat"),
            "lon": map_data.get("lon"),
            "detailed": map_data.get("show_detailed"),
        },
        "area_label": area_label,
        "area_source": area_source,
        "params": params,
        "area_sqm": (params.get("m") or {}).get("normalized_value"),
        "rooms": (params.get("rooms") or {}).get("normalized_value"),
        "seller": {
            "id": (ad.get("user") or {}).get("id"),
            "name": (ad.get("user") or {}).get("name"),
            "business": ad.get("isBusiness"),
        },
        "contact": {
            "chat": (ad.get("contact") or {}).get("chat"),
            "phone": (ad.get("contact") or {}).get("phone"),
            "name": (ad.get("contact") or {}).get("name"),
        },
        "promotion": {
            "highlighted": ad.get("isHighlighted"),
            "promoted": ad.get("isPromoted"),
            "search_reason": ad.get("searchReason"),
        },
        "photos_count": len(ad.get("photos") or []),
        "first_photo": (ad.get("photos") or [None])[0],
        "status": ad.get("status"),
        "created_time": ad.get("createdTime"),
        "search_total_pages": total_pages,
    }
    metadata = {key: value for key, value in metadata.items() if value not in (None, {}, [])}

    return NormalizedItem(
        source_id=source.id,
        item_type=ItemType.LISTING,
        title=title,
        canonical_url=url,
        external_id=str(listing_id) if listing_id is not None else None,
        description=description[:500] if description else None,
        content_text=description,
        published_at=_parse_datetime(ad.get("createdTime")),
        metadata=metadata,
    )


def fetch_olx_real_estate_search(source: SourceConfig) -> tuple[list[NormalizedItem], list[QuarantineCandidate], int, int]:
    max_pages = max(1, _int_config(source, "max_pages", 1))
    request_delay_seconds = max(0.0, _float_config(source, "request_delay_seconds", 1.0))
    headers = {
        "User-Agent": source.config.get(
            "user_agent",
            "tresor-index/0.1 personal non-commercial monitoring",
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ro,en;q=0.8",
    }

    items: list[NormalizedItem] = []
    rejected: list[QuarantineCandidate] = []
    total_bytes = 0
    last_status = 0
    total_pages: int | None = None
    seen_ids: set[str] = set()

    for page in range(1, max_pages + 1):
        if page > 1 and request_delay_seconds:
            time.sleep(request_delay_seconds)

        response = requests.get(_page_url(str(source.url), page), timeout=25, headers=headers)
        last_status = response.status_code
        total_bytes += len(response.content)
        response.raise_for_status()

        state = _load_state(response.text)
        listing = ((state.get("listing") or {}).get("listing") or {})
        total_pages = listing.get("totalPages") or total_pages
        ads = listing.get("ads") or []
        if not ads:
            break

        for ad in ads:
            listing_id = str(ad.get("id") or "")
            if listing_id and listing_id in seen_ids:
                continue
            if listing_id:
                seen_ids.add(listing_id)
            try:
                item = _normalize_ad(source, ad, total_pages=total_pages)
                if item is not None:
                    items.append(item)
            except ValidationError as exc:
                rejected.append(QuarantineCandidate(reason=str(exc), payload=ad))

        if total_pages is not None and page >= total_pages:
            break

    return items, rejected, last_status, total_bytes
