#!/usr/bin/env python3
"""
tresor-ctl — Tresor control panel
Run from: ~/Desktop/tresor/ansible/
Requires: pip install rich questionary paramiko pyyaml --break-system-packages
"""

from __future__ import annotations

import glob
import os
import re
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

try:
    import questionary
    from questionary import Choice, Style

    import paramiko
    import yaml
    from prompt_toolkit.formatted_text import FormattedText
    from rich.columns import Columns
    from rich.console import Console
    from rich.panel import Panel
except ImportError:
    print("Missing deps. Run:")
    print("  pip install rich questionary paramiko pyyaml --break-system-packages")
    sys.exit(1)

# ─── Config ────────────────────────────────────────────────────────────────────

INVENTORY = "inventory/hosts.ini"
VERSIONS_FILE = "inventory/group_vars/prod/versions.yml"
ANSIBLE_CMD = "ansible-playbook"
PLAYBOOKS_DIR = "playbooks"

# ─── Palette ───────────────────────────────────────────────────────────────────

C_ACCENT = "#a78bfa"
C_DIM = "#8b86c9"
C_MID = "#c4b5fd"
C_WHITE = "#e2e8f0"
C_RED = "#f87171"
C_BORDER = "#6d28d9"

C_BAR_LOW = "#60a5fa"   # blue
C_BAR_MID = "#a78bfa"   # purple
C_BAR_HIGH = "#f87171"  # red

C_DOT_ON = "#60a5fa"
C_DOT_OFF = "#f87171"

NET_COLOR = {"public": "#60a5fa", "internal": "#c084fc", "wg": "#34d399", "cron": "#fbbf24"}
NET_BADGE = {"public": "☁", "internal": "⌂", "wg": "⇄", "cron": "⏲"}
NET_ORDER = {"internal": 0, "public": 1, "wg": 2, "cron": 3}

STATE_COLOR = {
    "running": C_BAR_LOW,
    "restart": C_BAR_MID,
    "created": C_BAR_MID,
    "cron": C_DIM,
    "exited": C_DIM,
    "stopped": C_DIM,
}

PLAY_LABEL = {
    "deploy": "⬆  deploy",
    "start": "▶  start",
    "stop": "■  stop",
    "restart": "↺  restart",
    "remove": "✕  remove",
    "backup": "💾 backup",
    "status": "ℹ  status",
    "update": "↑  update",
    "verify": "✓  verify",
}

SKIP_SERVICES = {"infra", "vps", "motd"}
CRON_SERVICES = {"bday-notifier", "steam-free-notifier", "content-notifier"}
OWN_SERVICES = {"bday-notifier", "steam-free-notifier"}

SVC_META: Dict[str, Dict[str, Any]] = {
    "traefik": {"net": "public", "container": "traefik", "url": "", "desc": "reverse proxy"},
    "cloudflared": {"net": "public", "container": "cloudflared", "url": "", "desc": "Cloudflare Tunnel"},
    "uptime-kuma": {"net": "public", "container": "uptime-kuma", "url": "https://mc-status.example.com", "desc": "status page"},
    "jellyfin": {"net": "internal", "container": "jellyfin", "url": "http://192.168.1.100:8096", "desc": "media server"},
    "jellyfin-music": {"net": "wg", "container": "jellyfin-music", "url": "https://music.example.com", "desc": "music via VPS→WG"},
    "grafana": {"net": "internal", "container": "grafana", "url": "http://192.168.1.100:3000", "desc": "dashboards"},
    "prometheus": {"net": "internal", "container": "prometheus", "url": "http://192.168.1.100:9090", "desc": "metrics"},
    "filebrowser": {"net": "internal", "container": "filebrowser", "url": "http://192.168.1.100:8080", "desc": "file manager"},
    "kiwix": {"net": "internal", "container": "kiwix", "url": "http://192.168.1.100:8181", "desc": "offline Wikipedia"},
    "paper": {"net": "wg", "container": "paper", "url": "1.2.3.4:25565", "desc": "Minecraft Paper"},
    "bday-notifier": {"net": "cron", "container": None, "url": "", "desc": "birthday webhook"},
    "content-notifier": {"net": "cron", "container": None, "url": "", "desc": "new content webhook"},
    "steam-free-notifier": {"net": "cron", "container": None, "url": "", "desc": "Steam free games bot"},
    "filebrowser-public": {"net": "wg", "container": "filebrowser-public", "url": "https://cloud.example.com", "desc": "Scloud drop (friends)"}
}

console = Console()

def _bye(*_):
    console.print(f"\n  [{C_DIM}]// bye.[/{C_DIM}]\n")
    _close_ssh_clients()
    sys.exit(0)

signal.signal(signal.SIGINT, _bye)
signal.signal(signal.SIGTSTP, _bye)

Q_STYLE = Style(
    [
        ("qmark", "fg:#000000"),
        ("question", f"fg:{C_WHITE} bold"),
        ("answer", f"fg:{C_ACCENT} bold"),
        ("pointer", f"fg:{C_ACCENT} bold"),
        ("highlighted", "fg:#e2e8f0 bg:#1a1a2e bold"),
        ("selected", f"fg:{C_ACCENT}"),
        ("separator", f"fg:{C_DIM}"),
        ("instruction", "fg:#000000"),
        ("bottom-toolbar", "fg:#1a1a2e bg:#1a1a2e"),  # hide "(Use arrow keys)" on more versions
        ("text", f"fg:{C_WHITE}"),
    ]
)

# ─── Nuke "(Use arrow keys)" across questionary versions ──────────────────────
def _disable_questionary_instruction() -> None:
    for mod_name in (
        "questionary.prompts.common",
        "questionary.prompts.select",
        "questionary.constants",
    ):
        try:
            mod = __import__(mod_name, fromlist=["*"])
        except Exception:
            continue
        for attr in dir(mod):
            if "INSTRUCTION" not in attr:
                continue
            try:
                val = getattr(mod, attr)
            except Exception:
                continue
            if isinstance(val, str) and "arrow" in val.lower():
                try:
                    setattr(mod, attr, "")
                except Exception:
                    pass

_disable_questionary_instruction()

# ─── Questionary patch: keep row highlight even with FormattedText titles ─────

def _force_bg_on_selected_line_tokens(tokens, selected_bg: str = "#1a1a2e"):
    """
    Post-process prompt_toolkit tokens returned by Questionary and force a background
    color on the currently selected line (the one that starts with the pointer '>').

    This restores visible highlight when Choice.title is a formatted fragment list.
    """
    out = []
    line = []

    def flush_line():
        nonlocal line, out
        if not line:
            return

        # Build plain text of current line
        line_text = "".join(str(f[1]) for f in line if len(f) >= 2)
        is_selected = line_text.lstrip().startswith(">")

        if is_selected:
            for frag in line:
                if len(frag) < 2:
                    out.append(frag)
                    continue

                style = frag[0] or ""
                text = frag[1]
                rest = frag[2:] if len(frag) > 2 else ()

                # don't bother styling the newline itself
                if text == "\n":
                    out.append(frag)
                    continue

                merged_style = f"{style} bg:{selected_bg}".strip()
                out.append((merged_style, text, *rest))
        else:
            out.extend(line)

        line = []

    for frag in tokens:
        # prompt_toolkit tokens are typically (style, text) or (style, text, handler)
        if not isinstance(frag, tuple) or len(frag) < 2:
            line.append(frag)
            continue

        style = frag[0]
        text = str(frag[1])
        rest = frag[2:] if len(frag) > 2 else ()

        if "\n" not in text:
            line.append((style, text, *rest))
            continue

        # split while keeping newlines
        parts = re.split(r"(\n)", text)
        for part in parts:
            if part == "":
                continue
            line.append((style, part, *rest))
            if part == "\n":
                flush_line()

    flush_line()
    return out


def _patch_questionary_formatted_highlight() -> None:
    """
    Questionary versions differ internally. Patch the token-building method(s) if present.
    """
    try:
        from questionary.prompts.common import InquirerControl
    except Exception:
        return

    if getattr(InquirerControl, "_tresor_fmt_highlight_patch", False):
        return

    candidate_methods = [
        "_get_choice_tokens",   # common in many versions
        "_get_choices_tokens",  # seen in some versions
    ]

    patched_any = False

    for method_name in candidate_methods:
        orig = getattr(InquirerControl, method_name, None)
        if not callable(orig):
            continue

        def _make_patched(fn):
            def _patched(self, *args, **kwargs):
                tokens = fn(self, *args, **kwargs)
                try:
                    return _force_bg_on_selected_line_tokens(tokens, selected_bg="#1a1a2e")
                except Exception:
                    return tokens
            return _patched

        setattr(InquirerControl, method_name, _make_patched(orig))
        patched_any = True

    if patched_any:
        InquirerControl._tresor_fmt_highlight_patch = True


_patch_questionary_formatted_highlight()

def q_select(message: str, choices: List[Choice]):
    """
    Wrapper to remove instruction + qmark across questionary versions,
    remove radio circles, and prefer a simple '>' pointer.
    """
    base = dict(
        choices=choices,
        style=Q_STYLE,
        use_indicator=False,   # <-- removes empty circles
    )

    attempts = [
        dict(base, instruction="", qmark="", pointer=">"),
        dict(base, instructions="", qmark="", pointer=">"),
        dict(base, instructions=[], qmark="", pointer=">"),
        dict(base, instruction="", pointer=">"),
        dict(base, qmark="", pointer=">"),
        dict(base, pointer=">"),
        dict(base, instruction="", qmark=""),
        dict(base),
    ]
    for kw in attempts:
        try:
            return questionary.select(message, **kw).ask()
        except TypeError:
            continue
    return questionary.select(message, **base).ask()

# ─── Inventory ────────────────────────────────────────────────────────────────

def discover_hosts() -> Dict[str, Dict[str, str]]:
    hosts: Dict[str, Dict[str, str]] = {}
    current_group = None
    try:
        with open(INVENTORY, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith(("#", ";")):
                    continue
                grp = re.match(r"^\[(\w[\w-]*)\]", line)
                if grp:
                    g = grp.group(1)
                    current_group = g if ":" not in g else None
                    continue
                if current_group:
                    parts = line.split()
                    name = parts[0]
                    ip = ""
                    for p in parts[1:]:
                        if p.startswith("ansible_host="):
                            ip = p.split("=", 1)[1]
                    hosts[name] = {"group": current_group, "ip": ip}
    except FileNotFoundError:
        pass
    return hosts

def _ssh_key_for_section(section_header: str, fallback: str) -> str:
    try:
        with open(INVENTORY, encoding="utf-8") as f:
            in_section = False
            for line in f:
                stripped = line.strip()
                if stripped == section_header:
                    in_section = True
                    continue
                if in_section and stripped.startswith("["):
                    break
                if in_section and "ansible_ssh_private_key_file" in stripped:
                    return os.path.expanduser(stripped.split("=", 1)[1].strip())
    except Exception:
        pass
    return os.path.expanduser(fallback)

def _tresor_ssh_key() -> str:
    return _ssh_key_for_section("[all:vars]", "~/.ssh/id_ed25519_homelab")

def _vps_ssh_key() -> str:
    return _ssh_key_for_section("[vps:vars]", "~/.ssh/id_ed25519_homelab_vps")

# ─── Versions ─────────────────────────────────────────────────────────────────

def load_pinned_versions() -> Dict[str, str]:
    try:
        with open(VERSIONS_FILE, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        tv = data.get("tresor_versions") or {}

        image_vers: Dict[str, str] = {}
        explicit_vers: Dict[str, str] = {}

        for key, value in tv.items():
            is_ver = str(key).endswith("_version")
            svc_raw = str(key).replace("_image", "").replace("_version", "")
            svc_raw = svc_raw.replace("minecraft_server", "paper")
            svc = svc_raw.replace("_", "-")

            v = str(value)
            if is_ver:
                explicit_vers[svc] = v
            else:
                tag = v.rsplit(":", 1)[-1] if ":" in v else v
                image_vers[svc] = tag

        return {**image_vers, **explicit_vers}
    except Exception:
        return {}

# ─── Playbook discovery ───────────────────────────────────────────────────────

def discover_services() -> Dict[str, List[str]]:
    services: Dict[str, List[str]] = {}
    for path in sorted(glob.glob(os.path.join(PLAYBOOKS_DIR, "*", "*.yml"))):
        parts = path.replace("\\", "/").split("/")
        if len(parts) < 3:
            continue
        service = parts[-2]
        action = parts[-1].replace(".yml", "")
        if service in SKIP_SERVICES:
            continue
        services.setdefault(service, []).append(action)
    return services

def _discover_folder_plays(folder: str) -> List[Tuple[str, str]]:
    plays: List[Tuple[str, str]] = []
    for path in sorted(glob.glob(os.path.join(PLAYBOOKS_DIR, folder, "*.yml"))):
        plays.append((folder, os.path.basename(path).replace(".yml", "")))
    return plays

def discover_infra_plays() -> List[Tuple[str, str]]:
    return _discover_folder_plays("infra")

def discover_vps_plays() -> List[Tuple[str, str]]:
    return _discover_folder_plays("vps")

def get_playbook_host(service: str, action: str) -> str:
    path = os.path.join(PLAYBOOKS_DIR, service, f"{action}.yml")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\s*hosts:\s*(\S+)", line)
                if m:
                    return m.group(1)
    except FileNotFoundError:
        pass
    return ""

# ─── SSH ──────────────────────────────────────────────────────────────────────

_ssh_clients: Dict[Tuple[str, str, str], paramiko.SSHClient] = {}
_last_ssh_error: Optional[str] = None

def _close_ssh_clients():
    for c in list(_ssh_clients.values()):
        try:
            c.close()
        except Exception:
            pass
    _ssh_clients.clear()

def _get_ssh(host: str, user: str, key: str) -> paramiko.SSHClient:
    key_path = os.path.expanduser(key)
    cache_key = (host, user, key_path)

    existing = _ssh_clients.get(cache_key)
    if existing:
        t = existing.get_transport()
        if t and t.is_active():
            return existing

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        c.connect(host, username=user, timeout=8, allow_agent=True, look_for_keys=True)
        _ssh_clients[cache_key] = c
        return c
    except Exception:
        pass

    c.connect(host, username=user, key_filename=key_path, timeout=8, allow_agent=False, look_for_keys=False)
    _ssh_clients[cache_key] = c
    return c

def ssh_run(host: str, user: str, key: str, script: str) -> str:
    global _last_ssh_error
    _last_ssh_error = None

    key_path = os.path.expanduser(key)

    # 1) Prefer system ssh (this matches your manual tests that work)
    try:
        cmd = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=accept-new",
            "-i", key_path,
            f"{user}@{host}",
            "bash -s",
        ]
        proc = subprocess.run(
            cmd,
            input=script,
            text=True,
            capture_output=True,
            timeout=25,
        )
        if proc.returncode == 0:
            return (proc.stdout or "").strip()

        err = (proc.stderr or "").strip()
        if err:
            _last_ssh_error = err.splitlines()[-1]
        else:
            _last_ssh_error = f"ssh exited rc={proc.returncode}"
    except FileNotFoundError:
        _last_ssh_error = "ssh client not found"
    except subprocess.TimeoutExpired:
        _last_ssh_error = "ssh probe timed out"
    except Exception as e:
        _last_ssh_error = f"{type(e).__name__}: {e}"

    # 2) Fallback to paramiko (keeps compatibility)
    try:
        stdin, stdout, stderr = _get_ssh(host, user, key_path).exec_command("bash -s")
        stdin.write(script)
        stdin.flush()
        stdin.channel.shutdown_write()
        out = stdout.read().decode(errors="replace")
        _ = stderr.read()
        if out.strip():
            _last_ssh_error = None
        return out.strip()
    except paramiko.ssh_exception.PasswordRequiredException:
        _last_ssh_error = (
            "Key is passphrase-encrypted and ssh-agent has no unlocked key.\n"
            f"Fix: ssh-add {key_path}"
        )
        _close_ssh_clients()
        return ""
    except Exception as e:
        _last_ssh_error = f"{type(e).__name__}: {e}"
        _close_ssh_clients()
        return ""

# ─── Helpers ──────────────────────────────────────────────────────────────────
def confirm_remove(service: str, action: str, host: str) -> bool:
    if action != "remove":
        return True

    msg = (
        f"[remove] {service} on {host}\n"
        "Are you sure you want to do this?"
    )

    try:
        ok = questionary.confirm(
            msg,
            default=False,
            qmark="",
            style=Q_STYLE,
        ).ask()
    except TypeError:
        ok = questionary.confirm(
            msg,
            default=False,
            style=Q_STYLE,
        ).ask()

    return bool(ok)

def _parse_pct(s: str) -> Optional[float]:
    s = s.strip()
    if not s.endswith("%"):
        return None
    try:
        return float(s[:-1])
    except ValueError:
        return None

def _service_sort_key(item: Tuple[str, List[str]]) -> Tuple[int, str]:
    svc, _actions = item
    net = str(SVC_META.get(svc, {}).get("net", ""))
    return (NET_ORDER.get(net, 99), svc)

def _metric_color(pct: Optional[float]) -> str:
    if pct is None:
        return C_DIM
    if pct < 60:
        return C_BAR_LOW
    if pct < 85:
        return C_BAR_MID
    return C_BAR_HIGH

def _compress_duration(raw: str) -> str:
    x = raw.strip()
    for pat, repl in [
        (r"(\d+)\s+seconds?", r"\1s"),
        (r"(\d+)\s+minutes?", r"\1m"),
        (r"(\d+)\s+hours?", r"\1h"),
        (r"(\d+)\s+days?", r"\1d"),
        (r"(\d+)\s+weeks?", r"\1w"),
        (r"(\d+)\s+months?", r"\1mo"),
        (r",\s*", " "),
    ]:
        x = re.sub(pat, repl, x, flags=re.IGNORECASE)
    parts = x.split()
    return " ".join(parts[:2]) if parts else "—"

def container_uptime_from_status(status: str) -> str:
    m = re.search(r"\bUp\s+(.+?)(?:\s*\(|$)", status, re.IGNORECASE)
    if m:
        return _compress_duration(m.group(1))

    m = re.search(r"\bExited\b.*?\s(\d.+?)\sago\b", status, re.IGNORECASE)
    if m:
        return f"{_compress_duration(m.group(1))} ago"

    return "—"



def _bytes_to_human(n: int) -> str:
    if n < 0:
        return "—"
    units = ["B", "K", "M", "G", "T", "P"]
    v = float(n)
    i = 0
    while v >= 1024.0 and i < len(units) - 1:
        v /= 1024.0
        i += 1
    if i == 0:
        return f"{int(v)}{units[i]}"
    if v >= 100:
        return f"{v:.0f}{units[i]}"
    if v >= 10:
        return f"{v:.1f}{units[i]}"
    return f"{v:.2f}{units[i]}"

def _clamp(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))

def _panel_bar_width(panel_width: int) -> int:
    # Panel width includes border+padding. Keep bars adaptive but bounded.
    content_w = max(20, panel_width - 8)
    return _clamp(content_w - 18, 8, 24)

def _ui_density() -> str:
    h = console.size.height
    if h < 26:
        return "tight"
    if h < 34:
        return "normal"
    return "spacious"

def dot(active: bool) -> str:
    c = C_DOT_ON if active else C_DOT_OFF
    return f"[{c}]●[/{c}]"

def bar(pct: Optional[float], width: int = 20) -> str:
    """
    Render a bar with sub-cell precision so very small values (e.g. 0.5%, 2.5%)
    still show visibly instead of rounding to zero.

    Visual tweak: when there is a partial remainder, draw a full colored block for
    that cell (instead of a thin partial glyph) so the bar looks solid at the edge.
    """
    if pct is None:
        return f"[{C_DIM}]{'░' * width}[/{C_DIM}]"

    pct = max(0.0, min(100.0, float(pct)))
    color = C_BAR_LOW if pct < 60 else (C_BAR_MID if pct < 85 else C_BAR_HIGH)

    # 8 subunits per cell (partial blocks)
    total_sub = (width * 8) * pct / 100.0
    full_cells = int(total_sub // 8)
    rem_sub = int(round(total_sub - (full_cells * 8)))

    # Handle rounding edge case (e.g. rem rounds to 8)
    if rem_sub >= 8:
        full_cells += 1
        rem_sub = 0

    # If pct > 0 but rounds to nothing, force a tiny visible sliver
    if pct > 0 and full_cells == 0 and rem_sub == 0:
        rem_sub = 1

    # Visual preference: make the remainder cell a full colored block (solid edge)
    partial = "█" if rem_sub else ""

    fill = ("█" * full_cells) + partial
    used_cells = full_cells + (1 if rem_sub else 0)
    empty_cells = max(0, width - used_cells)

    return f"[{color}]{fill}[/{color}][{C_DIM}]{'░' * empty_cells}[/{C_DIM}]"

def render_header() -> str:
    return (
        f"[bold {C_ACCENT}]>[/] "
        f"[bold {C_WHITE}]admin.circei[/]  "
        f"[{C_DIM}]//[/{C_DIM}]  "
        f"[{C_MID}]Tresor control panel[/{C_MID}]"
    )

# ─── Docker name matching (compose-proof) ──────────────────────────────────────

def _normalize_name(s: str) -> str:
    return s.lower().replace("_", "-").strip()

def best_container_match(canonical: str, names: List[str]) -> Optional[str]:
    if not canonical:
        return None
    cn = _normalize_name(canonical)
    norm = {n: _normalize_name(n) for n in names}

    for n, nn in norm.items():
        if nn == cn:
            return n

    candidates: List[Tuple[int, int, str]] = []
    for n, nn in norm.items():
        if nn.endswith(cn):
            candidates.append((0, len(n), n))
        elif f"-{cn}-" in f"-{nn}-":
            candidates.append((1, len(n), n))
        elif cn in nn:
            candidates.append((2, len(n), n))

    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]

def build_name_map(containers: Dict[str, Any]) -> Dict[str, str]:
    names = list(containers.keys())
    out: Dict[str, str] = {}
    for meta in SVC_META.values():
        canonical = meta.get("container")
        if not canonical:
            continue
        hit = best_container_match(str(canonical), names)
        if hit:
            out[str(canonical)] = hit
    return out

def resolve_container_name(svc: str, name_map: Dict[str, str]) -> Optional[str]:
    canonical = SVC_META.get(svc, {}).get("container")
    if canonical is None:
        return None
    canonical = str(canonical)
    return name_map.get(canonical, canonical)

def image_tag(image: str) -> str:
    return image.rsplit(":", 1)[-1] if ":" in image else "—"

# ─── Storage: physical disk + mounted FS usage ─────────────────────────────────

@dataclass
class DiskView:
    label: str
    disk_size_b: int
    fs_used_b: int
    fs_size_b: int
    fs_pcent: str
    mountpoint: str

def _label_from_mount(mountpoint: str) -> str:
    if mountpoint == "/":
        return "root"
    if mountpoint.startswith("/mnt/"):
        parts = mountpoint.split("/")
        return parts[2] if len(parts) > 2 else "mnt"
    return os.path.basename(mountpoint) or mountpoint

def build_disk_views(lsblk_rows: List[Dict[str, Any]], df_rows: List[Dict[str, Any]]) -> List[DiskView]:
    """
    lsblk_rows: [{name,type,size_b,mountpoint,pkname}]
    df_rows:    [{target,used_b,size_b,pcent}]
    Returns one DiskView per physical disk, picking the best relevant mountpoint.
    """
    df_by_target = {r["target"]: r for r in df_rows if isinstance(r.get("target"), str)}
    disks: Dict[str, int] = {}
    parts: List[Dict[str, Any]] = []

    for r in lsblk_rows:
        if r.get("type") == "disk":
            disks[str(r["name"])] = int(r.get("size_b") or 0)
        elif r.get("type") in ("part", "lvm"):
            parts.append(r)

    out: List[DiskView] = []
    for disk_name, disk_size_b in disks.items():
        candidates: List[Tuple[int, int, str]] = []
        for p in parts:
            if str(p.get("pkname") or "") != disk_name:
                continue
            mp = str(p.get("mountpoint") or "")
            if not mp:
                continue
            if mp not in df_by_target:
                continue
            prio = 0 if mp.startswith("/mnt/") else (1 if mp == "/" else 2)
            fs_size_b = int(df_by_target[mp].get("size_b") or 0)
            candidates.append((prio, -fs_size_b, mp))

        if not candidates:
            continue

        candidates.sort()
        mp = candidates[0][2]
        df = df_by_target[mp]
        fs_used_b = int(df.get("used_b") or 0)
        fs_size_b = int(df.get("size_b") or 0)
        fs_pcent = str(df.get("pcent") or "").strip()
        out.append(
            DiskView(
                label=_label_from_mount(mp),
                disk_size_b=disk_size_b,
                fs_used_b=fs_used_b,
                fs_size_b=fs_size_b,
                fs_pcent=fs_pcent,
                mountpoint=mp,
            )
        )

    out.sort(key=lambda d: d.disk_size_b, reverse=True)
    return out

def format_disk_views(disks: List[DiskView], max_items: int = 3, max_width: Optional[int] = None) -> str:
    """
    Shows disk usage using the physical disk size as the displayed total when it
    differs noticeably from the mounted FS size (e.g. LVM/partitioned layouts),
    and avoids duplicating that value as a suffix.
    Soft-wraps by disk item when max_width is provided (for narrow panels).
    """
    items: List[str] = []
    for d in disks[:max_items]:
        use_physical_total = (
            d.disk_size_b > 0
            and d.fs_size_b > 0
            and abs(d.disk_size_b - d.fs_size_b) / d.disk_size_b >= 0.10
        )

        shown_total_b = d.disk_size_b if use_physical_total else d.fs_size_b

        # Recompute displayed percent against the displayed total (so it stays consistent)
        if shown_total_b > 0:
            shown_pct = int(round((d.fs_used_b / shown_total_b) * 100))
            pcent_str = f"{shown_pct}%"
        else:
            pcent_str = d.fs_pcent or "?"

        fs = f"{_bytes_to_human(d.fs_used_b)}/{_bytes_to_human(shown_total_b)} ({pcent_str})"

        items.append(f"[{C_DIM}]{d.label}[/{C_DIM}] [{C_WHITE}]{fs}[/{C_WHITE}]")

    if not items:
        return f"[{C_DIM}]disk[/{C_DIM}] —"

    if not max_width:
        return "   ".join(items)

    def _plain_len(s: str) -> int:
        # rough strip of Rich markup tags for width budgeting
        return len(re.sub(r"\[[^\]]*?\]", "", s))

    lines: List[str] = []
    cur = ""
    for item in items:
        sep = "   " if cur else ""
        if cur and (_plain_len(cur) + _plain_len(sep) + _plain_len(item) > max_width):
            lines.append(cur)
            cur = item
        else:
            cur = f"{cur}{sep}{item}" if cur else item

    if cur:
        lines.append(cur)

    return "\n".join(lines)

# ─── Fetch: Tresor ────────────────────────────────────────────────────────────
def _tresor_runtime_probe_fallback(host_ip: str, result: Dict[str, Any]) -> None:
    """
    Fallback probe for Docker/WG using the same structure that worked manually.
    Fills/overwrites result["containers"], result["metrics"], and WG fields when possible.
    """
    script = r"""
export LC_ALL=C
set +e

echo "=WHOAMI="
id
groups

echo "=DOCKER_PS="
FMT='{{.Names}}|{{.Image}}|{{.Status}}'
DOCKER_OUT=""
if DOCKER_OUT=$(docker ps -a --format "$FMT" 2>/tmp/tctl_docker_err); then
  echo "__ok__|plain"
elif DOCKER_OUT=$(sudo -n docker ps -a --format "$FMT" 2>/tmp/tctl_docker_err); then
  echo "__ok__|sudo-docker"
elif DOCKER_OUT=$(sudo -n /usr/bin/docker ps -a --format "$FMT" 2>/tmp/tctl_docker_err); then
  echo "__ok__|sudo-usrbin"
else
  rc=$?
  echo "__err__|rc=$rc|$(tail -n 1 /tmp/tctl_docker_err 2>/dev/null)"
fi
if [ -n "$DOCKER_OUT" ]; then
  printf '%s\n' "$DOCKER_OUT"
fi

echo "=DOCKER_STATS="
SFMT='{{.Name}}|{{.CPUPerc}}|{{.MemPerc}}'
STATS_OUT=""
if STATS_OUT=$(docker stats --no-stream --format "$SFMT" 2>/tmp/tctl_stats_err); then
  echo "__ok__|plain"
elif STATS_OUT=$(sudo -n docker stats --no-stream --format "$SFMT" 2>/tmp/tctl_stats_err); then
  echo "__ok__|sudo-docker"
elif STATS_OUT=$(sudo -n /usr/bin/docker stats --no-stream --format "$SFMT" 2>/tmp/tctl_stats_err); then
  echo "__ok__|sudo-usrbin"
else
  rc=$?
  echo "__err__|rc=$rc|$(tail -n 1 /tmp/tctl_stats_err 2>/dev/null)"
fi
if [ -n "$STATS_OUT" ]; then
  printf '%s\n' "$STATS_OUT"
fi

echo "=WG="
WG_ERR=$(mktemp)
if WG_OUT=$(sudo -n wg show wg0 2>"$WG_ERR"); then
  echo "__ok__|sudo"
elif WG_OUT=$(wg show wg0 2>"$WG_ERR"); then
  echo "__ok__|plain"
else
  rc=$?
  echo "__err__|rc=$rc|$(tail -n 1 "$WG_ERR" 2>/dev/null)"
  WG_OUT=""
fi
if [ -n "$WG_OUT" ]; then
  echo "$WG_OUT" | awk '/latest handshake:/{hs=$3" "$4} END{if(hs) printf "up|%s\n",hs; else print "up|no handshake yet"}'
fi
rm -f "$WG_ERR"

echo "=END="
"""
    raw = ssh_run(host_ip, "ansible", _tresor_ssh_key(), script)

    # Helpful debug if it still fails silently
    try:
        with open("/tmp/tresor-ctl-last-runtime-probe.txt", "w", encoding="utf-8") as f:
            f.write(raw or "")
    except Exception:
        pass

    if not raw:
        if not result.get("docker_error"):
            result["docker_error"] = _last_ssh_error or "runtime probe failed"
        return

    section: Optional[str] = None
    saw_docker_ps = False
    saw_docker_stats = False

    # We intentionally overwrite parsed runtime data if fallback returns good data
    containers_new: Dict[str, Any] = {}
    metrics_new: Dict[str, Any] = {}

    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("=") and s.endswith("="):
            section = s.strip("=").lower()
            continue
        if not s or section == "end":
            continue

        if section == "docker_ps":
            saw_docker_ps = True
            if s.startswith("__ok__"):
                continue
            if s.startswith("__err__") or s.startswith("__no_perms__"):
                msg = s.split("|", 1)[1].strip() if "|" in s else "docker ps probe failed"
                low = msg.lower()
                result["docker_error"] = msg
                if any(x in low for x in ("permission denied", "a password is required", "not in the docker group")):
                    result["docker_no_perms"] = True
                continue
            parts = s.split("|", 2)
            if len(parts) == 3:
                name, image, status = [p.strip() for p in parts]
                containers_new[name] = {"image": image, "status": status}

        elif section == "docker_stats":
            saw_docker_stats = True
            if s.startswith("__ok__"):
                continue
            if s.startswith("__err__") or s.startswith("__no_perms__"):
                msg = s.split("|", 1)[1].strip() if "|" in s else ""
                low = msg.lower()
                if any(x in low for x in ("permission denied", "a password is required", "not in the docker group")):
                    result["docker_no_perms"] = True
                continue
            parts = s.split("|", 2)
            if len(parts) == 3:
                name = parts[0].strip()
                metrics_new[name] = {"cpu": _parse_pct(parts[1]), "mem": _parse_pct(parts[2])}

        elif section == "wg":
            # This probe emits a status line first (__ok__/__err__), then up|...
            if s.startswith("__ok__"):
                continue
            if s.startswith("__err__"):
                msg = s.split("|", 1)[1].strip() if "|" in s else "wg probe failed"
                result["wg_status"] = "err"
                result["wg_handshake"] = msg
                continue
            parts = s.split("|", 1)
            if len(parts) >= 1:
                result["wg_status"] = parts[0].strip()
                result["wg_handshake"] = parts[1].strip() if len(parts) > 1 else "—"

    if containers_new:
        result["containers"] = containers_new
        # clear stale error if recovered
        result["docker_error"] = ""
        result["docker_no_perms"] = False

    if metrics_new:
        result["metrics"] = metrics_new

    if not result.get("containers"):
        if not result.get("docker_error"):
            if not saw_docker_ps:
                result["docker_error"] = "docker probe missing DOCKER_PS section"
            elif saw_docker_ps and not saw_docker_stats:
                result["docker_error"] = "docker probe missing DOCKER_STATS section"
            else:
                result["docker_error"] = "docker probe returned no container rows"


def fetch_tresor(host_ip: str) -> Dict[str, Any]:
    script = r"""
export LC_ALL=C
set +e

echo "=HOSTNAME="
hostname

echo "=UPTIME="
uptime -p 2>/dev/null | sed 's/^up //' || echo "?"

echo "=CPU="
S1=$(awk '/^cpu /{print $2,$3,$4,$5,$6,$7,$8; exit}' /proc/stat)
sleep 0.10
S2=$(awk '/^cpu /{print $2,$3,$4,$5,$6,$7,$8; exit}' /proc/stat)
awk -v s1="$S1" -v s2="$S2" 'BEGIN{
  split(s1,a," "); split(s2,b," ")
  t1=a[1]+a[2]+a[3]+a[4]+a[5]+a[6]+a[7]
  t2=b[1]+b[2]+b[3]+b[4]+b[5]+b[6]+b[7]
  idle1=a[4]; idle2=b[4]
  dt=t2-t1
  if(dt>0) printf "%.1f\n", (dt-(idle2-idle1))*100/dt; else print "0"
}'

echo "=MEM="
awk '/^MemTotal:/{t=$2} /^MemAvailable:/{a=$2} END{if(t>0){u=t-a; printf "%d/%d\n",u/1024,t/1024}}' /proc/meminfo

echo "=LSBLK="
lsblk -b -o NAME,TYPE,SIZE,MOUNTPOINT,PKNAME -nr 2>/dev/null | awk '{print $1 "|" $2 "|" $3 "|" $4 "|" $5}'

echo "=DF="
df -B1 -x tmpfs -x devtmpfs --output=source,target,used,size,pcent 2>/dev/null | tail -n +2 | awk '{print $1 "|" $2 "|" $3 "|" $4 "|" $5}'

echo "=WG="
WG_ERR=$(mktemp)
if WG_OUT=$(sudo -n wg show wg0 2>"$WG_ERR"); then
  if [ -n "$WG_OUT" ]; then
    echo "$WG_OUT" | awk '/latest handshake:/{hs=$3" "$4} END{if(hs) printf "up|%s\n",hs; else print "up|no handshake yet"}'
  else
    echo "up|no handshake yet"
  fi
elif WG_OUT=$(wg show wg0 2>"$WG_ERR"); then
  if [ -n "$WG_OUT" ]; then
    echo "$WG_OUT" | awk '/latest handshake:/{hs=$3" "$4} END{if(hs) printf "up|%s\n",hs; else print "up|no handshake yet"}'
  else
    echo "up|no handshake yet"
  fi
else
  echo "err|$(tail -n 1 "$WG_ERR" 2>/dev/null)"
fi
rm -f "$WG_ERR"

echo "=DOCKER_PS="
FMT='{{.Names}}|{{.Image}}|{{.Status}}'
DOCKER_OUT=""
if DOCKER_OUT=$(docker ps -a --format "$FMT" 2>/tmp/tctl_docker_err); then
  echo "__ok__|plain"
elif DOCKER_OUT=$(sudo -n docker ps -a --format "$FMT" 2>/tmp/tctl_docker_err); then
  echo "__ok__|sudo-docker"
elif DOCKER_OUT=$(sudo -n /usr/bin/docker ps -a --format "$FMT" 2>/tmp/tctl_docker_err); then
  echo "__ok__|sudo-usrbin"
else
  echo "__err__|$(tail -n 1 /tmp/tctl_docker_err 2>/dev/null)"
fi
if [ -n "$DOCKER_OUT" ]; then
  printf '%s\n' "$DOCKER_OUT"
fi

echo "=DOCKER_STATS="
SFMT='{{.Name}}|{{.CPUPerc}}|{{.MemPerc}}'
STATS_OUT=""
if STATS_OUT=$(docker stats --no-stream --format "$SFMT" 2>/tmp/tctl_stats_err); then
  echo "__ok__|plain"
elif STATS_OUT=$(sudo -n docker stats --no-stream --format "$SFMT" 2>/tmp/tctl_stats_err); then
  echo "__ok__|sudo-docker"
elif STATS_OUT=$(sudo -n /usr/bin/docker stats --no-stream --format "$SFMT" 2>/tmp/tctl_stats_err); then
  echo "__ok__|sudo-usrbin"
else
  echo "__err__|$(tail -n 1 /tmp/tctl_stats_err 2>/dev/null)"
fi
if [ -n "$STATS_OUT" ]; then
  printf '%s\n' "$STATS_OUT"
fi

echo "=END="
"""
    raw = ssh_run(host_ip, "ansible", _tresor_ssh_key(), script)

    result: Dict[str, Any] = {
        "containers": {},
        "metrics": {},
        "name_map": {},
        "lsblk": [],
        "df": [],
        "ip": host_ip,
        "cpu": None,
        "mem": None,
        "uptime": None,
        "hostname": "tresor",
        "wg_status": "?",
        "wg_handshake": "—",
        "docker_no_perms": False,
        "docker_error": "",
        "connected": bool(raw),
        "ssh_error": _last_ssh_error,
        "ssh_target": f"ansible@{host_ip}",
    }
    if not raw:
        return result

    section: Optional[str] = None
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("=") and s.endswith("="):
            section = s.strip("=").lower()
            continue
        if not s or section == "end":
            continue

        if section == "hostname":
            result["hostname"] = s
        elif section == "uptime":
            result["uptime"] = s
        elif section == "cpu":
            try:
                result["cpu"] = float(s)
            except ValueError:
                pass
        elif section == "mem":
            result["mem"] = s
        elif section == "lsblk":
            parts = s.split("|")
            if len(parts) >= 3:
                name, typ, size_b = parts[0], parts[1], parts[2]
                mp = parts[3] if len(parts) > 3 else ""
                pk = parts[4] if len(parts) > 4 else ""
                try:
                    result["lsblk"].append(
                        {"name": name, "type": typ, "size_b": int(size_b), "mountpoint": mp, "pkname": pk}
                    )
                except ValueError:
                    continue
        elif section == "df":
            parts = s.split("|")
            if len(parts) == 5:
                src, tgt, used_b, size_b, pcent = parts
                try:
                    result["df"].append(
                        {"source": src, "target": tgt, "used_b": int(used_b), "size_b": int(size_b), "pcent": pcent}
                    )
                except ValueError:
                    continue
        elif section == "wg":
            parts = s.split("|", 1)
            result["wg_status"] = parts[0].strip()
            result["wg_handshake"] = parts[1].strip() if len(parts) > 1 else "—"
        elif section == "docker_ps":
            if s.startswith("__ok__"):
                continue
            if s.startswith("__no_perms__") or s.startswith("__err__"):
                msg = s.split("|", 1)[1].strip() if "|" in s else "docker probe failed"
                result["docker_error"] = msg
                low = msg.lower()
                if any(x in low for x in ("permission denied", "a password is required", "not in the docker group")):
                    result["docker_no_perms"] = True
                continue
            parts = s.split("|", 2)
            if len(parts) == 3:
                name, image, status = [p.strip() for p in parts]
                result["containers"][name] = {"image": image, "status": status}
        elif section == "docker_stats":
            if s.startswith("__ok__"):
                continue
            if s.startswith("__no_perms__") or s.startswith("__err__"):
                msg = s.split("|", 1)[1].strip() if "|" in s else ""
                low = msg.lower()
                if any(x in low for x in ("permission denied", "a password is required", "not in the docker group")):
                    result["docker_no_perms"] = True
                continue
            parts = s.split("|", 2)
            if len(parts) == 3:
                name = parts[0].strip()
                result["metrics"][name] = {"cpu": _parse_pct(parts[1]), "mem": _parse_pct(parts[2])}

    # Fallback runtime probe only if Docker container state is missing entirely.
    # Avoid a second heavy probe just because docker stats/metrics are missing.
    if not result["containers"]:
        _tresor_runtime_probe_fallback(host_ip, result)

    if not result["containers"] and not result["docker_error"]:
        result["docker_error"] = "docker probe returned no records"
        
    result["name_map"] = build_name_map(result["containers"])
    return result

# ─── Fetch: VPS ───────────────────────────────────────────────────────────────

def fetch_vps(host_ip: str) -> Dict[str, Any]:
    script = r"""
export LC_ALL=C

echo "=HOSTNAME="
hostname

echo "=UPTIME="
uptime -p 2>/dev/null | sed 's/^up //' || echo "?"

echo "=CPU="
S1=$(awk '/^cpu /{print $2,$3,$4,$5,$6,$7,$8; exit}' /proc/stat)
sleep 0.10
S2=$(awk '/^cpu /{print $2,$3,$4,$5,$6,$7,$8; exit}' /proc/stat)
awk -v s1="$S1" -v s2="$S2" 'BEGIN{
  split(s1,a," "); split(s2,b," ")
  t1=a[1]+a[2]+a[3]+a[4]+a[5]+a[6]+a[7]
  t2=b[1]+b[2]+b[3]+b[4]+b[5]+b[6]+b[7]
  idle1=a[4]; idle2=b[4]
  dt=t2-t1
  if(dt>0) printf "%.1f\n", (dt-(idle2-idle1))*100/dt; else print "0"
}'

echo "=MEM="
awk '/^MemTotal:/{t=$2} /^MemAvailable:/{a=$2} END{if(t>0){u=t-a; printf "%d/%d\n",u/1024,t/1024}}' /proc/meminfo

echo "=DF="
df -B1 -x tmpfs -x devtmpfs --output=target,used,size,pcent 2>/dev/null | tail -n +2 | awk '$1=="/"{print $1 "|" $2 "|" $3 "|" $4; exit}'

echo "=NGINX="
systemctl is-active nginx 2>/dev/null || echo "inactive"

echo "=VELOCITY="
systemctl is-active velocity 2>/dev/null || echo "inactive"

echo "=WG="
WG_ERR=$(mktemp)
if WG_OUT=$(sudo -n wg show wg0 2>"$WG_ERR"); then
  if [ -n "$WG_OUT" ]; then
    echo "$WG_OUT" | awk '/latest handshake:/{hs=$3" "$4} END{if(hs) printf "up|%s\n",hs; else print "up|no handshake yet"}'
  else
    echo "up|no handshake yet"
  fi
elif WG_OUT=$(wg show wg0 2>"$WG_ERR"); then
  if [ -n "$WG_OUT" ]; then
    echo "$WG_OUT" | awk '/latest handshake:/{hs=$3" "$4} END{if(hs) printf "up|%s\n",hs; else print "up|no handshake yet"}'
  else
    echo "up|no handshake yet"
  fi
else
  echo "err|$(tail -n 1 "$WG_ERR" 2>/dev/null)"
fi
rm -f "$WG_ERR"

echo "=END="
"""
    raw = ssh_run(host_ip, "ansible", _vps_ssh_key(), script)

    result: Dict[str, Any] = {
        "hostname": "tresor-vps",
        "uptime": None,
        "cpu": None,
        "mem": None,
        "disk_root": None,  # {used_b,size_b,pcent}
        "nginx": "?",
        "velocity": "?",
        "wg_status": "?",
        "wg_handshake": "—",
        "connected": bool(raw),
        "ssh_error": _last_ssh_error,
        "ssh_target": f"ansible@{host_ip}",
    }
    if not raw:
        return result

    section: Optional[str] = None
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("=") and s.endswith("="):
            section = s.strip("=").lower()
            continue
        if not s or section == "end":
            continue

        if section == "hostname":
            result["hostname"] = s
        elif section == "uptime":
            result["uptime"] = s
        elif section == "cpu":
            try:
                result["cpu"] = float(s)
            except ValueError:
                pass
        elif section == "mem":
            result["mem"] = s
        elif section == "df":
            parts = s.split("|")
            if len(parts) == 4:
                try:
                    result["disk_root"] = {"used_b": int(parts[1]), "size_b": int(parts[2]), "pcent": parts[3]}
                except ValueError:
                    pass
        elif section == "nginx":
            result["nginx"] = s
        elif section == "velocity":
            result["velocity"] = s
        elif section == "wg":
            parts = s.split("|", 1)
            result["wg_status"] = parts[0].strip()
            result["wg_handshake"] = parts[1].strip() if len(parts) > 1 else "—"

    return result

# ─── Rendering ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TableLayout:
    mode: str              # full | mid | compact | tiny
    w_svc: int
    w_ver: int
    w_st: int
    show_metrics: bool
    show_uptime: bool
    w_mem: int
    w_cpu: int
    w_up: int


def compute_layout(term_w: int) -> TableLayout:
    # Reserve headroom because prompt_toolkit/questionary may wrap earlier than Rich.
    w = max(40, term_w - 4)

    # Keep metrics longer than before. Only start dropping them on actually narrow widths.
    if w >= 90:
        return TableLayout("full", 22, 14, 14, True, True, 6, 6, 10)
    if w >= 74:
        # still show metrics + uptime, just tighten widths a bit
        return TableLayout("mid", 20, 12, 12, True, True, 5, 5, 8)
    if w >= 62:
        # drop metrics first, keep uptime for one more tier
        return TableLayout("compact", 18, 10, 10, False, True, 0, 0, 8)
    return TableLayout("tiny", 16, 0, 10, False, False, 0, 0, 0)


def _panel_widths() -> Tuple[int, bool]:
    w = console.size.width
    gap = 3
    min_panel = 56
    desired = 76
    can_side = w >= (min_panel * 2 + gap)
    if can_side:
        each = max(min_panel, min(desired, (w - gap) // 2))
        return each, True
    return max(min_panel, min(desired, w - 2)), False

def colored_badge(net: str) -> str:
    sym = NET_BADGE.get(net, " ")
    col = NET_COLOR.get(net, C_DIM)
    return f"[{col}]{sym}[/{col}]"

def _fit(s: str, w: int) -> str:
    if w <= 0:
        return ""
    if len(s) <= w:
        return s.ljust(w)
    if w <= 1:
        return s[:w]
    return (s[: w - 1] + "…")

def _trim_fragments(chunks: List[Tuple[str, str]], max_chars: int) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    used = 0
    for style, text in chunks:
        if used >= max_chars:
            break
        remain = max_chars - used
        if len(text) <= remain:
            out.append((style, text))
            used += len(text)
        else:
            if remain >= 1:
                trimmed = text[: max(0, remain - 1)] + ("…" if remain > 0 else "")
                out.append((style, trimmed))
                used += len(trimmed)
            break
    return out

def resolve_version(svc: str, containers: Dict[str, Any], name_map: Dict[str, str], pinned: Dict[str, str]) -> str:
    cname = resolve_container_name(svc, name_map)
    if cname and cname in containers:
        tag = image_tag(containers[cname]["image"])
        if tag and tag not in ("—", "latest"):
            return tag
    if pinned.get(svc):
        return pinned[svc]
    if svc in OWN_SERVICES:
        return "v0"
    return "—"

def service_state(
    svc: str,
    actions: List[str],
    containers: Dict[str, Any],
    name_map: Dict[str, str],
) -> Tuple[str, str, str, str]:
    cname = resolve_container_name(svc, name_map)
    if cname and cname in containers:
        st = containers[cname]["status"]
        s = st.lower()
        upt = container_uptime_from_status(st)
        if s.startswith("up"):
            return "●", "running", STATE_COLOR["running"], upt
        if s.startswith("exited"):
            return "○", "exited", STATE_COLOR["exited"], upt
        if s.startswith("restart"):
            return "↺", "restart", STATE_COLOR["restart"], upt
        if s.startswith("created"):
            return "◌", "created", STATE_COLOR["created"], upt
        return "?", s[:8], C_DIM, "—"

    if svc in CRON_SERVICES:
        return "◷", "cron", STATE_COLOR["cron"], "—"

    return "○", "stopped", STATE_COLOR["stopped"], "—"

def render_tresor_panel(data: Dict[str, Any], width: int) -> Panel:
    hostname = data.get("hostname", "tresor")
    connected = data.get("connected", False)
    density = _ui_density()
    panel_bar_w = _panel_bar_width(width)
    compact_panel = width < 72

    if not connected:
        inner = (
            f"[bold {C_WHITE}]{hostname}[/]   [bold {C_RED}]✗ unreachable[/]\n"
            f"[{C_DIM}]{data.get('ssh_target', '?')}[/{C_DIM}]\n"
            f"[{C_RED}]{data.get('ssh_error') or 'unknown error'}[/{C_RED}]"
        )
        return Panel(inner, border_style=C_RED, padding=(1, 2), width=width)

    containers = data.get("containers") or {}
    n_total = len(containers)
    n_running = sum(1 for c in containers.values() if str(c.get("status", "")).lower().startswith("up"))

    up_raw = data.get("uptime") or "?"
    up_str = _compress_duration(up_raw) if compact_panel else up_raw
    line1 = f"[bold {C_WHITE}]{hostname}[/]   [{C_DIM}]up {up_str}[/{C_DIM}]"

    if n_total == 0 and data.get("docker_error"):
        err = data.get("docker_error") or "docker probe failed"
        ctr_label = f"[{C_BAR_MID}]● docker: {err}[/{C_BAR_MID}]"
    elif n_total == 0 and data.get("docker_no_perms"):
        err = data.get("docker_error") or "no access"
        ctr_label = f"[{C_BAR_MID}]● docker: {err}[/{C_BAR_MID}]"
    elif n_total == 0:
        ctr_label = f"[{C_DIM}]● 0/0 containers[/{C_DIM}]"
    elif n_running == n_total:
        ctr_label = f"[{C_BAR_LOW}]● {n_running}/{n_total} containers[/{C_BAR_LOW}]"
    elif n_running > 0:
        ctr_label = f"[{C_BAR_MID}]● {n_running}/{n_total} containers[/{C_BAR_MID}]"
    else:
        ctr_label = f"[{C_RED}]● {n_running}/{n_total} containers[/{C_RED}]"

    wg_st = data.get("wg_status", "?")
    wg_hs = data.get("wg_handshake", "—")
    if wg_st == "up":
        wg_c = C_BAR_LOW
        wg_detail = f" ({_compress_duration(wg_hs) if compact_panel else wg_hs})"
    elif wg_st == "err":
        wg_c = C_BAR_MID
        wg_detail = f" ({wg_hs})" if wg_hs and wg_hs != "—" else ""
    else:
        wg_c = C_RED
        wg_detail = ""
    line2 = f"{ctr_label}   [{wg_c}]●[/{wg_c}] [{C_DIM}]wg0{wg_detail}[/{C_DIM}]"

    cpu_val = data.get("cpu")
    cpu_line = (
        f"[{C_DIM}]cpu[/{C_DIM}]  {bar(cpu_val, width=panel_bar_w)}  [{C_WHITE}]{cpu_val:5.1f}%[/{C_WHITE}]"
        if cpu_val is not None
        else f"[{C_DIM}]cpu  {'░' * max(8, panel_bar_w)}     —[/{C_DIM}]"
    )

    mem_raw = data.get("mem")
    if mem_raw:
        try:
            u_mb, t_mb = (float(x) for x in str(mem_raw).split("/"))
            pct = u_mb / t_mb * 100 if t_mb > 0 else 0
            mem_line = f"[{C_DIM}]mem[/{C_DIM}]  {bar(pct, width=panel_bar_w)}  [{C_WHITE}]{u_mb/1024:.1f}G/{t_mb/1024:.1f}G[/{C_WHITE}]"
        except Exception:
            mem_line = f"[{C_DIM}]mem  {'░' * max(8, panel_bar_w)}     {mem_raw}[/{C_DIM}]"
    else:
        mem_line = f"[{C_DIM}]mem  {'░' * max(8, panel_bar_w)}     —[/{C_DIM}]"

    disks = build_disk_views(data.get("lsblk") or [], data.get("df") or [])
    disk_block = format_disk_views(disks, max_items=3, max_width=max(24, width - 8))

    spacer = "\n" if density != "tight" else ""
    inner = f"{line1}\n{line2}{spacer}\n\n{cpu_line}\n{mem_line}{spacer}\n\n{disk_block}"
    return Panel(inner, border_style=C_BORDER, padding=(1, 2), width=width)

def render_vps_panel(data: Dict[str, Any], width: int) -> Panel:
    connected = data.get("connected", False)
    hostname = data.get("hostname", "tresor-vps")
    density = _ui_density()
    panel_bar_w = _panel_bar_width(width)
    compact_panel = width < 72

    if not connected:
        inner = (
            f"[bold {C_WHITE}]{hostname}[/]  1.2.3.4   [bold {C_RED}]✗ unreachable[/]\n"
            f"[{C_DIM}]{data.get('ssh_target', '?')}[/{C_DIM}]\n"
            f"[{C_RED}]{data.get('ssh_error') or 'unreachable'}[/{C_RED}]"
        )
        return Panel(inner, border_style=C_RED, padding=(1, 2), width=width)

    up_raw = data.get("uptime") or "?"
    up_str = _compress_duration(up_raw) if compact_panel else up_raw
    line1 = f"[bold {C_WHITE}]{hostname}[/]  [{C_DIM}]1.2.3.4  up {up_str}[/{C_DIM}]"

    nginx = data.get("nginx", "?")
    velocity = data.get("velocity", "?")
    wg_st = data.get("wg_status", "?")
    wg_hs = data.get("wg_handshake", "—")
    wg_ok = (wg_st == "up")
    wg_hs_show = _compress_duration(wg_hs) if (compact_panel and wg_st == "up") else wg_hs
    wg_label = f"wg0 ({wg_hs_show})" if wg_st == "up" else ("wg0 (probe err)" if wg_st == "err" else "wg0")
    line2 = (
        f"{dot(nginx == 'active')} [{C_DIM}]nginx[/{C_DIM}]   "
        f"{dot(velocity == 'active')} [{C_DIM}]velocity[/{C_DIM}]   "
        f"{dot(wg_ok)} [{C_DIM}]{wg_label}[/{C_DIM}]"
    )

    cpu_val = data.get("cpu")
    cpu_line = (
        f"[{C_DIM}]cpu[/{C_DIM}]  {bar(cpu_val, width=panel_bar_w)}  [{C_WHITE}]{cpu_val:5.1f}%[/{C_WHITE}]"
        if cpu_val is not None
        else f"[{C_DIM}]cpu  {'░' * max(8, panel_bar_w)}     —[/{C_DIM}]"
    )

    mem_raw = data.get("mem")
    if mem_raw:
        try:
            u_mb, t_mb = (float(x) for x in str(mem_raw).split("/"))
            pct = u_mb / t_mb * 100 if t_mb > 0 else 0
            mem_line = f"[{C_DIM}]mem[/{C_DIM}]  {bar(pct, width=panel_bar_w)}  [{C_WHITE}]{u_mb/1024:.1f}G/{t_mb/1024:.1f}G[/{C_WHITE}]"
        except Exception:
            mem_line = f"[{C_DIM}]mem  {'░' * max(8, panel_bar_w)}     {mem_raw}[/{C_DIM}]"
    else:
        mem_line = f"[{C_DIM}]mem  {'░' * max(8, panel_bar_w)}     —[/{C_DIM}]"

    disk_root = data.get("disk_root")
    if disk_root:
        disk_line = f"[{C_DIM}]disk[/{C_DIM}] [{C_WHITE}]{_bytes_to_human(disk_root['used_b'])}/{_bytes_to_human(disk_root['size_b'])} ({disk_root['pcent']})[/{C_WHITE}]"
    else:
        disk_line = f"[{C_DIM}]disk[/{C_DIM}] —"

    spacer = "\n" if density != "tight" else ""
    inner = f"{line1}\n{line2}{spacer}\n\n{cpu_line}\n{mem_line}{spacer}\n\n{disk_line}"
    return Panel(inner, border_style=C_BORDER, padding=(1, 2), width=width)

def service_row(
    svc: str,
    actions: List[str],
    containers: Dict[str, Any],
    metrics: Dict[str, Any],
    name_map: Dict[str, str],
    pinned: Dict[str, str],
    layout: TableLayout,
):
    sym, label, state_color, upt = service_state(svc, actions, containers, name_map)
    ver = resolve_version(svc, containers, name_map, pinned)
    net = str(SVC_META.get(svc, {}).get("net", ""))
    badge = NET_BADGE.get(net, " ")
    badge_color = NET_COLOR.get(net, C_DIM)

    cpu_s, mem_s = "—", "—"
    cpu_color, mem_color = C_DIM, C_DIM

    cname = resolve_container_name(svc, name_map)
    if cname:
        m = metrics.get(cname)
        if m:
            cpu = m.get("cpu")
            mem = m.get("mem")
            if cpu is not None:
                cpu_s = f"{int(round(cpu)):>3}%"
                cpu_color = _metric_color(cpu)
            if mem is not None:
                mem_s = f"{int(round(mem)):>3}%"
                mem_color = _metric_color(mem)

    # Column order:
    # service | version | state | uptime | mem | cpu
    chunks: List[Tuple[str, str]] = [
        ("", "  "),
        (f"fg:{badge_color}", badge),
        ("", " "),
        (f"fg:{C_MID}", _fit(svc, layout.w_svc - 2)),
    ]

    if layout.w_ver > 0:
        chunks += [
            ("", " "),
            (f"fg:{C_MID}", _fit(ver, layout.w_ver)),
        ]

    chunks += [
        ("", " "),
        (f"fg:{state_color}", f"{sym} {_fit(label, layout.w_st - 2)}"),
    ]

    if layout.show_uptime:
        chunks += [
            ("", " "),
            (f"fg:{C_DIM}", _fit(upt, layout.w_up)),
        ]

    if layout.show_metrics:
        chunks += [
            ("", " "),
            (f"fg:{mem_color}", _fit(mem_s, layout.w_mem)),
            ("", " "),
            (f"fg:{cpu_color}", _fit(cpu_s, layout.w_cpu)),
        ]

    # Hard cap row width so prompt_toolkit wraps less aggressively on narrower terminals
    max_row = max(24, console.size.width - 6)
    return _trim_fragments(chunks, max_row)

def col_header(layout: TableLayout) -> str:
    base = f"    {'service':<{layout.w_svc - 2}}"

    if layout.w_ver > 0:
        base += f" {'version':<{layout.w_ver}}"

    base += f" {'state':<{layout.w_st}}"

    if layout.show_uptime:
        base += f" {'uptime':<{layout.w_up}}"

    if layout.show_metrics:
        base += f" {'mem':<{layout.w_mem}} {'cpu':<{layout.w_cpu}}"

    return base

# ─── Host picker ──────────────────────────────────────────────────────────────

def build_host_choices(hosts: Dict[str, Dict[str, str]]) -> List[Choice]:
    out: List[Choice] = []
    for name, info in hosts.items():
        out.append(Choice(title=f"  {name:<14} {info['group']:<5} {info['ip'] or '?'}", value=name))
    out.append(Choice(title="  cancel", value="__cancel__"))
    return out

def resolve_host(service: str, action: str, host_choices: List[Choice]):
    declared = get_playbook_host(service, action)
    if declared and declared not in ("all", ""):
        return declared, False

    host = q_select("", host_choices)
    if host is None or host == "__cancel__":
        return None, False
    return host, True

# ─── Runner ───────────────────────────────────────────────────────────────────

def run_playbook(service: str, action: str, host_choices: List[Choice]):
    host, needs_limit = resolve_host(service, action, host_choices)
    if host is None:
        return

    # Confirm destructive action
    if not confirm_remove(service, action, host):
        console.print(f"  [{C_DIM}]remove cancelled.[/{C_DIM}]")
        console.print()
        return

    playbook = f"{PLAYBOOKS_DIR}/{service}/{action}.yml"
    cmd = [ANSIBLE_CMD, "-i", INVENTORY, playbook]
    if needs_limit:
        cmd += ["--limit", host]

    console.print()
    console.print(
        f"  [{C_DIM}]{'─' * 12}[/{C_DIM}]  "
        f"[{C_ACCENT}]{service}[/{C_ACCENT}] "
        f"[{C_DIM}]→[/{C_DIM}] "
        f"[{C_WHITE}]{action}[/{C_WHITE}]  "
        f"[{C_DIM}]@ {host}[/{C_DIM}]  "
        f"[{C_DIM}]{'─' * 12}[/{C_DIM}]"
    )
    console.print(f"  [{C_DIM}]$ {' '.join(cmd)}[/{C_DIM}]\n")

    rc = subprocess.run(cmd).returncode
    console.print()
    console.print(f"  [bold {C_BAR_LOW}]✓  done[/]" if rc == 0 else f"  [bold {C_RED}]✗  failed (rc {rc})[/]")
    console.print()
    questionary.press_any_key_to_continue(style=Q_STYLE).ask()

# ─── Sub-menus ────────────────────────────────────────────────────────────────

def service_menu(service: str, actions: List[str], host_choices: List[Choice]):
    order = ["deploy", "start", "stop", "restart", "status", "verify", "backup", "update", "remove"]
    sorted_actions = sorted(actions, key=lambda a: order.index(a) if a in order else 99)

    choices = [Choice(title=f"  {PLAY_LABEL.get(a, f'•  {a}')}", value=a) for a in sorted_actions]
    choices.append(Choice(title="  ← back", value="__back__"))
    choices.append(Choice(title="  ✕ quit", value="__quit__"))

    meta = SVC_META.get(service, {})
    header = f"{service}"
    if meta.get("desc"):
        header += f" — {meta['desc']}"
    if meta.get("url"):
        header += f"\n{meta['url']}"

    while True:
        action = q_select(header, choices)
        if action is None or action == "__back__":
            return
        if action == "__quit__":
            _bye()
        run_playbook(service, action, host_choices)

def _plays_menu(title: str, plays: List[Tuple[str, str]], host_choices: List[Choice]):
    choices = [Choice(title=f"  {name.replace('-', ' ').replace('_', ' ')}", value=(folder, name)) for folder, name in plays]
    choices.append(Choice(title="  ← back", value="__back__"))

    while True:
        sel = q_select(title, choices)
        if sel is None or sel == "__back__":
            return
        folder, action = sel
        run_playbook(folder, action, host_choices)

def infra_menu(plays: List[Tuple[str, str]], host_choices: List[Choice]):
    _plays_menu("infrastructure", plays, host_choices)

def vps_menu(plays: List[Tuple[str, str]], host_choices: List[Choice]):
    _plays_menu("vps", plays, host_choices)

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    if not os.path.exists(INVENTORY):
        console.print(f"  [bold {C_RED}]✗  run from the ansible/ directory[/]")
        sys.exit(1)

    hosts = discover_hosts()
    host_choices = build_host_choices(hosts)
    services = discover_services()
    pinned_versions = load_pinned_versions()
    infra_plays = discover_infra_plays()
    vps_plays = discover_vps_plays()

    if not services:
        console.print(f"  [bold {C_RED}]✗  no playbooks in {PLAYBOOKS_DIR}/[/]")
        sys.exit(1)

    prod_hosts = [h for h, i in hosts.items() if i["group"] == "prod"]
    vps_hosts = [h for h, i in hosts.items() if i["group"] == "vps"]
    tresor_ip = hosts[prod_hosts[0]]["ip"] if prod_hosts else "192.168.1.100"
    vps_ip = hosts[vps_hosts[0]]["ip"] if vps_hosts else "1.2.3.4"

    while True:
        console.clear()
        console.print(render_header())

        layout = compute_layout(console.size.width)
        with console.status("", spinner="dots"):
            # Force fresh logins each refresh to avoid stale Paramiko sessions
            # holding old group memberships / privilege context.
            _close_ssh_clients()

            with ThreadPoolExecutor(max_workers=2) as ex:
                fut_tresor = ex.submit(fetch_tresor, tresor_ip)
                fut_vps = ex.submit(fetch_vps, vps_ip)
                tresor_data = fut_tresor.result()
                vps_data = fut_vps.result()

            tresor_data["ip"] = tresor_ip
            vps_data["ip"] = vps_ip

        console.clear()
        console.print(render_header())

        pw, side = _panel_widths()
        t_panel = render_tresor_panel(tresor_data, width=pw)
        v_panel = render_vps_panel(vps_data, width=pw)

        if side:
            console.print(Columns([v_panel, t_panel], padding=(0, 2), equal=True, expand=False))
        else:
            console.print(v_panel)
            console.print(t_panel)

        # Height responsiveness: hide legend on very short screens to preserve rows
        if _ui_density() != "tight":
            legend_parts = [f"{colored_badge(net)} [{C_DIM}]{net}[/{C_DIM}]" for net in NET_BADGE]
            console.print("  " + "  ".join(legend_parts))

        console.print(f"  [{C_DIM}]{col_header(layout)}[/{C_DIM}]")

        containers = tresor_data.get("containers") or {}
        metrics = tresor_data.get("metrics") or {}
        name_map = tresor_data.get("name_map") or {}

        svc_choices: List[Choice] = []
        for svc, actions in sorted(services.items(), key=_service_sort_key):
            svc_choices.append(
                Choice(
                    title=service_row(svc, actions, containers, metrics, name_map, pinned_versions, layout),
                    value=svc,
                )
            )

        if infra_plays:
            svc_choices.append(Choice(title="  🔧 infrastructure", value="__infra__"))
        if vps_plays:
            svc_choices.append(Choice(title="  🌐 vps", value="__vps__"))
        svc_choices.append(Choice(title="  ⟳  refresh", value="__refresh__"))
        svc_choices.append(Choice(title="  ✕  quit", value="__quit__"))

        sel = q_select("", svc_choices)

        if sel is None or sel == "__quit__":
            _bye()
        if sel == "__refresh__":
            continue
        if sel == "__infra__":
            infra_menu(infra_plays, host_choices)
            continue
        if sel == "__vps__":
            vps_menu(vps_plays, host_choices)
            continue

        service_menu(sel, services[sel], host_choices)

if __name__ == "__main__":
    main()