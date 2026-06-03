from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import requests

from . import db


LOCAL_TZ = ZoneInfo(os.getenv("TRESOR_INDEX_TIMEZONE", "Europe/Bucharest"))
DISCORD_LIMIT = 1900
DEFAULT_USERNAME = os.getenv("TRESOR_INDEX_DISCORD_USERNAME", "Tresor Index")


@dataclass(frozen=True)
class DigestRule:
    id: str
    name: str
    kind: str
    webhook_env: str
    schedule_env: str
    default_schedule: str
    color: int

    @property
    def webhook_url(self) -> str:
        return os.getenv(self.webhook_env, "").strip()

    @property
    def schedule_time(self) -> time:
        raw = os.getenv(self.schedule_env, self.default_schedule).strip()
        hour, minute = raw.split(":", 1)
        return time(hour=int(hour), minute=int(minute), tzinfo=LOCAL_TZ)


DAILY_RULES: dict[str, DigestRule] = {
    "votes": DigestRule(
        id="votes",
        name="Daily Voting Digest",
        kind="votes",
        webhook_env="TRESOR_INDEX_DISCORD_WEBHOOK_VOTES",
        schedule_env="TRESOR_INDEX_DIGEST_VOTES_TIME",
        default_schedule="20:00",
        color=0x8B5CF6,
    ),
    "romanian_news": DigestRule(
        id="romanian_news",
        name="Romanian News Digest",
        kind="romanian_news",
        webhook_env="TRESOR_INDEX_DISCORD_WEBHOOK_ROMANIAN_NEWS",
        schedule_env="TRESOR_INDEX_DIGEST_ROMANIAN_NEWS_TIME",
        default_schedule="20:30",
        color=0x3B82F6,
    ),
    "tech_news": DigestRule(
        id="tech_news",
        name="Tech News Digest",
        kind="tech_news",
        webhook_env="TRESOR_INDEX_DISCORD_WEBHOOK_TECH_NEWS",
        schedule_env="TRESOR_INDEX_DIGEST_TECH_NEWS_TIME",
        default_schedule="21:00",
        color=0xA855F7,
    ),
    "real_estate": DigestRule(
        id="real_estate",
        name="Bucharest Houses Digest",
        kind="real_estate",
        webhook_env="TRESOR_INDEX_DISCORD_WEBHOOK_REAL_ESTATE",
        schedule_env="TRESOR_INDEX_DIGEST_REAL_ESTATE_TIME",
        default_schedule="21:30",
        color=0x14B8A6,
    ),
}


STOPWORDS = {
    "acasa",
    "acel",
    "acela",
    "acele",
    "aceasta",
    "aceste",
    "acest",
    "acum",
    "about",
    "across",
    "after",
    "again",
    "against",
    "aici",
    "ajuns",
    "also",
    "alte",
    "altfel",
    "altor",
    "always",
    "and",
    "another",
    "apoi",
    "alte",
    "ani",
    "anul",
    "are",
    "arata",
    "are",
    "as",
    "asta",
    "astazi",
    "asupra",
    "atunci",
    "available",
    "avut",
    "back",
    "been",
    "being",
    "buna",
    "bune",
    "buni",
    "but",
    "can",
    "care",
    "cand",
    "catre",
    "cea",
    "cele",
    "celor",
    "celui",
    "cere",
    "cei",
    "cine",
    "citi",
    "cnd",
    "come",
    "could",
    "cum",
    "cumva",
    "daca",
    "deja",
    "despre",
    "dintr",
    "din",
    "dupa",
    "each",
    "ele",
    "era",
    "erau",
    "este",
    "etc",
    "face",
    "faca",
    "fara",
    "fel",
    "fie",
    "fiecare",
    "fiind",
    "fost",
    "fostul",
    "from",
    "going",
    "good",
    "got",
    "has",
    "have",
    "how",
    "iar",
    "ieri",
    "important",
    "inapoi",
    "insa",
    "intre",
    "into",
    "isi",
    "its",
    "mai",
    "make",
    "many",
    "mereu",
    "might",
    "mai",
    "mare",
    "mari",
    "mica",
    "mici",
    "model",
    "models",
    "modul",
    "more",
    "mult",
    "multe",
    "multi",
    "nevoie",
    "new",
    "news",
    "noi",
    "nou",
    "noua",
    "noul",
    "numai",
    "numar",
    "oficial",
    "once",
    "one",
    "orice",
    "or",
    "other",
    "others",
    "our",
    "out",
    "pana",
    "pare",
    "pentru",
    "peste",
    "poate",
    "pot",
    "poti",
    "prin",
    "privind",
    "putea",
    "recent",
    "romania",
    "roman",
    "romana",
    "romaneasca",
    "same",
    "sau",
    "seara",
    "see",
    "sees",
    "should",
    "some",
    "spre",
    "still",
    "sunt",
    "such",
    "take",
    "than",
    "that",
    "the",
    "their",
    "there",
    "these",
    "they",
    "this",
    "those",
    "timp",
    "toate",
    "toata",
    "toate",
    "tot",
    "toti",
    "trei",
    "unde",
    "unor",
    "unui",
    "until",
    "urma",
    "urmator",
    "use",
    "used",
    "user",
    "users",
    "using",
    "very",
    "via",
    "want",
    "was",
    "were",
    "what",
    "when",
    "while",
    "who",
    "why",
    "will",
    "with",
    "would",
    "your",
}

INVESTIGATION_KEYWORDS = (
    "ancheta",
    "anchetă",
    "documentar",
    "investigatie",
    "investigație",
    "investigatia",
    "investigația",
)

ROMANIAN_NEWS_DIGEST_SOURCE_IDS = {
    "recorder_general",
    "recorder_youtube",
    "pressone_general",
    "context_general",
    "rise_project_general",
    "snoop_general",
    "g4media_general",
}

TECH_NEWS_DIGEST_SOURCE_IDS = {
    "hacker_news_global",
    "the_register_global",
    "bleepingcomputer_global",
    "krebs_security_global",
    "techcrunch_global",
    "toms_hardware_global",
    "ars_technica_global",
}

TECH_NEWS_DIGEST_KEYWORDS = (
    "cve",
    "vulnerability",
    "zero day",
    "0 day",
    "exploit",
    "exploited",
    "malware",
    "ransomware",
    "breach",
    "leak",
    "leaked",
    "credential",
    "token",
    "key",
    "supply chain",
    "package",
    "npm",
    "pypi",
    "composer",
    "packagist",
    "github",
    "botnet",
    "phishing",
    "backdoor",
    "patch",
    "security",
    "incident",
    "outage",
    "downtime",
    "cloudflare",
    "aws",
    "azure",
    "google cloud",
    "data center",
    "datacenter",
    "infrastructure",
)

RECORDER_YOUTUBE_EXCLUDE_KEYWORDS = (
    "stirile zilei",
    "stirea zilei",
    "recorder stirile",
)


def _now() -> datetime:
    return datetime.now(LOCAL_TZ)


def _local_day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, LOCAL_TZ)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _json(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _rows(sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [{key: _json(value) for key, value in dict(row).items()} for row in cur.fetchall()]


def _one(sql: str, params: list[Any] | tuple[Any, ...] = ()) -> dict[str, Any] | None:
    rows = _rows(sql, params)
    return rows[0] if rows else None


def _alert_sent(rule_id: str, dedupe_key: str) -> bool:
    row = _one("SELECT 1 FROM alert_events WHERE rule_id = %s AND dedupe_key = %s", [rule_id, dedupe_key])
    return row is not None


def _record_alert(rule_id: str, dedupe_key: str, payload: dict[str, Any], *, item_id: int | None = None) -> None:
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alert_rules (id, name, enabled, mode, match, channel, config, updated_at)
                VALUES (%s, %s, true, 'digest', '{}'::jsonb, 'discord', '{}'::jsonb, now())
                ON CONFLICT (id) DO UPDATE SET updated_at = now()
                """,
                (rule_id, DAILY_RULES.get(rule_id, DigestRule(rule_id, rule_id, rule_id, "", "", "00:00", 0)).name),
            )
            cur.execute(
                """
                INSERT INTO alert_events (rule_id, item_id, channel, dedupe_key, payload, sent_at)
                VALUES (%s, %s, 'discord', %s, %s::jsonb, now())
                ON CONFLICT (rule_id, dedupe_key) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    sent_at = EXCLUDED.sent_at
                """,
                (rule_id, item_id, dedupe_key, json.dumps(payload, default=str, ensure_ascii=False)),
            )
        conn.commit()


def _discord_post(webhook_url: str, payload: dict[str, Any]) -> None:
    if not webhook_url:
        raise RuntimeError("discord webhook URL is not configured")
    response = requests.post(webhook_url, json=payload, timeout=20)
    response.raise_for_status()


def _truncate(value: str, limit: int) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _money(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"€{int(round(float(value))):,}".replace(",", " ")


def _embed_payload(*, title: str, description: str, color: int, fields: list[dict[str, Any]], footer: str) -> dict[str, Any]:
    return {
        "username": DEFAULT_USERNAME,
        "embeds": [
            {
                "title": _truncate(title, 256),
                "description": _truncate(description, 4096),
                "color": color,
                "fields": fields[:25],
                "footer": {"text": footer},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }


def _field(name: str, value: str, *, inline: bool = False) -> dict[str, Any]:
    return {"name": _truncate(name, 256), "value": _truncate(value or "n/a", 1024), "inline": inline}


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text)


def _tokens(value: str) -> set[str]:
    return {token for token in _normalize_text(value).split() if len(token) >= 4 and token not in STOPWORDS}


def _select_article_rows(rows: list[dict[str, Any]], *, limit: int = 10) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    for row in rows:
        source_id = row.get("source_id")
        if source_id in seen_sources:
            continue
        selected.append(row)
        seen_sources.add(source_id)
        if len(selected) >= limit:
            break
    return selected


def _shared_words(rows: list[dict[str, Any]], *, limit: int = 12) -> list[tuple[str, int]]:
    sources_by_word: dict[str, set[str]] = {}
    for row in rows:
        source_id = str(row.get("source_id") or "")
        for token in _tokens(f"{row.get('title') or ''} {row.get('description') or ''}"):
            sources_by_word.setdefault(token, set()).add(source_id)
    shared = [(word, len(source_ids)) for word, source_ids in sources_by_word.items() if len(source_ids) >= 2]
    return sorted(shared, key=lambda item: (item[1], item[0]), reverse=True)[:limit]


def _is_enabled_env(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _matches_tech_digest_interest(row: dict[str, Any]) -> bool:
    haystack = _normalize_text(f"{row.get('title') or ''} {row.get('description') or ''}")
    if re.search(r"\bcve\s+\d{4}\b", haystack):
        return True
    return any(_normalize_text(keyword) in haystack for keyword in TECH_NEWS_DIGEST_KEYWORDS)


def _matches_recorder_main_clip(row: dict[str, Any]) -> bool:
    haystack = _normalize_text(f"{row.get('title') or ''} {row.get('description') or ''}")
    return not any(_normalize_text(keyword) in haystack for keyword in RECORDER_YOUTUBE_EXCLUDE_KEYWORDS)


def _fetch_daily_articles(category: str, day: date, *, source_ids: set[str] | None = None) -> list[dict[str, Any]]:
    start, end = _local_day_bounds(day)
    source_filter = ""
    params: list[Any] = [category, start, end]
    if source_ids:
        source_filter = "AND i.source_id = ANY(%s)"
        params.append(sorted(source_ids))
    return _rows(
        f"""
        SELECT i.id, i.source_id, s.name AS source_name, i.title, i.description,
               i.canonical_url, i.first_seen_at, i.published_at
        FROM items i
        JOIN sources s ON s.id = i.source_id
        WHERE i.item_type = 'article'
          AND s.category = %s
          AND i.first_seen_at >= %s
          AND i.first_seen_at < %s
          {source_filter}
        ORDER BY i.first_seen_at DESC, i.id DESC
        """,
        params,
    )


def build_news_digest(rule: DigestRule, day: date) -> dict[str, Any] | None:
    category = "romanian_news" if rule.kind == "romanian_news" else "tech"
    if category == "romanian_news":
        rows = _fetch_daily_articles(category, day, source_ids=ROMANIAN_NEWS_DIGEST_SOURCE_IDS)
        candidate_rows = rows
        selected = _select_article_rows(candidate_rows, limit=8)
        label = "Romanian news"
        description = (
            f"{label} digest for {day.isoformat()}. Curated sources only: "
            "Recorder, PressOne, Context, RISE, Snoop and G4Media."
        )
    else:
        rows = _fetch_daily_articles(category, day, source_ids=TECH_NEWS_DIGEST_SOURCE_IDS)
        candidate_rows = [row for row in rows if _matches_tech_digest_interest(row)]
        selected = _select_article_rows(candidate_rows, limit=8)
        label = "Tech signal"
        description = (
            f"{label} digest for {day.isoformat()}. Security, outage, supply-chain "
            "and infrastructure items from curated sources only."
        )
    if not selected:
        return None
    shared = _shared_words(candidate_rows)

    fields: list[dict[str, Any]] = [
        _field("Curated articles scanned", str(len(rows)), inline=True),
        _field("Sources shown", str(len(selected)), inline=True),
    ]
    for idx, row in enumerate(selected, start=1):
        value = f"[{_truncate(row['title'], 180)}]({row['canonical_url']})"
        fields.append(_field(f"{idx}. {row['source_name']}", value))
    if shared:
        words = ", ".join(f"{word} ({count})" for word, count in shared)
        fields.append(_field("Words seen across multiple sources", words))

    return _embed_payload(
        title=rule.name,
        description=description,
        color=rule.color,
        fields=fields,
        footer="Tresor Index daily digest",
    )


def build_real_estate_digest(rule: DigestRule, day: date) -> dict[str, Any]:
    start, end = _local_day_bounds(day)
    stats = _one(
        """
        SELECT
            count(*)::int AS new_listings,
            percentile_cont(0.5) WITHIN GROUP (ORDER BY (i.metadata->'price'->>'value')::numeric) AS median_price,
            min((i.metadata->'price'->>'value')::numeric) AS min_price,
            max((i.metadata->'price'->>'value')::numeric) AS max_price
        FROM items i
        WHERE i.item_type = 'listing'
          AND i.source_id = 'olx_bucuresti_case_50_1m_eur'
          AND i.first_seen_at >= %s
          AND i.first_seen_at < %s
        """,
        [start, end],
    ) or {}
    listings = _rows(
        """
        SELECT i.title, i.canonical_url, i.source_id, i.first_seen_at,
               (i.metadata->'price'->>'value')::numeric AS price,
               COALESCE(i.metadata->'location'->>'district', 'unknown') AS district,
               i.metadata->>'area_sqm' AS area_sqm,
               i.metadata->'seller'->>'business' AS seller_business
        FROM items i
        WHERE i.item_type = 'listing'
          AND i.source_id = 'olx_bucuresti_case_50_1m_eur'
          AND i.first_seen_at >= %s
          AND i.first_seen_at < %s
          AND (i.metadata->'price'->>'value')::numeric BETWEEN 50000 AND 200000
        ORDER BY price ASC NULLS LAST, i.first_seen_at DESC, i.id DESC
        LIMIT 8
        """,
        [start, end],
    )
    fields = [
        _field("New Bucharest houses", str(stats.get("new_listings") or 0), inline=True),
        _field("Median price", _money(stats.get("median_price")), inline=True),
        _field("Range", f"{_money(stats.get('min_price'))} - {_money(stats.get('max_price'))}", inline=True),
    ]
    if not listings:
        fields.append(_field("No cheap picks", "No new Bucharest houses in the default EUR 50k-200k digest range today."))
    for idx, row in enumerate(listings, start=1):
        bits = [_money(row.get("price")), str(row.get("district") or "unknown")]
        if row.get("area_sqm"):
            bits.append(f"{row['area_sqm']} sqm")
        fields.append(_field(f"{idx}. {_truncate(row['title'], 90)}", f"{' - '.join(bits)}\n{row['canonical_url']}"))

    return _embed_payload(
        title=rule.name,
        description=f"Bucharest OLX houses digest for {day.isoformat()}. Picks are the cheapest new listings in the quiet default EUR 50k-200k range.",
        color=rule.color,
        fields=fields,
        footer="Tresor Index daily digest",
    )


def _vote_outcome_label(outcome: str | None) -> str:
    return {"adopted": "adopted", "rejected": "rejected"}.get(outcome or "", outcome or "unknown")


def _chunk_lines(lines: list[str], *, max_chars: int = 900, max_chunks: int = 22) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        extra_len = len(line) + (2 if current else 0)
        if current and current_len + extra_len > max_chars:
            chunks.append("\n\n".join(current))
            current = [line]
            current_len = len(line)
            if len(chunks) >= max_chunks:
                break
            continue
        current.append(line)
        current_len += extra_len
    if current and len(chunks) < max_chunks:
        chunks.append("\n\n".join(current))

    included = sum(chunk.count("\n\n") + 1 for chunk in chunks)
    if len(lines) > included:
        chunks.append(f"{len(lines) - included} additional votes omitted because Discord embeds have field limits.")
    return chunks


def build_votes_digest(rule: DigestRule, day: date) -> dict[str, Any] | None:
    start, end = _local_day_bounds(day)
    stats = _one(
        """
        SELECT count(*)::int AS votes,
               count(*) FILTER (WHERE outcome = 'adopted')::int AS adopted,
               count(*) FILTER (WHERE outcome = 'rejected')::int AS rejected,
               count(*) FILTER (WHERE chamber = 'Camera Deputatilor')::int AS camera,
               count(*) FILTER (WHERE chamber = 'Senat')::int AS senat
        FROM parliament_votes
        WHERE vote_time >= %s AND vote_time < %s
        """,
        [start, end],
    ) or {}
    if not stats.get("votes"):
        return None
    votes = _rows(
        """
        SELECT vote_id, chamber, vote_time, title, outcome, bill_code, bill_number, bill_year,
               bill_url, yes_count, no_count, abstain_count, not_voted_count
        FROM parliament_votes
        WHERE vote_time >= %s AND vote_time < %s
        ORDER BY vote_time DESC, vote_id DESC
        """,
        [start, end],
    )
    fields = [
        _field("Votes", str(stats.get("votes") or 0), inline=True),
        _field("Adopted / rejected", f"{stats.get('adopted') or 0} / {stats.get('rejected') or 0}", inline=True),
        _field("Camera / Senat", f"{stats.get('camera') or 0} / {stats.get('senat') or 0}", inline=True),
    ]
    for idx, vote in enumerate(votes, start=1):
        bill = ""
        if vote.get("bill_code") and vote.get("bill_number") and vote.get("bill_year"):
            bill = f"{vote['bill_code']}-{vote['bill_number']}/{vote['bill_year']} · "
        counts = f"{vote.get('yes_count') or 0} yes / {vote.get('no_count') or 0} no / {vote.get('abstain_count') or 0} abstain"
        link = vote.get("bill_url") or ""
        title = _truncate(vote["title"], 170)
        value = f"{bill}{vote['chamber']} · {vote.get('outcome') or 'unknown'}\n{counts}"
        if link:
            value += f"\n{link}"
        fields.append(_field(f"{idx}. {title}", value))

    if len(fields) > 25:
        vote_lines = [f"**{field['name']}**\n{field['value']}" for field in fields[3:]]
        fields = fields[:3]
        for idx, chunk in enumerate(_chunk_lines(vote_lines), start=1):
            fields.append(_field(f"Votes batch {idx}", chunk))

    return _embed_payload(
        title=rule.name,
        description=f"Final plenary votes recorded on {day.isoformat()}.",
        color=rule.color,
        fields=fields,
        footer="Tresor Index daily digest",
    )


def build_daily_digest(rule: DigestRule, day: date) -> dict[str, Any] | None:
    if rule.kind in {"romanian_news", "tech_news"}:
        return build_news_digest(rule, day)
    if rule.kind == "real_estate":
        return build_real_estate_digest(rule, day)
    if rule.kind == "votes":
        return build_votes_digest(rule, day)
    raise ValueError(f"unsupported digest kind: {rule.kind}")


def send_daily_digest(rule_id: str, *, day: date | None = None, force: bool = False) -> dict[str, Any]:
    if rule_id not in DAILY_RULES:
        raise ValueError(f"unknown digest rule: {rule_id}")
    rule = DAILY_RULES[rule_id]
    if not rule.webhook_url:
        return {"rule_id": rule.id, "status": "skipped", "reason": "webhook_not_configured"}
    if rule.kind == "real_estate" and not _is_enabled_env("TRESOR_INDEX_DIGEST_REAL_ESTATE_ENABLED", default=False):
        return {"rule_id": rule.id, "status": "skipped", "reason": "digest_paused"}
    target_day = day or _now().date()
    scheduled_dedupe_key = f"{rule.id}:{target_day.isoformat()}"
    dedupe_key = scheduled_dedupe_key
    if force:
        dedupe_key = f"{scheduled_dedupe_key}:manual:{datetime.now(timezone.utc).isoformat(timespec='seconds')}"
    elif _alert_sent(rule.id, scheduled_dedupe_key):
        return {"rule_id": rule.id, "status": "skipped", "reason": "already_sent", "dedupe_key": scheduled_dedupe_key}
    payload = build_daily_digest(rule, target_day)
    if payload is None:
        return {"rule_id": rule.id, "status": "skipped", "reason": "no_digest_content"}
    _discord_post(rule.webhook_url, payload)
    _record_alert(rule.id, dedupe_key, payload)
    return {"rule_id": rule.id, "status": "sent", "dedupe_key": dedupe_key, "scheduled_dedupe_key": scheduled_dedupe_key}


def run_due_digests(now: datetime | None = None) -> list[dict[str, Any]]:
    current = now.astimezone(LOCAL_TZ) if now else _now()
    results: list[dict[str, Any]] = []
    for rule in DAILY_RULES.values():
        scheduled = datetime.combine(current.date(), rule.schedule_time, LOCAL_TZ)
        if current >= scheduled:
            try:
                result = send_daily_digest(rule.id, day=current.date(), force=False)
            except Exception as exc:
                result = {"rule_id": rule.id, "status": "error", "reason": str(exc)}
            results.append(result)
    try:
        results.extend(send_recorder_youtube_alerts())
    except Exception as exc:
        results.append({"rule_id": "recorder_youtube_clip", "status": "error", "reason": str(exc)})
    return results


def _matches_investigation(row: dict[str, Any]) -> bool:
    haystack = f"{row.get('title') or ''} {row.get('description') or ''}"
    normalized = _normalize_text(haystack)
    return any(_normalize_text(keyword) in normalized for keyword in INVESTIGATION_KEYWORDS)


def send_recorder_youtube_alerts() -> list[dict[str, Any]]:
    webhook_url = os.getenv("TRESOR_INDEX_DISCORD_WEBHOOK_ROMANIAN_NEWS", "").strip()
    if not webhook_url:
        return []
    rows = _rows(
        """
        SELECT i.id, i.title, i.description, i.canonical_url, i.first_seen_at, i.published_at
        FROM items i
        WHERE i.source_id = 'recorder_youtube'
          AND i.item_type = 'article'
          AND i.first_seen_at >= now() - interval '14 days'
          AND COALESCE(i.published_at, i.first_seen_at) >= now() - interval '48 hours'
        ORDER BY i.first_seen_at ASC, i.id ASC
        """
    )
    results: list[dict[str, Any]] = []
    for row in rows:
        if not _matches_recorder_main_clip(row):
            continue
        dedupe_key = hashlib.sha256(str(row["canonical_url"]).encode("utf-8")).hexdigest()
        rule_id = "recorder_youtube_clip"
        if _alert_sent(rule_id, dedupe_key):
            continue
        payload = _embed_payload(
            title="Recorder posted a new clip",
            description=f"[{_truncate(row['title'], 220)}]({row['canonical_url']})",
            color=0xEF4444,
            fields=[
                _field("Source", "Recorder YouTube", inline=True),
                _field("Detected", str(row.get("first_seen_at")), inline=True),
            ],
            footer="Tresor Index immediate alert",
        )
        _discord_post(webhook_url, payload)
        _record_alert(rule_id, dedupe_key, payload, item_id=int(row["id"]))
        results.append({"rule_id": rule_id, "status": "sent", "item_id": row["id"]})
    return results


def send_recorder_investigation_alerts() -> list[dict[str, Any]]:
    return send_recorder_youtube_alerts()
