#!/usr/bin/env python3
"""
Watch a Resident Advisor artist page and send Discord alerts for new events.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
DISCORD_WEBHOOK_RE = re.compile(r"^https://discord(?:app)?\.com/api/webhooks/.+")


@dataclass(frozen=True)
class RaEvent:
    event_id: str
    title: str
    location: str
    date_label: str
    url: str


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name)
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


def log(message: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def sanitize_text(value: str, max_len: int) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    value = "".join(ch for ch in value if ch >= " ")
    return value[: max_len - 1] + "." if len(value) > max_len else value


def fetch_text(url: str, timeout_s: int, user_agent: str) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urlopen(req, timeout=timeout_s) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def load_next_data(page_html: str) -> dict[str, Any]:
    match = NEXT_DATA_RE.search(page_html)
    if not match:
        raise RuntimeError("RA page did not contain __NEXT_DATA__")
    return json.loads(html.unescape(match.group(1)))


def deref(state: dict[str, Any], ref: Any) -> dict[str, Any]:
    if isinstance(ref, dict) and isinstance(ref.get("__ref"), str):
        target = state.get(ref["__ref"])
        return target if isinstance(target, dict) else {}
    return ref if isinstance(ref, dict) else {}


def parse_date_label(raw_date: str, raw_start_time: str) -> str:
    raw = raw_start_time or raw_date
    if not raw:
        return "Date TBA"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:10]

    has_time = bool(raw_start_time) and not (dt.hour == 0 and dt.minute == 0)
    date_part = dt.strftime("%a, %-d %b %Y") if os.name != "nt" else dt.strftime("%a, %#d %b %Y")
    return f"{date_part}, {dt.strftime('%H:%M')}" if has_time else date_part


def is_upcoming(raw_date: str) -> bool:
    if not raw_date:
        return True
    try:
        event_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).date()
    except ValueError:
        return True
    return event_date >= datetime.now().date()


def event_location(state: dict[str, Any], event: dict[str, Any]) -> str:
    venue = deref(state, event.get("venue"))
    area = deref(state, venue.get("area"))

    venue_name = sanitize_text(venue.get("name") or "", 120)
    area_name = sanitize_text(area.get("name") or "", 80)
    if venue_name and area_name:
        return f"{venue_name}, {area_name}"
    return venue_name or area_name or "Location TBA"


def parse_events(page_html: str, base_url: str) -> list[RaEvent]:
    data = load_next_data(page_html)
    state = data.get("props", {}).get("apolloState")
    if not isinstance(state, dict):
        raise RuntimeError("RA page did not contain Apollo state")

    events: list[RaEvent] = []
    seen: set[str] = set()
    for value in state.values():
        if not isinstance(value, dict) or value.get("__typename") != "Event":
            continue
        event_id = str(value.get("id") or "").strip()
        title = sanitize_text(value.get("title") or "", 240)
        content_url = value.get("contentUrl") or ""
        raw_date = value.get("date") or ""
        if not event_id or not title or not content_url or event_id in seen:
            continue
        if not is_upcoming(raw_date):
            continue

        seen.add(event_id)
        events.append(
            RaEvent(
                event_id=event_id,
                title=title,
                location=event_location(state, value),
                date_label=parse_date_label(raw_date, value.get("startTime") or ""),
                url=urljoin(base_url, content_url),
            )
        )

    events.sort(key=lambda item: (item.date_label, item.event_id))
    return events


def load_state(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def save_state(path: Path, seen_event_ids: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "seen_event_ids": sorted(seen_event_ids),
    }
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.write("\n")
        os.chmod(tmp_name, 0o640)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def discord_payload(artist_name: str, event: RaEvent) -> dict[str, Any]:
    content = (
        f"Hey, {artist_name} has a new event announced:\n"
        f"**{event.title}**\n"
        f"Location: {event.location}\n"
        f"Date: {event.date_label}\n"
        f"Tickets / RA link: {event.url}"
    )
    payload: dict[str, Any] = {
        "username": env("RA_ARTIST_NOTIFIER_DISCORD_USERNAME", "RA Event Watcher"),
        "content": content[:1900],
        "allowed_mentions": {"parse": []},
    }
    avatar_url = env("RA_ARTIST_NOTIFIER_DISCORD_AVATAR_URL")
    if avatar_url:
        payload["avatar_url"] = avatar_url
    return payload


def post_discord(webhook_url: str, payload: dict[str, Any], timeout_s: int) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "tresor-ra-artist-notifier/1.0"},
        method="POST",
    )
    with urlopen(req, timeout=timeout_s) as resp:
        if resp.status not in (200, 204):
            body = resp.read(300).decode("utf-8", errors="replace")
            raise RuntimeError(f"Discord webhook failed: HTTP {resp.status} - {body}")


def run_once(dry_run: bool = False) -> int:
    artist_name = env("RA_ARTIST_NOTIFIER_ARTIST_NAME", "Helena Hauff")
    artist_url = env("RA_ARTIST_NOTIFIER_ARTIST_URL", "https://ra.co/dj/helenahauff")
    webhook_url = env("RA_ARTIST_NOTIFIER_WEBHOOK_URL")
    state_file = Path(env("RA_ARTIST_NOTIFIER_STATE_FILE", "/tmp/ra-artist-notifier-state.json"))
    timeout_s = env_int("RA_ARTIST_NOTIFIER_REQUEST_TIMEOUT_SECONDS", 20)
    user_agent = env("RA_ARTIST_NOTIFIER_USER_AGENT", "tresor-ra-artist-notifier/1.0")
    notify_first_run = env_bool("RA_ARTIST_NOTIFIER_NOTIFY_FIRST_RUN", False)

    if not dry_run and not DISCORD_WEBHOOK_RE.match(webhook_url):
        log("RA_ARTIST_NOTIFIER_WEBHOOK_URL is missing or invalid")
        return 2

    page_html = fetch_text(artist_url, timeout_s, user_agent)
    events = parse_events(page_html, "https://ra.co")
    current_ids = {event.event_id for event in events}

    state = load_state(state_file)
    previous_ids = set(str(item) for item in state.get("seen_event_ids", []) if item)
    first_run = not previous_ids
    new_events = events if (first_run and notify_first_run) else [event for event in events if event.event_id not in previous_ids]
    if first_run and not notify_first_run:
        new_events = []

    log(f"found {len(events)} upcoming RA events for {artist_name}; new={len(new_events)}")
    for event in new_events:
        if dry_run:
            print(json.dumps(event.__dict__, ensure_ascii=False))
            continue
        post_discord(webhook_url, discord_payload(artist_name, event), timeout_s)
        log(f"notified event {event.event_id}: {event.title}")
        time.sleep(1)

    if not dry_run:
        save_state(state_file, previous_ids | current_ids)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Fetch and print new events without posting Discord or saving state")
    args = parser.parse_args()
    try:
        return run_once(dry_run=args.dry_run)
    except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
        log(f"error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
