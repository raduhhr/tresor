from __future__ import annotations

import re
import logging
import time
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from psycopg.rows import dict_row

from .config import public_database_url


app = FastAPI(
    title="Tresor Index Civic API",
    version="0.1.0",
    description="Internal read-only API for Romanian parliament voting data.",
)

logger = logging.getLogger("uvicorn.error")

REQUEST_COUNT = Counter(
    "tresor_index_api_requests_total",
    "Tresor Index API requests by method, route, and status.",
    ["method", "route", "status"],
)
REQUEST_LATENCY = Histogram(
    "tresor_index_api_request_duration_seconds",
    "Tresor Index API request duration by method, route, and status.",
    ["method", "route", "status"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)

UNAFFILIATED_PARTY_KEYS = (
    "neafiliat",
    "neafiliati",
    "independent",
    "independenti",
    "parlamentar_fara_apartenenta_la_grupurile_parlamentare",
)

CURRENT_LEGISLATURE_START = date(2024, 12, 20)

CIVIC_OVERVIEW_CACHE_KEY = "civic_overview"
PARTY_LINE_CACHE_LIMIT = 500
CIVIC_PARTIES_CACHE_PREFIX = "civic_parties"
CIVIC_BILLS_CACHE_PREFIX = "civic_bills"
TOPIC_SEARCH_EXPANSIONS = (
    (("fiscal",), ("fiscal", "cod fiscal", "impozit", "impozite", "taxa", "taxe", "tva")),
    (("penal",), ("penal", "cod penal", "infractiune", "infractiuni", "pedeapsa", "pedepse")),
    (("salari", "salar"), ("salariu", "salarii", "salari", "salarizare", "salarial", "remunerare")),
)


@app.middleware("http")
async def request_metrics_middleware(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)
    started = time.perf_counter()
    status = "500"
    try:
        response = await call_next(request)
        status = str(response.status_code)
        return response
    finally:
        duration = time.perf_counter() - started
        route = getattr(request.scope.get("route"), "path", request.url.path)
        REQUEST_COUNT.labels(request.method, route, status).inc()
        REQUEST_LATENCY.labels(request.method, route, status).observe(duration)
        logger.info(
            "request_timing method=%s route=%s status=%s duration_ms=%.1f",
            request.method,
            route,
            status,
            duration * 1000,
        )


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _connect() -> psycopg.Connection:
    return psycopg.connect(public_database_url(), row_factory=dict_row)


def _json(value: Any) -> Any:
    if isinstance(value, list):
        return [_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _rows(sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [_json(dict(row)) for row in cur.fetchall()]


def _one(sql: str, params: list[Any] | tuple[Any, ...] = ()) -> dict[str, Any] | None:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return _json(dict(row)) if row else None


def _limit(value: int) -> int:
    return max(1, min(value, 500))


def _normalize_search_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


def _compact_search_text(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def _search_sql(expr: str) -> str:
    accents = "ăâîșşțţãĂÂÎȘŞȚŢÃ"
    replacements = "aaissttaaisstta"
    return f"lower(translate(coalesce({expr}, ''), '{accents}', '{replacements}'))"


def _bill_key_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    derived = f"lower({prefix}bill_code) || '-' || {prefix}bill_year::text || '-' || {prefix}bill_number::text"
    return f"COALESCE({prefix}bill_key, {derived})"


def _bill_type_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f"lower(regexp_replace(coalesce({prefix}bill_code, ''), '[^a-zA-Z0-9]+', '', 'g'))"


def _party_line_applicable_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    keys = ", ".join(f"'{key}'" for key in UNAFFILIATED_PARTY_KEYS)
    return f"coalesce({prefix}party_normalized, '') NOT IN ({keys})"


def _has_time_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f"({prefix}chamber <> 'Senat' OR {prefix}vote_time::time <> TIME '00:00:00')"


def _normalize_bill_type(value: str) -> str:
    return "".join(char.lower() for char in value if char.isalnum())


def _expanded_search_terms(value: str | None) -> list[str]:
    normalized = _normalize_search_text(value)
    if not normalized:
        return []

    terms = [normalized]
    tokens = normalized.split()
    if len(tokens) == 1:
        token = tokens[0]
        if len(token) >= 4:
            for triggers, expansions in TOPIC_SEARCH_EXPANSIONS:
                if any(token.startswith(trigger) or trigger.startswith(token) for trigger in triggers):
                    terms.extend(expansions)

    seen: set[str] = set()
    unique_terms: list[str] = []
    for term in terms:
        clean = _normalize_search_text(term)
        if clean and clean not in seen:
            seen.add(clean)
            unique_terms.append(clean)
    return unique_terms


def _search_patterns(value: str | None) -> list[str]:
    return [f"%{term}%" for term in _expanded_search_terms(value)]


def _compact_search_patterns(value: str | None) -> list[str]:
    patterns: list[str] = []
    seen: set[str] = set()
    for term in _expanded_search_terms(value):
        compact = _normalize_bill_type(term)
        if compact and compact not in seen:
            seen.add(compact)
            patterns.append(f"%{compact}%")
    return patterns


def _ilike_any_sql(expr: str, patterns: list[str], params: list[Any]) -> str:
    if not patterns:
        return "FALSE"
    params.extend(patterns)
    return "(" + " OR ".join(f"{expr} ILIKE %s" for _ in patterns) + ")"


def _year_bounds(year: int) -> tuple[datetime, datetime]:
    return datetime(year, 1, 1), datetime(year + 1, 1, 1)


def _adopted_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f"{prefix}outcome IN ('adopted', 'passed')"


def _rejected_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f"{prefix}outcome IN ('rejected', 'failed')"


def _normalized_outcome_sql(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    outcome = f"lower(coalesce({prefix}outcome, ''))"
    return f"""
        CASE
            WHEN {outcome} IN ('adopted', 'passed', 'adoptat', 'adoptată', 'adoptata', 'aprobat', 'aprobată', 'aprobata') THEN 'adopted'
            WHEN {outcome} IN ('rejected', 'failed', 'respins', 'respinsă', 'respinsa', 'respinge') THEN 'rejected'
            ELSE NULLIF({outcome}, '')
        END
    """


def _outcome_filter_sql(alias: str, outcome: str) -> tuple[str, list[Any]]:
    if outcome in ("adopted", "passed"):
        return f"{_normalized_outcome_sql(alias)} = 'adopted'", []
    if outcome in ("rejected", "failed"):
        return f"{_normalized_outcome_sql(alias)} = 'rejected'", []
    return f"{_normalized_outcome_sql(alias)} = %s", [outcome]


def _party_line_cte(extra_where: str = "") -> str:
    scoped_filter = f"\n              AND {extra_where}" if extra_where else ""
    return """
        party_vote_choices AS (
            SELECT vote_id, party_normalized, vote_choice, count(*) AS choice_count
            FROM parliament_vote_positions
            WHERE party_normalized IS NOT NULL
              AND vote_choice IN ('yes', 'no', 'abstain')
              {scoped_filter}
            GROUP BY vote_id, party_normalized, vote_choice
        ),
        party_vote_max AS (
            SELECT vote_id, party_normalized, max(choice_count) AS max_choice_count
            FROM party_vote_choices
            GROUP BY vote_id, party_normalized
        ),
        party_vote_majority AS (
            SELECT c.vote_id, c.party_normalized, max(c.vote_choice) AS majority_choice
            FROM party_vote_choices c
            JOIN party_vote_max m
              ON m.vote_id = c.vote_id
             AND m.party_normalized = c.party_normalized
             AND m.max_choice_count = c.choice_count
            GROUP BY c.vote_id, c.party_normalized
            HAVING count(*) = 1
        ),
        party_line_positions AS (
            SELECT
                p.vote_id,
                p.politician_key,
                p.party_normalized,
                m.majority_choice,
                p.vote_choice = m.majority_choice AS aligned
            FROM parliament_vote_positions p
            JOIN party_vote_majority m
              ON m.vote_id = p.vote_id
             AND m.party_normalized = p.party_normalized
            WHERE p.vote_choice IN ('yes', 'no', 'abstain')
        )
    """.format(scoped_filter=scoped_filter)


def _vote_filters(
    *,
    chamber: str | None,
    outcome: str | None,
    party: str | None,
    politician: str | None,
    bill: str | None,
    year: int | None,
    bill_type: str | None,
    q: str | None,
    since: datetime | None,
    until: datetime | None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[str], list[Any]]:
    clauses = ["1 = 1"]
    params: list[Any] = []
    if chamber:
        clauses.append("v.chamber = %s")
        params.append(chamber)
    if outcome:
        clause, clause_params = _outcome_filter_sql("v", outcome)
        clauses.append(clause)
        params.extend(clause_params)
    if party:
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM parliament_vote_positions p
                WHERE p.vote_id = v.vote_id
                  AND p.party_normalized = %s
            )
            """
        )
        params.append(party)
    if politician:
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM parliament_vote_positions p
                WHERE p.vote_id = v.vote_id
                  AND p.politician_key = %s
            )
            """
        )
        params.append(politician)
    if bill:
        clauses.append(f"{_bill_key_sql('v')} = ANY(%s)")
        params.append(_expanded_bill_keys(bill))
    if year is not None:
        start, end = _year_bounds(year)
        clauses.append("v.vote_time >= %s AND v.vote_time < %s")
        params.extend([start, end])
    if bill_type:
        clauses.append(_bill_type_sql("v") + " = %s")
        params.append(_normalize_bill_type(bill_type))
    if q:
        normalized_patterns = _search_patterns(q)
        compact_q = _compact_search_text(q)
        q_params: list[Any] = []
        v_title_match = _ilike_any_sql(_search_sql('v.title'), normalized_patterns, q_params)
        v_title_raw_match = _ilike_any_sql("v.title", [f"%{q}%"], q_params)
        q_params.extend([f"%{compact_q}%", f"%{q}%"])
        pb_title_match = _ilike_any_sql(_search_sql('pb.title'), normalized_patterns, q_params)
        pb_stage_match = _ilike_any_sql(_search_sql('pb.stage'), normalized_patterns, q_params)
        q_params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
        pbe_action_match = _ilike_any_sql(_search_sql('pbe.action'), normalized_patterns, q_params)
        clauses.append(
            f"""
            (
                {v_title_match}
                OR {v_title_raw_match}
                OR COALESCE(v.bill_code || v.bill_number::text || '/' || v.bill_year::text, '') ILIKE %s
                OR COALESCE(v.bill_code || ' ' || v.bill_number::text || '/' || v.bill_year::text, '') ILIKE %s
                OR EXISTS (
                    SELECT 1 FROM parliament_bills pb
                    WHERE pb.bill_key = {_bill_key_sql('v')}
                      AND (
                        {pb_title_match}
                        OR {pb_stage_match}
                        OR pb.title ILIKE %s
                        OR COALESCE(pb.stage, '') ILIKE %s
                        OR pb.registration_numbers::text ILIKE %s
                      )
                )
                OR EXISTS (
                    SELECT 1 FROM parliament_bill_events pbe
                    WHERE pbe.bill_key = {_bill_key_sql('v')}
                      AND {pbe_action_match}
                )
            )
            """
        )
        params.extend(q_params)
    if date_from:
        clauses.append("v.vote_time >= %s")
        params.append(datetime.combine(date_from, datetime.min.time()))
    if date_to:
        clauses.append("v.vote_time < %s")
        params.append(datetime.combine(date_to, datetime.min.time()) + timedelta(days=1))
    if since:
        clauses.append("v.vote_time >= %s")
        params.append(since)
    if until:
        clauses.append("v.vote_time <= %s")
        params.append(until)
    return clauses, params


def _bill_by_key(bill_key: str) -> dict[str, Any] | None:
    return _one(
        """
        SELECT
            bill_key, source_id, source_site, bill_code, bill_number, bill_year,
            label, title, short_title, description, procedure,
            decisional_chamber, initiative_type, urgency, urgency_text, stage,
            initiators, registration_numbers, documents, source_url,
            first_seen_at, last_seen_at, metadata, updated_at
        FROM parliament_bills
        WHERE bill_key = %s
        """,
        [bill_key],
    )


def _bill_key_from_parts(code: str, number: str, year: str) -> str:
    normalized_code = str(code).strip().lower().replace(" ", "-")
    return f"{normalized_code}-{year}-{number}"


def _bill_key_parts(bill_key: str) -> tuple[str, str, str] | None:
    match = re.match(r"^(.+)-(\d{4})-(\d+)$", bill_key)
    if not match:
        return None
    return match.group(1), match.group(3), match.group(2)


def _related_bill_keys_from_registration_numbers(registration_numbers: Any) -> list[str]:
    values: list[str] = []
    if isinstance(registration_numbers, dict):
        values = [str(value) for value in registration_numbers.values() if value]
    elif isinstance(registration_numbers, list):
        values = [str(value) for value in registration_numbers if value]
    elif registration_numbers:
        values = [str(registration_numbers)]

    keys: set[str] = set()
    pattern = re.compile(r"\b(PL-x|L|PH\s*CD|PH\s*Senat|HCD|HS)\s*-?\s*(\d+)\s*/\s*(\d{4})\b", re.IGNORECASE)
    for value in values:
        for match in pattern.finditer(value):
            keys.add(_bill_key_from_parts(match.group(1), match.group(2), match.group(3)))
    return sorted(keys)


def _related_bill_keys_for_reference(bill_key: str) -> list[str]:
    parts = _bill_key_parts(bill_key)
    if parts is None:
        return []
    code, number, year = parts
    code_space = code.replace("-", " ")
    code_compact = code.replace("-", "")
    rows = _rows(
        """
        SELECT DISTINCT bill_key
        FROM parliament_bills
        WHERE registration_numbers::text ILIKE %s
           OR registration_numbers::text ILIKE %s
           OR registration_numbers::text ILIKE %s
           OR registration_numbers::text ILIKE %s
           OR registration_numbers::text ILIKE %s
           OR registration_numbers::text ILIKE %s
        UNION
        SELECT DISTINCT bill_key
        FROM parliament_bill_events
        WHERE action ILIKE %s
           OR action ILIKE %s
           OR action ILIKE %s
           OR action ILIKE %s
           OR action ILIKE %s
           OR action ILIKE %s
        """,
        [
            f"%{code_space} {number}/{year}%",
            f"%{code_space}-{number}/{year}%",
            f"%{code_space}{number}/{year}%",
            f"%{code} {number}/{year}%",
            f"%{code}-{number}/{year}%",
            f"%{code_compact}{number}/{year}%",
            f"%{code_space} {number}/{year}%",
            f"%{code_space}-{number}/{year}%",
            f"%{code_space}{number}/{year}%",
            f"%{code} {number}/{year}%",
            f"%{code}-{number}/{year}%",
            f"%{code_compact}{number}/{year}%",
        ],
    )
    return [row["bill_key"] for row in rows if row.get("bill_key")]


def _bill_events_for_keys(bill_keys: list[str]) -> list[dict[str, Any]]:
    if not bill_keys:
        return []
    return _rows(
        """
        SELECT
            event_id, bill_key, event_date, chamber, action,
            source_site, source_url, documents, metadata, updated_at
        FROM parliament_bill_events
        WHERE bill_key = ANY(%s)
        ORDER BY event_date NULLS LAST, event_id
        """,
        [bill_keys],
    )


def _expanded_bill_keys(bill_key: str) -> list[str]:
    related_keys = {bill_key}
    bill = _bill_by_key(bill_key)
    related_keys.update(_related_bill_keys_for_reference(bill_key))
    if bill is not None:
        related_keys.update(_related_bill_keys_from_registration_numbers(bill.get("registration_numbers")))
    return sorted(related_keys)


@app.get("/health")
def health() -> dict[str, Any]:
    row = _one(
        """
        SELECT
            (SELECT count(*) FROM parliament_votes) AS votes,
            (SELECT count(*) FROM parliament_vote_positions) AS positions,
            (SELECT count(*) FROM parliament_politicians) AS politicians
        """
    )
    return {"status": "ok", "civic": row}


@app.get("/api/civic/overview")
def civic_overview() -> dict[str, Any]:
    cached = _cached_payload(CIVIC_OVERVIEW_CACHE_KEY)
    if cached is not None:
        return cached
    payload = build_civic_overview_payload()
    payload["cache"] = {"key": CIVIC_OVERVIEW_CACHE_KEY, "status": "miss_live"}
    return payload


def _cached_payload(key: str) -> dict[str, Any] | None:
    row = _one(
        """
        SELECT key, payload, refreshed_at, expires_at,
               expires_at IS NOT NULL AND expires_at <= now() AS expired
        FROM api_cache
        WHERE key = %s
        """,
        [key],
    )
    if row is None:
        return None
    payload = dict(row.get("payload") or {})
    payload["cache"] = {
        "key": row["key"],
        "status": "stale" if row.get("expired") else "hit",
        "refreshed_at": row.get("refreshed_at"),
        "expires_at": row.get("expires_at"),
    }
    return payload


def _cached_party_line_payload(
    *,
    group_by: str,
    order: str,
    limit: int,
    offset: int,
) -> dict[str, Any] | None:
    if offset != 0 or limit > PARTY_LINE_CACHE_LIMIT:
        return None
    cached = _cached_payload(party_line_cache_key(group_by=group_by, order=order))
    if cached is None:
        return None
    payload = dict(cached)
    items = list(payload.get("items") or [])
    payload["items"] = items[:limit]
    payload["limit"] = limit
    payload["offset"] = offset
    return payload


def civic_parties_cache_key(*, chamber: str | None) -> str:
    return f"{CIVIC_PARTIES_CACHE_PREFIX}:{chamber or 'all'}"


def civic_bills_cache_key(*, limit: int) -> str:
    return f"{CIVIC_BILLS_CACHE_PREFIX}:latest:{limit}"


def _cached_civic_parties_payload(
    *,
    chamber: str | None,
    min_votes: int,
) -> dict[str, Any] | None:
    cached = _cached_payload(civic_parties_cache_key(chamber=chamber))
    if cached is None:
        return None
    payload = dict(cached)
    payload["min_votes"] = min_votes
    return payload


def _cached_civic_bills_payload(
    *,
    limit: int,
    offset: int,
) -> dict[str, Any] | None:
    if offset != 0 or limit > 500:
        return None
    cached = _cached_payload(civic_bills_cache_key(limit=limit))
    if cached is None:
        return None
    payload = dict(cached)
    payload["limit"] = limit
    payload["offset"] = offset
    return payload


def build_civic_overview_payload() -> dict[str, Any]:
    totals = _one(
        f"""
        SELECT
            count(*) AS votes,
            count(*) FILTER (WHERE {_normalized_outcome_sql()} = 'adopted') AS adopted,
            count(*) FILTER (WHERE {_normalized_outcome_sql()} = 'rejected') AS rejected,
            (SELECT count(*) FROM parliament_bills) AS bills,
            (SELECT count(*) FROM parliament_politicians) AS politicians,
            (SELECT count(DISTINCT party_normalized) FROM parliament_vote_positions WHERE party_normalized IS NOT NULL) AS parties
        FROM parliament_votes
        """
    )
    by_chamber = _rows(
        f"""
        SELECT chamber, count(*) AS votes,
               count(*) FILTER (WHERE {_normalized_outcome_sql()} = 'adopted') AS adopted,
               count(*) FILTER (WHERE {_normalized_outcome_sql()} = 'rejected') AS rejected,
               max(vote_time) AS latest_vote_time
        FROM parliament_votes
        GROUP BY chamber
        ORDER BY chamber
        """
    )
    metrics = _one(
        """
        SELECT
            count(*) AS positions,
            count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain')) AS present_positions,
            round(
                count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain'))::numeric
                / NULLIF(count(*), 0),
                4
            ) AS attendance_rate,
            0 AS party_line_eligible_positions,
            0 AS party_line_aligned_positions,
            NULL::numeric AS party_line_discipline_rate
        FROM parliament_vote_positions p
        """
    )
    week = _one(
        f"""
        SELECT
            count(*) AS votes,
            count(*) FILTER (WHERE {_normalized_outcome_sql()} = 'adopted') AS adopted,
            count(*) FILTER (WHERE {_normalized_outcome_sql()} = 'rejected') AS rejected,
            count(DISTINCT chamber) AS active_chambers
        FROM parliament_votes
        WHERE vote_time >= now() - interval '7 days'
        """
    )
    latest_session = _one(
        f"""
        WITH latest AS (
            SELECT vote_time::date AS session_date
            FROM parliament_votes
            ORDER BY vote_time DESC
            LIMIT 1
        )
        SELECT
            latest.session_date,
            count(v.*) AS votes,
            count(v.*) FILTER (WHERE {_normalized_outcome_sql('v')} = 'adopted') AS adopted,
            count(v.*) FILTER (WHERE {_normalized_outcome_sql('v')} = 'rejected') AS rejected,
            count(DISTINCT v.chamber) AS active_chambers
        FROM latest
        JOIN parliament_votes v ON v.vote_time::date = latest.session_date
        GROUP BY latest.session_date
        """
    )
    latest = civic_votes(year=None, bill_type=None, limit=10, offset=0)
    coverage = _one(
        f"""
        SELECT
            min(v.vote_time) AS first_vote_time,
            max(v.vote_time) AS latest_vote_time,
            max(GREATEST(v.vote_time, COALESCE(pb.updated_at, v.vote_time))) AS latest_data_time
        FROM parliament_votes v
        LEFT JOIN parliament_bills pb ON pb.bill_key = {_bill_key_sql('v')}
        """
    )
    return {
        "totals": totals,
        "metrics": metrics,
        "week": week,
        "latest_session": latest_session,
        "by_chamber": by_chamber,
        "coverage": coverage,
        "latest_votes": latest["items"],
    }


@app.get("/api/civic/votes")
def civic_votes(
    chamber: str | None = None,
    outcome: str | None = None,
    party: str | None = None,
    politician: str | None = None,
    bill: str | None = None,
    year: int | None = Query(None, ge=1990, le=2100),
    bill_type: str | None = None,
    q: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    clauses, params = _vote_filters(
        chamber=chamber,
        outcome=outcome,
        party=party,
        politician=politician,
        bill=bill,
        year=year,
        bill_type=bill_type,
        q=q,
        since=since,
        until=until,
        date_from=date_from,
        date_to=date_to,
    )
    where = " AND ".join(clauses)
    items = _rows(
        f"""
        SELECT
            v.vote_id, v.chamber, v.vote_time, v.title, v.vote_kind, v.outcome,
            {_has_time_sql('v')} AS has_time,
            v.bill_code, v.bill_number, v.bill_year,
            {_bill_type_sql('v')} AS bill_type,
            CASE WHEN v.bill_code IS NOT NULL THEN {_bill_key_sql('v')} END AS bill_key,
            COALESCE(pb.source_url, v.bill_url) AS bill_url,
            v.nominal_url,
            personal_position.vote_choice AS personal_vote_choice,
            pb.title AS bill_title,
            pb.short_title AS bill_short_title,
            pb.stage AS bill_stage,
            pb.initiators AS bill_initiators,
            v.present_count, v.yes_count, v.no_count, v.abstain_count, v.not_voted_count,
            positions.positions_count
        FROM parliament_votes v
        LEFT JOIN parliament_bills pb ON pb.bill_key = {_bill_key_sql('v')}
        LEFT JOIN LATERAL (
            SELECT count(*) AS positions_count
            FROM parliament_vote_positions p
            WHERE p.vote_id = v.vote_id
        ) positions ON true
        LEFT JOIN LATERAL (
            SELECT p.vote_choice
            FROM parliament_vote_positions p
            WHERE p.vote_id = v.vote_id
              AND p.politician_key = %s
            LIMIT 1
        ) personal_position ON %s::text IS NOT NULL
        WHERE {where}
        ORDER BY v.vote_time DESC, v.vote_id DESC
        LIMIT %s OFFSET %s
        """,
        [politician, politician, *params, _limit(limit), offset],
    )
    total = _one(f"SELECT count(*) AS total FROM parliament_votes v WHERE {where}", params)
    return {
        "items": items,
        "total": total["total"] if total else 0,
        "limit": _limit(limit),
        "offset": offset,
    }


@app.get("/api/civic/votes/summary")
def civic_votes_summary(
    chamber: str | None = None,
    outcome: str | None = None,
    party: str | None = None,
    politician: str | None = None,
    bill: str | None = None,
    year: int | None = Query(None, ge=1990, le=2100),
    bill_type: str | None = None,
    q: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    clauses, params = _vote_filters(
        chamber=chamber,
        outcome=outcome,
        party=party,
        politician=politician,
        bill=bill,
        year=year,
        bill_type=bill_type,
        q=q,
        since=since,
        until=until,
        date_from=date_from,
        date_to=date_to,
    )
    where = " AND ".join(clauses)
    summary = _one(
        f"""
        SELECT
            count(*) AS votes,
            count(*) FILTER (WHERE {_normalized_outcome_sql('v')} = 'adopted') AS adopted,
            count(*) FILTER (WHERE {_normalized_outcome_sql('v')} = 'rejected') AS rejected,
            count(*) FILTER (
                WHERE COALESCE(v.yes_count, 0)::numeric
                    / NULLIF(positions.positions_count, 0) > 0.95
            ) AS unanimous_votes,
            count(*) FILTER (
                WHERE {_normalized_outcome_sql('v')} = 'adopted'
                  AND COALESCE(v.no_count, 0)::numeric
                    / NULLIF(positions.positions_count, 0) > 0.30
            ) AS contested_adopted_votes,
            round(
                count(*) FILTER (WHERE {_normalized_outcome_sql('v')} = 'adopted')::numeric
                / NULLIF(count(*), 0),
                4
            ) AS adoption_rate
        FROM parliament_votes v
        LEFT JOIN LATERAL (
            SELECT count(*) AS positions_count
            FROM parliament_vote_positions p
            WHERE p.vote_id = v.vote_id
        ) positions ON true
        WHERE {where}
        """,
        params,
    )
    return summary or {
        "votes": 0,
        "adopted": 0,
        "rejected": 0,
        "unanimous_votes": 0,
        "contested_adopted_votes": 0,
        "adoption_rate": None,
    }


@app.get("/api/civic/votes/{vote_id}")
def civic_vote_detail(vote_id: str) -> dict[str, Any]:
    vote = _one(
        f"""
        SELECT
            v.vote_id, v.chamber, v.vote_time, v.title, v.vote_kind, v.outcome,
            {_has_time_sql('v')} AS has_time,
            v.bill_code, v.bill_number, v.bill_year,
            {_bill_type_sql('v')} AS bill_type,
            CASE WHEN v.bill_code IS NOT NULL THEN {_bill_key_sql('v')} END AS bill_key,
            COALESCE(pb.source_url, v.bill_url) AS bill_url,
            v.nominal_url,
            v.present_count, v.yes_count, v.no_count, v.abstain_count, v.not_voted_count,
            positions.positions_count,
            v.metadata
        FROM parliament_votes v
        LEFT JOIN parliament_bills pb ON pb.bill_key = {_bill_key_sql('v')}
        LEFT JOIN LATERAL (
            SELECT count(*) AS positions_count
            FROM parliament_vote_positions p
            WHERE p.vote_id = v.vote_id
        ) positions ON true
        WHERE v.vote_id = %s
        """,
        [vote_id],
    )
    if vote is None:
        raise HTTPException(status_code=404, detail="vote not found")
    positions = _rows(
        """
        SELECT politician_key, politician_name, family_name, given_name,
               party, party_normalized, vote_choice, chamber
        FROM parliament_vote_positions
        WHERE vote_id = %s
        ORDER BY party_normalized NULLS LAST, politician_name
        """,
        [vote_id],
    )
    party_breakdown = _rows(
        f"""
        WITH {_party_line_cte()}
        SELECT COALESCE(p.party_normalized, 'unknown') AS party_key,
               max(p.party) AS party,
               count(*) AS total,
               count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain')) AS present,
               count(*) FILTER (WHERE p.vote_choice = 'yes') AS yes,
               count(*) FILTER (WHERE p.vote_choice = 'no') AS no,
               count(*) FILTER (WHERE p.vote_choice = 'abstain') AS abstain,
               count(*) FILTER (WHERE p.vote_choice = 'not_voted') AS not_voted,
               count(*) FILTER (WHERE p.vote_choice = 'unknown') AS unknown,
               round(
                   count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain'))::numeric
                   / NULLIF(count(*), 0),
                   4
               ) AS attendance_rate,
               max(line.majority_choice) AS majority_choice,
               count(line.politician_key) AS party_line_eligible_positions,
               count(line.politician_key) FILTER (WHERE line.aligned) AS party_line_aligned_positions,
               round(
                   count(line.politician_key) FILTER (WHERE line.aligned)::numeric
                   / NULLIF(count(line.politician_key), 0),
                   4
               ) AS party_line_discipline_rate
        FROM parliament_vote_positions p
        LEFT JOIN party_line_positions line
          ON line.vote_id = p.vote_id
         AND line.politician_key = p.politician_key
        WHERE p.vote_id = %s
        GROUP BY COALESCE(p.party_normalized, 'unknown')
        ORDER BY party_key
        """,
        [vote_id],
    )
    bill = None
    if vote.get("bill_key"):
        bill = _bill_by_key(vote["bill_key"])
    return {"vote": vote, "bill": bill, "party_breakdown": party_breakdown, "positions": positions}


@app.get("/api/civic/politicians")
def civic_politicians(
    chamber: str | None = None,
    party: str | None = None,
    q: str | None = None,
    match: str = Query("contains", pattern="^(contains|prefix)$"),
    status: str = Query("all", pattern="^(all|current|past)$"),
    active_since: date = CURRENT_LEGISLATURE_START,
    min_attendance: float | None = Query(None, ge=0, le=1),
    max_attendance: float | None = Query(None, ge=0, le=1),
    sort: str = Query("name", pattern="^(name|attendance|votes|latest)$"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    clauses = ["1 = 1"]
    params: list[Any] = []
    if chamber:
        clauses.append("(pp.first_chamber = %s OR pp.latest_chamber = %s)")
        params.append(chamber)
        params.append(chamber)
    if status == "current":
        clauses.append("COALESCE(ps.latest_vote_time, pp.last_seen_at) >= %s::date")
        params.append(active_since)
    elif status == "past":
        clauses.append("(COALESCE(ps.latest_vote_time, pp.last_seen_at) < %s::date OR ps.latest_vote_time IS NULL)")
        params.append(active_since)
    if party:
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM parliament_vote_positions party_positions
                WHERE party_positions.politician_key = pp.politician_key
                  AND party_positions.party_normalized = %s
            )
            """
        )
        params.append(party)
    if q:
        normalized_q = _normalize_search_text(q)
        normalized_key_q = normalized_q.replace(" ", "_")
        search_pattern = f"{normalized_q}%" if match == "prefix" else f"%{normalized_q}%"
        raw_pattern = f"{q}%" if match == "prefix" else f"%{q}%"
        key_pattern = f"{normalized_key_q}%" if match == "prefix" else f"%{normalized_key_q}%"
        clauses.append(
            f"({_search_sql('pp.display_name')} ILIKE %s OR pp.display_name ILIKE %s OR pp.normalized_name ILIKE %s OR pp.normalized_name ILIKE %s)"
        )
        params.append(search_pattern)
        params.append(raw_pattern)
        params.append(search_pattern)
        params.append(key_pattern)
    if min_attendance is not None:
        clauses.append("ps.attendance_rate >= %s")
        params.append(min_attendance)
    if max_attendance is not None:
        clauses.append("ps.attendance_rate <= %s")
        params.append(max_attendance)
    where = " AND ".join(clauses)
    direction = "ASC" if order == "asc" else "DESC"
    attendance_sort = (
        "CASE WHEN COALESCE(ps.votes_recorded, 0) >= 50 THEN 0 ELSE 1 END ASC, "
        f"ps.attendance_rate {direction} NULLS LAST, COALESCE(ps.votes_recorded, 0) DESC, pp.display_name ASC"
    )
    sort_sql = {
        "name": f"pp.display_name {direction}",
        "attendance": attendance_sort,
        "votes": f"COALESCE(ps.votes_recorded, 0) {direction}, pp.display_name ASC",
        "latest": f"COALESCE(ps.latest_vote_time, pp.last_seen_at) {direction} NULLS LAST, pp.display_name ASC",
    }[sort]
    items = _rows(
        f"""
        WITH selected_politicians AS (
            SELECT
                pp.politician_key,
                pp.display_name,
                ps.latest_party,
                ps.latest_party_key,
                COALESCE(ps.chambers, ARRAY(
                    SELECT DISTINCT chamber
                    FROM unnest(ARRAY[pp.first_chamber, pp.latest_chamber]) AS chamber
                    WHERE chamber IS NOT NULL
                )) AS chambers,
                COALESCE(ps.votes_recorded, 0) AS votes_recorded,
                COALESCE(ps.present_votes, 0) AS present_votes,
                ps.attendance_rate,
                COALESCE(ps.yes, 0) AS yes,
                COALESCE(ps.no, 0) AS no,
                COALESCE(ps.abstain, 0) AS abstain,
                COALESCE(ps.not_voted, 0) AS not_voted,
                COALESCE(ps.first_vote_time, pp.first_seen_at) AS first_vote_time,
                COALESCE(ps.latest_vote_time, pp.last_seen_at) AS latest_vote_time,
                COALESCE(ps.latest_vote_time, pp.last_seen_at) >= %s::date AS is_current,
                CASE
                    WHEN COALESCE(ps.latest_vote_time, pp.last_seen_at) >= %s::date THEN 'current'
                    ELSE 'past'
                END AS tenure_status
            FROM parliament_politicians pp
            LEFT JOIN parliament_politician_summaries ps ON ps.politician_key = pp.politician_key
            WHERE {where}
            ORDER BY {sort_sql}
            LIMIT %s OFFSET %s
        ),
        {_party_line_cte("""
            EXISTS (
                SELECT 1
                FROM parliament_vote_positions selected_positions
                JOIN selected_politicians selected
                  ON selected.politician_key = selected_positions.politician_key
                WHERE selected_positions.vote_id = parliament_vote_positions.vote_id
            )
        """)}
        ,
        party_line_summary AS (
            SELECT
                politician_key,
                count(*) AS party_line_eligible_votes,
                count(*) FILTER (WHERE aligned) AS party_line_votes,
                round(
                    count(*) FILTER (WHERE aligned)::numeric / NULLIF(count(*), 0),
                    4
                ) AS party_line_discipline_rate
            FROM party_line_positions
            GROUP BY politician_key
        )
        SELECT
            selected.*,
            COALESCE(line.party_line_eligible_votes, 0) AS party_line_eligible_votes,
            COALESCE(line.party_line_votes, 0) AS party_line_votes,
            line.party_line_discipline_rate
        FROM selected_politicians selected
        LEFT JOIN party_line_summary line ON line.politician_key = selected.politician_key
        """,
        [active_since, active_since, *params, _limit(limit), offset],
    )
    total = _one(
        f"""
        SELECT count(*) AS total
        FROM parliament_politicians pp
        LEFT JOIN parliament_politician_summaries ps ON ps.politician_key = pp.politician_key
        WHERE {where}
        """,
        params,
    )
    return {
        "items": items,
        "total": total["total"] if total else 0,
        "limit": _limit(limit),
        "offset": offset,
        "status": status,
        "active_since": active_since.isoformat(),
    }


@app.get("/api/civic/politicians/summary")
def civic_politicians_summary(
    chamber: str | None = None,
    party: str | None = None,
    status: str = Query("current", pattern="^(all|current|past)$"),
    active_since: date = CURRENT_LEGISLATURE_START,
) -> dict[str, Any]:
    clauses = ["1 = 1"]
    params: list[Any] = []
    chambers_sql = """
        ARRAY(
            SELECT DISTINCT chamber_value
            FROM unnest(COALESCE(ps.chambers, ARRAY[pp.first_chamber, pp.latest_chamber])) AS chamber_values(chamber_value)
            WHERE chamber_value IS NOT NULL
        )
    """
    if chamber:
        clauses.append(f"%s = ANY({chambers_sql})")
        params.append(chamber)
    if status == "current":
        clauses.append("COALESCE(ps.latest_vote_time, pp.last_seen_at) >= %s::date")
        params.append(active_since)
    elif status == "past":
        clauses.append("(COALESCE(ps.latest_vote_time, pp.last_seen_at) < %s::date OR ps.latest_vote_time IS NULL)")
        params.append(active_since)
    if party:
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM parliament_vote_positions party_positions
                WHERE party_positions.politician_key = pp.politician_key
                  AND party_positions.party_normalized = %s
            )
            """
        )
        params.append(party)
    where = " AND ".join(clauses)
    filtered_sql = f"""
        SELECT
            pp.politician_key,
            ps.attendance_rate,
            {chambers_sql} AS chambers
        FROM parliament_politicians pp
        LEFT JOIN parliament_politician_summaries ps ON ps.politician_key = pp.politician_key
        WHERE {where}
    """
    summary = _one(
        f"""
        WITH filtered_politicians AS ({filtered_sql})
        SELECT
            count(*) AS politicians,
            round(avg(attendance_rate), 4) AS attendance_rate
        FROM filtered_politicians
        """,
        params,
    )
    by_chamber = _rows(
        f"""
        WITH filtered_politicians AS ({filtered_sql})
        SELECT
            chamber,
            count(*) AS politicians,
            round(avg(attendance_rate), 4) AS attendance_rate
        FROM filtered_politicians
        CROSS JOIN LATERAL unnest(chambers) AS chamber_values(chamber)
        WHERE chamber IS NOT NULL
        GROUP BY chamber
        ORDER BY chamber
        """,
        params,
    )
    histogram = _rows(
        f"""
        WITH filtered_politicians AS ({filtered_sql}),
        buckets(bucket, label, min_rate, max_rate) AS (
            VALUES
                ('under_50', '0-50%%', 0::numeric, 0.5::numeric),
                ('50_75', '50-75%%', 0.5::numeric, 0.75::numeric),
                ('75_90', '75-90%%', 0.75::numeric, 0.9::numeric),
                ('90_100', '90-100%%', 0.9::numeric, 1.00001::numeric)
        ),
        bucketed AS (
            SELECT b.bucket, count(f.politician_key) AS politicians
            FROM buckets b
            LEFT JOIN filtered_politicians f
              ON f.attendance_rate >= b.min_rate
             AND f.attendance_rate < b.max_rate
            GROUP BY b.bucket
        )
        SELECT b.bucket, b.label, COALESCE(bucketed.politicians, 0) AS politicians
        FROM buckets b
        LEFT JOIN bucketed ON bucketed.bucket = b.bucket
        ORDER BY b.min_rate
        """,
        params,
    )
    return {
        "politicians": summary["politicians"] if summary else 0,
        "attendance_rate": summary["attendance_rate"] if summary else None,
        "by_chamber": by_chamber,
        "histogram": histogram,
        "status": status,
        "active_since": active_since.isoformat(),
    }


@app.get("/api/civic/politicians/{politician_key}")
def civic_politician_detail(
    politician_key: str,
    recent_limit: int = Query(50, ge=1, le=100),
    recent_offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    politician = _one(
        """
        SELECT
            pp.politician_key, pp.display_name, pp.normalized_name,
            pp.family_name, pp.given_name, pp.first_chamber, pp.latest_chamber,
            pp.first_seen_at, pp.last_seen_at, pp.metadata,
            COALESCE(ps.latest_vote_time, pp.last_seen_at) >= %s::date AS is_current,
            CASE
                WHEN COALESCE(ps.latest_vote_time, pp.last_seen_at) >= %s::date THEN 'current'
                ELSE 'past'
            END AS tenure_status,
            %s::date AS active_since
        FROM parliament_politicians pp
        LEFT JOIN parliament_politician_summaries ps ON ps.politician_key = pp.politician_key
        WHERE pp.politician_key = %s
        """,
        [CURRENT_LEGISLATURE_START, CURRENT_LEGISLATURE_START, CURRENT_LEGISLATURE_START, politician_key],
    )
    if politician is None:
        raise HTTPException(status_code=404, detail="politician not found")
    summary = _one(
        f"""
        WITH {_party_line_cte("vote_id IN (SELECT vote_id FROM parliament_vote_positions WHERE politician_key = %s)")}
        SELECT
            count(*) AS votes_recorded,
            count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain')) AS present_votes,
            round(
                count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain'))::numeric
                / NULLIF(count(*), 0),
                4
            ) AS attendance_rate,
            count(*) FILTER (WHERE p.vote_choice = 'yes') AS yes,
            count(*) FILTER (WHERE p.vote_choice = 'no') AS no,
            count(*) FILTER (WHERE p.vote_choice = 'abstain') AS abstain,
            count(*) FILTER (WHERE p.vote_choice = 'not_voted') AS not_voted,
            count(*) FILTER (WHERE p.vote_choice = 'unknown') AS unknown,
            count(line.politician_key) AS party_line_eligible_votes,
            count(line.politician_key) FILTER (WHERE line.aligned) AS party_line_votes,
            round(
                count(line.politician_key) FILTER (WHERE line.aligned)::numeric
                / NULLIF(count(line.politician_key), 0),
                4
            ) AS party_line_discipline_rate,
            array_agg(DISTINCT p.chamber ORDER BY p.chamber) AS chambers,
            array_agg(DISTINCT p.party_normalized ORDER BY p.party_normalized) FILTER (WHERE p.party_normalized IS NOT NULL) AS party_keys
        FROM parliament_vote_positions p
        LEFT JOIN party_line_positions line
          ON line.vote_id = p.vote_id
         AND line.politician_key = p.politician_key
        WHERE p.politician_key = %s
        """,
        [politician_key, politician_key],
    )
    recent_page = civic_votes(
        politician=politician_key,
        year=None,
        bill_type=None,
        limit=recent_limit,
        offset=recent_offset,
    )
    group_deviations = _rows(
        f"""
        WITH {_party_line_cte("vote_id IN (SELECT vote_id FROM parliament_vote_positions WHERE politician_key = %s)")}
        SELECT
            v.vote_id, v.chamber, v.vote_time, v.title, v.vote_kind, v.outcome,
            {_has_time_sql('v')} AS has_time,
            v.bill_code, v.bill_number, v.bill_year,
            {_bill_type_sql('v')} AS bill_type,
            CASE WHEN v.bill_code IS NOT NULL THEN {_bill_key_sql('v')} END AS bill_key,
            COALESCE(pb.source_url, v.bill_url) AS bill_url,
            v.nominal_url,
            p.vote_choice,
            line.majority_choice AS group_majority_choice,
            pb.title AS bill_title,
            pb.short_title AS bill_short_title,
            pb.stage AS bill_stage,
            pb.initiators AS bill_initiators,
            v.present_count, v.yes_count, v.no_count, v.abstain_count, v.not_voted_count,
            positions.positions_count
        FROM parliament_vote_positions p
        JOIN parliament_votes v ON v.vote_id = p.vote_id
        LEFT JOIN parliament_bills pb ON pb.bill_key = {_bill_key_sql('v')}
        JOIN party_line_positions line
          ON line.vote_id = p.vote_id
         AND line.politician_key = p.politician_key
        LEFT JOIN LATERAL (
            SELECT count(*) AS positions_count
            FROM parliament_vote_positions positions_p
            WHERE positions_p.vote_id = v.vote_id
        ) positions ON true
        WHERE p.politician_key = %s
          AND NOT line.aligned
        ORDER BY v.vote_time DESC, v.vote_id DESC
        LIMIT 50
        """,
        [politician_key, politician_key],
    )
    return {
        "politician": politician,
        "summary": summary,
        "recent_votes": recent_page["items"],
        "recent_votes_page": recent_page,
        "group_deviations": group_deviations,
    }


@app.get("/api/civic/parties")
def civic_parties(
    chamber: str | None = None,
    min_votes: int = Query(10, ge=0, le=100000),
) -> dict[str, Any]:
    cached = _cached_civic_parties_payload(chamber=chamber, min_votes=min_votes)
    if cached is not None:
        return cached
    payload = build_civic_parties_payload(chamber=chamber, min_votes=min_votes)
    payload["cache"] = {"key": civic_parties_cache_key(chamber=chamber), "status": "miss_live"}
    return payload


def build_civic_parties_payload(
    *,
    chamber: str | None = None,
    min_votes: int = 10,
) -> dict[str, Any]:
    clauses = ["p.party_normalized IS NOT NULL"]
    params: list[Any] = []
    if chamber:
        clauses.append("p.chamber = %s")
        params.append(chamber)
    cohesion_scope = "AND chamber = %s" if chamber else ""
    cohesion_params = [chamber] if chamber else []
    items = _rows(
        f"""
        WITH {_party_line_cte()},
        party_vote_cohesion AS (
            SELECT
                vote_id,
                party_normalized,
                count(*) AS present_positions,
                count(DISTINCT vote_choice) AS distinct_choices
            FROM parliament_vote_positions
            WHERE party_normalized IS NOT NULL
              AND vote_choice IN ('yes', 'no', 'abstain')
              {cohesion_scope}
            GROUP BY vote_id, party_normalized
        ),
        party_cohesion AS (
            SELECT
                party_normalized,
                count(*) AS cohesion_votes,
                count(*) FILTER (WHERE distinct_choices = 1) AS unanimous_votes,
                round(
                    count(*) FILTER (WHERE distinct_choices = 1)::numeric
                    / NULLIF(count(*), 0),
                    4
                ) AS cohesion_rate
            FROM party_vote_cohesion
            GROUP BY party_normalized
        )
        SELECT
            p.party_normalized AS party_key,
            CASE
                WHEN p.party_normalized IN ('neafiliat', 'neafiliati', 'independent', 'independenti', 'parlamentar_fara_apartenenta_la_grupurile_parlamentare')
                    THEN 'Neafiliați'
                ELSE max(p.party)
            END AS party,
            array_agg(DISTINCT p.chamber ORDER BY p.chamber) AS chambers,
            count(DISTINCT p.politician_key) AS politicians,
            count(*) AS positions,
            count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain')) AS present_positions,
            round(
                count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain'))::numeric
                / NULLIF(count(*), 0),
                4
            ) AS attendance_rate,
            count(*) FILTER (WHERE p.vote_choice = 'yes') AS yes,
            count(*) FILTER (WHERE p.vote_choice = 'no') AS no,
            count(*) FILTER (WHERE p.vote_choice = 'abstain') AS abstain,
            count(*) FILTER (WHERE p.vote_choice = 'not_voted') AS not_voted,
            count(line.politician_key) AS party_line_eligible_positions,
            count(line.politician_key) FILTER (WHERE line.aligned) AS party_line_aligned_positions,
            {_party_line_applicable_sql('p')} AS party_line_applicable,
            count(line.politician_key) >= %s AS party_line_sample_ok,
            round(
                count(line.politician_key) FILTER (WHERE line.aligned)::numeric
                / NULLIF(count(line.politician_key), 0),
                4
            ) AS party_line_discipline_rate,
            max(cohesion.cohesion_votes) AS cohesion_votes,
            max(cohesion.unanimous_votes) AS unanimous_votes,
            max(cohesion.cohesion_rate) AS cohesion_rate,
            max(v.vote_time) AS latest_vote_time
        FROM parliament_vote_positions p
        JOIN parliament_votes v ON v.vote_id = p.vote_id
        LEFT JOIN party_line_positions line
          ON line.vote_id = p.vote_id
         AND line.politician_key = p.politician_key
        LEFT JOIN party_cohesion cohesion ON cohesion.party_normalized = p.party_normalized
        WHERE {" AND ".join(clauses)}
        GROUP BY p.party_normalized
        ORDER BY positions DESC, party_key
        """,
        [*cohesion_params, min_votes, *params],
    )
    return {"items": items, "min_votes": min_votes}


@app.get("/api/civic/metrics/attendance")
def civic_attendance(
    group_by: str = Query("politician", pattern="^(politician|party)$"),
    chamber: str | None = None,
    party: str | None = None,
    year: int | None = Query(None, ge=1990, le=2100),
    min_votes: int = Query(10, ge=0, le=100000),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    clauses = ["1 = 1"]
    params: list[Any] = []
    if chamber:
        clauses.append("p.chamber = %s")
        params.append(chamber)
    if party:
        clauses.append("p.party_normalized = %s")
        params.append(party)
    if year is not None:
        start, end = _year_bounds(year)
        clauses.append("v.vote_time >= %s AND v.vote_time < %s")
        params.extend([start, end])
    where = " AND ".join(clauses)
    direction = "ASC" if order == "asc" else "DESC"
    if group_by == "party":
        items = _rows(
            f"""
            SELECT
                p.party_normalized AS party_key,
                max(p.party) AS party,
                array_agg(DISTINCT p.chamber ORDER BY p.chamber) AS chambers,
                count(DISTINCT p.politician_key) AS politicians,
                count(*) AS positions,
                count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain')) AS present_positions,
                count(*) FILTER (WHERE p.vote_choice = 'not_voted') AS not_voted,
                round(
                    count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain'))::numeric
                    / NULLIF(count(*), 0),
                    4
                ) AS attendance_rate
            FROM parliament_vote_positions p
            JOIN parliament_votes v ON v.vote_id = p.vote_id
            WHERE {where} AND p.party_normalized IS NOT NULL
            GROUP BY p.party_normalized
            HAVING count(*) >= %s
            ORDER BY attendance_rate {direction} NULLS LAST, positions DESC, party_key
            LIMIT %s OFFSET %s
            """,
            [*params, min_votes, _limit(limit), offset],
        )
    else:
        items = _rows(
            f"""
            SELECT
                p.politician_key,
                max(p.politician_name) AS display_name,
                max(p.party) AS latest_party,
                max(p.party_normalized) AS latest_party_key,
                array_agg(DISTINCT p.chamber ORDER BY p.chamber) AS chambers,
                count(*) AS votes_recorded,
                count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain')) AS present_votes,
                count(*) FILTER (WHERE p.vote_choice = 'not_voted') AS not_voted,
                round(
                    count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain'))::numeric
                    / NULLIF(count(*), 0),
                    4
                ) AS attendance_rate
            FROM parliament_vote_positions p
            JOIN parliament_votes v ON v.vote_id = p.vote_id
            WHERE {where}
            GROUP BY p.politician_key
            HAVING count(*) >= %s
            ORDER BY attendance_rate {direction} NULLS LAST, votes_recorded DESC, display_name
            LIMIT %s OFFSET %s
            """,
            [*params, min_votes, _limit(limit), offset],
        )
    return {
        "definition": "Attendance rate is present voting positions divided by all recorded voting positions. Yes, no, and abstain count as present; not_voted does not.",
        "group_by": group_by,
        "items": items,
        "limit": _limit(limit),
        "min_votes": min_votes,
        "offset": offset,
        "order": order,
    }


@app.get("/api/civic/metrics/party-line-discipline")
def civic_party_line_discipline(
    group_by: str = Query("party", pattern="^(politician|party)$"),
    chamber: str | None = None,
    party: str | None = None,
    year: int | None = Query(None, ge=1990, le=2100),
    min_votes: int = Query(10, ge=0, le=100000),
    include_unaffiliated: bool = False,
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    if _party_line_request_cacheable(
        chamber=chamber,
        party=party,
        year=year,
        min_votes=min_votes,
        include_unaffiliated=include_unaffiliated,
    ):
        cached = _cached_party_line_payload(group_by=group_by, order=order, limit=_limit(limit), offset=offset)
        if cached is not None:
            return cached
    payload = build_civic_party_line_discipline_payload(
        group_by=group_by,
        chamber=chamber,
        party=party,
        year=year,
        min_votes=min_votes,
        include_unaffiliated=include_unaffiliated,
        order=order,
        limit=limit,
        offset=offset,
    )
    payload["cache"] = {
        "key": party_line_cache_key(group_by=group_by, order=order),
        "status": "miss_live" if _party_line_request_cacheable(
            chamber=chamber,
            party=party,
            year=year,
            min_votes=min_votes,
            include_unaffiliated=include_unaffiliated,
        ) else "uncacheable",
    }
    return payload


def party_line_cache_key(*, group_by: str, order: str) -> str:
    return f"civic_party_line:{group_by}:{order}"


def _party_line_request_cacheable(
    *,
    chamber: str | None,
    party: str | None,
    year: int | None,
    min_votes: int,
    include_unaffiliated: bool,
) -> bool:
    return (
        chamber is None
        and party is None
        and year is None
        and min_votes == 10
        and not include_unaffiliated
    )


def build_civic_party_line_discipline_payload(
    *,
    group_by: str = "party",
    chamber: str | None = None,
    party: str | None = None,
    year: int | None = None,
    min_votes: int = 10,
    include_unaffiliated: bool = False,
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    clauses = ["1 = 1"]
    params: list[Any] = []
    if chamber:
        clauses.append("p.chamber = %s")
        params.append(chamber)
    if party:
        clauses.append("p.party_normalized = %s")
        params.append(party)
    if year is not None:
        start, end = _year_bounds(year)
        clauses.append("v.vote_time >= %s AND v.vote_time < %s")
        params.extend([start, end])
    if not include_unaffiliated:
        clauses.append(_party_line_applicable_sql("p"))
    where = " AND ".join(clauses)
    direction = "ASC" if order == "asc" else "DESC"
    if group_by == "party":
        items = _rows(
            f"""
            WITH {_party_line_cte()}
            SELECT
                p.party_normalized AS party_key,
                max(p.party) AS party,
                array_agg(DISTINCT p.chamber ORDER BY p.chamber) AS chambers,
                count(DISTINCT p.politician_key) AS politicians,
                count(line.politician_key) AS eligible_positions,
                count(line.politician_key) FILTER (WHERE line.aligned) AS aligned_positions,
                round(
                    count(line.politician_key) FILTER (WHERE line.aligned)::numeric
                    / NULLIF(count(line.politician_key), 0),
                    4
                ) AS party_line_discipline_rate
            FROM parliament_vote_positions p
            JOIN parliament_votes v ON v.vote_id = p.vote_id
            JOIN party_line_positions line
              ON line.vote_id = p.vote_id
             AND line.politician_key = p.politician_key
            WHERE {where} AND p.party_normalized IS NOT NULL
            GROUP BY p.party_normalized
            HAVING count(line.politician_key) >= %s
            ORDER BY party_line_discipline_rate {direction} NULLS LAST, eligible_positions DESC, party_key
            LIMIT %s OFFSET %s
            """,
            [*params, min_votes, _limit(limit), offset],
        )
    else:
        items = _rows(
            f"""
            WITH {_party_line_cte()}
            SELECT
                p.politician_key,
                max(p.politician_name) AS display_name,
                max(p.party) AS latest_party,
                max(p.party_normalized) AS latest_party_key,
                array_agg(DISTINCT p.chamber ORDER BY p.chamber) AS chambers,
                count(line.politician_key) AS eligible_votes,
                count(line.politician_key) FILTER (WHERE line.aligned) AS party_line_votes,
                round(
                    count(line.politician_key) FILTER (WHERE line.aligned)::numeric
                    / NULLIF(count(line.politician_key), 0),
                    4
                ) AS party_line_discipline_rate
            FROM parliament_vote_positions p
            JOIN parliament_votes v ON v.vote_id = p.vote_id
            JOIN party_line_positions line
              ON line.vote_id = p.vote_id
             AND line.politician_key = p.politician_key
            WHERE {where}
            GROUP BY p.politician_key
            HAVING count(line.politician_key) >= %s
            ORDER BY party_line_discipline_rate {direction} NULLS LAST, eligible_votes DESC, display_name
            LIMIT %s OFFSET %s
            """,
            [*params, min_votes, _limit(limit), offset],
        )
    return {
        "definition": "Party-line discipline is the share of eligible present votes matching the party majority choice for that vote. Tied party majorities and not_voted positions are excluded.",
        "group_by": group_by,
        "items": items,
        "include_unaffiliated": include_unaffiliated,
        "limit": _limit(limit),
        "min_votes": min_votes,
        "offset": offset,
        "order": order,
    }


@app.get("/api/civic/parties/{party_key}")
def civic_party_detail(
    party_key: str,
    scope: str = Query("current", pattern="^(current|all)$"),
    active_since: date = CURRENT_LEGISLATURE_START,
    min_votes: int = Query(10, ge=0, le=100000),
    members_limit: int = Query(30, ge=1, le=500),
    votes_limit: int = Query(30, ge=1, le=100),
    votes_offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    scoped = scope == "current"
    vote_scope_clause = "AND v.vote_time >= %s::date" if scoped else ""
    vote_scope_params: list[Any] = [active_since] if scoped else []
    cte_scope = "party_normalized = %s"
    cte_params: list[Any] = [party_key]
    if scoped:
        cte_scope += " AND vote_id IN (SELECT vote_id FROM parliament_votes WHERE vote_time >= %s::date)"
        cte_params.append(active_since)
    party = _one(
        f"""
        WITH {_party_line_cte(cte_scope)}
        SELECT
            p.party_normalized AS party_key,
            CASE
                WHEN p.party_normalized IN ('neafiliat', 'neafiliati', 'independent', 'independenti', 'parlamentar_fara_apartenenta_la_grupurile_parlamentare')
                    THEN 'Neafiliați'
                ELSE max(p.party)
            END AS party,
            array_agg(DISTINCT p.chamber ORDER BY p.chamber) AS chambers,
            count(DISTINCT p.politician_key) AS politicians,
            count(*) AS positions,
            count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain')) AS present_positions,
            round(
                count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain'))::numeric
                / NULLIF(count(*), 0),
                4
            ) AS attendance_rate,
            count(*) FILTER (WHERE p.vote_choice = 'yes') AS yes,
            count(*) FILTER (WHERE p.vote_choice = 'no') AS no,
            count(*) FILTER (WHERE p.vote_choice = 'abstain') AS abstain,
            count(*) FILTER (WHERE p.vote_choice = 'not_voted') AS not_voted,
            count(line.politician_key) AS party_line_eligible_positions,
            count(line.politician_key) FILTER (WHERE line.aligned) AS party_line_aligned_positions,
            {_party_line_applicable_sql('p')} AS party_line_applicable,
            count(line.politician_key) >= %s AS party_line_sample_ok,
            round(
                count(line.politician_key) FILTER (WHERE line.aligned)::numeric
                / NULLIF(count(line.politician_key), 0),
                4
            ) AS party_line_discipline_rate,
            max(v.vote_time) AS latest_vote_time
        FROM parliament_vote_positions p
        JOIN parliament_votes v ON v.vote_id = p.vote_id
        LEFT JOIN party_line_positions line
          ON line.vote_id = p.vote_id
         AND line.politician_key = p.politician_key
        WHERE p.party_normalized = %s
          {vote_scope_clause}
        GROUP BY p.party_normalized
        """,
        [*cte_params, min_votes, party_key, *vote_scope_params],
    )
    if party is None:
        raise HTTPException(status_code=404, detail="party not found")
    politicians = _rows(
        f"""
        WITH member_stats AS (
            SELECT
                p.politician_key,
                (array_agg(p.politician_name ORDER BY v.vote_time DESC, p.vote_id DESC))[1] AS display_name,
                (array_agg(p.party ORDER BY v.vote_time DESC, p.vote_id DESC))[1] AS latest_party,
                (array_agg(p.party_normalized ORDER BY v.vote_time DESC, p.vote_id DESC))[1] AS latest_party_key,
                array_agg(DISTINCT p.chamber ORDER BY p.chamber) AS chambers,
                count(*) AS votes_recorded,
                count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain')) AS present_votes,
                round(
                    count(*) FILTER (WHERE p.vote_choice IN ('yes', 'no', 'abstain'))::numeric
                    / NULLIF(count(*), 0),
                    4
                ) AS attendance_rate,
                count(*) FILTER (WHERE p.vote_choice = 'yes') AS yes,
                count(*) FILTER (WHERE p.vote_choice = 'no') AS no,
                count(*) FILTER (WHERE p.vote_choice = 'abstain') AS abstain,
                count(*) FILTER (WHERE p.vote_choice = 'not_voted') AS not_voted,
                0 AS party_line_eligible_votes,
                0 AS party_line_votes,
                NULL::numeric AS party_line_discipline_rate,
                min(v.vote_time) AS first_vote_time,
                max(v.vote_time) AS latest_vote_time
            FROM parliament_vote_positions p
            JOIN parliament_votes v ON v.vote_id = p.vote_id
            WHERE p.party_normalized = %s
              {vote_scope_clause}
            GROUP BY p.politician_key
        )
        SELECT
            politician_key, display_name, latest_party, latest_party_key, chambers,
            votes_recorded, present_votes, attendance_rate, yes, no, abstain, not_voted,
            party_line_eligible_votes, party_line_votes, party_line_discipline_rate,
            first_vote_time, latest_vote_time
        FROM member_stats
        ORDER BY display_name
        LIMIT %s
        """,
        [party_key, *vote_scope_params, _limit(members_limit)],
    )
    recent_votes = _rows(
        f"""
        WITH party_vote_ids AS (
            SELECT DISTINCT p.vote_id
            FROM parliament_vote_positions p
            JOIN parliament_votes v ON v.vote_id = p.vote_id
            WHERE p.party_normalized = %s
              {vote_scope_clause}
        )
        SELECT
            v.vote_id, v.chamber, v.vote_time, v.title, v.vote_kind, v.outcome,
            {_has_time_sql('v')} AS has_time,
            v.bill_code, v.bill_number, v.bill_year,
            {_bill_type_sql('v')} AS bill_type,
            CASE WHEN v.bill_code IS NOT NULL THEN {_bill_key_sql('v')} END AS bill_key,
            COALESCE(pb.source_url, v.bill_url) AS bill_url,
            v.nominal_url,
            pb.title AS bill_title,
            pb.short_title AS bill_short_title,
            pb.stage AS bill_stage,
            pb.initiators AS bill_initiators,
            v.present_count, v.yes_count, v.no_count, v.abstain_count, v.not_voted_count,
            positions.positions_count
        FROM parliament_votes v
        LEFT JOIN parliament_bills pb ON pb.bill_key = {_bill_key_sql('v')}
        LEFT JOIN LATERAL (
            SELECT count(*) AS positions_count
            FROM parliament_vote_positions p
            WHERE p.vote_id = v.vote_id
        ) positions ON true
        JOIN party_vote_ids pv ON pv.vote_id = v.vote_id
        ORDER BY v.vote_time DESC, v.vote_id DESC
        LIMIT %s OFFSET %s
        """,
        [party_key, *vote_scope_params, _limit(votes_limit), votes_offset],
    )
    recent_total = _one(
        f"""
        SELECT count(*) AS total
        FROM (
            SELECT DISTINCT p.vote_id
            FROM parliament_vote_positions p
            JOIN parliament_votes v ON v.vote_id = p.vote_id
            WHERE p.party_normalized = %s
              {vote_scope_clause}
        ) party_votes
        """,
        [party_key, *vote_scope_params],
    )
    votes_page = {
        "items": recent_votes,
        "total": recent_total["total"] if recent_total else 0,
        "limit": _limit(votes_limit),
        "offset": votes_offset,
    }
    return {
        "party": party,
        "politicians": politicians,
        "recent_votes": recent_votes,
        "recent_votes_page": votes_page,
        "min_votes": min_votes,
        "scope": scope,
        "active_since": active_since.isoformat(),
    }


@app.get("/api/civic/bills")
def civic_bills(
    chamber: str | None = None,
    outcome: str | None = None,
    final_outcome: str | None = None,
    year: int | None = Query(None, ge=1990, le=2100),
    bill_type: str | None = None,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    cacheable = (
        chamber is None
        and outcome is None
        and final_outcome is None
        and year is None
        and bill_type is None
        and q is None
        and date_from is None
        and date_to is None
    )
    safe_limit = _limit(limit)
    if cacheable:
        cached = _cached_civic_bills_payload(limit=safe_limit, offset=offset)
        if cached is not None:
            return cached
    payload = build_civic_bills_payload(
        chamber=chamber,
        outcome=outcome,
        final_outcome=final_outcome,
        year=year,
        bill_type=bill_type,
        q=q,
        date_from=date_from,
        date_to=date_to,
        limit=safe_limit,
        offset=offset,
    )
    if cacheable and offset == 0:
        payload["cache"] = {"key": civic_bills_cache_key(limit=safe_limit), "status": "miss_live"}
    else:
        payload["cache"] = {"status": "uncacheable"}
    return payload


def build_civic_bills_payload(
    *,
    chamber: str | None = None,
    outcome: str | None = None,
    final_outcome: str | None = None,
    year: int | None = None,
    bill_type: str | None = None,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    clauses = ["v.bill_code IS NOT NULL", "v.bill_number IS NOT NULL", "v.bill_year IS NOT NULL"]
    params: list[Any] = []
    if chamber:
        clauses.append("v.chamber = %s")
        params.append(chamber)
    if outcome:
        clause, clause_params = _outcome_filter_sql("v", outcome)
        clauses.append(clause)
        params.extend(clause_params)
    if year is not None:
        clauses.append("v.vote_time >= %s AND v.vote_time < %s")
        params.extend(_year_bounds(year))
    if date_from:
        clauses.append("v.vote_time >= %s")
        params.append(datetime.combine(date_from, datetime.min.time()))
    if date_to:
        clauses.append("v.vote_time < %s")
        params.append(datetime.combine(date_to, datetime.min.time()) + timedelta(days=1))
    if bill_type:
        clauses.append(_bill_type_sql("v") + " = %s")
        params.append(_normalize_bill_type(bill_type))
    if q:
        normalized_patterns = _search_patterns(q)
        compact_patterns = _compact_search_patterns(q)
        compact_q = _compact_search_text(q)
        q_params: list[Any] = []
        v_title_match = _ilike_any_sql(_search_sql('v.title'), normalized_patterns, q_params)
        pb_title_match = _ilike_any_sql(_search_sql('pb.title'), normalized_patterns, q_params)
        q_params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
        initiative_match = _ilike_any_sql(_search_sql('pb.initiative_type'), normalized_patterns, q_params)
        compact_v_title_match = _ilike_any_sql("regexp_replace(lower(coalesce(v.title, '')), '[^a-z0-9]+', '', 'g')", compact_patterns, q_params)
        compact_pb_title_match = _ilike_any_sql("regexp_replace(lower(coalesce(pb.title, '')), '[^a-z0-9]+', '', 'g')", compact_patterns, q_params)
        compact_initiative_match = _ilike_any_sql("regexp_replace(lower(coalesce(pb.initiative_type, '')), '[^a-z0-9]+', '', 'g')", compact_patterns, q_params)
        q_params.extend([f"%{compact_q}%", f"%{q}%"])
        clauses.append(
            f"""
            (
                {v_title_match}
                OR {pb_title_match}
                OR v.title ILIKE %s
                OR COALESCE(pb.title, '') ILIKE %s
                OR pb.registration_numbers::text ILIKE %s
                OR {initiative_match}
                OR {compact_v_title_match}
                OR {compact_pb_title_match}
                OR {compact_initiative_match}
                OR v.bill_code || v.bill_number::text || '/' || v.bill_year::text ILIKE %s
                OR v.bill_code || ' ' || v.bill_number::text || '/' || v.bill_year::text ILIKE %s
            )
            """
        )
        params.extend(q_params)
    where = " AND ".join(clauses)
    final_filter_clauses: list[str] = []
    final_filter_params: list[Any] = []
    if final_outcome:
        clause, clause_params = _outcome_filter_sql("latest_vote", final_outcome)
        final_filter_clauses.append(clause)
        final_filter_params.extend(clause_params)
    final_filter = f"WHERE {' AND '.join(final_filter_clauses)}" if final_filter_clauses else ""
    items = _rows(
        f"""
        WITH grouped_bills AS (
            SELECT
                {_bill_key_sql('v')} AS bill_key,
                max(COALESCE(pb.bill_code, v.bill_code)) AS bill_code,
                max(COALESCE(pb.bill_number, v.bill_number)) AS bill_number,
                max(COALESCE(pb.bill_year, v.bill_year)) AS bill_year,
                max(COALESCE({_bill_type_sql('pb')}, {_bill_type_sql('v')})) AS bill_type,
                max(COALESCE(pb.source_url, v.bill_url)) AS bill_url,
                max(pb.title) AS title,
                max(pb.short_title) AS short_title,
                max(pb.stage) AS stage,
                max(pb.decisional_chamber) AS decisional_chamber,
                array_agg(DISTINCT v.chamber ORDER BY v.chamber) AS chambers,
                count(*) AS votes,
                count(*) FILTER (WHERE {_normalized_outcome_sql('v')} = 'adopted') AS adopted,
                count(*) FILTER (WHERE {_normalized_outcome_sql('v')} = 'rejected') AS rejected,
                max(v.vote_time) AS latest_vote_time,
                (array_agg(v.vote_id ORDER BY v.vote_time DESC, v.vote_id DESC))[1] AS latest_vote_id,
                COALESCE(max(pb.title), (array_agg(v.title ORDER BY v.vote_time DESC, v.vote_id DESC))[1]) AS latest_title
            FROM parliament_votes v
            LEFT JOIN parliament_bills pb ON pb.bill_key = {_bill_key_sql('v')}
            WHERE {where}
            GROUP BY {_bill_key_sql('v')}
        )
        SELECT
            gb.*,
            {_normalized_outcome_sql('latest_vote')} AS latest_outcome
        FROM grouped_bills gb
        JOIN parliament_votes latest_vote ON latest_vote.vote_id = gb.latest_vote_id
        {final_filter}
        ORDER BY gb.latest_vote_time DESC
        LIMIT %s OFFSET %s
        """,
        [*params, *final_filter_params, _limit(limit), offset],
    )
    total = _one(
        f"""
        WITH grouped_bills AS (
            SELECT
                {_bill_key_sql('v')} AS bill_key,
                (array_agg(v.vote_id ORDER BY v.vote_time DESC, v.vote_id DESC))[1] AS latest_vote_id
            FROM parliament_votes v
            LEFT JOIN parliament_bills pb ON pb.bill_key = {_bill_key_sql('v')}
            WHERE {where}
            GROUP BY {_bill_key_sql('v')}
        )
        SELECT count(*) AS total
        FROM grouped_bills gb
        JOIN parliament_votes latest_vote ON latest_vote.vote_id = gb.latest_vote_id
        {final_filter}
        """,
        [*params, *final_filter_params],
    )
    return {
        "items": items,
        "total": total["total"] if total else 0,
        "limit": _limit(limit),
        "offset": offset,
    }


@app.get("/api/civic/bills/{bill_key}")
def civic_bill_detail(bill_key: str) -> dict[str, Any]:
    bill = _bill_by_key(bill_key)
    related_keys = {bill_key}
    related_keys.update(_related_bill_keys_for_reference(bill_key))
    if bill is not None:
        related_keys.update(_related_bill_keys_from_registration_numbers(bill.get("registration_numbers")))
    related_key_list = sorted(related_keys)
    fallback = _one(
        f"""
        SELECT
            %s AS bill_key,
            max(v.bill_code) AS bill_code,
            max(v.bill_number) AS bill_number,
            max(v.bill_year) AS bill_year,
            max(v.bill_url) AS bill_url,
            array_agg(DISTINCT v.chamber ORDER BY v.chamber) AS chambers,
            count(*) AS votes,
            count(*) FILTER (WHERE {_normalized_outcome_sql('v')} = 'adopted') AS adopted,
            count(*) FILTER (WHERE {_normalized_outcome_sql('v')} = 'rejected') AS rejected,
            max(v.vote_time) AS latest_vote_time,
            (array_agg(v.title ORDER BY v.vote_time DESC))[1] AS latest_title
        FROM parliament_votes v
        WHERE {_bill_key_sql('v')} = ANY(%s)
        """,
        [bill_key, related_key_list],
    )
    if fallback is None or (bill is None and not fallback.get("votes")):
        raise HTTPException(status_code=404, detail="bill not found")
    if bill is None:
        bill = fallback
    else:
        bill = {**fallback, **bill, "latest_title": bill.get("title") or fallback.get("latest_title")}
    events = _bill_events_for_keys(related_key_list)
    votes = _rows(
        f"""
        SELECT
            v.vote_id, v.chamber, v.vote_time, v.title, v.vote_kind, v.outcome,
            {_has_time_sql('v')} AS has_time,
            v.bill_code, v.bill_number, v.bill_year,
            {_bill_type_sql('v')} AS bill_type,
            CASE WHEN v.bill_code IS NOT NULL THEN {_bill_key_sql('v')} END AS bill_key,
            COALESCE(pb.source_url, v.bill_url) AS bill_url,
            v.nominal_url,
            pb.title AS bill_title,
            pb.short_title AS bill_short_title,
            pb.stage AS bill_stage,
            pb.initiators AS bill_initiators,
            v.present_count, v.yes_count, v.no_count, v.abstain_count, v.not_voted_count,
            positions.positions_count
        FROM parliament_votes v
        LEFT JOIN parliament_bills pb ON pb.bill_key = {_bill_key_sql('v')}
        LEFT JOIN LATERAL (
            SELECT count(*) AS positions_count
            FROM parliament_vote_positions p
            WHERE p.vote_id = v.vote_id
        ) positions ON true
        WHERE {_bill_key_sql('v')} = ANY(%s)
        ORDER BY v.vote_time DESC, v.vote_id DESC
        LIMIT 500
        """,
        [related_key_list],
    )
    return {"bill": bill, "votes": votes, "events": events, "related_bill_keys": related_key_list}


@app.get("/api/civic/timeline")
def civic_timeline(
    bucket: str = Query("month", pattern="^(day|week|month|year)$"),
    chamber: str | None = None,
    party: str | None = None,
    politician: str | None = None,
    year: int | None = Query(None, ge=1990, le=2100),
    bill_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    clauses, params = _vote_filters(
        chamber=chamber,
        outcome=None,
        party=party,
        politician=politician,
        bill=None,
        year=year,
        bill_type=bill_type,
        q=None,
        since=since,
        until=until,
    )
    where = " AND ".join(clauses)
    items = _rows(
        f"""
        SELECT
            date_trunc('{bucket}', v.vote_time) AS bucket,
            v.chamber,
            COALESCE(v.outcome, 'unknown') AS outcome,
            count(*) AS votes
        FROM parliament_votes v
        WHERE {where}
        GROUP BY 1, 2, 3
        ORDER BY 1 DESC, 2, 3
        """,
        params,
    )
    return {"bucket": bucket, "items": items}
