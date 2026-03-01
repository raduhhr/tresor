#!/usr/bin/env python3
"""
content-notifier
- Scans configured media roots (top-level dirs only)
- Sends Discord webhook when a new top-level folder appears
- Persists state in JSON (atomic write)
- Designed for cron execution
"""

from __future__ import annotations

import json
import os
import sys
import time
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any, Tuple

try:
    import requests
except ImportError:
    print("Missing dependency: requests", file=sys.stderr)
    sys.exit(1)


# ----------------------------
# Helpers
# ----------------------------

def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _json_env(name: str, default: Any) -> Any:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _now() -> int:
    return int(time.time())


def _safe_print(msg: str) -> None:
    # Cron-safe logging to stdout/stderr file
    print(msg, flush=True)


def _truncate(s: str, max_len: int) -> str:
    if max_len <= 1:
        return s[:max_len]
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def _normalize_key(label: str, folder_name: str) -> str:
    return f"{label}::{folder_name}"


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".content-notifier-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            pass


def _load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"version": 1, "items": {}}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("state root is not object")
        if "items" not in data or not isinstance(data["items"], dict):
            data["items"] = {}
        if "version" not in data:
            data["version"] = 1
        return data
    except Exception as e:
        _safe_print(f"[WARN] Failed to read state ({path}): {e}; starting with empty state")
        return {"version": 1, "items": {}}


def _sanitize_discord_text(s: str) -> str:
    # Prevent accidental mentions and weird formatting surprises.
    # Discord supports allowed_mentions too (we use it), but sanitize anyway.
    replacements = {
        "@everyone": "@\u200beveryone",
        "@here": "@\u200bhere",
    }
    for a, b in replacements.items():
        s = s.replace(a, b)
    return s


def _looks_ignored(name: str, ignore_hidden: bool, ignore_names: set[str], ignore_contains: List[str]) -> bool:
    if not name:
        return True
    if ignore_hidden and name.startswith("."):
        return True
    if name in ignore_names:
        return True

    lower = name.lower()
    for frag in ignore_contains:
        if frag and frag.lower() in lower:
            return True
    return False


@dataclass
class MonitoredRoot:
    label: str
    path: Path


def _parse_roots(raw: Any) -> List[MonitoredRoot]:
    roots: List[MonitoredRoot] = []
    if not isinstance(raw, list):
        return roots
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        path = str(item.get("path", "")).strip()
        if not label or not path:
            continue
        roots.append(MonitoredRoot(label=label, path=Path(path)))
    return roots


def _list_new_top_level_folders(
    root: MonitoredRoot,
    state_items: Dict[str, Dict[str, Any]],
    min_age_seconds: int,
    ignore_hidden: bool,
    ignore_names: set[str],
    ignore_contains: List[str],
    debug: bool = False,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Returns (notifications_to_send, seen_count)
    Adds entries to state for newly observed folders, but only returns notifications
    for folders older than min_age_seconds and not yet notified.
    """
    notifications: List[Dict[str, Any]] = []
    seen_count = 0
    now_ts = _now()

    try:
        entries = list(root.path.iterdir())
    except Exception as e:
        raise RuntimeError(f"Cannot read monitored root {root.path}: {e}") from e

    for entry in entries:
        name = entry.name
        if _looks_ignored(name, ignore_hidden, ignore_names, ignore_contains):
            if debug:
                _safe_print(f"[DEBUG] ignored: {root.label}/{name}")
            continue

        try:
            if not entry.is_dir():
                continue
        except OSError:
            continue

        seen_count += 1
        key = _normalize_key(root.label, name)

        try:
            st = entry.stat()
            mtime = int(st.st_mtime)
        except OSError:
            mtime = now_ts

        # IMPORTANT: must fetch current state item before branching
        item = state_items.get(key)

        if item is None:
            item = {
                "label": root.label,
                "folder_name": name,
                "path": str(entry),
                "first_seen": now_ts,
                "last_seen": now_ts,
                "mtime": mtime,
                # Bootstrap existing folders as already known to avoid first-run spam
                "notified_at": None,
            }
            state_items[key] = item
            if debug:
                _safe_print(f"[DEBUG] first seen: {root.label}/{name}")

        else:
            # keep state current if folder moved/renamed weirdly under same key impossible,
            # but update timestamps anyway
            item["last_seen"] = now_ts
            item["mtime"] = mtime
            item["path"] = str(entry)

        # Notification rule: not notified yet + directory older than settle window
        if item.get("notified_at") is None:
            age = max(0, now_ts - mtime)
            if age >= min_age_seconds:
                notifications.append(
                    {
                        "key": key,
                        "label": root.label,
                        "folder_name": name,
                        "path": str(entry),
                        "age_seconds": age,
                    }
                )
            elif debug:
                _safe_print(f"[DEBUG] not settled yet ({age}s<{min_age_seconds}s): {root.label}/{name}")

    return notifications, seen_count


def _build_message(prefix: str, label: str, folder_name: str, max_len: int) -> str:
    # Example: New content added (Movies): Dune Part Two (2024)
    text = f"{prefix} ({label}): {folder_name}"
    text = _sanitize_discord_text(text)
    return _truncate(text, max_len)


def _send_discord(webhook_url: str, message: str, timeout_s: int) -> None:
    payload = {
        "content": message,
        "allowed_mentions": {"parse": []},  # no @everyone/@here/user mentions
    }
    resp = requests.post(webhook_url, json=payload, timeout=timeout_s)
    # Discord webhooks often return 204 No Content on success
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"Discord webhook failed: HTTP {resp.status_code} - {resp.text[:300]}")


def main() -> int:
    webhook_url = (_env("CONTENT_NOTIFIER_WEBHOOK_URL") or "").strip()
    state_file = Path((_env("CONTENT_NOTIFIER_STATE_FILE") or "/tmp/content-notifier-state.json").strip())
    _ = _env("CONTENT_NOTIFIER_LOG_FILE")  # currently just inherited via cron redirect

    min_age_seconds = _env_int("CONTENT_NOTIFIER_MIN_AGE_SECONDS", 180)
    request_timeout_seconds = _env_int("CONTENT_NOTIFIER_REQUEST_TIMEOUT_SECONDS", 10)
    max_message_len = _env_int("CONTENT_NOTIFIER_MAX_MESSAGE_LEN", 1900)
    debug = _env_bool("CONTENT_NOTIFIER_DEBUG", False)
    message_prefix = (_env("CONTENT_NOTIFIER_MESSAGE_PREFIX", "New content added") or "New content added").strip()

    ignore_hidden = _env_bool("CONTENT_NOTIFIER_IGNORE_HIDDEN", True)
    ignore_names = set(_json_env("CONTENT_NOTIFIER_IGNORE_NAMES_JSON", []))
    ignore_contains = list(_json_env("CONTENT_NOTIFIER_IGNORE_NAME_CONTAINS_JSON", []))
    roots = _parse_roots(_json_env("CONTENT_NOTIFIER_PATHS_JSON", []))

    if not webhook_url:
        _safe_print("[ERROR] CONTENT_NOTIFIER_WEBHOOK_URL is missing")
        return 2
    if not roots:
        _safe_print("[ERROR] No monitored roots configured (CONTENT_NOTIFIER_PATHS_JSON)")
        return 2

    # Basic safety guard to avoid accidental arbitrary path scanning if misconfigured later.
    # Adjust if you ever intentionally monitor outside this parent.
    approved_parent = Path("/mnt/data/files")
    for root in roots:
        try:
            resolved = root.path.resolve()
        except Exception:
            resolved = root.path
        if approved_parent not in resolved.parents and resolved != approved_parent:
            _safe_print(f"[ERROR] Refusing to monitor path outside approved parent {approved_parent}: {root.path}")
            return 2

    state = _load_state(state_file)
    items: Dict[str, Dict[str, Any]] = state.setdefault("items", {})

    pending_notifications: List[Dict[str, Any]] = []
    total_seen = 0

    try:
        for root in roots:
            if debug:
                _safe_print(f"[DEBUG] scanning {root.label} -> {root.path}")
            notifications, seen_count = _list_new_top_level_folders(
                root=root,
                state_items=items,
                min_age_seconds=min_age_seconds,
                ignore_hidden=ignore_hidden,
                ignore_names=ignore_names,
                ignore_contains=ignore_contains,
                debug=debug,
            )
            total_seen += seen_count
            pending_notifications.extend(notifications)
    except Exception as e:
        _safe_print(f"[ERROR] Scan failed: {e}")
        # Save state anyway in case some folders were first-seen before the failure
        _atomic_write_json(state_file, state)
        return 1

    # Deterministic order keeps logs predictable
    pending_notifications.sort(key=lambda x: (x["label"], x["folder_name"].lower()))

    sent = 0
    for item in pending_notifications:
        msg = _build_message(
            prefix=message_prefix,
            label=item["label"],
            folder_name=item["folder_name"],
            max_len=max_message_len,
        )
        try:
            _send_discord(webhook_url, msg, timeout_s=request_timeout_seconds)
            sent += 1
            state["items"][item["key"]]["notified_at"] = _now()
            if debug:
                _safe_print(f"[DEBUG] notified: {msg}")
        except Exception as e:
            _safe_print(f"[ERROR] Notify failed for {item['key']}: {e}")
            # Continue to next item; do not mark notified.
            # This preserves retry behavior on next cron run.

    _atomic_write_json(state_file, state)
    _safe_print(f"[INFO] scan complete: roots={len(roots)} seen={total_seen} pending={len(pending_notifications)} sent={sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())