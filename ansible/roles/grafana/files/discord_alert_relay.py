#!/usr/bin/env python3
import json
import os
import re
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


DISCORD_WEBHOOK_URL = env("DISCORD_WEBHOOK_URL")
DISCORD_USER_ID = env("DISCORD_USER_ID")
RELAY_TOKEN = env("RELAY_TOKEN")
LISTEN_HOST = env("LISTEN_HOST", "127.0.0.1")
LISTEN_PORT = int(env("LISTEN_PORT", "3101"))
DISCORD_USERNAME = env("DISCORD_USERNAME", "Tresor Guardian")


def _alert_name(alert: dict) -> str:
    labels = alert.get("labels") or {}
    return labels.get("alertname") or labels.get("rulename") or "Grafana alert"


def _alert_target(alert: dict) -> str:
    labels = alert.get("labels") or {}
    return labels.get("name") or labels.get("instance") or ""


def _alert_summary(alert: dict) -> str:
    annotations = alert.get("annotations") or {}
    return annotations.get("summary") or annotations.get("description") or alert.get("valueString") or ""


def _alert_annotation(alert: dict, name: str) -> str:
    annotations = alert.get("annotations") or {}
    return str(annotations.get(name) or "").strip()


def _alert_percent(alert: dict) -> str:
    value = str(alert.get("valueString") or "")
    match = re.search(r"\bA=([0-9]+(?:\.[0-9]+)?)", value)
    if not match:
        match = re.search(r"value=([0-9]+(?:\.[0-9]+)?)", value)
    if not match:
        return ""
    return str(round(float(match.group(1))))


def _alert_link(alert: dict) -> str:
    return (
        alert.get("generatorURL")
        or alert.get("silenceURL")
        or alert.get("dashboardURL")
        or alert.get("panelURL")
        or ""
    )


def _append_alert_link(line: str, alert: dict) -> str:
    url = _alert_link(alert)
    if not url:
        return line
    return f"{line}\n  Alert: <{url}>"


def _format_firing_alert(alert: dict) -> str:
    target = _alert_target(alert)
    name = _alert_name(alert)
    subject = f"**{target}**" if target else f"**{name}**"
    percent = _alert_percent(alert)
    percent_text = f" ({percent}%)" if percent else ""
    sustained_for = _alert_annotation(alert, "sustained_for")
    duration_text = f" for {sustained_for}" if sustained_for else ""
    hardcap = _alert_annotation(alert, "hardcap")
    hardcap_text = f" Hardcap: {hardcap}." if hardcap else ""

    if "memory" in name.lower() and "cap" in name.lower():
        return _append_alert_link(f"- {subject} is running close to its memory cap{percent_text}{duration_text}.{hardcap_text}", alert)
    if "cpu" in name.lower() and "hardcap" in name.lower():
        return _append_alert_link(f"- {subject} is running at its CPU cap{percent_text}{duration_text}.{hardcap_text}", alert)
    if "host cpu" in name.lower():
        return _append_alert_link(f"- Host CPU is high{percent_text}{duration_text}.", alert)
    if "host ram" in name.lower():
        return _append_alert_link(f"- Host RAM is high{percent_text}{duration_text}.", alert)
    if "restart" in name.lower():
        return _append_alert_link(f"- {subject} restarted too many times.", alert)
    if "missing" in name.lower() or "down" in name.lower():
        return _append_alert_link(f"- {subject} is down or missing.", alert)

    summary = _alert_summary(alert)
    if summary:
        return _append_alert_link(f"- {subject}: {summary}", alert)
    return _append_alert_link(f"- {subject}", alert)


def _format_resolved_alert(alert: dict) -> str:
    target = _alert_target(alert)
    name = _alert_name(alert)
    subject = f"**{target}**" if target else f"**{name}**"
    return _append_alert_link(f"- {subject} alert stopped. All good now, you can breathe.", alert)


def build_discord_payload(grafana_payload: dict) -> dict:
    alerts = grafana_payload.get("alerts") or []
    firing = [alert for alert in alerts if alert.get("status") == "firing"]
    resolved = [alert for alert in alerts if alert.get("status") == "resolved"]

    should_mention = bool(DISCORD_USER_ID and (firing or resolved))
    mention = f"<@{DISCORD_USER_ID}> " if should_mention else ""
    status = "TRESOR ALERT" if firing else "TRESOR OK"
    if firing:
        lines = [f"{mention}**{status}**"]
    else:
        lines = [f"{mention}**TRESOR OK** - alert stopped. All good now, you can breathe."]

    for alert in firing[:8]:
        lines.append(_format_firing_alert(alert))

    for alert in resolved[:8]:
        lines.append(_format_resolved_alert(alert))

    truncated = grafana_payload.get("truncatedAlerts")
    if truncated:
        lines.append(f"- {truncated} additional alert(s) truncated by Grafana")

    content = "\n".join(lines)
    if len(content) > 1900:
        content = content[:1890].rstrip() + "\n- truncated"

    payload = {
        "content": content,
        "username": DISCORD_USERNAME,
        "allowed_mentions": {"parse": [], "users": [DISCORD_USER_ID] if should_mention else []},
    }
    return payload


def post_discord(payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        DISCORD_WEBHOOK_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Tresor-Grafana-Discord-Relay/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Discord returned HTTP {response.status}")


class Handler(BaseHTTPRequestHandler):
    server_version = "TresorGrafanaDiscordRelay/1.0"

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if not RELAY_TOKEN or self.path.strip("/") != RELAY_TOKEN:
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            grafana_payload = json.loads(body.decode("utf-8"))
            post_discord(build_discord_payload(grafana_payload))
        except Exception as exc:
            print(f"relay error: {exc}", file=sys.stderr, flush=True)
            self.send_error(502)
            return

        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)


def main() -> int:
    if not DISCORD_WEBHOOK_URL:
        print("DISCORD_WEBHOOK_URL is required", file=sys.stderr)
        return 2
    if not RELAY_TOKEN:
        print("RELAY_TOKEN is required", file=sys.stderr)
        return 2

    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(f"listening on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
