#!/usr/bin/env python3
import json
import subprocess
import sys
import urllib.parse


WINDOWS = [
    ("30d", "30 days"),
    ("90d", "90 days"),
    ("180d", "180 days"),
]


def prom_query(query):
    url = "http://localhost:9090/api/v1/query?" + urllib.parse.urlencode({"query": query})
    output = subprocess.check_output(
        ["docker", "exec", "prometheus", "wget", "-qO-", url],
        text=True,
    )
    payload = json.loads(output)
    if payload.get("status") != "success":
        raise RuntimeError(payload)
    return payload["data"]["result"]


def prom_scalar(query, default=None):
    result = prom_query(query)
    if not result:
        return default
    return float(result[0]["value"][1])


def label_set():
    result = prom_query('group by (name,image) (container_memory_working_set_bytes{name!="",image!=""})')
    items = []
    for item in result:
        metric = item["metric"]
        name = metric.get("name", "")
        image = metric.get("image", "")
        if not name:
            continue
        items.append({"name": name, "image": image})
    return sorted(items, key=lambda x: x["name"])


def by_name(result):
    out = {}
    for item in result:
        name = item["metric"].get("name")
        if not name:
            continue
        value = float(item["value"][1])
        out[name] = max(out.get(name, 0.0), value)
    return out


def mib(value):
    return value / 1024 / 1024


def main():
    containers = {item["name"]: item for item in label_set()}
    print(json.dumps({"containers_seen": list(containers.values())}, indent=2))

    up_start = prom_scalar("min_over_time(timestamp(up)[180d:1h])")
    up_end = prom_scalar("max_over_time(timestamp(up)[180d:1h])")
    print(json.dumps({"sample_time_bounds_unix": {"min": up_start, "max": up_end}}, indent=2))

    summary = {}
    for window, _label in WINDOWS:
        memory_peak = by_name(prom_query(
            f'max_over_time(container_memory_working_set_bytes{{name!="",image!=""}}[{window}:5m])'
        ))
        memory_p95 = by_name(prom_query(
            f'quantile_over_time(0.95, container_memory_working_set_bytes{{name!="",image!=""}}[{window}:5m])'
        ))
        rss_peak = by_name(prom_query(
            f'max_over_time(container_memory_rss{{name!="",image!=""}}[{window}:5m])'
        ))
        rss_p95 = by_name(prom_query(
            f'quantile_over_time(0.95, container_memory_rss{{name!="",image!=""}}[{window}:5m])'
        ))
        cache_peak = by_name(prom_query(
            f'max_over_time(container_memory_cache{{name!="",image!=""}}[{window}:5m])'
        ))
        cache_p95 = by_name(prom_query(
            f'quantile_over_time(0.95, container_memory_cache{{name!="",image!=""}}[{window}:5m])'
        ))
        cpu_peak = by_name(prom_query(
            f'max_over_time(rate(container_cpu_usage_seconds_total{{name!="",image!=""}}[5m])[{window}:5m])'
        ))
        cpu_p95 = by_name(prom_query(
            f'quantile_over_time(0.95, rate(container_cpu_usage_seconds_total{{name!="",image!=""}}[5m])[{window}:5m])'
        ))
        restarts = by_name(prom_query(
            f'changes(container_start_time_seconds{{name!="",image!=""}}[{window}:5m])'
        ))

        rows = []
        for name in sorted(containers):
            rows.append({
                "name": name,
                "image": containers[name]["image"],
                "memory_peak_mib": round(mib(memory_peak.get(name, 0.0)), 1),
                "memory_p95_mib": round(mib(memory_p95.get(name, 0.0)), 1),
                "rss_peak_mib": round(mib(rss_peak.get(name, 0.0)), 1),
                "rss_p95_mib": round(mib(rss_p95.get(name, 0.0)), 1),
                "cache_peak_mib": round(mib(cache_peak.get(name, 0.0)), 1),
                "cache_p95_mib": round(mib(cache_p95.get(name, 0.0)), 1),
                "cpu_peak_cores": round(cpu_peak.get(name, 0.0), 3),
                "cpu_p95_cores": round(cpu_p95.get(name, 0.0), 3),
                "restarts": int(restarts.get(name, 0.0)),
            })
        summary[window] = rows

    print(json.dumps({"windows": summary}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
