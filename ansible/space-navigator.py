#!/usr/bin/env python3
"""
space-navigator - Satelite Watcher operator cockpit
Run from: the ansible/ directory
Requires: pip install rich questionary paramiko --break-system-packages
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

try:
    import paramiko
    import questionary
    from questionary import Choice, Style
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError:
    print("Missing deps. Run:")
    print("  pip install rich questionary paramiko --break-system-packages")
    sys.exit(1)


INVENTORY = "inventory/hosts.ini"
ANSIBLE_CMD = "ansible-playbook"
STATUS_PLAYBOOK = "playbooks/satelite-watcher/status.yml"
TARGET_HOST = "tresor"
SSH_USER = "ansible"

C_BG = "#111827"
C_PANEL = "#1f2937"
C_BORDER = "#38bdf8"
C_ACCENT = "#22d3ee"
C_GREEN = "#34d399"
C_YELLOW = "#fbbf24"
C_RED = "#fb7185"
C_DIM = "#94a3b8"
C_TEXT = "#e5e7eb"
C_MUTED = "#cbd5e1"
C_METEOR = "#a78bfa"
C_NOAA = "#60a5fa"
C_ISS = "#fbbf24"
C_BLUE = "#93c5fd"

PROFILE_COLOR = {
    "meteor_lrpt": C_METEOR,
    "noaa_apt": C_NOAA,
    "iss_sstv": C_ISS,
}

RUN_BOARD_LIMIT = 64
PASS_CONTEXT_LIMIT = 16
HIGH_PASS_MIN_ELEVATION = 30.0

SPACE_ART = r"""
     .--------------.
  .-'  o   O   .   `-.
.'   @@@@     .       `.
`.      .      o     .'
  `-.       .      .-'
     `------------'

   .       ______
      .   ///////
        .//____/\   .
         ||   | |\
         \\__./ //
"""

console = Console()
_ssh_clients: Dict[Tuple[str, str, str], paramiko.SSHClient] = {}
_last_ssh_error: Optional[str] = None
_display_timezone = "Europe/Bucharest"
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


Q_STYLE = Style(
    [
        ("qmark", "fg:#000000"),
        ("question", f"fg:{C_TEXT} bold"),
        ("answer", f"fg:{C_ACCENT} bold"),
        ("pointer", f"fg:{C_ACCENT} bold"),
        ("highlighted", f"fg:{C_TEXT} bg:{C_PANEL} bold"),
        ("selected", f"fg:{C_ACCENT}"),
        ("separator", f"fg:{C_DIM}"),
        ("instruction", "fg:#000000"),
        ("bottom-toolbar", f"fg:{C_BG} bg:{C_BG}"),
        ("text", f"fg:{C_TEXT}"),
    ]
)


def _bye(*_: Any) -> None:
    console.print(f"\n  [{C_DIM}]space-navigator closed[/{C_DIM}]\n")
    close_ssh_clients()
    sys.exit(0)


signal.signal(signal.SIGINT, _bye)
if hasattr(signal, "SIGTSTP"):
    signal.signal(signal.SIGTSTP, _bye)


def close_ssh_clients() -> None:
    for client in list(_ssh_clients.values()):
        try:
            client.close()
        except Exception:
            pass
    _ssh_clients.clear()


def inventory_hosts() -> Dict[str, Dict[str, Any]]:
    hosts: Dict[str, Dict[str, Any]] = {}
    current_group: Optional[str] = None
    with open(INVENTORY, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_group = line.strip("[]")
                continue
            if current_group and current_group.endswith(":vars"):
                continue
            parts = line.split()
            name = parts[0]
            data: Dict[str, Any] = {"group": current_group}
            for part in parts[1:]:
                if "=" in part:
                    key, value = part.split("=", 1)
                    data[key] = value
            hosts[name] = data
    return hosts


def inventory_var(section_header: str, key: str, fallback: str = "") -> str:
    try:
        with open(INVENTORY, encoding="utf-8") as handle:
            in_section = False
            for raw in handle:
                line = raw.strip()
                if line == section_header:
                    in_section = True
                    continue
                if in_section and line.startswith("["):
                    break
                if in_section and line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except Exception:
        pass
    return fallback


def target_ip() -> str:
    hosts = inventory_hosts()
    return hosts.get(TARGET_HOST, {}).get("ansible_host", TARGET_HOST)


def ssh_key() -> str:
    return os.path.expanduser(
        inventory_var("[all:vars]", "ansible_ssh_private_key_file", "~/.ssh/id_ed25519_tresor")
    )


def get_ssh(host: str, user: str, key: str) -> paramiko.SSHClient:
    key_path = os.path.expanduser(key)
    cache_key = (host, user, key_path)
    existing = _ssh_clients.get(cache_key)
    if existing:
        transport = existing.get_transport()
        if transport and transport.is_active():
            return existing

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=user, timeout=8, allow_agent=True, look_for_keys=True)
    except Exception:
        client.connect(
            host,
            username=user,
            key_filename=key_path,
            timeout=8,
            allow_agent=False,
            look_for_keys=False,
        )
    _ssh_clients[cache_key] = client
    return client


def ssh_run(host: str, user: str, key: str, script: str, timeout: int = 20) -> str:
    global _last_ssh_error
    _last_ssh_error = None
    key_path = os.path.expanduser(key)

    try:
        proc = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=8",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-i",
                key_path,
                f"{user}@{host}",
                "bash -s",
            ],
            input=script,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
        _last_ssh_error = (proc.stderr or f"ssh exited rc={proc.returncode}").strip().splitlines()[-1]
    except FileNotFoundError:
        _last_ssh_error = "ssh client not found"
    except subprocess.TimeoutExpired:
        _last_ssh_error = "ssh probe timed out"
    except Exception as exc:
        _last_ssh_error = f"{type(exc).__name__}: {exc}"

    try:
        stdin, stdout, stderr = get_ssh(host, user, key_path).exec_command("bash -s", timeout=timeout)
        stdin.write(script)
        stdin.flush()
        stdin.channel.shutdown_write()
        out = stdout.read().decode(errors="replace").strip()
        err = stderr.read().decode(errors="replace").strip()
        if out:
            _last_ssh_error = None
            return out
        _last_ssh_error = err or "remote probe returned no output"
    except paramiko.ssh_exception.PasswordRequiredException:
        _last_ssh_error = f"key is passphrase-encrypted; run ssh-add {key_path}"
        close_ssh_clients()
    except Exception as exc:
        _last_ssh_error = f"{type(exc).__name__}: {exc}"
        close_ssh_clients()
    return ""


REMOTE_STATUS_SCRIPT = r"""set -euo pipefail
PYTHON_BIN="/opt/satelite-watcher/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  printf '{"ok": false, "error": "python3 not found"}\n'
  exit 0
fi

"$PYTHON_BIN" - <<'PY'
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except Exception:
    yaml = None

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

ROOT = Path("/opt/satelite-watcher")
CONFIG = ROOT / "config" / "config.yml"
SATELLITES = ROOT / "config" / "satellites.yml"
PASSES = ROOT / "state" / "passes.json"
SCHEDULED = ROOT / "state" / "scheduled.json"
METADATA_DIR = ROOT / "state" / "pass_metadata"
SCHEDULER_LOG = ROOT / "logs" / "scheduler.log"
RECORD_LOG = ROOT / "logs" / "record.log"
SATDUMP_BIN = Path("/usr/local/bin/satdump")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def load_json(path, default=None):
    if default is None:
        default = {}
    try:
        if not path or not Path(path).exists():
            return default
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def load_yaml(path):
    if not yaml or not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def run(cmd, timeout=8):
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        return {
            "rc": proc.returncode,
            "stdout": proc.stdout.splitlines(),
            "stderr": proc.stderr.splitlines(),
        }
    except Exception as exc:
        return {"rc": 255, "stdout": [], "stderr": [f"{type(exc).__name__}: {exc}"]}


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def iso_or_none(value):
    dt = parse_ts(value)
    return dt.isoformat() if dt else None


def decode_profile_for(item):
    value = item.get("decode_profile")
    if value and str(value).strip().lower() not in {"none", "null", "n/a"}:
        return str(value)
    satellite = str(item.get("satellite", item.get("name", ""))).upper()
    if satellite.startswith("NOAA-") or satellite.startswith("NOAA "):
        return "noaa_apt"
    if satellite.startswith("METEOR"):
        return "meteor_lrpt"
    if satellite == "ISS SSTV":
        return "iss_sstv"
    return "n/a"


def tail(path, lines):
    try:
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    except Exception as exc:
        return [f"{type(exc).__name__}: {exc}"]


def scan_recording_outputs(root_value):
    root = Path(root_value or "")
    result = {
        "root": str(root) if root_value else "",
        "exists": bool(root_value) and root.exists(),
        "recent_runs": [],
        "recent_images": [],
        "image_count": 0,
    }
    if not result["exists"]:
        return result

    run_dirs = {}
    images = []
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            path = Path(dirpath)
            if ".git" in path.parts:
                continue
            for filename in filenames:
                file_path = path / filename
                suffix = file_path.suffix.lower()
                try:
                    stat = file_path.stat()
                except OSError:
                    continue
                if filename == "metadata.json":
                    run_dirs[str(path)] = {
                        "path": str(path),
                        "name": path.name,
                        "mtime": stat.st_mtime,
                    }
                if suffix in IMAGE_SUFFIXES:
                    try:
                        relative_parts = file_path.relative_to(root).parts
                        run_name = relative_parts[2] if len(relative_parts) >= 3 else path.name
                    except Exception:
                        run_name = path.name
                    result["image_count"] += 1
                    images.append({
                        "path": str(file_path),
                        "name": file_path.name,
                        "run": run_name,
                        "size_bytes": stat.st_size,
                        "mtime": stat.st_mtime,
                    })
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    recent_runs = sorted(run_dirs.values(), key=lambda item: item["mtime"], reverse=True)[:12]
    recent_images = sorted(images, key=lambda item: item["mtime"], reverse=True)[:12]
    result["recent_runs"] = [
        {
            **item,
            "mtime_utc": datetime.fromtimestamp(item["mtime"], timezone.utc).isoformat(),
        }
        for item in recent_runs
    ]
    result["recent_images"] = [
        {
            **item,
            "mtime_utc": datetime.fromtimestamp(item["mtime"], timezone.utc).isoformat(),
        }
        for item in recent_images
    ]
    return result


config = load_yaml(CONFIG)
paths = config.get("paths", {})
outputs = scan_recording_outputs(paths.get("recordings_dir"))
satellites_cfg = load_yaml(SATELLITES)
passes_payload = load_json(PASSES, {"passes": []})
scheduled_payload = load_json(SCHEDULED, {"scheduled": {}})
tle_cache = load_json(paths.get("tle_cache_file"), {}) if paths.get("tle_cache_file") else {}
iss_events = load_json(paths.get("iss_sstv_events_file"), {}) if paths.get("iss_sstv_events_file") else {}
local_tz_name = config.get("timezone", "Europe/Bucharest")
local_tz = ZoneInfo(local_tz_name) if ZoneInfo else timezone.utc
now = datetime.now(timezone.utc)

passes = sorted(passes_payload.get("passes", []), key=lambda item: item.get("record_start_utc", ""))
passes_by_id = {item.get("pass_id"): item for item in passes if item.get("pass_id")}
queue = []
for pass_id, item in (scheduled_payload.get("scheduled") or {}).items():
    end_dt = parse_ts(item.get("record_end_utc"))
    if end_dt and end_dt <= now:
        continue
    enriched = dict(item)
    enriched["pass_id"] = pass_id
    if pass_id in passes_by_id:
        src = passes_by_id[pass_id]
        for key in (
            "satellite",
            "decode_profile",
            "frequency_hz",
            "record_start_utc",
            "record_end_utc",
            "aos_utc",
            "tca_utc",
            "los_utc",
            "max_elevation_deg",
            "peak_azimuth_label",
            "timeout_seconds",
        ):
            if src.get(key) is not None:
                enriched[key] = src.get(key)
    enriched["decode_profile"] = decode_profile_for(enriched)
    queue.append(enriched)
queue.sort(key=lambda item: item.get("record_start_utc", ""))

latest_record = None
failed_records = []
if METADATA_DIR.exists():
    for path in sorted(METADATA_DIR.glob("*.json")):
        payload = load_json(path, {})
        if not isinstance(payload, dict) or "stage" not in payload:
            continue
        payload["_path"] = str(path)
        payload["_sort_key"] = payload.get("ended_at") or payload.get("started_at") or payload.get("record_start_utc") or ""
        payload["decode_profile"] = decode_profile_for(payload)
        if latest_record is None or payload["_sort_key"] > latest_record.get("_sort_key", ""):
            latest_record = payload
        if payload.get("stage") == "failed":
            failed_records.append(payload)
failed_records.sort(key=lambda item: item.get("_sort_key", ""), reverse=True)

events = sorted(iss_events.get("events", []), key=lambda item: item.get("start_utc", ""))
active_iss = []
upcoming_iss = []
for event in events:
    start = parse_ts(event.get("start_utc"))
    end = parse_ts(event.get("end_utc"))
    if not start or not end:
        continue
    if start <= now <= end:
        active_iss.append(event)
    elif start > now:
        upcoming_iss.append(event)

weather_targets = satellites_cfg.get("satellites", [])
tle_names = {item.get("name") for item in tle_cache.get("satellites", []) if item.get("name")}
for target in weather_targets:
    target["decode_profile"] = decode_profile_for(target)
    target["tle_resolved"] = target.get("name") in tle_names

sdr_probe = run([str(SATDUMP_BIN), "sdr_probe"], timeout=8) if SATDUMP_BIN.exists() else {"rc": 127, "stdout": [], "stderr": ["satdump missing"]}
timer_line = run(["systemctl", "list-timers", "satelite-watcher-schedule.timer", "--all", "--no-pager"])

payload = {
    "ok": True,
    "host": "tresor",
    "root_exists": ROOT.exists(),
    "now_utc": now.isoformat(),
    "now_local": datetime.now(local_tz).strftime("%Y-%m-%d %H:%M:%S %Z"),
    "timezone": local_tz_name,
    "satdump_present": SATDUMP_BIN.exists(),
    "timer_active": (run(["systemctl", "is-active", "satelite-watcher-schedule.timer"])["stdout"] or ["unknown"])[0],
    "timer_enabled": (run(["systemctl", "is-enabled", "satelite-watcher-schedule.timer"])["stdout"] or ["unknown"])[0],
    "timer_line": timer_line["stdout"][1] if len(timer_line["stdout"]) > 1 else "unknown",
    "scheduler_logs": tail(SCHEDULER_LOG, 18),
    "record_logs": tail(RECORD_LOG, 16),
    "sdr_probe": sdr_probe,
    "weather_targets": weather_targets,
    "passes": passes,
    "queue": queue,
    "latest_record": latest_record,
    "failed_records": failed_records[:6],
    "outputs": outputs,
    "counts": {
        "passes": len(passes),
        "queue": len(queue),
        "targets": len(weather_targets),
        "tle_resolved": sum(1 for item in weather_targets if item.get("tle_resolved")),
    },
    "scheduler": {
        "updated_at_utc": scheduled_payload.get("updated_at_utc"),
        "created_this_run": scheduled_payload.get("created_this_run"),
        "canceled_this_run": scheduled_payload.get("canceled_this_run"),
        "first_record_utc": passes[0].get("record_start_utc") if passes else None,
        "last_record_utc": passes[-1].get("record_start_utc") if passes else None,
    },
    "config": {
        "recordings_dir": paths.get("recordings_dir"),
        "sdr": config.get("sdr", {}),
        "decode": config.get("decode", {}),
        "schedule": config.get("schedule", {}),
        "filter": config.get("filter", {}),
        "notifications": config.get("notifications", {}),
        "iss_sstv": config.get("iss_sstv", {}),
        "tle": config.get("tle", {}),
    },
    "iss": {
        "enabled": config.get("iss_sstv", {}).get("enabled", False),
        "updated_at_utc": iss_events.get("updated_at_utc"),
        "event_count": len(events),
        "active_count": len(active_iss),
        "upcoming_count": len(upcoming_iss),
        "next_event": (active_iss or upcoming_iss or [None])[0],
    },
}
print(json.dumps(payload))
PY
"""


def fetch_status() -> Dict[str, Any]:
    host = target_ip()
    key = ssh_key()
    raw = ssh_run(host, SSH_USER, key, REMOTE_STATUS_SCRIPT, timeout=30)
    if not raw:
        return {
            "ok": False,
            "error": _last_ssh_error or "empty SSH response",
            "ssh_target": f"{SSH_USER}@{host}",
        }
    try:
        data = json.loads(raw.splitlines()[-1])
        set_display_timezone(data.get("timezone"))
        return data
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "error": f"could not parse status JSON: {exc}",
            "raw": raw[-2000:],
            "ssh_target": f"{SSH_USER}@{host}",
        }


def run_status_playbook() -> None:
    cmd = [ANSIBLE_CMD, "-i", INVENTORY, STATUS_PLAYBOOK]
    console.clear()
    console.rule(f"[{C_ACCENT}]space-navigator raw status")
    console.print(f"[{C_DIM}]$ {' '.join(cmd)}[/{C_DIM}]\n")
    try:
        rc = subprocess.run(cmd).returncode
    except FileNotFoundError:
        console.print(f"[bold {C_RED}]ansible-playbook was not found on this machine[/]")
        pause()
        return
    console.print()
    if rc == 0:
        console.print(f"[bold {C_GREEN}]status playbook completed[/]")
    else:
        console.print(f"[bold {C_RED}]status playbook failed rc={rc}[/]")
    pause()


def pause() -> None:
    questionary.press_any_key_to_continue(style=Q_STYLE).ask()


def set_display_timezone(value: Any) -> None:
    global _display_timezone
    if value:
        _display_timezone = str(value)


def display_tz():
    if ZoneInfo:
        try:
            return ZoneInfo(_display_timezone)
        except Exception:
            pass
    return datetime.now().astimezone().tzinfo or timezone.utc


def parse_dt(value: Any) -> datetime:
    dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(display_tz())


def fmt_dt(value: Any, fallback: str = "n/a") -> str:
    if not value:
        return fallback
    try:
        dt = parse_dt(value)
        return dt.strftime("%a %H:%M")
    except Exception:
        return str(value)


def fmt_date_short(value: Any, fallback: str = "n/a") -> str:
    if not value:
        return fallback
    try:
        dt = parse_dt(value)
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return str(value)


def fmt_full_dt(value: Any, fallback: str = "n/a") -> str:
    if not value:
        return fallback
    try:
        dt = parse_dt(value)
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return str(value)


def fmt_mhz(value: Any) -> str:
    try:
        return f"{float(value) / 1_000_000:.4f}"
    except Exception:
        return "n/a"


def fmt_el(value: Any) -> str:
    try:
        return f"{float(value):.1f}"
    except Exception:
        return "n/a"


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def fmt_size(value: Any) -> str:
    try:
        size = float(value)
    except Exception:
        return "n/a"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.1f} {units[idx]}"


def fmt_until(value: Any) -> str:
    if not value:
        return "n/a"
    try:
        delta = parse_dt(value) - datetime.now(display_tz())
        seconds = int(delta.total_seconds())
    except Exception:
        return "n/a"
    if seconds < -60:
        return "past"
    if seconds < 60:
        return "now"
    minutes = seconds // 60
    hours = minutes // 60
    if hours:
        return f"{hours}h {minutes % 60}m"
    return f"{minutes}m"


def compact_text(value: Any, max_len: int) -> str:
    text = str(value or "n/a")
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3] + "..."


def compact_path(value: Any, max_len: int = 76) -> str:
    text = str(value or "n/a")
    if len(text) <= max_len:
        return text
    return "..." + text[-(max_len - 3):]


def compact_pass_id(value: Any) -> str:
    text = str(value or "n/a")
    replacements = (
        ("meteor-m-n2-", "m-n2-"),
        ("meteor-m-", "m-"),
        ("noaa-", "n-"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def clean_log_line(value: Any) -> str:
    text = ANSI_RE.sub("", str(value or ""))
    text = text.replace("/opt/satelite-watcher/", "~/")
    text = text.replace("/mnt/data/files/Satelite Data recs/", "recs/")
    text = text.replace("satelite-watcher-trigger-", "trigger-")
    return text


def peak_label(item: Dict[str, Any]) -> str:
    elevation = fmt_el(item.get("max_elevation_deg"))
    azimuth = str(item.get("peak_azimuth_label") or "").strip()
    if azimuth and azimuth.lower() != "n/a":
        return f"{elevation} {azimuth}"
    return elevation


def status_style(value: Any) -> str:
    text = str(value).lower()
    if text in {"active", "enabled", "success", "true", "0"}:
        return C_GREEN
    if text in {"inactive", "disabled", "failed", "false", "missing"}:
        return C_RED
    return C_YELLOW


def profile_label(profile: Any) -> Text:
    text = str(profile or "n/a")
    return Text(text, style=PROFILE_COLOR.get(text, C_MUTED))


def bool_badge(value: Any, true_text: str = "on", false_text: str = "off") -> Text:
    return Text(true_text if bool(value) else false_text, style=status_style(bool(value)))


def pass_priority_style(item: Dict[str, Any]) -> str:
    elevation = as_float(item.get("max_elevation_deg"), 0.0)
    if elevation >= 80:
        return f"bold {C_GREEN}"
    if elevation >= 60:
        return C_ACCENT
    if elevation >= HIGH_PASS_MIN_ELEVATION:
        return C_TEXT
    return C_DIM


def next_high_pass(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rows = high_passes(data)
    try:
        now = datetime.now(display_tz())
        for item in rows:
            end = parse_dt(item.get("record_end_utc"))
            if end >= now:
                return item
    except Exception:
        pass
    return rows[0] if rows else None


def run_state_label(item: Dict[str, Any], index: int) -> Text:
    try:
        now = datetime.now(display_tz())
        start = parse_dt(item.get("record_start_utc"))
        end = parse_dt(item.get("record_end_utc"))
        if start <= now <= end:
            return Text("LIVE", style=f"bold {C_RED}")
        if end < now:
            return Text("done", style=C_DIM)
    except Exception:
        pass
    if index == 0:
        return Text("NEXT", style=f"bold {C_GREEN}")
    return Text("armed", style=C_ACCENT)


def queued_pass_ids(data: Dict[str, Any]) -> set[str]:
    return {
        str(item.get("pass_id"))
        for item in data.get("queue", []) or []
        if item.get("pass_id")
    }


def high_passes(data: Dict[str, Any], min_elevation: float = HIGH_PASS_MIN_ELEVATION) -> List[Dict[str, Any]]:
    rows = [
        item
        for item in data.get("passes", []) or []
        if as_float(item.get("max_elevation_deg"), -999.0) >= min_elevation
    ]
    return sorted(rows, key=lambda item: str(item.get("record_start_utc") or ""))


def pass_state_label(item: Dict[str, Any], queued_ids: set[str]) -> Text:
    pass_id = str(item.get("pass_id") or "")
    if pass_id in queued_ids:
        return Text("armed", style=C_GREEN)
    try:
        now = datetime.now(display_tz())
        start = parse_dt(item.get("record_start_utc"))
        end = parse_dt(item.get("record_end_utc"))
        if start <= now <= end:
            return Text("LIVE", style=f"bold {C_RED}")
        if end < now:
            return Text("past", style=C_DIM)
    except Exception:
        pass
    return Text("scan", style=C_YELLOW)


def header(data: Dict[str, Any]) -> Table:
    title = Text("space-navigator", style=f"bold {C_ACCENT}")
    subtitle = Text("satelite-watcher operator cockpit", style=C_MUTED)
    line = Text()
    line.append(title)
    line.append("  ")
    line.append(subtitle)
    line.append("\n")
    line.append(f"{data.get('host', 'tresor')}  ", style=f"bold {C_TEXT}")
    line.append(data.get("now_local", "unknown time"), style=C_ACCENT)
    line.append("   ")
    line.append(f"tz {data.get('timezone', 'n/a')}", style=C_DIM)
    layout = Table.grid(expand=True)
    layout.add_column(ratio=1)
    layout.add_column(width=34)
    layout.add_row(
        Panel(line, border_style=C_BORDER, box=box.ROUNDED),
        Panel(Text(SPACE_ART.strip("\n"), style=C_BLUE), border_style=C_DIM, box=box.ROUNDED),
    )
    return layout


def summary_panels(data: Dict[str, Any]) -> Panel:
    counts = data.get("counts", {})
    scheduler = data.get("scheduler", {})
    config = data.get("config", {})
    sdr = config.get("sdr", {})
    notifications = config.get("notifications", {})
    iss = data.get("iss", {})
    outputs = data.get("outputs") or {}
    next_pass = next_high_pass(data)

    def section(title: str, rows: List[Tuple[str, Any]]) -> Table:
        body = Table.grid(padding=(0, 1))
        body.add_column(style=C_DIM, no_wrap=True)
        body.add_column(style=C_TEXT)
        body.add_row(Text(title, style=f"bold {C_ACCENT}"), "")
        for key, value in rows:
            body.add_row(key, value)
        return body

    scheduler_section = section(
        "Scheduler",
        [
            ("Timer", Text(str(data.get("timer_active", "unknown")), style=status_style(data.get("timer_active")))),
            ("Enabled", Text(str(data.get("timer_enabled", "unknown")), style=status_style(data.get("timer_enabled")))),
            ("Next", f"{fmt_dt(next_pass.get('record_start_utc'), 'none') if next_pass else 'none'}  {fmt_until(next_pass.get('record_start_utc')) if next_pass else ''}".strip()),
            ("Updated", fmt_dt(scheduler.get("updated_at_utc"))),
        ],
    )
    radio_section = section(
        "Radio",
        [
            ("SatDump", Text("present" if data.get("satdump_present") else "missing", style=status_style(data.get("satdump_present")))),
            ("SDR", str(sdr.get("source", "n/a"))),
            ("Sample", str(sdr.get("samplerate", "n/a"))),
            ("Offset", str(sdr.get("record_frequency_offset_hz", "n/a"))),
        ],
    )
    window_section = section(
        "Window",
        [
            ("Targets", f"{counts.get('targets', 0)}"),
            ("TLEs", f"{counts.get('tle_resolved', 0)}/{counts.get('targets', 0)}"),
            ("Passes", f"{counts.get('passes', 0)} scanned / {counts.get('queue', 0)} armed"),
            ("Images", str(outputs.get("image_count", 0))),
        ],
    )
    signals_section = section(
        "Signals",
        [
            ("Discord", bool_badge(notifications.get("webhook_enabled", False))),
            ("Weather", bool_badge((notifications.get("weather_prepass") or {}).get("enabled", False))),
            ("Images", bool_badge((notifications.get("weather_image") or {}).get("enabled", False))),
            ("ISS", f"{iss.get('active_count', 0)} active / {iss.get('upcoming_count', 0)} up"),
        ],
    )

    strip = Table.grid(expand=True)
    strip.add_column(ratio=1)
    strip.add_column(ratio=1)
    strip.add_row(scheduler_section, radio_section)
    strip.add_row(window_section, signals_section)
    return Panel(strip, title="Mission Control", border_style=C_BORDER, box=box.ROUNDED)


def targets_table(data: Dict[str, Any]) -> Table:
    table = Table(title="Weather Targets", box=box.SIMPLE_HEAVY, expand=True, show_lines=False)
    table.add_column("Satellite", style=C_TEXT)
    table.add_column("Profile")
    table.add_column("Frequency MHz", justify="right", style=C_MUTED)
    table.add_column("TLE", justify="center")
    for item in data.get("weather_targets", []):
        table.add_row(
            str(item.get("name", "unknown")),
            profile_label(item.get("decode_profile")),
            fmt_mhz(item.get("frequency_hz")),
            Text("ok" if item.get("tle_resolved") else "missing", style=status_style(item.get("tle_resolved"))),
        )
    if not data.get("weather_targets"):
        table.add_row("none", "n/a", "n/a", "missing")
    return table


def active_satellites_table(data: Dict[str, Any]) -> Table:
    table = Table(title="Actively Tracked Satellites", box=box.SIMPLE_HEAVY, expand=True, show_lines=False)
    table.add_column("Sat", style=C_TEXT, no_wrap=True)
    table.add_column("Mode", no_wrap=True)
    table.add_column("MHz", justify="right", style=C_MUTED, no_wrap=True)
    table.add_column("TLE", justify="center", no_wrap=True)
    table.add_column("Good", justify="right", no_wrap=True)
    table.add_column("Armed", justify="right", no_wrap=True)
    table.add_column("Next", style=C_MUTED, no_wrap=True)

    rows = data.get("passes") or []
    queue = data.get("queue") or []
    queue_by_sat: Dict[str, int] = {}
    for item in queue:
        sat = str(item.get("satellite") or "")
        queue_by_sat[sat] = queue_by_sat.get(sat, 0) + 1

    for target in data.get("weather_targets", []) or []:
        name = str(target.get("name", "unknown"))
        target_high = [
            item
            for item in rows
            if str(item.get("satellite") or "") == name
            and as_float(item.get("max_elevation_deg"), -999.0) >= HIGH_PASS_MIN_ELEVATION
        ]
        next_good = target_high[0] if target_high else {}
        table.add_row(
            name,
            profile_label(target.get("decode_profile")),
            fmt_mhz(target.get("frequency_hz")),
            Text("ok" if target.get("tle_resolved") else "missing", style=status_style(target.get("tle_resolved"))),
            str(len(target_high)),
            str(queue_by_sat.get(name, 0)),
            f"{fmt_date_short(next_good.get('record_start_utc'), 'none')}  {peak_label(next_good) if next_good else ''}".strip(),
        )

    if not data.get("weather_targets"):
        table.add_row("none", "n/a", "n/a", "missing", "0", "0", "none")
    return table


def high_passes_table(data: Dict[str, Any]) -> Table:
    rows = high_passes(data)
    queued_ids = queued_pass_ids(data)
    title = f"All Passes Above {HIGH_PASS_MIN_ELEVATION:.0f} deg"
    table = Table(title=title, box=box.SIMPLE_HEAVY, expand=True, show_lines=False)
    table.add_column("Run", justify="center", no_wrap=True)
    table.add_column("When", style=C_MUTED, no_wrap=True)
    table.add_column("Until", justify="right", style=C_ACCENT, no_wrap=True)
    table.add_column("Sat", no_wrap=True)
    table.add_column("Mode", no_wrap=True)
    table.add_column("Peak", justify="right", no_wrap=True)
    table.add_column("MHz", justify="right", style=C_MUTED, no_wrap=True)

    for item in rows:
        table.add_row(
            pass_state_label(item, queued_ids),
            fmt_date_short(item.get("record_start_utc")),
            fmt_until(item.get("record_start_utc")),
            Text(str(item.get("satellite", "?")), style=pass_priority_style(item)),
            profile_label(item.get("decode_profile")),
            peak_label(item),
            fmt_mhz(item.get("frequency_hz")),
        )

    if not rows:
        table.add_row("none", "none", "-", "No passes above threshold", "n/a", "-", "-")
    else:
        armed_count = sum(1 for item in rows if str(item.get("pass_id") or "") in queued_ids)
        table.caption = f"{len(rows)} good passes in scan window, {armed_count} armed"
    return table


def next_pass_focus(data: Dict[str, Any]) -> Panel:
    item = next_high_pass(data)
    if not item:
        return Panel("No passes above threshold in the current scan window.", title="Next Good Pass", border_style=C_DIM, box=box.ROUNDED)

    config = data.get("config", {})
    sdr = config.get("sdr", {})
    try:
        tuned = int(item.get("frequency_hz") or 0) + int(sdr.get("record_frequency_offset_hz") or 0)
    except Exception:
        tuned = 0

    grid = Table.grid(expand=True)
    grid.add_column(ratio=2)
    grid.add_column(ratio=1)

    priority_style = pass_priority_style(item)
    headline = Text()
    headline.append(str(item.get("satellite", "unknown")), style=priority_style if "bold" in priority_style else f"bold {priority_style}")
    headline.append("  ")
    headline.append(str(item.get("decode_profile", "n/a")), style=PROFILE_COLOR.get(str(item.get("decode_profile")), C_MUTED))
    headline.append("\n")
    headline.append(f"{fmt_full_dt(item.get('record_start_utc'))}  ", style=C_ACCENT)
    headline.append(f"in {fmt_until(item.get('record_start_utc'))}", style=f"bold {C_GREEN}")

    details = Table.grid(padding=(0, 1))
    details.add_column(style=C_DIM, no_wrap=True)
    details.add_column(style=C_TEXT)
    details.add_row("Peak", peak_label(item))
    details.add_row("TCA", fmt_full_dt(item.get("tca_utc")))
    details.add_row("MHz", f"{fmt_mhz(item.get('frequency_hz'))} / tuned {fmt_mhz(tuned) if tuned else 'n/a'}")
    details.add_row("Timeout", f"{item.get('timeout_seconds', 'n/a')} s")

    grid.add_row(headline, details)
    return Panel(grid, title="Next Good Pass", border_style=priority_style.replace("bold ", ""), box=box.ROUNDED)


def recording_board_table(data: Dict[str, Any]) -> Table:
    rows = data.get("queue") or []
    total = int((data.get("counts") or {}).get("queue") or len(rows))
    shown = min(len(rows), RUN_BOARD_LIMIT)
    title = f"Recording Run Board - all {shown} armed passes" if total == shown else f"Recording Run Board - next {shown} of {total}"
    table = Table(title=title, box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("State", justify="center", no_wrap=True)
    table.add_column("Start", style=C_MUTED, no_wrap=True)
    table.add_column("In", justify="right", style=C_ACCENT, no_wrap=True)
    table.add_column("Satellite", style=C_TEXT, no_wrap=True, overflow="ellipsis", max_width=16)
    table.add_column("Profile", no_wrap=True, overflow="ellipsis", max_width=12)
    table.add_column("Peak", justify="right", no_wrap=True)
    table.add_column("Pass ID", style=C_DIM, overflow="ellipsis", no_wrap=True, max_width=22)

    for index, item in enumerate(rows[:RUN_BOARD_LIMIT], start=1):
        row_style = None
        if index == 1:
            row_style = f"bold {C_TEXT}"
        table.add_row(
            run_state_label(item, index - 1),
            fmt_dt(item.get("record_start_utc")),
            fmt_until(item.get("record_start_utc")),
            str(item.get("satellite", "?")),
            profile_label(item.get("decode_profile")),
            peak_label(item),
            compact_pass_id(item.get("pass_id", "n/a")),
            style=row_style,
        )

    if not rows:
        table.add_row("none", "none", "-", "No armed recording timers", "n/a", "-", "-")
    elif total > shown:
        table.caption = f"showing {shown} of {total} armed recordings"
    else:
        table.caption = f"showing all {shown} armed recordings"
    return table


def passes_table(title: str, rows: List[Dict[str, Any]], limit: int = PASS_CONTEXT_LIMIT) -> Table:
    shown = min(len(rows), limit)
    table = Table(title=title, box=box.SIMPLE_HEAVY, expand=True)
    table.add_column("Start", style=C_MUTED, no_wrap=True)
    table.add_column("Satellite", style=C_TEXT, no_wrap=True, overflow="ellipsis", max_width=18)
    table.add_column("Profile", no_wrap=True, overflow="ellipsis", max_width=12)
    table.add_column("Peak", justify="right", no_wrap=True)
    table.add_column("MHz", justify="right", style=C_MUTED)
    table.add_column("Pass ID", style=C_DIM, overflow="ellipsis", no_wrap=True, max_width=24)
    for item in rows[:limit]:
        table.add_row(
            fmt_dt(item.get("record_start_utc")),
            str(item.get("satellite", "?")),
            profile_label(item.get("decode_profile")),
            peak_label(item),
            fmt_mhz(item.get("frequency_hz")),
            compact_pass_id(item.get("pass_id", "n/a")),
        )
    if not rows:
        table.add_row("none", "No passes found", "n/a", "-", "-", "-")
    elif len(rows) > shown:
        table.caption = f"showing {shown} of {len(rows)} scanned passes"
    return table


def latest_panel(data: Dict[str, Any]) -> Panel:
    latest = data.get("latest_record")
    grid = Table.grid(padding=(0, 1))
    grid.add_column(style=C_DIM)
    grid.add_column(style=C_TEXT)
    if not latest:
        grid.add_row("Latest", "no recordings yet")
        return Panel(grid, title="Latest Recording", border_style=C_DIM, box=box.ROUNDED)

    grid.add_row("Satellite", Text(str(latest.get("satellite", "n/a")), style=f"bold {C_TEXT}"))
    grid.add_row("Pass ID", compact_pass_id(latest.get("pass_id", "n/a")))
    grid.add_row("Stage", Text(str(latest.get("stage", "n/a")), style=status_style(latest.get("stage"))))
    grid.add_row("Decode", Text(str(latest.get("decode_stage", "n/a")), style=status_style(latest.get("decode_stage"))))
    grid.add_row("Profile", profile_label(latest.get("decode_profile")))
    grid.add_row("Ended", fmt_full_dt(latest.get("ended_at")))
    grid.add_row("Size", fmt_size(latest.get("output_size_bytes")))
    grid.add_row("Images", Text(str(latest.get("image_stage", "n/a")), style=status_style(latest.get("image_stage"))))
    return Panel(grid, title="Latest Recording", border_style=status_style(latest.get("stage")), box=box.ROUNDED)


def outputs_panel(data: Dict[str, Any]) -> Panel:
    outputs = data.get("outputs") or {}
    table = Table.grid(padding=(0, 1))
    table.add_column(style=C_DIM)
    table.add_column(style=C_TEXT)

    root = outputs.get("root") or "n/a"
    table.add_row("Root", compact_path(root, 58))
    table.add_row("Exists", Text(str(outputs.get("exists", False)), style=status_style(outputs.get("exists"))))
    table.add_row("Images", str(outputs.get("image_count", 0)))
    if outputs.get("error"):
        table.add_row("Error", Text(str(outputs.get("error")), style=C_RED))

    images = outputs.get("recent_images") or []
    if images:
        table.add_row("", "")
        for item in images[:5]:
            table.add_row(
                fmt_dt(item.get("mtime_utc")),
                f"{compact_text(item.get('run', '?'), 34)} / {compact_text(item.get('name', '?'), 34)} ({fmt_size(item.get('size_bytes'))})",
            )
    else:
        runs = outputs.get("recent_runs") or []
        table.add_row("Recent runs", str(len(runs)))
        for item in runs[:4]:
            table.add_row(fmt_dt(item.get("mtime_utc")), compact_text(item.get("name", "?"), 74))
        if not runs:
            table.add_row("Recent", "no run folders found yet")

    border = C_GREEN if images else (C_YELLOW if outputs.get("exists") else C_RED)
    return Panel(table, title="Output Images", border_style=border, box=box.ROUNDED)


def next_detail_panel(data: Dict[str, Any]) -> Panel:
    queue = data.get("queue") or []
    config = data.get("config", {})
    sdr = config.get("sdr", {})
    grid = Table.grid(padding=(0, 1))
    grid.add_column(style=C_DIM)
    grid.add_column(style=C_TEXT)
    if not queue:
        grid.add_row("Next", "no queued recordings")
        return Panel(grid, title="Next Recording", border_style=C_DIM, box=box.ROUNDED)
    item = queue[0]
    try:
        tuned = int(item.get("frequency_hz") or 0) + int(sdr.get("record_frequency_offset_hz") or 0)
    except Exception:
        tuned = 0
    grid.add_row("Satellite", str(item.get("satellite", "n/a")))
    grid.add_row("Profile", profile_label(item.get("decode_profile")))
    grid.add_row("Record", fmt_full_dt(item.get("record_start_utc")))
    grid.add_row("AOS", fmt_full_dt(item.get("aos_utc")))
    grid.add_row("TCA", fmt_full_dt(item.get("tca_utc")))
    grid.add_row("LOS", fmt_full_dt(item.get("los_utc")))
    grid.add_row("Frequency", f"{fmt_mhz(item.get('frequency_hz'))} MHz")
    grid.add_row("Tuned", f"{fmt_mhz(tuned)} MHz" if tuned else "n/a")
    grid.add_row("Peak", f"{item.get('max_elevation_deg', 'n/a')} deg {item.get('peak_azimuth_label', '')}")
    grid.add_row("Timeout", f"{item.get('timeout_seconds', 'n/a')} s")
    return Panel(grid, title="Next Recording", border_style=C_GREEN, box=box.ROUNDED)


def iss_panel(data: Dict[str, Any]) -> Panel:
    iss = data.get("iss", {})
    event = iss.get("next_event")
    grid = Table.grid(padding=(0, 1))
    grid.add_column(style=C_DIM)
    grid.add_column(style=C_TEXT)
    grid.add_row("Enabled", Text(str(iss.get("enabled", False)), style=status_style(iss.get("enabled"))))
    grid.add_row("Cache", fmt_full_dt(iss.get("updated_at_utc")))
    grid.add_row("Events", f"{iss.get('event_count', 0)} cached")
    grid.add_row("Gate", f"{iss.get('active_count', 0)} active / {iss.get('upcoming_count', 0)} upcoming")
    if event:
        grid.add_row("Next", str(event.get("title", "n/a"))[:80])
        grid.add_row("Start", fmt_full_dt(event.get("start_utc")))
        grid.add_row("End", fmt_full_dt(event.get("end_utc")))
        grid.add_row("Mode", str(event.get("mode", "n/a")))
        grid.add_row("MHz", fmt_mhz(event.get("frequency_hz")))
    else:
        grid.add_row("Next", "none in cache / lookahead")
    return Panel(grid, title="ISS SSTV Gate", border_style=C_ISS, box=box.ROUNDED)


def log_panel(title: str, lines: List[str], border: str) -> Panel:
    text = Text()
    visible_lines = [
        clean_log_line(line) for line in lines
        if not (
            (
                "Failed to reset failed state of unit meteor-trigger-" in line
                or "Failed to reset failed state of unit satelite-watcher-trigger-" in line
            )
            and "not loaded" in line
        )
    ]
    for line in visible_lines[-14:]:
        style = C_DIM
        lowered = line.lower()
        if "failed" in lowered or "error" in lowered or "warning" in lowered:
            style = C_YELLOW
        if "success" in lowered or "verified" in lowered:
            style = C_GREEN
        text.append(line[-140:] + "\n", style=style)
    if not visible_lines:
        text.append("no log lines found", style=C_DIM)
    return Panel(text, title=title, border_style=border, box=box.ROUNDED)


def render_dashboard(data: Dict[str, Any]) -> None:
    console.clear()
    if not data.get("ok"):
        console.print(header({"host": "tresor", "now_local": "offline", "timezone": "n/a"}))
        message = data.get("error") or "unknown error"
        target = data.get("ssh_target", f"{SSH_USER}@{target_ip()}")
        console.print(Panel(f"[{C_RED}]{message}[/]\n[{C_DIM}]{target}[/]", title="Connection Failed", border_style=C_RED))
        return

    console.print(header(data))
    console.print(summary_panels(data))
    console.print()

    console.print(next_pass_focus(data))
    console.print()

    console.print(high_passes_table(data))
    console.print()

    status_grid = Table.grid(expand=True)
    status_grid.add_column(ratio=2)
    status_grid.add_column(ratio=1)
    status_grid.add_row(active_satellites_table(data), latest_panel(data))
    console.print(status_grid)
    console.print()

    bottom = Table.grid(expand=True)
    bottom.add_column(ratio=1)
    bottom.add_column(ratio=1)
    bottom.add_row(
        log_panel("Scheduler Log Tail", data.get("scheduler_logs", []), C_DIM),
        log_panel("Recorder Log Tail", data.get("record_logs", []), C_ACCENT),
    )
    console.print(bottom)


def show_logs(data: Dict[str, Any]) -> None:
    console.clear()
    console.print(header(data if data.get("ok") else {"host": "tresor", "now_local": "offline", "timezone": "n/a"}))
    if not data.get("ok"):
        console.print(Panel(data.get("error", "no data"), title="No Logs", border_style=C_RED))
        pause()
        return
    console.print(log_panel("Scheduler Log", data.get("scheduler_logs", []), C_BORDER))
    console.print(log_panel("Record Log", data.get("record_logs", []), C_ACCENT))
    probe = data.get("sdr_probe", {})
    probe_lines = (probe.get("stdout") or []) + (probe.get("stderr") or [])
    console.print(log_panel("SatDump SDR Probe", probe_lines, C_GREEN))
    pause()


def menu(data: Dict[str, Any]) -> str:
    choices = [
        Choice("refresh", "refresh"),
        Choice("logs", "logs"),
        Choice("raw status playbook", "raw"),
        Choice("quit", "quit"),
    ]
    answer = questionary.select(
        "space-navigator",
        choices=choices,
        style=Q_STYLE,
        qmark="",
        pointer=">",
    ).ask()
    return answer or "quit"


def main() -> None:
    if not Path(INVENTORY).exists():
        console.print(f"[bold {C_RED}]Run from the ansible/ directory.[/]")
        sys.exit(1)

    data: Dict[str, Any] = {}
    while True:
        with console.status(f"[{C_ACCENT}]scanning Satelite Watcher over SSH...", spinner="dots"):
            close_ssh_clients()
            data = fetch_status()
        render_dashboard(data)
        action = menu(data)
        if action == "quit":
            _bye()
        if action == "logs":
            show_logs(data)
        elif action == "raw":
            run_status_playbook()


if __name__ == "__main__":
    main()
