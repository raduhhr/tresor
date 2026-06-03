#!/usr/bin/env python3
"""
plane-navigator - Plane Watcher operator cockpit
Run from: the ansible/ directory
Requires: pip install rich questionary paramiko --break-system-packages
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import paramiko
    import questionary
    from questionary import Choice, Style
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
STATUS_PLAYBOOK = "playbooks/plane-watcher/status.yml"
TARGET_HOST = "tresor"

C_PANEL = "#1f2937"
C_BORDER = "#60a5fa"
C_ACCENT = "#38bdf8"
C_GREEN = "#34d399"
C_YELLOW = "#fbbf24"
C_RED = "#fb7185"
C_DIM = "#94a3b8"
C_TEXT = "#e5e7eb"

PLANE_ART = r"""
        __|__
--o--o--(_)--o--o--
"""

console = Console()
_ssh_clients: Dict[Tuple[str, str, str], paramiko.SSHClient] = {}
_last_ssh_error: Optional[str] = None

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
        ("bottom-toolbar", "fg:#111827 bg:#111827"),
        ("text", f"fg:{C_TEXT}"),
    ]
)


def _bye(*_: Any) -> None:
    console.print(f"\n  [{C_DIM}]plane-navigator closed[/{C_DIM}]\n")
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


def target_ip() -> str:
    hosts = inventory_hosts()
    return hosts.get(TARGET_HOST, {}).get("ansible_host", TARGET_HOST)


def ssh_key() -> str:
    return os.path.expanduser("~/.ssh/id_ed25519_tresor")


def ssh_run(host: str, user: str, key: str, script: str, timeout: int = 20) -> str:
    global _last_ssh_error
    _last_ssh_error = None
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
                key,
                f"{user}@{host}",
                "bash -s",
            ],
            input=script,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
        _last_ssh_error = (proc.stderr or f"ssh exited rc={proc.returncode}").strip().splitlines()[-1]
        return ""
    except Exception as exc:
        _last_ssh_error = str(exc)
        return ""


def fetch_status() -> Dict[str, Any]:
    host = target_ip()
    raw = ssh_run(
        host,
        "ansible",
        ssh_key(),
        r"""
set -euo pipefail
echo "=SUMMARY="
python3 - <<'PY'
from pathlib import Path
import yaml

cfg_path = Path("/mnt/ssd/configs/plane-watcher/config.yml")
if not cfg_path.exists():
    print("missing=true")
    raise SystemExit(0)

cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
ui = cfg.get("ui", {})
sdr = cfg.get("sdr", {})
ultra = cfg.get("ultrafeeder", {})
runtime = cfg.get("runtime", {})
print(f"missing=false")
print(f"url={ui.get('url', 'n/a')}")
print(f"bind={ui.get('bind_address', 'n/a')}:{ui.get('port', 'n/a')}")
print(f"serial={sdr.get('device_serial', 'n/a')}")
print(f"gain={sdr.get('gain', 'n/a')}")
print(f"image={ultra.get('image', 'n/a')}")
print(f"paused={runtime.get('satelite_watcher_recording_paused', 'n/a')}")
PY
echo "=SYSTEMD="
docker inspect -f 'running={{.State.Running}}' plane-watcher 2>/dev/null || true
docker inspect -f 'image={{.Config.Image}}' plane-watcher 2>/dev/null || true
echo "=DOCKER="
docker ps -a --filter name=^plane-watcher$ --format '{{.Names}}|{{.Image}}|{{.Status}}' 2>/dev/null || true
echo "=LOGS="
docker logs --tail 25 plane-watcher 2>&1 || true
echo "=END="
""",
        timeout=25,
    )
    if not raw:
        return {"ok": False, "host": host, "error": _last_ssh_error or "ssh failed"}

    data: Dict[str, Any] = {
        "ok": True,
        "host": host,
        "summary": {},
        "runtime": [],
        "docker": [],
        "logs": [],
    }
    section = ""
    for line in raw.splitlines():
        s = line.rstrip()
        if s.startswith("=") and s.endswith("="):
            section = s.strip("=").lower()
            continue
        if not s or section == "end":
            continue
        if section == "summary":
            if "=" in s:
                key, value = s.split("=", 1)
                data["summary"][key] = value
        elif section == "systemd":
            data["runtime"].append(s)
        elif section == "docker":
            data["docker"].append(s)
        elif section == "logs":
            data["logs"].append(s)
    return data


def run_status_playbook() -> None:
    cmd = [ANSIBLE_CMD, "-i", INVENTORY, STATUS_PLAYBOOK, "--limit", TARGET_HOST]
    console.clear()
    console.print(f"[{C_DIM}]$ {' '.join(cmd)}[/]\n")
    subprocess.run(cmd)
    pause()


def pause() -> None:
    questionary.press_any_key_to_continue(style=Q_STYLE).ask()


def render_dashboard(data: Dict[str, Any]) -> None:
    console.clear()
    title = Text("plane-navigator", style=f"bold {C_ACCENT}")
    subtitle = Text("plane-watcher operator cockpit", style=C_DIM)
    console.print(Panel.fit(f"{PLANE_ART}\n", title=title, subtitle=subtitle, border_style=C_BORDER))

    if not data.get("ok"):
        console.print(Panel(data.get("error", "unknown error"), title="Offline", border_style=C_RED))
        return

    summary = data.get("summary", {})
    runtime_state = data.get("runtime", [])
    running = next((line.split("=", 1)[1] for line in runtime_state if line.startswith("running=")), "unknown")
    image = next((line.split("=", 1)[1] for line in runtime_state if line.startswith("image=")), summary.get("image", "n/a"))

    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)
    grid.add_row(
        Panel(
            "\n".join(
                [
                    f"[{C_DIM}]Host[/]   [{C_TEXT}]{data.get('host', 'n/a')}[/]",
                    f"[{C_DIM}]UI[/]     [{C_TEXT}]{summary.get('url', 'n/a')}[/]",
                    f"[{C_DIM}]Bind[/]   [{C_TEXT}]{summary.get('bind', 'n/a')}[/]",
                    f"[{C_DIM}]Image[/]  [{C_TEXT}]{image}[/]",
                ]
            ),
            title="Runtime",
            border_style=C_BORDER,
        ),
        Panel(
            "\n".join(
                [
                    f"[{C_DIM}]Running[/] [{C_TEXT}]{running}[/]",
                    f"[{C_DIM}]SDR[/]     [{C_TEXT}]{summary.get('serial', 'n/a')}[/]",
                    f"[{C_DIM}]Gain[/]    [{C_TEXT}]{summary.get('gain', 'n/a')}[/]",
                    f"[{C_DIM}]Sat pause[/] [{C_TEXT}]{summary.get('paused', 'n/a')}[/]",
                ]
            ),
            title="Control",
            border_style=C_GREEN if running == "true" else C_YELLOW,
        ),
    )
    console.print(grid)
    console.print()
    console.print(Panel("\n".join(data.get("docker", []) or ["no containers"]), title="Containers", border_style=C_ACCENT))
    console.print(Panel("\n".join(data.get("logs", []) or ["no logs"]), title="Plane Watcher Logs", border_style=C_DIM))


def menu() -> str:
    choices = [
        Choice("refresh", "refresh"),
        Choice("raw status playbook", "raw"),
        Choice("quit", "quit"),
    ]
    answer = questionary.select(
        "plane-navigator",
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

    while True:
        with console.status(f"[{C_ACCENT}]scanning Plane Watcher over SSH...", spinner="dots"):
            close_ssh_clients()
            data = fetch_status()
        render_dashboard(data)
        action = menu()
        if action == "quit":
            _bye()
        if action == "raw":
            run_status_playbook()


if __name__ == "__main__":
    main()
