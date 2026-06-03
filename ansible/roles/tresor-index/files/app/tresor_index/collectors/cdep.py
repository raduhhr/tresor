from __future__ import annotations

import re
import time
import unicodedata
from html import unescape
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from pydantic import ValidationError
import requests
from urllib3.exceptions import InsecureRequestWarning
import urllib3

from ..models import ItemType, NormalizedItem, QuarantineCandidate, SourceConfig


_BUCHAREST_TZ = ZoneInfo("Europe/Bucharest")
_BILL_RE = re.compile(r"\b(?P<code>PL-x|Pl-x|PH\s+CD)\s*(?P<number>\d+)\s*/\s*(?P<year>\d{4})", re.IGNORECASE)


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


def _text(row: ElementTree.Element, tag: str) -> str | None:
    value = row.findtext(tag)
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


def _int_text(row: ElementTree.Element, tag: str) -> int | None:
    value = _text(row, tag)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _endpoint(source: SourceConfig, path: str) -> str:
    parts = urlsplit(str(source.url))
    return f"{parts.scheme}://{parts.netloc}{path}"


def _get_xml(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    *,
    encoding: str = "utf-8",
    allow_empty: bool = False,
) -> tuple[ElementTree.Element, int, int]:
    response = session.get(url, timeout=30, headers=headers)
    response.raise_for_status()
    text = response.content.decode(encoding, errors="replace")
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text, count=1)
    if allow_empty and not text.strip():
        return ElementTree.Element("ROWSET"), response.status_code, len(response.content)
    return ElementTree.fromstring(text), response.status_code, len(response.content)


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


def _parse_vote_time(value: str | None, fallback_date: date) -> datetime:
    for pattern in ("%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S"):
        if value:
            try:
                return datetime.strptime(value, pattern).replace(tzinfo=_BUCHAREST_TZ)
            except ValueError:
                pass
    return datetime.combine(fallback_date, datetime.min.time(), tzinfo=_BUCHAREST_TZ)


def _bill_from_title(title: str) -> dict[str, Any]:
    match = _BILL_RE.search(title)
    if not match:
        return {}
    code = re.sub(r"\s+", " ", match.group("code")).upper()
    if code == "PL-X":
        code = "PL-x"
    if code == "PH CD":
        code = "PH CD"
    number = int(match.group("number"))
    year = int(match.group("year"))
    return {
        "code": code,
        "number": number,
        "year": year,
        "label": f"{code} {number}/{year}",
        "normalized_id": f"{code.lower().replace(' ', '-')}-{year}-{number}",
    }


def _vote_kind(title: str) -> str:
    normalized = _normalize_text(title)
    if "vot final" in normalized and "adopt" in normalized:
        return "final_adoption"
    if "vot final" in normalized and "resping" in normalized:
        return "final_rejection"
    if "vot final" in normalized:
        return "final"
    if "timpi dezbateri" in normalized:
        return "debate_time"
    if "verificare prezenta" in normalized:
        return "presence_check"
    return "other"


def _outcome(title: str, yes: int | None, no: int | None) -> str | None:
    if yes is None or no is None:
        return None
    passed = yes > no
    kind = _vote_kind(title)
    if kind == "final_adoption":
        return "adopted" if passed else "not_adopted"
    if kind == "final_rejection":
        return "rejected" if passed else "not_rejected"
    if kind == "final":
        return "passed" if passed else "failed"
    return None


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).strip()


def _plain_html(value: str) -> str:
    value = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value.replace("&nbsp;", " "))
    return " ".join(value.split())


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


def _registration_numbers(text: str) -> dict[str, str]:
    section = _between(
        text,
        "Nr. inregistrare:",
        ["Procedura legislativa:", "Procedura legislativă:"],
    ) or _between(text, "Nr. înregistrare:", ["Procedura legislativa:", "Procedura legislativă:"])
    if not section:
        section = text
    registrations: dict[str, str] = {}
    for match in re.finditer(r"(?:^|\s+-\s*)([^:]+):\s*(.*?)(?=\s+-\s*[^:]+:|$)", section):
        key = " ".join(match.group(1).split()).strip()
        value = " ".join(match.group(2).split()).strip()
        if key and value:
            registrations[key] = value
    for key, pattern in {
        "Senat": r"\bSenat\s*:?\s*(L\s*\d+\s*/\s*\d{4})\b",
        "Camera Deputatilor": r"\bCamera\s+Deputa(?:t|ţ|ț)ilor\s*:?\s*([0-9]+\s*/\s*\d{2}\.\d{2}\.\d{4})\b",
        "Guvern": r"\bGuvern\s*:?\s*(E\s*\d+\s*/\s*\d{2}\.\d{2}\.\d{4})\b",
    }.items():
        if key in registrations:
            continue
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            registrations[key] = " ".join(match.group(1).split())
    return registrations


def _project_documents(source: SourceConfig, body: str) -> list[dict[str, str]]:
    allowed_labels = {
        "adresa senatului",
        "adresa initiatorului",
        "adresa guvernului",
        "expunerea de motive",
        "forma initiatorului",
        "ordonanta de urgenta a guvernului",
        "avizul consiliului economic si social",
        "avizul consiliului legislativ",
        "punctul de vedere al guvernului",
        "raportul comisiei sesizate in fond",
        "raportul comisiei",
        "forma adoptata",
    }
    documents: list[dict[str, str]] = []
    row_pattern = re.compile(
        r'<a\s+[^>]*href="(?P<href>[^"]+)"[^>]*>[\s\S]*?</a>[\s\S]*?<td[^>]*>\s*(?P<label>[^<]+?)\s*</td>',
        re.IGNORECASE,
    )
    for match in row_pattern.finditer(body):
        label = _plain_html(match.group("label"))
        normalized = _normalize_text(label)
        if normalized not in allowed_labels:
            continue
        href = unescape(match.group("href"))
        if "upl_pck2015" not in href and "proiecte" not in href and ".pdf" not in href.lower():
            continue
        documents.append({"label": label, "url": urljoin(str(source.url), href)})
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for document in documents:
        key = (document["label"], document["url"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(document)
    return unique[:25]


def _infer_event_chamber(action: str) -> str | None:
    normalized = _normalize_text(action)
    if "senat" in normalized:
        return "Senat"
    if "camera deputatilor" in normalized or "camerei deputatilor" in normalized:
        return "Camera Deputatilor"
    if "guvern" in normalized:
        return "Guvern"
    return None


def _event_chamber_from_marker(value: str | None) -> str | None:
    normalized = _normalize_text(value)
    if normalized == "se":
        return "Senat"
    if normalized == "cd":
        return "Camera Deputatilor"
    return None


def _project_events(source: SourceConfig, body: str, project_url: str) -> list[dict[str, Any]]:
    marker = re.search(r"Derularea\s+procedurii\s+legislative", body, re.IGNORECASE)
    if not marker:
        return []
    section = body[marker.start():]
    stop = re.search(r"(?:</table>\s*){2,}", section, re.IGNORECASE)
    if stop:
        section = section[: stop.end()]

    row_pattern = re.compile(
        r"<tr[^>]*>[\s\S]*?(?P<date>\d{2}\.\d{2}\.\d{4})[\s\S]*?</tr>",
        re.IGNORECASE,
    )
    fallback_pattern = re.compile(r"(?P<date>\d{2}\.\d{2}\.\d{4})(?P<action>[\s\S]{1,2500}?)(?=\d{2}\.\d{2}\.\d{4}|$)")
    matches = list(row_pattern.finditer(section)) or list(fallback_pattern.finditer(section))
    events: list[dict[str, Any]] = []
    current_chamber: str | None = None

    for match in matches:
        try:
            event_date = datetime.strptime(match.group("date"), "%d.%m.%Y").date()
        except ValueError:
            continue
        row_html = match.group(0)
        raw_cells = re.findall(r"<td[^>]*>([\s\S]*?)</td>", row_html, flags=re.IGNORECASE)
        plain_cells = [_plain_html(cell) for cell in raw_cells]
        date_indexes = [index for index, cell in enumerate(plain_cells) if cell == match.group("date")]
        start_index = date_indexes[-1] + 1 if date_indexes else 0
        marker = next((cell for cell in plain_cells if _normalize_text(cell) in {"se", "cd"}), None)
        action_cells = [
            cell
            for cell in plain_cells[start_index:]
            if cell
            and cell != match.group("date")
            and _normalize_text(cell) not in {"data", "actiunea", "actiune", "se", "cd"}
        ]
        raw_action = " ".join(raw_cells[start_index:]) if date_indexes else row_html.replace(match.group("date"), " ", 1)
        action = " ".join(action_cells) if action_cells else _plain_html(raw_action)
        action = re.sub(r"^(?:SE|CD)\s+", "", action, flags=re.IGNORECASE).strip()
        action = re.sub(rf"^{re.escape(match.group('date'))}\s+", "", action).strip()
        action = re.sub(r"^(Data|Actiunea|Acțiunea)\s+", "", action, flags=re.IGNORECASE).strip()
        action = re.sub(r"\s*(?:SE|CD)\s*$", "", action).strip()
        if not action or _normalize_text(action) in {"data actiunea", "actiunea"}:
            continue
        links = [
            {"url": urljoin(str(source.url), unescape(href))}
            for href in re.findall(r'href=["\'](?P<href>[^"\']+)["\']', raw_action, flags=re.IGNORECASE)
        ]
        marker_chamber = _event_chamber_from_marker(marker)
        inferred_chamber = _infer_event_chamber(action)
        event_chamber = marker_chamber or inferred_chamber or current_chamber
        if event_chamber in {"Senat", "Camera Deputatilor"}:
            current_chamber = event_chamber
        events.append(
            {
                "date": event_date.isoformat(),
                "action": action,
                "chamber": event_chamber,
                "source_site": "cdep",
                "source_url": project_url,
                "documents": links[:10],
            }
        )

    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for event in events:
        key = (event["date"], event["action"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


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
    if normalized.startswith("sos"):
        return "sos"
    if "minor" in normalized:
        return "minoritati"
    if "neafili" in normalized or "independent" in normalized:
        return "neafiliati"
    return normalized.replace(" ", "_")


def _politician_key(family_name: str | None, given_name: str | None) -> str:
    slug = _normalize_text(f"{family_name or ''} {given_name or ''}").replace(" ", "_")
    return f"ro-parliament:{slug}" if slug else "ro-parliament:unknown"


def _normalize_vote_choice(value: str | None) -> str:
    normalized = _normalize_text(value)
    if normalized == "da":
        return "yes"
    if normalized == "nu":
        return "no"
    if normalized in {"ab", "abtineri", "abtinere"}:
        return "abstain"
    if normalized in {"", "-", "nu au votat"}:
        return "not_voted"
    return normalized or "unknown"


def _project_context_from_url(source: SourceConfig, url: str, session: requests.Session, headers: dict[str, str]) -> dict[str, Any]:
    response = session.get(url, timeout=30, headers=headers)
    response.raise_for_status()
    response.encoding = source.config.get("html_encoding", "utf-8")
    body = response.text
    text = _plain_html(body)
    title = None
    label_matches = list(re.finditer(r"\b(?:PL-x|Pl-x|PH\s+CD)(?:\s+nr\.)?\s*\d+\s*/\s*\d{4}", text, re.IGNORECASE))
    if label_matches:
        match = label_matches[-1]
        title = _between(text[match.start():], match.group(0), ["Nr. înregistrare:", "Nr. inregistrare:"])

    urgency_text = _between(text, "Procedura de urgenta:", ["Stadiu:", "Iniţiator:", "Initiator:", "Consultati:"])
    return {
        "source_site": "cdep",
        "source_url": url,
        "title": title,
        "procedure": _between(text, "Procedura legislativa:", ["Camera decizionala:", "Termen adoptare:", "Tip initiativa:"]),
        "decisional_chamber": _between(text, "Camera decizionala:", ["Termen adoptare:", "Data la care", "Tip initiativa:"]),
        "initiative_type": _between(text, "Tip initiativa:", ["Caracter:", "Procedura de urgenta:", "Stadiu:"]),
        "urgency": urgency_text,
        "urgency_text": urgency_text,
        "stage": _between(text, "Stadiu:", ["Iniţiator:", "Initiator:", "Consultati:", "Derularea procedurii legislative"]),
        "initiators": [
            value
            for value in [
                _between(text, "Initiator:", ["Consultati:", "Derularea procedurii legislative"]),
                _between(text, "Iniţiator:", ["Consultati:", "Derularea procedurii legislative"]),
            ]
            if value
        ],
        "registration_numbers": _registration_numbers(text),
        "documents": _project_documents(source, body),
        "events": _project_events(source, body, url),
        "metadata": {
            "source": "cdep_project_page",
            "fetched_at": datetime.now(_BUCHAREST_TZ).isoformat(),
        },
    }


def _project_contexts(source: SourceConfig, project_keys: set[tuple[int, int]], session: requests.Session, headers: dict[str, str]) -> dict[tuple[int, int], dict[str, Any]]:
    links: dict[tuple[int, int], str] = {}
    base = _endpoint(source, "/ords/pls/proiecte/upl_pck2015.lista")
    for year in {key[1] for key in project_keys}:
        url = f"{base}?cam=2&anp={year}"
        response = session.get(url, timeout=30, headers=headers)
        response.raise_for_status()
        response.encoding = source.config.get("html_encoding", "utf-8")
        body = response.text
        for match in re.finditer(
            r'href="(?P<href>[^"]*upl_pck2015\.proiect\?cam=2&amp;idp=\d+|[^"]*upl_pck2015\.proiect\?cam=2&idp=\d+)">(?:PL-x|Pl-x)\s+(?P<number>\d+)/\d{2}\.\d{2}\.(?P<year>\d{4})',
            body,
        ):
            href = match.group("href").replace("&amp;", "&")
            key = (int(match.group("number")), int(match.group("year")))
            if key in project_keys:
                links[key] = urljoin(str(source.url), href)
    contexts: dict[tuple[int, int], dict[str, Any]] = {}
    for key, url in links.items():
        try:
            contexts[key] = _project_context_from_url(source, url, session, headers)
        except Exception:
            contexts[key] = {"source_site": "cdep", "source_url": url}
    return contexts


def _positions_for_vote(
    source: SourceConfig,
    vote_id: str,
    session: requests.Session,
    headers: dict[str, str],
) -> tuple[list[dict[str, Any]], int, int]:
    url = f"{_endpoint(source, '/ords/pls/steno/evot2015.xml')}?par1=2&par2={vote_id}"
    root, status, size = _get_xml(session, url, headers, encoding=str(source.config.get("xml_encoding", "utf-8")))
    positions: list[dict[str, Any]] = []
    for row in root.findall("ROW"):
        family_name = _text(row, "NUME")
        given_name = _text(row, "PRENUME")
        party = _text(row, "GRUP")
        vote_choice = _normalize_vote_choice(_text(row, "VOT"))
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
                "vote_choice": vote_choice,
                "chamber": "Camera Deputatilor",
                "politician_metadata": {
                    "source": "cdep",
                    "chambers_seen": ["Camera Deputatilor"],
                },
            }
        )
    return positions, status, size


def fetch_cdep_final_votes(source: SourceConfig) -> tuple[list[NormalizedItem], list[QuarantineCandidate], int, int]:
    headers = {
        "User-Agent": source.config.get("user_agent", "tresor-index/0.1 civic public-data collector"),
        "Accept": "application/xml,text/xml,text/html;q=0.8,*/*;q=0.5",
    }
    request_delay_seconds = max(0.0, _float_config(source, "request_delay_seconds", 0.3))
    final_only = bool(source.config.get("final_only", True))
    max_votes = _int_config(source, "max_votes", 200)
    xml_encoding = str(source.config.get("xml_encoding", "utf-8"))

    session = requests.Session()
    session.verify = bool(source.config.get("verify_tls", True))
    if not session.verify:
        urllib3.disable_warnings(InsecureRequestWarning)
    rows: list[tuple[date, ElementTree.Element]] = []
    rejected: list[QuarantineCandidate] = []
    total_bytes = 0
    last_status = 0

    for day in _date_range(source):
        url = f"{_endpoint(source, '/ords/pls/steno/evot2015.xml')}?par1=1&par2={day:%Y%m%d}"
        try:
            root, status, size = _get_xml(session, url, headers, encoding=xml_encoding, allow_empty=True)
        except Exception as exc:
            rejected.append(QuarantineCandidate(reason=f"failed to fetch vote list for {day}: {exc}", payload={"date": str(day), "url": url}))
            continue
        total_bytes += size
        last_status = status
        rows.extend((day, row) for row in root.findall("ROW"))
        if request_delay_seconds:
            time.sleep(request_delay_seconds)

    candidate_votes: list[dict[str, Any]] = []
    project_keys: set[tuple[int, int]] = set()
    for day, row in rows:
        title = _text(row, "DESCRIERE") or ""
        if final_only and "vot final" not in _normalize_text(title):
            continue
        bill = _bill_from_title(title)
        if bill.get("code") == "PL-x" and bill.get("year"):
            project_keys.add((int(bill["number"]), int(bill["year"])))
        candidate_votes.append(
            {
                "day": day,
                "vote_id": str(_int_text(row, "VOTID") or _text(row, "VOTID") or ""),
                "title": title,
                "vote_time": _parse_vote_time(_text(row, "TIME_VOT"), day),
                "bill": bill,
                "counts": {
                    "present": _int_text(row, "PREZENTI"),
                    "yes": _int_text(row, "AU_VOTAT_DA"),
                    "no": _int_text(row, "AU_VOTAT_NU"),
                    "abstain": _int_text(row, "AU_VOTAT_AB"),
                    "not_voted": _int_text(row, "NU_AU_VOTAT"),
                },
            }
        )

    project_contexts = _project_contexts(source, project_keys, session, headers) if project_keys else {}
    items: list[NormalizedItem] = []
    seen_vote_ids: set[str] = set()

    for vote in sorted(candidate_votes, key=lambda item: item["vote_time"], reverse=True)[:max_votes]:
        vote_id = vote["vote_id"]
        if not vote_id or vote_id in seen_vote_ids:
            continue
        seen_vote_ids.add(vote_id)
        try:
            positions, status, size = _positions_for_vote(source, vote_id, session, headers)
            total_bytes += size
            last_status = status
            if request_delay_seconds:
                time.sleep(request_delay_seconds)
        except Exception as exc:
            rejected.append(QuarantineCandidate(reason=f"failed to fetch nominal vote {vote_id}: {exc}", payload={"vote_id": vote_id}))
            positions = []

        bill = vote["bill"]
        if bill.get("code") == "PL-x":
            context = project_contexts.get((int(bill["number"]), int(bill["year"])))
            if context:
                bill["url"] = context.get("source_url")
                bill["context"] = context

        counts = vote["counts"]
        nominal_url = f"{_endpoint(source, '/ords/pls/steno/evot2015.nominal')}?idv={vote_id}&idl=1"
        metadata = {
            "site": "cdep",
            "vote": {
                "id": vote_id,
                "chamber": "Camera Deputatilor",
                "kind": _vote_kind(vote["title"]),
                "outcome": _outcome(vote["title"], counts.get("yes"), counts.get("no")),
            },
            "bill": bill,
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
                    canonical_url=nominal_url,
                    external_id=vote_id,
                    description=f"{counts.get('yes') or 0} yes, {counts.get('no') or 0} no, {counts.get('abstain') or 0} abstain",
                    published_at=vote["vote_time"],
                    metadata=metadata,
                )
            )
        except ValidationError as exc:
            rejected.append(QuarantineCandidate(reason=str(exc), payload=metadata))

    return items, rejected, last_status, total_bytes
