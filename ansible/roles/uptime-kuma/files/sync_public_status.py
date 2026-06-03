#!/usr/bin/env python3
import json
import os
import sys
from typing import Any

from uptime_kuma_api import MonitorType, UptimeKumaApi


def _env(name: str, default: str = "", required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _monitor_id(monitor: dict[str, Any]) -> int:
    value = monitor.get("id", monitor.get("monitorID"))
    if value is None:
        raise SystemExit(f"Monitor payload has no id: {monitor}")
    return int(value)


def _extract_monitor_id(result: dict[str, Any]) -> int | None:
    for key in ("monitorId", "monitorID", "id"):
        value = result.get(key)
        if value is not None:
            return int(value)
    monitor = result.get("monitor")
    if isinstance(monitor, dict):
        value = monitor.get("id", monitor.get("monitorID"))
        if value is not None:
            return int(value)
    return None


def _desired_monitor_payload(monitor: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": MonitorType.HTTP,
        "name": monitor["name"],
        "url": monitor["url"],
        "interval": int(monitor.get("interval", 60)),
        "retryInterval": int(monitor.get("retryInterval", 60)),
        "maxretries": int(monitor.get("maxretries", 1)),
        "maxredirects": int(monitor.get("maxredirects", 10)),
        "accepted_statuscodes": monitor.get("accepted_statuscodes", ["200-299"]),
        "ignoreTls": bool(monitor.get("ignoreTls", False)),
        "method": monitor.get("method", "GET"),
        "description": monitor.get("description"),
        "upsideDown": bool(monitor.get("upsideDown", False)),
        "expiryNotification": bool(monitor.get("expiryNotification", False)),
    }


def _monitor_needs_update(current: dict[str, Any], desired: dict[str, Any]) -> bool:
    comparable_keys = [
        "name",
        "url",
        "interval",
        "retryInterval",
        "maxretries",
        "maxredirects",
        "ignoreTls",
        "method",
        "description",
        "upsideDown",
        "expiryNotification",
    ]

    for key in comparable_keys:
        if current.get(key) != desired.get(key):
            return True

    current_status_codes = current.get("accepted_statuscodes") or []
    desired_status_codes = desired.get("accepted_statuscodes") or []
    if list(current_status_codes) != list(desired_status_codes):
        return True

    current_type = current.get("type")
    desired_type = desired.get("type")
    if str(current_type).lower() != str(desired_type.value).lower():
        return True

    return False


def _normalize_public_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for index, group in enumerate(groups):
        normalized.append(
            {
                "id": group.get("id"),
                "name": group.get("name"),
                "weight": int(group.get("weight", index + 1)),
                "monitorList": [{"id": _monitor_id(monitor)} for monitor in group.get("monitorList", [])],
            }
        )
    return normalized


def main() -> int:
    base_url = _env("KUMA_BASE_URL", required=True).rstrip("/")
    username = _env("KUMA_USERNAME", required=True)
    password = _env("KUMA_PASSWORD", required=True)
    status_page_slug = _env("KUMA_STATUS_PAGE_SLUG", required=True)
    status_page_title = _env("KUMA_STATUS_PAGE_TITLE", default="Tresor Status")
    public_group_name = _env("KUMA_PUBLIC_GROUP_NAME", default="Public Services")
    desired_monitors = json.loads(_env("KUMA_MONITORS_JSON", default="[]"))

    if not desired_monitors:
        print("No public monitors configured. Nothing to sync.")
        return 0

    with UptimeKumaApi(base_url) as api:
        api.login(username, password)

        existing_monitors = api.get_monitors()
        monitors_by_name = {monitor["name"]: monitor for monitor in existing_monitors}
        synced_monitor_ids: list[int] = []

        for desired_monitor in desired_monitors:
            desired_payload = _desired_monitor_payload(desired_monitor)
            existing_monitor = monitors_by_name.get(desired_monitor["name"])

            if existing_monitor is None:
                result = api.add_monitor(**desired_payload)
                monitor_id = _extract_monitor_id(result)
                if monitor_id is None:
                    refreshed_monitors = api.get_monitors()
                    refreshed_monitor = next(
                        (monitor for monitor in refreshed_monitors if monitor.get("name") == desired_monitor["name"]),
                        None,
                    )
                    if refreshed_monitor is None:
                        raise SystemExit(f"Monitor was created but could not be reloaded by name: {desired_monitor['name']}")
                    monitor_id = _monitor_id(refreshed_monitor)
                synced_monitor_ids.append(monitor_id)
                print(f"Created monitor '{desired_monitor['name']}' ({monitor_id})")
                continue

            monitor_id = _monitor_id(existing_monitor)
            current_monitor = api.get_monitor(monitor_id)
            if _monitor_needs_update(current_monitor, desired_payload):
                api.edit_monitor(monitor_id, **desired_payload)
                print(f"Updated monitor '{desired_monitor['name']}' ({monitor_id})")
            else:
                print(f"Monitor '{desired_monitor['name']}' already matches desired config ({monitor_id})")

            synced_monitor_ids.append(monitor_id)

        try:
            status_page = api.get_status_page(status_page_slug)
            print(f"Loaded existing status page '{status_page_slug}'")
        except Exception:
            api.add_status_page(status_page_slug, status_page_title)
            status_page = api.get_status_page(status_page_slug)
            print(f"Created status page '{status_page_slug}'")

        public_groups = _normalize_public_groups(status_page.get("publicGroupList", []))

        target_group = None
        for group in public_groups:
            if group.get("name") == public_group_name:
                target_group = group
                break

        if target_group is None:
            target_group = {
                "name": public_group_name,
                "weight": len(public_groups) + 1,
                "monitorList": [],
            }
            public_groups.append(target_group)

        existing_group_ids = [_monitor_id(monitor) for monitor in target_group.get("monitorList", [])]
        merged_ids = []
        for monitor_id in existing_group_ids + synced_monitor_ids:
            if monitor_id not in merged_ids:
                merged_ids.append(monitor_id)
        target_group["monitorList"] = [{"id": monitor_id} for monitor_id in merged_ids]

        save_result = api.save_status_page(
            status_page_slug,
            id=status_page["id"],
            title=status_page.get("title") or status_page_title,
            description=status_page.get("description"),
            theme=status_page.get("theme", "auto"),
            published=bool(status_page.get("published", True)),
            showTags=bool(status_page.get("showTags", False)),
            domainNameList=status_page.get("domainNameList", []),
            googleAnalyticsId=status_page.get("googleAnalyticsId"),
            customCSS=status_page.get("customCSS", ""),
            footerText=status_page.get("footerText"),
            showPoweredBy=bool(status_page.get("showPoweredBy", True)),
            showCertificateExpiry=bool(status_page.get("showCertificateExpiry", False)),
            icon=status_page.get("icon", "/icon.svg"),
            publicGroupList=public_groups,
        )

        print(
            json.dumps(
                {
                    "status_page_slug": status_page_slug,
                    "public_group_name": public_group_name,
                    "monitor_ids": synced_monitor_ids,
                    "save_result": save_result,
                },
                indent=2,
                default=str,
            )
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
