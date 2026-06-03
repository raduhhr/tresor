#!/usr/bin/env python3
"""
tresor-index-cli - Tresor Index operator cockpit
Run from: the ansible/ directory
Requires: pip install rich questionary pyyaml --break-system-packages
"""

from __future__ import annotations

import glob
import signal
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import questionary
    import yaml
    from questionary import Choice, Style
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
except ImportError:
    print("Missing deps. Run:")
    print("  pip install rich questionary pyyaml --break-system-packages")
    sys.exit(1)


INVENTORY = "inventory/hosts.ini"
ANSIBLE_CMD = "ansible-playbook"
PLAYBOOK_DIR = Path("playbooks/tresor-index")
SOURCE_CONFIG = Path("inventory/group_vars/prod/tresor-index.yml")
TARGET_HOST = "tresor"

C_PANEL = "#111827"
C_BORDER = "#22c55e"
C_ACCENT = "#34d399"
C_GREEN = "#34d399"
C_YELLOW = "#fbbf24"
C_RED = "#fb7185"
C_DIM = "#94a3b8"
C_TEXT = "#e5e7eb"

ACTION_ORDER = [
    "status",
    "source-list",
    "listing-latest",
    "listing-summary",
    "run-once",
    "run-all-enabled",
    "deploy",
    "restart",
    "start",
    "stop",
    "remove",
]

ACTION_LABELS = {
    "deploy": "deploy / sync config",
    "status": "status",
    "source-list": "list sources",
    "listing-latest": "latest listings",
    "listing-summary": "listing summary",
    "run-once": "run due sources once",
    "run-all-enabled": "run all enabled sources",
    "restart": "restart containers",
    "start": "start containers",
    "stop": "stop containers",
    "remove": "remove containers",
}

ACTION_HELP = {
    "deploy": "Build/sync app, DB, source registry, scheduler.",
    "status": "Show DB counts, recent fetches, and container health.",
    "source-list": "Print configured source ids and feed URLs.",
    "listing-latest": "Show latest stored OLX/imobiliare listings.",
    "listing-summary": "Summarize stored listings by district and price.",
    "run-once": "Fetch only sources that are due by interval.",
    "run-all-enabled": "Fetch every enabled source immediately.",
    "restart": "Restart existing containers.",
    "start": "Start existing containers.",
    "stop": "Stop scheduler and DB containers.",
    "remove": "Remove containers; data is kept unless role vars say otherwise.",
}

INDEX_ART = r"""
  ______                              ____          __
 /_  __/_______  _________  _____   /  _/___  ____/ /__  _  __
  / / / ___/ _ \/ ___/ __ \/ ___/   / // __ \/ __  / _ \| |/_/
 / / / /  /  __(__  ) /_/ / /     _/ // / / / /_/ /  __/>  <
/_/ /_/   \___/____/\____/_/     /___/_/ /_/\__,_/\___/_/|_|
"""

console = Console()

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
    console.print(f"\n  [{C_DIM}]tresor-index-cli closed[/{C_DIM}]\n")
    sys.exit(0)


signal.signal(signal.SIGINT, _bye)
if hasattr(signal, "SIGTSTP"):
    signal.signal(signal.SIGTSTP, _bye)


def require_ansible_dir() -> None:
    if not Path(INVENTORY).exists() or not PLAYBOOK_DIR.exists():
        console.print(f"[bold {C_RED}]Run from the ansible/ directory.[/]")
        sys.exit(1)


def playbooks() -> list[str]:
    actions = []
    for path in glob.glob(str(PLAYBOOK_DIR / "*.yml")):
        actions.append(Path(path).stem)
    return sorted(actions, key=lambda name: ACTION_ORDER.index(name) if name in ACTION_ORDER else 99)


def source_config() -> dict[str, Any]:
    if not SOURCE_CONFIG.exists():
        return {"sources": []}
    payload = yaml.safe_load(SOURCE_CONFIG.read_text(encoding="utf-8")) or {}
    if "sources" not in payload and "tresor_index_sources" in payload:
        payload["sources"] = payload.get("tresor_index_sources") or []
    payload.setdefault("sources", [])
    return payload


def source_summary() -> dict[str, Any]:
    sources = source_config().get("sources") or []
    enabled = [item for item in sources if item.get("enabled", True)]
    categories = Counter(str(item.get("category", "uncategorized")) for item in enabled)
    return {
        "configured": len(sources),
        "enabled": len(enabled),
        "disabled": len(sources) - len(enabled),
        "categories": categories,
        "sources": sources,
    }


def render_dashboard() -> None:
    summary = source_summary()
    actions = playbooks()
    console.clear()
    console.print(
        Panel.fit(
            INDEX_ART,
            title=Text("tresor-index-cli", style=f"bold {C_ACCENT}"),
            subtitle=Text("source ingestion cockpit", style=C_DIM),
            border_style=C_BORDER,
        )
    )

    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_column(ratio=1)

    left = Table.grid(padding=(0, 1))
    left.add_column(style=C_DIM, no_wrap=True)
    left.add_column(style=C_TEXT)
    left.add_row("configured", str(summary["configured"]))
    left.add_row("enabled", str(summary["enabled"]))
    left.add_row("disabled", str(summary["disabled"]))
    left.add_row("playbooks", str(len(actions)))

    categories = Table.grid(padding=(0, 1))
    categories.add_column(style=C_DIM, no_wrap=True)
    categories.add_column(style=C_TEXT)
    for category, count in sorted(summary["categories"].items()):
        categories.add_row(category, str(count))
    if not summary["categories"]:
        categories.add_row("none", "0")

    grid.add_row(
        Panel(left, title="Local Config", border_style=C_BORDER),
        Panel(categories, title="Enabled Categories", border_style=C_BORDER),
    )
    console.print(grid)

    if actions:
        action_line = ", ".join(ACTION_LABELS.get(action, action) for action in actions)
        console.print(Panel(action_line, title="Available Playbooks", border_style=C_BORDER))
    else:
        console.print(Panel("No playbooks found under playbooks/tresor-index", border_style=C_RED))


def run_playbook(action: str) -> None:
    playbook = PLAYBOOK_DIR / f"{action}.yml"
    cmd = [ANSIBLE_CMD, "-i", INVENTORY, str(playbook)]
    console.clear()
    console.rule(f"[{C_ACCENT}]tresor-index {ACTION_LABELS.get(action, action)}")
    console.print(f"[{C_DIM}]$ {' '.join(cmd)}[/{C_DIM}]\n")
    try:
        rc = subprocess.run(cmd).returncode
    except FileNotFoundError:
        console.print(f"[bold {C_RED}]ansible-playbook was not found[/]")
        pause()
        return
    console.print()
    if rc == 0:
        console.print(f"[bold {C_GREEN}]playbook completed[/]")
    else:
        console.print(f"[bold {C_RED}]playbook failed rc={rc}[/]")
    pause()


def pause() -> None:
    questionary.press_any_key_to_continue(style=Q_STYLE).ask()


def menu() -> str:
    actions = playbooks()
    choices: list[Choice] = []
    choices.append(Choice("refresh", "refresh"))
    for action in actions:
        label = ACTION_LABELS.get(action, action)
        help_text = ACTION_HELP.get(action, "")
        title = f"{label:<24} {help_text}"
        choices.append(Choice(title, action))
    choices.append(Choice("quit", "quit"))
    answer = questionary.select(
        "tresor-index-cli",
        choices=choices,
        style=Q_STYLE,
        qmark="",
        pointer=">",
    ).ask()
    return answer or "quit"


def main() -> None:
    require_ansible_dir()
    while True:
        render_dashboard()
        action = menu()
        if action == "quit":
            _bye()
        if action == "refresh":
            continue
        run_playbook(action)


if __name__ == "__main__":
    main()
