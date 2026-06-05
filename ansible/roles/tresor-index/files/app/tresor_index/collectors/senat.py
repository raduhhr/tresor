from __future__ import annotations

import re
import time
import unicodedata
from datetime import date, datetime, timedelta
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit
from zoneinfo import ZoneInfo

from pydantic import ValidationError
import requests

from ..models import ItemType, NormalizedItem, QuarantineCandidate, SourceConfig


_BUCHAREST_TZ = ZoneInfo("Europe/Bucharest")
_BILL_RE = re.compile(r"\b(?P<code>L)\s*(?P<number>\d+)\s*/\s*(?P<year>\d{4})", re.IGNORECASE)
_POSTBACK_RE = re.compile(r"__doPostBack\('(?P<target>[^']+)','(?P<argument>[^']*)'\)")
_ROMANIAN_MONTHS = {
    "ianuarie": 1,
    "februarie": 2,
    "martie": 3,
    "aprilie": 4,
    "mai": 5,
    "iunie": 6,
    "iulie": 7,
    "august": 8,
    "septembrie": 9,
    "octombrie": 10,
    "noiembrie": 11,
    "decembrie": 12,
}


class _FormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.inputs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "input":
            return
        data = dict(attrs)
        name = data.get("name")
        if name:
            self.inputs[name] = data.get("value") or ""


class _CalendarParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_calendar = False
        self.calendar_depth = 0
        self.in_title_table = False
        self.in_title_cell = False
        self.title_parts: list[str] = []
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = dict(attrs)
        if tag.lower() == "table" and data.get("id") == "ctl00_B_Center_VoturiPlen1_calVOT":
            self.in_calendar = True
            self.calendar_depth = 1
            return
        if not self.in_calendar:
            return
        if tag.lower() == "table":
            self.calendar_depth += 1
            if data.get("class") == "myCalendarTitle":
                self.in_title_table = True
        elif tag.lower() == "td" and self.in_title_table:
            self.in_title_cell = True
        elif tag.lower() == "a":
            href = data.get("href") or ""
            title = data.get("title") or ""
            match = _POSTBACK_RE.search(href)
            if match and title:
                self.links.append({"title": title, "target": match.group("target"), "argument": match.group("argument")})

    def handle_endtag(self, tag: str) -> None:
        if not self.in_calendar:
            return
        if tag.lower() == "td":
            self.in_title_cell = False
        elif tag.lower() == "table":
            if self.in_title_table and self.calendar_depth == 2:
                self.in_title_table = False
            self.calendar_depth -= 1
            if self.calendar_depth <= 0:
                self.in_calendar = False

    def handle_data(self, data: str) -> None:
        if self.in_title_cell:
            text = " ".join(data.split())
            if text:
                self.title_parts.append(text)


class _TableParser(HTMLParser):
    def __init__(self, table_id: str | None = None, table_class: str | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.table_id = table_id
        self.table_class = table_class
        self.tables: list[list[list[dict[str, Any]]]] = []
        self._depth = 0
        self._capture = False
        self._table: list[list[dict[str, Any]]] | None = None
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        data = dict(attrs)
        if tag == "table":
            matches_id = self.table_id is not None and data.get("id") == self.table_id
            matches_class = self.table_class is not None and self.table_class in (data.get("class") or "").split()
            if not self._capture and (matches_id or matches_class or (self.table_id is None and self.table_class is None)):
                self._capture = True
                self._depth = 1
                self._table = []
            elif self._capture:
                self._depth += 1
        elif self._capture and tag == "tr":
            self._row = []
        elif self._capture and tag in {"td", "th"} and self._row is not None:
            self._cell = {"text": [], "links": []}
        elif self._capture and tag == "a" and self._cell is not None:
            href = data.get("href")
            if href:
                self._cell["links"].append(href)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self._capture:
            return
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            self._row.append({"text": _clean_text(" ".join(self._cell["text"])), "links": self._cell["links"]})
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._table is not None and self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table":
            self._depth -= 1
            if self._depth <= 0:
                if self._table is not None:
                    self.tables.append(self._table)
                self._capture = False
                self._table = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.replace("\xa0", " ").split())


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


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


def _vote_scope(source: SourceConfig) -> str:
    value = str(source.config.get("vote_scope") or "").strip().lower()
    if value in {"all", "substantive", "final"}:
        return value
    return "final" if bool(source.config.get("final_only", True)) else "all"


def _int_value(value: str | None) -> int | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        return int(re.sub(r"[^\d-]+", "", text))
    except ValueError:
        return None


def _base_url(source: SourceConfig) -> str:
    parts = urlsplit(str(source.url))
    return f"{parts.scheme}://{parts.netloc}/"


def _get_html(session: requests.Session, url: str, headers: dict[str, str], encoding: str) -> tuple[str, int, int]:
    response = session.get(url, timeout=30, headers=headers)
    response.raise_for_status()
    return response.content.decode(encoding, errors="replace"), response.status_code, len(response.content)


def _postback(
    session: requests.Session,
    url: str,
    html: str,
    event_target: str,
    event_argument: str,
    headers: dict[str, str],
    encoding: str,
) -> tuple[str, int, int]:
    parser = _FormParser()
    parser.feed(html)
    data = parser.inputs
    data["__EVENTTARGET"] = event_target
    data["__EVENTARGUMENT"] = event_argument
    response = session.post(url, data=data, timeout=30, headers={**headers, "Referer": url})
    response.raise_for_status()
    return response.content.decode(encoding, errors="replace"), response.status_code, len(response.content)


def _date_range(source: SourceConfig) -> list[date]:
    configured = source.config.get("dates")
    if configured:
        dates: list[date] = []
        for value in configured:
            try:
                dates.append(datetime.strptime(str(value), "%Y-%m-%d").date())
            except ValueError:
                continue
        return sorted(set(dates), reverse=True)

    days_back = max(1, _int_config(source, "days_back", 14))
    today = datetime.now(_BUCHAREST_TZ).date()
    return [today - timedelta(days=offset) for offset in range(days_back)]


def _calendar_year_month(parser: _CalendarParser) -> tuple[int, int] | None:
    for value in parser.title_parts:
        parts = _normalize_text(value).split()
        if len(parts) != 2:
            continue
        month = _ROMANIAN_MONTHS.get(parts[0])
        if month and parts[1].isdigit():
            return int(parts[1]), month
    return None


def _calendar_year_month_from_html(html: str) -> tuple[int, int] | None:
    parser = _CalendarParser()
    parser.feed(html)
    return _calendar_year_month(parser)


def _calendar_month_links(html: str) -> dict[str, dict[str, str]]:
    parser = _CalendarParser()
    parser.feed(html)
    links: dict[str, dict[str, str]] = {}
    for link in parser.links:
        title = _normalize_text(link["title"])
        if "previous month" in title or "luna precedenta" in title:
            links["previous"] = {"target": link["target"], "argument": link["argument"]}
        elif "next month" in title or "luna urmatoare" in title:
            links["next"] = {"target": link["target"], "argument": link["argument"]}
    return links


def _month_index(year_month: tuple[int, int]) -> int:
    return year_month[0] * 12 + year_month[1]


def _calendar_events(html: str) -> dict[date, dict[str, str]]:
    parser = _CalendarParser()
    parser.feed(html)
    year_month = _calendar_year_month(parser)
    if year_month is None:
        return {}
    calendar_year, calendar_month = year_month
    events: dict[date, dict[str, str]] = {}
    for link in parser.links:
        normalized_title = _normalize_text(link["title"])
        parts = normalized_title.split()
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        day = int(parts[0])
        month = _ROMANIAN_MONTHS.get(parts[1])
        if not month:
            continue
        year = calendar_year
        if calendar_month == 1 and month == 12:
            year -= 1
        elif calendar_month == 12 and month == 1:
            year += 1
        try:
            events[date(year, month, day)] = {"target": link["target"], "argument": link["argument"]}
        except ValueError:
            continue
    return events


def _extract_current_date(html: str) -> date | None:
    match = re.search(r"Data\s+Curenta:\s*(\d{2})\.(\d{2})\.(\d{4})", html)
    if not match:
        return None
    return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))


def _parse_vote_time(day: date, value: str | None) -> datetime:
    text = _clean_text(value)
    for pattern in ("%H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(text, pattern).time()
            return datetime.combine(day, parsed, tzinfo=_BUCHAREST_TZ)
        except ValueError:
            continue
    return datetime.combine(day, datetime.min.time(), tzinfo=_BUCHAREST_TZ)


def _bill_from_title(title: str) -> dict[str, Any]:
    match = _BILL_RE.search(title)
    if not match:
        return {}
    code = match.group("code").upper()
    number = int(match.group("number"))
    year = int(match.group("year"))
    return {
        "code": code,
        "number": number,
        "year": year,
        "label": f"{code}{number}/{year}",
        "normalized_id": f"{code.lower()}-{year}-{number}",
    }


def _bill_context_from_vote(source: SourceConfig, bill: dict[str, Any], name_text: str, description_text: str, bill_href: str | None) -> dict[str, Any]:
    title = _clean_text(description_text.replace("|", " "))
    if bill.get("code") and bill.get("number") and bill.get("year"):
        title = re.sub(
            rf"^\s*{re.escape(str(bill['code']))}\s*{bill['number']}\s*/\s*{bill['year']}\s*",
            "",
            title,
            flags=re.IGNORECASE,
        )
    title = re.sub(r"^\s*vot\s+final\s+", "", title, flags=re.IGNORECASE).strip(" -")
    source_url = urljoin(_base_url(source), bill_href) if bill_href else None
    return {
        "source_site": "senat",
        "source_url": source_url,
        "title": title or _clean_text(name_text) or None,
        "stage": "vot final",
        "documents": [{"label": "Pagina proiectului", "url": source_url}] if source_url else [],
        "metadata": {
            "source": "senat_vote_list",
            "raw_name": name_text,
            "fetched_at": datetime.now(_BUCHAREST_TZ).isoformat(),
        },
    }


def _plain_html(value: str) -> str:
    value = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    return _clean_text(unescape(value.replace("&nbsp;", " ")))


def _between(text: str, start: str, stops: list[str]) -> str | None:
    start_index = text.find(start)
    if start_index < 0:
        return None
    start_index += len(start)
    end_index = len(text)
    for stop in stops:
        candidate = text.find(stop, start_index)
        if candidate >= 0:
            end_index = min(end_index, candidate)
    value = text[start_index:end_index].strip(" :-")
    return value or None


def _context_field(text: str, label: str, stops: list[str]) -> str | None:
    return _between(text, f"{label}:", [f"{stop}:" for stop in stops])


def _project_title(text: str, bill: dict[str, Any]) -> str | None:
    number = bill.get("number")
    year = bill.get("year")
    if not number or not year:
        return None
    match = re.search(rf"\bL\s*{number}\s*/\s*{year}\b", text, re.IGNORECASE)
    if not match:
        return None
    value = _between(text[match.end() :], "", ["Inițiatori:", "Initiatori:", "Număr de înregistrare Senat:", "Numar de inregistrare Senat:"])
    return value


def _registration_numbers(text: str) -> dict[str, str]:
    fields = {
        "senat": _context_field(text, "Număr de înregistrare Senat", ["Număr de înregistrare Camera Deputaților", "Adresa", "Prima cameră"]),
        "camera_deputatilor": _context_field(text, "Număr de înregistrare Camera Deputaților", ["Adresa", "Prima cameră", "Tip inițiativă"]),
        "adresa": _context_field(text, "Adresa", ["Prima cameră", "Tip inițiativă", "Inițiatori"]),
        "aviz_consiliul_legislativ": _context_field(text, "Avizul Consiliului Legislativ", ["Procedura de urgență", "Stadiu", "Caracterul legii"]),
    }
    return {key: value for key, value in fields.items() if value}


def _project_documents(source: SourceConfig, body: str) -> list[dict[str, str]]:
    documents: list[dict[str, str]] = []
    for match in re.finditer(r'<a\s+[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<body>[\s\S]*?)</a>', body, re.IGNORECASE):
        href = unescape(match.group("href"))
        if "/legis/pdf/" not in href.lower() and ".pdf" not in href.lower():
            continue
        label = _plain_html(match.group("body"))
        if not label or _normalize_text(label) in {"oug 13 24 04 2012"}:
            continue
        documents.append({"label": label, "url": urljoin(_base_url(source), href)})

    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for document in documents:
        key = (document["label"], document["url"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(document)
    return unique[:25]


def _project_context_from_url(
    source: SourceConfig,
    url: str,
    bill: dict[str, Any],
    session: requests.Session,
    headers: dict[str, str],
    encoding: str,
) -> tuple[dict[str, Any], int, int]:
    html, status, size = _get_html(session, url, headers, encoding)
    text = _plain_html(html)
    detail_start = text.find("Număr de înregistrare Senat:")
    detail_text = text[detail_start:] if detail_start >= 0 else text
    initiator = _context_field(detail_text, "Inițiatori", ["Avizul Consiliului Legislativ", "Procedura de urgență", "Stadiu", "Derularea procedurii legislative"])
    if initiator is None:
        initiator = _context_field(detail_text, "Initiatori", ["Avizul Consiliului Legislativ", "Procedura de urgență", "Stadiu", "Derularea procedurii legislative"])
    urgency_text = _context_field(detail_text, "Procedura de urgență", ["Stadiu", "Caracterul legii", "Termen adoptare"])
    first_chamber = _context_field(detail_text, "Prima cameră", ["Tip inițiativă", "Inițiatori", "Avizul Consiliului Legislativ"])
    law_character = _context_field(detail_text, "Caracterul legii", ["Termen adoptare", "Opiniile persoanelor interesate", "Derularea procedurii legislative"])
    return {
        "source_site": "senat",
        "source_url": url,
        "title": _project_title(text, bill),
        "initiative_type": _context_field(detail_text, "Tip inițiativă", ["Inițiatori", "Avizul Consiliului Legislativ", "Procedura de urgență"]),
        "urgency": urgency_text,
        "urgency_text": urgency_text,
        "stage": _context_field(detail_text, "Stadiu", ["Caracterul legii", "Termen adoptare", "Opiniile persoanelor interesate", "Derularea procedurii legislative"]),
        "initiators": [initiator] if initiator else [],
        "registration_numbers": _registration_numbers(detail_text),
        "documents": _project_documents(source, html),
        "metadata": {
            "source": "senat_project_page",
            "first_chamber": first_chamber,
            "law_character": law_character,
            "fetched_at": datetime.now(_BUCHAREST_TZ).isoformat(),
        },
    }, status, size


def _vote_kind(text: str) -> str:
    normalized = _normalize_text(text)
    if "raport de respingere" in normalized:
        return "final_rejection"
    if "vot final" in normalized:
        return "final"
    if "verificare prezenta" in normalized or "prezenta" == normalized:
        return "presence_check"
    if "amendament" in normalized:
        return "amendment"
    if "procedur" in normalized:
        return "procedural"
    return "other"


def _include_vote(vote: dict[str, Any], scope: str) -> bool:
    if scope == "all":
        return True
    kind = str(vote.get("kind") or "")
    if scope == "final":
        return kind.startswith("final")
    if kind in {"presence_check", "procedural"}:
        return False
    if kind.startswith("final") or kind == "amendment":
        return True
    if vote.get("bill"):
        return True
    outcome = _normalize_text(vote.get("outcome"))
    return bool(outcome and outcome not in {"unknown"})


def _outcome(value: str | None) -> str | None:
    normalized = _normalize_text(value)
    if "adopt" in normalized:
        return "adopted"
    if "respin" in normalized:
        return "rejected"
    return normalized or None


def _party_normalized(value: str | None) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    if normalized.startswith("psd"):
        return "psd"
    if normalized.startswith("pnl"):
        return "pnl"
    if normalized.startswith("usr"):
        return "usr"
    if normalized.startswith("aur"):
        return "aur"
    if normalized.startswith("udmr"):
        return "udmr"
    if normalized.startswith("pir"):
        return "pir"
    if "neafili" in normalized or "independent" in normalized:
        return "neafiliati"
    return normalized.replace(" ", "_")


def _politician_key(family_name: str | None, given_name: str | None) -> str:
    slug = _normalize_text(f"{family_name or ''} {given_name or ''}").replace(" ", "_")
    return f"ro-parliament:{slug}" if slug else "ro-parliament:unknown"


def _vote_choice(row: list[dict[str, Any]]) -> str:
    choices = [("yes", 3), ("no", 4), ("abstain", 5), ("not_voted", 6)]
    for choice, index in choices:
        if len(row) > index and _clean_text(row[index]["text"]):
            return choice
    return "unknown"


def _vote_tables(html: str) -> list[list[list[dict[str, Any]]]]:
    parser = _TableParser(table_class="display")
    parser.feed(html)
    return parser.tables


def _positions_for_vote(
    source: SourceConfig,
    detail_url: str,
    session: requests.Session,
    headers: dict[str, str],
    encoding: str,
) -> tuple[list[dict[str, Any]], int, int]:
    html, status, size = _get_html(session, detail_url, headers, encoding)
    tables = _vote_tables(html)
    if not tables:
        return [], status, size

    rows = tables[-1]
    for table in tables:
        if not table:
            continue
        header = [_normalize_text(cell["text"]) for cell in table[0]]
        if len(header) >= 7 and header[0] == "nume" and header[1] == "prenume":
            rows = table
            break

    positions: list[dict[str, Any]] = []
    for row in rows[1:]:
        if len(row) < 7:
            continue
        family_name = _clean_text(row[0]["text"])
        given_name = _clean_text(row[1]["text"])
        party = _clean_text(row[2]["text"])
        politician_name = " ".join(part for part in (family_name, given_name) if part)
        if not politician_name:
            continue
        normalized_name = _normalize_text(politician_name).replace(" ", "_")
        positions.append(
            {
                "politician_key": _politician_key(family_name, given_name),
                "politician_name": politician_name,
                "normalized_name": normalized_name,
                "family_name": family_name,
                "given_name": given_name,
                "party": party,
                "party_normalized": _party_normalized(party),
                "vote_choice": _vote_choice(row),
                "chamber": "Senat",
                "politician_metadata": {
                    "source": "senat",
                    "chambers_seen": ["Senat"],
                },
            }
        )
    return positions, status, size


def _parse_vote_rows(source: SourceConfig, html: str, day: date) -> list[dict[str, Any]]:
    parser = _TableParser(table_id="ctl00_B_Center_VoturiPlen1_GridVoturi")
    parser.feed(html)
    if not parser.tables:
        return []
    votes: list[dict[str, Any]] = []
    for row in parser.tables[0][1:]:
        if len(row) < 9:
            continue
        description_cell = row[2]
        detail_href = next((href for href in description_cell["links"] if "VoturiPlenDetaliu.aspx" in href), None)
        if not detail_href:
            continue
        detail_url = urljoin(str(source.url), detail_href)
        app_id = (parse_qs(urlsplit(detail_url).query).get("AppID") or [""])[0]
        if not app_id:
            continue
        name_text = row[1]["text"]
        description_text = description_cell["text"]
        title = _clean_text(description_text.replace("|", " "))
        bill = _bill_from_title(name_text or description_text)
        bill_href = row[1]["links"][0] if row[1]["links"] else None
        if bill_href:
            bill["url"] = urljoin(_base_url(source), bill_href)
        if bill:
            bill["context"] = _bill_context_from_vote(source, bill, name_text, description_text, bill_href)
        counts = {
            "present": _int_value(row[4]["text"]),
            "yes": _int_value(row[5]["text"]),
            "no": _int_value(row[6]["text"]),
            "abstain": _int_value(row[7]["text"]),
            "not_voted": _int_value(row[8]["text"]),
        }
        votes.append(
            {
                "vote_id": f"senat:{app_id}",
                "raw_vote_id": app_id,
                "title": title,
                "vote_time": _parse_vote_time(day, row[0]["text"]),
                "bill": bill,
                "detail_url": detail_url,
                "counts": counts,
                "kind": _vote_kind(f"{name_text} {description_text}"),
                "outcome": _outcome(row[3]["text"]),
            }
        )
    return votes


def _pager_targets(html: str, max_pages: int) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    for match in _POSTBACK_RE.finditer(html):
        argument = match.group("argument")
        if not argument.startswith("Page$"):
            continue
        try:
            page = int(argument.split("$", 1)[1])
        except ValueError:
            continue
        if page <= max_pages:
            targets.append((match.group("target"), argument))
    return sorted(set(targets), key=lambda item: int(item[1].split("$", 1)[1]))


def fetch_senat_final_votes(source: SourceConfig) -> tuple[list[NormalizedItem], list[QuarantineCandidate], int, int]:
    headers = {
        "User-Agent": source.config.get("user_agent", "tresor-index/0.1 civic public-data collector"),
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
    }
    encoding = str(source.config.get("html_encoding", "utf-8"))
    request_delay_seconds = max(0.0, _float_config(source, "request_delay_seconds", 0.3))
    vote_scope = _vote_scope(source)
    max_votes = _int_config(source, "max_votes", 200)
    max_pages_per_day = max(1, _int_config(source, "max_pages_per_day", 5))
    max_month_steps = max(1, _int_config(source, "max_month_steps", 120))

    session = requests.Session()
    rejected: list[QuarantineCandidate] = []
    total_bytes = 0
    last_status = 0
    votes: list[dict[str, Any]] = []

    base_html, status, size = _get_html(session, str(source.url), headers, encoding)
    total_bytes += size
    last_status = status
    current_date = _extract_current_date(base_html)
    calendar_events = _calendar_events(base_html)
    month_cache: dict[tuple[int, int], tuple[str, dict[date, dict[str, str]]]] = {}
    base_year_month = _calendar_year_month_from_html(base_html)
    if base_year_month is not None:
        month_cache[base_year_month] = (base_html, calendar_events)

    def calendar_for_day(day: date) -> tuple[str, dict[date, dict[str, str]]]:
        nonlocal last_status, total_bytes
        target_year_month = (day.year, day.month)
        if target_year_month in month_cache:
            return month_cache[target_year_month]
        current_html = base_html
        current_year_month = base_year_month
        if current_year_month is None:
            raise ValueError("could not detect Senate calendar month")

        steps = 0
        while current_year_month != target_year_month:
            if steps >= max_month_steps:
                raise ValueError(f"refusing to traverse more than {max_month_steps} Senate calendar months")
            direction = "previous" if _month_index(target_year_month) < _month_index(current_year_month) else "next"
            month_links = _calendar_month_links(current_html)
            event = month_links.get(direction)
            if event is None:
                raise ValueError(f"Senate calendar has no {direction} month link")
            current_html, status, size = _postback(
                session,
                str(source.url),
                current_html,
                event["target"],
                event["argument"],
                headers,
                encoding,
            )
            total_bytes += size
            last_status = status
            if request_delay_seconds:
                time.sleep(request_delay_seconds)
            parsed_year_month = _calendar_year_month_from_html(current_html)
            if parsed_year_month is None:
                raise ValueError("could not detect Senate calendar month after navigation")
            current_year_month = parsed_year_month
            month_cache[current_year_month] = (current_html, _calendar_events(current_html))
            steps += 1

        return month_cache[target_year_month]

    for day in _date_range(source):
        if current_date == day:
            day_html = base_html
        else:
            try:
                month_html, month_events = calendar_for_day(day)
            except Exception as exc:
                rejected.append(QuarantineCandidate(reason=f"failed to navigate Senate calendar for {day}: {exc}", payload={"date": str(day)}))
                continue
            event = month_events.get(day)
            if event is None:
                continue
            try:
                day_html, status, size = _postback(session, str(source.url), month_html, event["target"], event["argument"], headers, encoding)
                total_bytes += size
                last_status = status
            except Exception as exc:
                rejected.append(QuarantineCandidate(reason=f"failed to fetch Senate vote list for {day}: {exc}", payload={"date": str(day)}))
                continue
            if request_delay_seconds:
                time.sleep(request_delay_seconds)

        votes.extend(_parse_vote_rows(source, day_html, day))
        for target, argument in _pager_targets(day_html, max_pages_per_day):
            try:
                page_html, status, size = _postback(session, str(source.url), day_html, target, argument, headers, encoding)
                total_bytes += size
                last_status = status
            except Exception as exc:
                rejected.append(
                    QuarantineCandidate(reason=f"failed to fetch Senate vote page {argument} for {day}: {exc}", payload={"date": str(day), "page": argument})
                )
                continue
            votes.extend(_parse_vote_rows(source, page_html, day))
            if request_delay_seconds:
                time.sleep(request_delay_seconds)

    items: list[NormalizedItem] = []
    seen_vote_ids: set[str] = set()
    bill_contexts: dict[str, dict[str, Any]] = {}
    for vote in sorted(votes, key=lambda item: item["vote_time"], reverse=True):
        vote_id = vote["vote_id"]
        if vote_id in seen_vote_ids:
            continue
        seen_vote_ids.add(vote_id)
        if not _include_vote(vote, vote_scope):
            continue
        if len(items) >= max_votes:
            break

        bill = vote["bill"]
        bill_url = bill.get("url")
        if bill_url:
            try:
                if bill_url not in bill_contexts:
                    context, status, size = _project_context_from_url(source, bill_url, bill, session, headers, encoding)
                    total_bytes += size
                    last_status = status
                    bill_contexts[bill_url] = context
                    if request_delay_seconds:
                        time.sleep(request_delay_seconds)
                shallow_context = bill.get("context") or {}
                detailed_context = {key: value for key, value in bill_contexts[bill_url].items() if value not in (None, "", [], {})}
                bill["context"] = {**shallow_context, **detailed_context}
            except Exception as exc:
                rejected.append(QuarantineCandidate(reason=f"failed to fetch Senate project context {vote_id}: {exc}", payload={"vote_id": vote_id, "url": bill_url}))

        try:
            positions, status, size = _positions_for_vote(source, vote["detail_url"], session, headers, encoding)
            total_bytes += size
            last_status = status
            if request_delay_seconds:
                time.sleep(request_delay_seconds)
        except Exception as exc:
            rejected.append(QuarantineCandidate(reason=f"failed to fetch Senate nominal vote {vote_id}: {exc}", payload={"vote_id": vote_id}))
            positions = []

        counts = vote["counts"]
        metadata = {
            "site": "senat",
            "vote": {
                "id": vote_id,
                "raw_id": vote["raw_vote_id"],
                "chamber": "Senat",
                "kind": vote["kind"],
                "outcome": vote["outcome"],
                "scope": vote_scope,
            },
            "bill": vote["bill"],
            "counts": counts,
            "positions_count": len(positions),
            "positions": positions,
        }
        try:
            items.append(
                NormalizedItem(
                    source_id=source.id,
                    item_type=ItemType.PARLIAMENT_VOTE,
                    title=vote["title"],
                    canonical_url=vote["detail_url"],
                    external_id=vote_id,
                    description=f"{counts.get('yes') or 0} yes, {counts.get('no') or 0} no, {counts.get('abstain') or 0} abstain",
                    published_at=vote["vote_time"],
                    metadata=metadata,
                )
            )
        except ValidationError as exc:
            rejected.append(QuarantineCandidate(reason=str(exc), payload=metadata))

    return items, rejected, last_status, total_bytes
