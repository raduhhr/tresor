from __future__ import annotations

import hashlib
import json
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from .config import database_url
from .models import NormalizedItem, SourceConfig


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        yield conn


def content_hash(item: NormalizedItem) -> str:
    payload = {
        "title": item.title,
        "description": item.description,
        "content_text": item.content_text,
        "canonical_url": str(item.canonical_url),
        "metadata": item.metadata,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def migrate() -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def sync_sources(sources: list[SourceConfig]) -> int:
    source_ids = [source.id for source in sources]
    with connect() as conn:
        with conn.cursor() as cur:
            for source in sources:
                cur.execute(
                    """
                    INSERT INTO sources (
                        id, name, source_type, category, url, enabled,
                        interval_minutes, parser, config, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        source_type = EXCLUDED.source_type,
                        category = EXCLUDED.category,
                        url = EXCLUDED.url,
                        enabled = EXCLUDED.enabled,
                        interval_minutes = EXCLUDED.interval_minutes,
                        parser = EXCLUDED.parser,
                        config = EXCLUDED.config,
                        updated_at = now()
                    """,
                    (
                        source.id,
                        source.name,
                        source.source_type.value,
                        source.category,
                        str(source.url),
                        source.enabled,
                        source.interval_minutes,
                        source.parser,
                        json.dumps(source.config),
                    ),
                )
            if source_ids:
                cur.execute(
                    """
                    UPDATE sources
                    SET enabled = false,
                        updated_at = now()
                    WHERE id <> ALL(%s)
                    """,
                    (source_ids,),
                )
            else:
                cur.execute("UPDATE sources SET enabled = false, updated_at = now()")
        conn.commit()
    return len(sources)


def begin_fetch_run(source_id: str) -> int:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO fetch_runs (source_id) VALUES (%s) RETURNING id",
                (source_id,),
            )
            run_id = cur.fetchone()["id"]
        conn.commit()
    return int(run_id)


def finish_fetch_run(
    run_id: int,
    *,
    status: str,
    http_status: int | None = None,
    items_found: int = 0,
    items_new: int = 0,
    items_changed: int = 0,
    bytes_downloaded: int = 0,
    error: str | None = None,
) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE fetch_runs
                SET finished_at = now(),
                    status = %s,
                    http_status = %s,
                    items_found = %s,
                    items_new = %s,
                    items_changed = %s,
                    bytes_downloaded = %s,
                    error = %s
                WHERE id = %s
                """,
                (status, http_status, items_found, items_new, items_changed, bytes_downloaded, error, run_id),
            )
        conn.commit()


def quarantine(source_id: str, run_id: int, reason: str, payload: dict) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO quarantine_items (source_id, fetch_run_id, reason, payload)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                (source_id, run_id, reason, json.dumps(payload, default=str)),
            )
        conn.commit()


def set_api_cache(
    key: str,
    payload: dict,
    *,
    ttl_seconds: int | None = None,
    metadata: dict | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds) if ttl_seconds is not None else None
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO api_cache (key, payload, refreshed_at, expires_at, metadata)
                VALUES (%s, %s::jsonb, %s, %s, %s::jsonb)
                ON CONFLICT (key) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    refreshed_at = EXCLUDED.refreshed_at,
                    expires_at = EXCLUDED.expires_at,
                    metadata = EXCLUDED.metadata
                """,
                (
                    key,
                    json.dumps(payload, default=str, ensure_ascii=False),
                    now,
                    expires_at,
                    json.dumps(metadata or {}, default=str, ensure_ascii=False),
                ),
            )
        conn.commit()


def api_cache_status() -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT key, refreshed_at, expires_at, metadata,
                       expires_at IS NOT NULL AND expires_at <= now() AS expired
                FROM api_cache
                ORDER BY key
                """
            )
            return [dict(row) for row in cur.fetchall()]


def refresh_parliament_politician_summaries() -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO parliament_politician_summaries (
                    politician_key, latest_party, latest_party_key, chambers,
                    votes_recorded, present_votes, attendance_rate,
                    yes, no, abstain, not_voted,
                    first_vote_time, latest_vote_time, refreshed_at
                )
                SELECT
                    p.politician_key,
                    (array_agg(p.party ORDER BY v.vote_time DESC, p.vote_id DESC))[1] AS latest_party,
                    (array_agg(p.party_normalized ORDER BY v.vote_time DESC, p.vote_id DESC))[1] AS latest_party_key,
                    array_agg(DISTINCT p.chamber ORDER BY p.chamber) AS chambers,
                    count(*)::integer AS votes_recorded,
                    count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain'))::integer AS present_votes,
                    round(
                        count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain'))::numeric
                        / NULLIF(count(*), 0),
                        4
                    ) AS attendance_rate,
                    count(*) FILTER (WHERE p.vote_choice = 'yes')::integer AS yes,
                    count(*) FILTER (WHERE p.vote_choice = 'no')::integer AS no,
                    count(*) FILTER (WHERE p.vote_choice = 'abstain')::integer AS abstain,
                    count(*) FILTER (WHERE p.vote_choice = 'not_voted')::integer AS not_voted,
                    min(v.vote_time) AS first_vote_time,
                    max(v.vote_time) AS latest_vote_time,
                    now() AS refreshed_at
                FROM parliament_vote_positions p
                JOIN parliament_votes v ON v.vote_id = p.vote_id
                GROUP BY p.politician_key
                ON CONFLICT (politician_key) DO UPDATE SET
                    latest_party = EXCLUDED.latest_party,
                    latest_party_key = EXCLUDED.latest_party_key,
                    chambers = EXCLUDED.chambers,
                    votes_recorded = EXCLUDED.votes_recorded,
                    present_votes = EXCLUDED.present_votes,
                    attendance_rate = EXCLUDED.attendance_rate,
                    yes = EXCLUDED.yes,
                    no = EXCLUDED.no,
                    abstain = EXCLUDED.abstain,
                    not_voted = EXCLUDED.not_voted,
                    first_vote_time = EXCLUDED.first_vote_time,
                    latest_vote_time = EXCLUDED.latest_vote_time,
                    refreshed_at = EXCLUDED.refreshed_at
                """
            )
            cur.execute("SELECT count(*) AS summaries FROM parliament_politician_summaries")
            row = cur.fetchone()
        conn.commit()
    return {"status": "refreshed", "summaries": row["summaries"] if row else 0}


def upsert_item_with_id(item: NormalizedItem) -> tuple[str, int]:
    digest = content_hash(item)
    now = datetime.now(timezone.utc)
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO items (
                    source_id, item_type, canonical_url, external_id, title, description,
                    first_seen_at, last_seen_at, published_at, latest_hash, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (source_id, canonical_url) DO UPDATE SET
                    last_seen_at = EXCLUDED.last_seen_at,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    published_at = COALESCE(EXCLUDED.published_at, items.published_at),
                    metadata = EXCLUDED.metadata,
                    latest_hash = EXCLUDED.latest_hash
                RETURNING id, (xmax = 0) AS inserted, latest_hash
                """,
                (
                    item.source_id,
                    item.item_type.value,
                    str(item.canonical_url),
                    item.external_id,
                    item.title,
                    item.description,
                    now,
                    now,
                    item.published_at,
                    digest,
                    json.dumps(item.metadata, default=str),
                ),
            )
            row = cur.fetchone()
            cur.execute(
                """
                INSERT INTO item_versions (
                    item_id, title, description, content_text, content_hash, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (item_id, content_hash) DO NOTHING
                """,
                (
                    row["id"],
                    item.title,
                    item.description,
                    item.content_text,
                    digest,
                    json.dumps(item.metadata, default=str),
                ),
            )
            version_inserted = cur.rowcount == 1
        conn.commit()
    if row["inserted"]:
        return "new", int(row["id"])
    if version_inserted:
        return "changed", int(row["id"])
    return "unchanged", int(row["id"])


def upsert_item(item: NormalizedItem) -> str:
    state, _ = upsert_item_with_id(item)
    return state


def record_observation_if_changed(
    item_id: int,
    observation_type: str,
    *,
    value_num: int | float | None = None,
    value_text: str | None = None,
    metadata: dict | None = None,
) -> bool:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT value_num, value_text
                FROM observations
                WHERE item_id = %s
                  AND observation_type = %s
                ORDER BY observed_at DESC, id DESC
                LIMIT 1
                """,
                (item_id, observation_type),
            )
            previous = cur.fetchone()
            if previous is not None:
                previous_num = previous["value_num"]
                previous_text = previous["value_text"]
                same_num = previous_num == value_num or (previous_num is not None and value_num is not None and float(previous_num) == float(value_num))
                same_text = previous_text == value_text
                if same_num and same_text:
                    return False

            cur.execute(
                """
                INSERT INTO observations (item_id, observation_type, value_num, value_text, metadata)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                (item_id, observation_type, value_num, value_text, json.dumps(metadata or {}, default=str)),
            )
        conn.commit()
    return True


def _bill_key(bill: dict) -> str | None:
    code = bill.get("code")
    number = bill.get("number")
    year = bill.get("year")
    if code is None or number is None or year is None:
        return None
    return f"{str(code).lower().replace(' ', '-')}-{year}-{number}"


def _truthy_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"yes", "true", "1", "da"}:
        return True
    if normalized in {"no", "false", "0", "nu"}:
        return False
    return None


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    return text or None


def _same_text(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return left.casefold() == right.casefold()


def _upsert_parliament_bill(
    cur: psycopg.Cursor,
    *,
    source_id: str,
    bill: dict,
    fallback_title: str,
) -> str | None:
    bill_key = _bill_key(bill)
    if bill_key is None:
        return None

    context = bill.get("context") or {}
    title = _clean_text(context.get("title") or bill.get("title"))
    fallback = _clean_text(fallback_title)
    if _same_text(title, fallback):
        title = None
    source_url = context.get("source_url") or bill.get("url")
    initiators = context.get("initiators") or []
    if isinstance(initiators, str):
        initiators = [initiators]

    cur.execute(
        """
        INSERT INTO parliament_bills (
            bill_key, source_id, source_site, bill_code, bill_number, bill_year,
            label, title, short_title, description, procedure,
            decisional_chamber, initiative_type, urgency, urgency_text, stage,
            initiators, registration_numbers, documents, source_url,
            last_seen_at, metadata, updated_at
        )
        VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s::jsonb, %s::jsonb, %s,
            now(), %s::jsonb, now()
        )
        ON CONFLICT (bill_key) DO UPDATE SET
            source_id = COALESCE(EXCLUDED.source_id, parliament_bills.source_id),
            source_site = COALESCE(EXCLUDED.source_site, parliament_bills.source_site),
            label = COALESCE(EXCLUDED.label, parliament_bills.label),
            title = COALESCE(EXCLUDED.title, parliament_bills.title),
            short_title = COALESCE(EXCLUDED.short_title, parliament_bills.short_title),
            description = COALESCE(EXCLUDED.description, parliament_bills.description),
            procedure = COALESCE(EXCLUDED.procedure, parliament_bills.procedure),
            decisional_chamber = COALESCE(EXCLUDED.decisional_chamber, parliament_bills.decisional_chamber),
            initiative_type = COALESCE(EXCLUDED.initiative_type, parliament_bills.initiative_type),
            urgency = COALESCE(EXCLUDED.urgency, parliament_bills.urgency),
            urgency_text = COALESCE(EXCLUDED.urgency_text, parliament_bills.urgency_text),
            stage = COALESCE(EXCLUDED.stage, parliament_bills.stage),
            initiators = CASE
                WHEN cardinality(EXCLUDED.initiators) > 0 THEN EXCLUDED.initiators
                ELSE parliament_bills.initiators
            END,
            registration_numbers = CASE
                WHEN EXCLUDED.registration_numbers <> '{}'::jsonb THEN EXCLUDED.registration_numbers
                ELSE parliament_bills.registration_numbers
            END,
            documents = CASE
                WHEN EXCLUDED.documents <> '[]'::jsonb THEN EXCLUDED.documents
                ELSE parliament_bills.documents
            END,
            source_url = COALESCE(EXCLUDED.source_url, parliament_bills.source_url),
            last_seen_at = now(),
            metadata = parliament_bills.metadata || EXCLUDED.metadata,
            updated_at = now()
        """,
        (
            bill_key,
            source_id,
            context.get("source_site") or bill.get("source_site"),
            bill.get("code"),
            bill.get("number"),
            bill.get("year"),
            bill.get("label"),
            title,
            context.get("short_title"),
            context.get("description"),
            context.get("procedure"),
            context.get("decisional_chamber"),
            context.get("initiative_type"),
            _truthy_bool(context.get("urgency")),
            context.get("urgency_text"),
            context.get("stage"),
            initiators,
            json.dumps(context.get("registration_numbers") or {}, default=str),
            json.dumps(context.get("documents") or [], default=str),
            source_url,
            json.dumps(context.get("metadata") or {}, default=str),
        ),
    )
    _upsert_parliament_bill_events(cur, bill_key=bill_key, source_id=source_id, context=context)
    return bill_key


def _event_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[:10], pattern).date()
        except ValueError:
            continue
    return None


def _event_id(bill_key: str, event_date: date | None, action: str) -> str:
    payload = "|".join([bill_key, event_date.isoformat() if event_date else "", action])
    return f"{bill_key}:event:{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:16]}"


def _upsert_parliament_bill_events(
    cur: psycopg.Cursor,
    *,
    bill_key: str,
    source_id: str,
    context: dict,
) -> None:
    events = context.get("events") or []
    if not isinstance(events, list):
        return
    if events:
        source_sites = sorted(
            {
                str(event.get("source_site") or context.get("source_site"))
                for event in events
                if isinstance(event, dict) and (event.get("source_site") or context.get("source_site"))
            }
        )
        if source_sites:
            cur.execute(
                """
                DELETE FROM parliament_bill_events
                WHERE bill_key = %s
                  AND source_site = ANY(%s)
                """,
                (bill_key, source_sites),
            )
    for event in events:
        if not isinstance(event, dict):
            continue
        action = _clean_text(event.get("action"))
        if not action:
            continue
        event_date = _event_date(event.get("date") or event.get("event_date"))
        documents = event.get("documents") if isinstance(event.get("documents"), list) else []
        metadata = {
            "source": "bill_project_page",
            "source_id": source_id,
            **(event.get("metadata") if isinstance(event.get("metadata"), dict) else {}),
        }
        cur.execute(
            """
            INSERT INTO parliament_bill_events (
                event_id, bill_key, event_date, chamber, action,
                source_site, source_url, documents, metadata, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, now())
            ON CONFLICT (event_id) DO UPDATE SET
                event_date = EXCLUDED.event_date,
                chamber = COALESCE(EXCLUDED.chamber, parliament_bill_events.chamber),
                action = EXCLUDED.action,
                source_site = COALESCE(EXCLUDED.source_site, parliament_bill_events.source_site),
                source_url = COALESCE(EXCLUDED.source_url, parliament_bill_events.source_url),
                documents = CASE
                    WHEN EXCLUDED.documents <> '[]'::jsonb THEN EXCLUDED.documents
                    ELSE parliament_bill_events.documents
                END,
                metadata = parliament_bill_events.metadata || EXCLUDED.metadata,
                updated_at = now()
            """,
            (
                _event_id(bill_key, event_date, action),
                bill_key,
                event_date,
                event.get("chamber"),
                action,
                event.get("source_site") or context.get("source_site"),
                event.get("source_url") or context.get("source_url"),
                json.dumps(documents, default=str),
                json.dumps(metadata, default=str),
            ),
        )


def upsert_parliament_vote(item_id: int, item: NormalizedItem, positions: list[dict]) -> None:
    vote = item.metadata.get("vote") or {}
    bill = item.metadata.get("bill") or {}
    counts = item.metadata.get("counts") or {}
    if positions:
        position_counts = Counter(position.get("vote_choice") for position in positions)
        counts = {
            "present": counts.get("present")
            if counts.get("present") is not None
            else sum(position_counts.get(choice, 0) for choice in ("yes", "no", "abstain", "not_voted")),
            "yes": counts.get("yes") if counts.get("yes") is not None else position_counts.get("yes", 0),
            "no": counts.get("no") if counts.get("no") is not None else position_counts.get("no", 0),
            "abstain": counts.get("abstain") if counts.get("abstain") is not None else position_counts.get("abstain", 0),
            "not_voted": counts.get("not_voted") if counts.get("not_voted") is not None else position_counts.get("not_voted", 0),
        }
    vote_id = str(vote.get("id") or item.external_id or "")
    if not vote_id:
        raise ValueError("parliament vote item is missing vote id")

    with connect() as conn:
        with conn.cursor() as cur:
            bill_key = _upsert_parliament_bill(cur, source_id=item.source_id, bill=bill, fallback_title=item.title)
            cur.execute(
                """
                INSERT INTO parliament_votes (
                    vote_id, item_id, chamber, source_id, vote_time, title,
                    vote_kind, outcome, bill_code, bill_number, bill_year,
                    bill_key, bill_url, nominal_url, present_count, yes_count, no_count,
                    abstain_count, not_voted_count, metadata, updated_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s::jsonb, now()
                )
                ON CONFLICT (vote_id) DO UPDATE SET
                    item_id = EXCLUDED.item_id,
                    chamber = EXCLUDED.chamber,
                    source_id = EXCLUDED.source_id,
                    vote_time = EXCLUDED.vote_time,
                    title = EXCLUDED.title,
                    vote_kind = EXCLUDED.vote_kind,
                    outcome = EXCLUDED.outcome,
                    bill_code = EXCLUDED.bill_code,
                    bill_number = EXCLUDED.bill_number,
                    bill_year = EXCLUDED.bill_year,
                    bill_key = EXCLUDED.bill_key,
                    bill_url = EXCLUDED.bill_url,
                    nominal_url = EXCLUDED.nominal_url,
                    present_count = EXCLUDED.present_count,
                    yes_count = EXCLUDED.yes_count,
                    no_count = EXCLUDED.no_count,
                    abstain_count = EXCLUDED.abstain_count,
                    not_voted_count = EXCLUDED.not_voted_count,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                """,
                (
                    vote_id,
                    item_id,
                    str(vote.get("chamber") or "Camera Deputatilor"),
                    item.source_id,
                    item.published_at,
                    item.title,
                    vote.get("kind"),
                    vote.get("outcome"),
                    bill.get("code"),
                    bill.get("number"),
                    bill.get("year"),
                    bill_key,
                    bill.get("url"),
                    str(item.canonical_url),
                    counts.get("present"),
                    counts.get("yes"),
                    counts.get("no"),
                    counts.get("abstain"),
                    counts.get("not_voted"),
                    json.dumps({k: v for k, v in item.metadata.items() if k != "positions"}, default=str),
                ),
            )

            if positions:
                cur.execute("DELETE FROM parliament_vote_positions WHERE vote_id = %s", (vote_id,))

            for position in positions:
                politician_key = position.get("politician_key")
                politician_name = position.get("politician_name")
                vote_choice = position.get("vote_choice")
                if not politician_key or not politician_name or not vote_choice:
                    continue
                cur.execute(
                    """
                    INSERT INTO parliament_politicians (
                        politician_key, display_name, normalized_name,
                        family_name, given_name, first_chamber, latest_chamber,
                        first_seen_at, last_seen_at, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, now(), now(), %s::jsonb)
                    ON CONFLICT (politician_key) DO UPDATE SET
                        display_name = EXCLUDED.display_name,
                        normalized_name = EXCLUDED.normalized_name,
                        family_name = EXCLUDED.family_name,
                        given_name = EXCLUDED.given_name,
                        latest_chamber = EXCLUDED.latest_chamber,
                        last_seen_at = now(),
                        metadata = parliament_politicians.metadata || EXCLUDED.metadata
                    """,
                    (
                        politician_key,
                        politician_name,
                        position.get("normalized_name") or politician_key,
                        position.get("family_name"),
                        position.get("given_name"),
                        position.get("chamber") or vote.get("chamber") or "Camera Deputatilor",
                        position.get("chamber") or vote.get("chamber") or "Camera Deputatilor",
                        json.dumps(position.get("politician_metadata") or {}, default=str),
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO parliament_vote_positions (
                        vote_id, politician_key, politician_name, family_name,
                        given_name, party, party_normalized, vote_choice, chamber, metadata, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
                    ON CONFLICT (vote_id, politician_key) DO UPDATE SET
                        politician_name = EXCLUDED.politician_name,
                        family_name = EXCLUDED.family_name,
                        given_name = EXCLUDED.given_name,
                        party = EXCLUDED.party,
                        party_normalized = EXCLUDED.party_normalized,
                        vote_choice = EXCLUDED.vote_choice,
                        chamber = EXCLUDED.chamber,
                        metadata = EXCLUDED.metadata,
                        updated_at = now()
                    """,
                    (
                        vote_id,
                        politician_key,
                        politician_name,
                        position.get("family_name"),
                        position.get("given_name"),
                        position.get("party"),
                        position.get("party_normalized"),
                        vote_choice,
                        position.get("chamber") or vote.get("chamber") or "Camera Deputatilor",
                        json.dumps(position.get("metadata") or {}, default=str),
                    ),
                )
        conn.commit()


def observation_counts() -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT observation_type, count(*)::int AS observations
                FROM observations
                GROUP BY observation_type
                ORDER BY observation_type
                """
            )
            return [dict(row) for row in cur.fetchall()]


def listing_price_changes(*, source_id: str | None = None, limit: int = 25, drops_only: bool = False) -> list[dict]:
    clauses = ["i.item_type = 'listing'"]
    params: list[object] = []
    if source_id:
        clauses.append("i.source_id = %s")
        params.append(source_id)
    if drops_only:
        clauses.append("latest.value_num < previous.value_num")

    sql = f"""
        SELECT
            i.external_id,
            i.title,
            i.canonical_url,
            latest.observed_at,
            previous.value_num AS previous_price,
            latest.value_num AS latest_price,
            latest.value_num - previous.value_num AS delta,
            i.metadata->'location'->>'district' AS district,
            i.metadata->>'area_sqm' AS area_sqm
        FROM items i
        JOIN LATERAL (
            SELECT observed_at, value_num
            FROM observations
            WHERE item_id = i.id
              AND observation_type = 'price_eur'
            ORDER BY observed_at DESC, id DESC
            LIMIT 1
        ) latest ON true
        JOIN LATERAL (
            SELECT observed_at, value_num
            FROM observations
            WHERE item_id = i.id
              AND observation_type = 'price_eur'
              AND observed_at < latest.observed_at
            ORDER BY observed_at DESC, id DESC
            LIMIT 1
        ) previous ON true
        WHERE {' AND '.join(clauses)}
        ORDER BY latest.observed_at DESC, abs(latest.value_num - previous.value_num) DESC
        LIMIT %s
    """
    params.append(max(1, min(limit, 500)))

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def status_counts() -> dict:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (SELECT count(*) FROM sources) AS sources,
                    (SELECT count(*) FROM sources WHERE enabled) AS enabled_sources,
                    (SELECT count(*) FROM items) AS items,
                    (SELECT count(*) FROM item_versions) AS item_versions,
                    (SELECT count(*) FROM observations) AS observations,
                    (SELECT count(*) FROM fetch_runs) AS fetch_runs,
                    (SELECT count(*) FROM quarantine_items) AS quarantine_items
                """
            )
            counts = dict(cur.fetchone())
            cur.execute(
                """
                SELECT source_id, status, started_at, finished_at, items_found, items_new, items_changed, error
                FROM fetch_runs
                ORDER BY started_at DESC
                LIMIT 5
                """
            )
            counts["recent_fetch_runs"] = [dict(row) for row in cur.fetchall()]
    return counts


def due_sources() -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT s.*
                FROM sources s
                LEFT JOIN LATERAL (
                    SELECT finished_at
                    FROM fetch_runs fr
                    WHERE fr.source_id = s.id
                      AND fr.finished_at IS NOT NULL
                    ORDER BY fr.finished_at DESC
                    LIMIT 1
                ) last_run ON true
                WHERE s.enabled
                  AND (
                    last_run.finished_at IS NULL
                    OR last_run.finished_at <= now() - (s.interval_minutes || ' minutes')::interval
                  )
                ORDER BY COALESCE(last_run.finished_at, '1970-01-01'::timestamptz), s.id
                """
            )
            return [dict(row) for row in cur.fetchall()]


def query_listings(
    *,
    source_id: str | None = None,
    category: str | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    district: str | None = None,
    text: str | None = None,
    changed_only: bool = False,
    sort: str = "newest",
    limit: int = 25,
) -> list[dict]:
    clauses = ["i.item_type = 'listing'"]
    params: list[object] = []

    if source_id:
        clauses.append("i.source_id = %s")
        params.append(source_id)
    if category:
        clauses.append("s.category = %s")
        params.append(category)
    if min_price is not None:
        clauses.append("(i.metadata->'price'->>'value')::numeric >= %s")
        params.append(min_price)
    if max_price is not None:
        clauses.append("(i.metadata->'price'->>'value')::numeric <= %s")
        params.append(max_price)
    if district:
        clauses.append("COALESCE(i.metadata->'location'->>'district', '') ILIKE %s")
        params.append(f"%{district}%")
    if text:
        clauses.append("(i.title ILIKE %s OR COALESCE(i.description, '') ILIKE %s)")
        params.extend([f"%{text}%", f"%{text}%"])
    if changed_only:
        clauses.append("versions.version_count > 1")

    order_by = {
        "newest": "i.first_seen_at DESC, i.id DESC",
        "seen": "i.last_seen_at DESC, i.id DESC",
        "price_asc": "price_value ASC NULLS LAST, i.first_seen_at DESC",
        "price_desc": "price_value DESC NULLS LAST, i.first_seen_at DESC",
        "changed": "versions.version_count DESC, i.last_seen_at DESC",
    }.get(sort, "i.first_seen_at DESC, i.id DESC")

    sql = f"""
        SELECT
            i.id,
            i.source_id,
            s.name AS source_name,
            s.category,
            i.external_id,
            i.title,
            i.canonical_url,
            i.first_seen_at,
            i.last_seen_at,
            i.published_at,
            i.current_status,
            i.metadata->'price'->>'display' AS price_display,
            (i.metadata->'price'->>'value')::numeric AS price_value,
            i.metadata->'price'->>'currency' AS price_currency,
            i.metadata->'location'->>'city' AS city,
            i.metadata->'location'->>'district' AS district,
            i.metadata->>'area_sqm' AS area_sqm,
            i.metadata->>'rooms' AS rooms,
            i.metadata->'seller'->>'name' AS seller_name,
            i.metadata->'seller'->>'business' AS seller_business,
            versions.version_count
        FROM items i
        JOIN sources s ON s.id = i.source_id
        JOIN LATERAL (
            SELECT count(*)::int AS version_count
            FROM item_versions iv
            WHERE iv.item_id = i.id
        ) versions ON true
        WHERE {' AND '.join(clauses)}
        ORDER BY {order_by}
        LIMIT %s
    """
    params.append(max(1, min(limit, 500)))

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def listing_summary(*, source_id: str | None = None, category: str | None = None) -> list[dict]:
    clauses = ["i.item_type = 'listing'"]
    params: list[object] = []
    if source_id:
        clauses.append("i.source_id = %s")
        params.append(source_id)
    if category:
        clauses.append("s.category = %s")
        params.append(category)

    sql = f"""
        SELECT
            COALESCE(i.metadata->'location'->>'district', 'unknown') AS district,
            count(*)::int AS listings,
            min((i.metadata->'price'->>'value')::numeric) AS min_price,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY (i.metadata->'price'->>'value')::numeric) AS median_price,
            avg((i.metadata->'price'->>'value')::numeric) AS avg_price,
            max((i.metadata->'price'->>'value')::numeric) AS max_price,
            max(i.first_seen_at) AS newest_seen_at
        FROM items i
        JOIN sources s ON s.id = i.source_id
        WHERE {' AND '.join(clauses)}
        GROUP BY COALESCE(i.metadata->'location'->>'district', 'unknown')
        ORDER BY listings DESC, district ASC
    """

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
