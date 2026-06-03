#!/usr/bin/env python3
"""
Follow Paper's latest.log and send Discord webhook notifications for player joins.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


JOIN_RE = re.compile(r"\b(?P<player>[A-Za-z0-9_]{1,16}) joined the game\b")
DISCORD_WEBHOOK_RE = re.compile(r"^https://discord(?:app)?\.com/api/webhooks/.+")
RUNNING = True


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    val = env(name)
    if not val:
        return default
    return val.lower() in {"1", "true", "yes", "on"}


def env_float(name: str, default: float) -> float:
    try:
        return float(env(name, str(default)))
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


def log(message: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def handle_signal(signum: int, _frame: object) -> None:
    global RUNNING
    RUNNING = False
    log(f"received signal {signum}, stopping")


def sanitize_text(value: str, max_len: int) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    value = "".join(ch for ch in value if ch >= " ")
    return value[: max_len - 1] + "." if len(value) > max_len else value


def discord_payload(player: str) -> dict:
    server_name = sanitize_text(env("PAPER_JOIN_NOTIFIER_SERVER_NAME", "Tresor Minecraft Server"), 80)
    username = sanitize_text(env("PAPER_JOIN_NOTIFIER_DISCORD_USERNAME", server_name), 80)
    avatar_url = env("PAPER_JOIN_NOTIFIER_DISCORD_AVATAR_URL")
    color = env_int("PAPER_JOIN_NOTIFIER_EMBED_COLOR", 5763719)

    payload = {
        "username": username,
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": f"{player} joined {server_name}",
                "description": f"Player joined {server_name}.",
                "color": color,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": {"text": server_name},
            }
        ],
    }
    if avatar_url:
        payload["avatar_url"] = avatar_url
    return payload


def send_discord(webhook_url: str, player: str, timeout_s: int) -> None:
    payload = json.dumps(discord_payload(player)).encode("utf-8")
    req = Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "paper-join-notifier/1.0"},
        method="POST",
    )
    with urlopen(req, timeout=timeout_s) as resp:
        if resp.status not in (200, 204):
            body = resp.read(300).decode("utf-8", errors="replace")
            raise RuntimeError(f"Discord webhook failed: HTTP {resp.status} - {body}")


def iter_follow(path: Path, start_at_end: bool, poll_interval: float) -> Iterator[str]:
    current_inode: Optional[tuple[int, int]] = None
    fh = None

    while RUNNING:
        try:
            stat = path.stat()
        except FileNotFoundError:
            if fh:
                fh.close()
                fh = None
                current_inode = None
            time.sleep(poll_interval)
            continue

        inode = (stat.st_dev, stat.st_ino)
        if fh is None or inode != current_inode:
            if fh:
                fh.close()
            fh = path.open("r", encoding="utf-8", errors="replace")
            current_inode = inode
            if start_at_end:
                fh.seek(0, os.SEEK_END)
            log(f"following {path}")

        line = fh.readline()
        if line:
            yield line.rstrip("\r\n")
            continue

        time.sleep(poll_interval)

    if fh:
        fh.close()


def extract_join_player(line: str) -> Optional[str]:
    match = JOIN_RE.search(line)
    if not match:
        return None
    return match.group("player")


def run() -> int:
    webhook_url = env("PAPER_JOIN_NOTIFIER_DISCORD_WEBHOOK_URL")
    log_file = Path(env("PAPER_JOIN_NOTIFIER_LOG_FILE"))
    timeout_s = env_int("PAPER_JOIN_NOTIFIER_REQUEST_TIMEOUT_SECONDS", 10)
    poll_interval = env_float("PAPER_JOIN_NOTIFIER_POLL_INTERVAL_SECONDS", 1.0)
    start_at_end = env_bool("PAPER_JOIN_NOTIFIER_START_AT_END", True)
    debug = env_bool("PAPER_JOIN_NOTIFIER_DEBUG", False)

    if not webhook_url or not DISCORD_WEBHOOK_RE.match(webhook_url):
        log("PAPER_JOIN_NOTIFIER_DISCORD_WEBHOOK_URL is missing or invalid")
        return 2
    if not str(log_file):
        log("PAPER_JOIN_NOTIFIER_LOG_FILE is missing")
        return 2

    log(f"watching joins in {log_file}")
    for line in iter_follow(log_file, start_at_end=start_at_end, poll_interval=poll_interval):
        player = extract_join_player(line)
        if not player:
            if debug:
                log(f"ignored: {line}")
            continue

        try:
            send_discord(webhook_url, player, timeout_s)
            log(f"notified join: {player}")
        except HTTPError as exc:
            body = exc.read(300).decode("utf-8", errors="replace")
            log(f"Discord webhook failed: HTTP {exc.code} - {body}")
        except (URLError, TimeoutError, RuntimeError) as exc:
            log(f"Discord webhook failed: {exc}")

    return 0


def test_line(line: str) -> int:
    player = extract_join_player(line)
    if player:
        print(player)
        return 0
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-line", help="Parse one log line and print the detected player")
    args = parser.parse_args()

    if args.test_line is not None:
        return test_line(args.test_line)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    return run()


if __name__ == "__main__":
    sys.exit(main())
