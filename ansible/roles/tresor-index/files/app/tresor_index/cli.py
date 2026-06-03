from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from . import __version__, db
from .civic_cache import DEFAULT_TTL_SECONDS, refresh_civic_caches
from .config import load_sources
from .digest import DAILY_RULES, send_daily_digest, send_recorder_investigation_alerts
from .ingest import fetch_source
from .scheduler import run_forever, run_once


def cmd_migrate(_: argparse.Namespace) -> int:
    db.migrate()
    print("migrations applied")
    return 0


def cmd_source_list(_: argparse.Namespace) -> int:
    for source in load_sources():
        state = "enabled" if source.enabled else "disabled"
        print(f"{source.id}\t{state}\t{source.source_type.value}\t{source.category}\t{source.url}")
    return 0


def cmd_source_sync(_: argparse.Namespace) -> int:
    sources = load_sources()
    count = db.sync_sources(sources)
    print(f"synced {count} sources")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    sources = {source.id: source for source in load_sources()}
    if args.source not in sources:
        print(f"unknown source: {args.source}", file=sys.stderr)
        return 2
    result = fetch_source(sources[args.source])
    print(json.dumps(result.model_dump(), indent=2, default=str))
    return 0 if result.status == "success" else 1


def cmd_status(_: argparse.Namespace) -> int:
    counts = db.status_counts()
    print(json.dumps(counts, indent=2, default=str))
    return 0


def _as_json(rows: list[dict[str, Any]]) -> None:
    print(json.dumps(rows, indent=2, default=str, ensure_ascii=False))


def _short(value: Any, width: int) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "..."


def _money(value: Any, currency: str | None = "EUR") -> str:
    if value is None:
        return ""
    amount = int(round(value)) if isinstance(value, (Decimal, float)) else value
    suffix = f" {currency}" if currency else ""
    return f"{amount:,}".replace(",", " ") + suffix


def _print_listing_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("no listings matched")
        return
    header = f"{'id':<10} {'price':>12} {'district':<14} {'area':>6} {'v':>2}  title"
    print(header)
    print("-" * len(header))
    for row in rows:
        price = row.get("price_display") or _money(row.get("price_value"), row.get("price_currency"))
        print(
            f"{_short(row.get('external_id') or row.get('id'), 10):<10} "
            f"{_short(price, 12):>12} "
            f"{_short(row.get('district'), 14):<14} "
            f"{_short(row.get('area_sqm'), 6):>6} "
            f"{row.get('version_count', 0):>2}  "
            f"{_short(row.get('title'), 96)}"
        )
        print(f"{'':<10} {'':>12} {'':<14} {'':>6} {'':>2}  {row.get('canonical_url')}")


def _print_summary_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("no listing summary rows matched")
        return
    header = f"{'district':<18} {'count':>5} {'min':>11} {'median':>11} {'avg':>11} {'max':>11}"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{_short(row.get('district'), 18):<18} "
            f"{row.get('listings', 0):>5} "
            f"{_money(row.get('min_price')):>11} "
            f"{_money(row.get('median_price')):>11} "
            f"{_money(row.get('avg_price')):>11} "
            f"{_money(row.get('max_price')):>11}"
        )


def _print_observation_counts(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("no observations recorded")
        return
    header = f"{'observation_type':<24} {'observations':>12}"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(f"{_short(row.get('observation_type'), 24):<24} {row.get('observations', 0):>12}")


def _print_price_changes(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("no listing price changes matched")
        return
    header = f"{'id':<10} {'previous':>12} {'latest':>12} {'delta':>12} {'district':<14} title"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{_short(row.get('external_id'), 10):<10} "
            f"{_money(row.get('previous_price')):>12} "
            f"{_money(row.get('latest_price')):>12} "
            f"{_money(row.get('delta')):>12} "
            f"{_short(row.get('district'), 14):<14} "
            f"{_short(row.get('title'), 80)}"
        )
        print(f"{'':<10} {'':>12} {'':>12} {'':>12} {'':<14} {row.get('canonical_url')}")


def cmd_listing_search(args: argparse.Namespace) -> int:
    rows = db.query_listings(
        source_id=args.source,
        category=args.category,
        min_price=args.min_price,
        max_price=args.max_price,
        district=args.district,
        text=args.text,
        changed_only=args.changed_only,
        sort=args.sort,
        limit=args.limit,
    )
    if args.json:
        _as_json(rows)
    else:
        _print_listing_rows(rows)
    return 0


def cmd_listing_summary(args: argparse.Namespace) -> int:
    rows = db.listing_summary(source_id=args.source, category=args.category)
    if args.json:
        _as_json(rows)
    else:
        _print_summary_rows(rows)
    return 0


def cmd_listing_price_changes(args: argparse.Namespace) -> int:
    rows = db.listing_price_changes(source_id=args.source, limit=args.limit, drops_only=args.drops_only)
    if args.json:
        _as_json(rows)
    else:
        _print_price_changes(rows)
    return 0


def cmd_observation_counts(args: argparse.Namespace) -> int:
    rows = db.observation_counts()
    if args.json:
        _as_json(rows)
    else:
        _print_observation_counts(rows)
    return 0


def cmd_run_once(args: argparse.Namespace) -> int:
    results = run_once(all_enabled=args.all_enabled)
    print(json.dumps(results, indent=2, default=str))
    return 0


def cmd_scheduler(_: argparse.Namespace) -> int:
    run_forever()
    return 0


def cmd_digest_send(args: argparse.Namespace) -> int:
    target_day = date.fromisoformat(args.date) if args.date else None
    rule_ids = list(DAILY_RULES) if args.rule == "all" else [args.rule]
    results: list[dict[str, Any]] = []
    for rule_id in rule_ids:
        results.append(send_daily_digest(rule_id, day=target_day, force=args.force))
    if args.include_recorder_investigations:
        results.extend(send_recorder_investigation_alerts())
    print(json.dumps(results, indent=2, default=str, ensure_ascii=False))
    return 0


def _date_span(start: date, end: date) -> list[date]:
    if start > end:
        raise ValueError("--from date must be before or equal to --to date")
    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def _batches(values: list[date], size: int) -> list[list[date]]:
    size = max(1, size)
    return [values[index : index + size] for index in range(0, len(values), size)]


def cmd_civic_backfill(args: argparse.Namespace) -> int:
    sources = {source.id: source for source in load_sources()}
    source = sources.get(args.source)
    if source is None:
        print(f"unknown source: {args.source}", file=sys.stderr)
        return 2
    if source.parser not in {"cdep_final_votes", "senat_final_votes"}:
        print("only cdep_final_votes and senat_final_votes backfill are implemented right now", file=sys.stderr)
        return 2

    start = date.fromisoformat(args.from_date)
    end = date.fromisoformat(args.to_date)
    days = _date_span(start, end)
    batches = _batches(days, args.batch_days)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "source_id": source.id,
                    "from": start.isoformat(),
                    "to": end.isoformat(),
                    "days": len(days),
                    "batches": len(batches),
                    "batch_days": args.batch_days,
                },
                indent=2,
            )
        )
        return 0

    totals = {"batches": len(batches), "days": len(days), "items_found": 0, "items_new": 0, "items_changed": 0, "errors": 0}
    for index, batch in enumerate(batches, start=1):
        batch_config = {
            **source.config,
            "dates": [day.isoformat() for day in batch],
            "max_votes": args.max_votes,
        }
        if args.request_delay_seconds is not None:
            batch_config["request_delay_seconds"] = args.request_delay_seconds
        backfill_source = source.model_copy(update={"config": batch_config})
        result = fetch_source(backfill_source)
        totals["items_found"] += result.items_found
        totals["items_new"] += result.items_new
        totals["items_changed"] += result.items_changed
        if result.status != "success":
            totals["errors"] += 1
        print(
            json.dumps(
                {
                    "batch": index,
                    "batches": len(batches),
                    "from": batch[0].isoformat(),
                    "to": batch[-1].isoformat(),
                    **result.model_dump(),
                },
                default=str,
                ensure_ascii=False,
            ),
            flush=True,
        )
        if result.status != "success" and args.stop_on_error:
            print(json.dumps({"status": "stopped", **totals}, indent=2), file=sys.stderr)
            return 1

    print(json.dumps({"status": "complete", **totals}, indent=2, default=str, ensure_ascii=False))
    return 0 if totals["errors"] == 0 else 1


def cmd_civic_cache_refresh(args: argparse.Namespace) -> int:
    db.migrate()
    results = refresh_civic_caches(ttl_seconds=args.ttl_seconds)
    print(json.dumps(results, indent=2, default=str, ensure_ascii=False))
    return 0


def cmd_civic_cache_status(_: argparse.Namespace) -> int:
    rows = db.api_cache_status()
    print(json.dumps(rows, indent=2, default=str, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tresor-index")
    parser.add_argument("--version", action="version", version=f"tresor-index {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    migrate = sub.add_parser("migrate", help="apply database migrations")
    migrate.set_defaults(func=cmd_migrate)

    source = sub.add_parser("source", help="source registry commands")
    source_sub = source.add_subparsers(dest="source_command", required=True)
    source_list = source_sub.add_parser("list", help="list configured sources")
    source_list.set_defaults(func=cmd_source_list)
    source_sync = source_sub.add_parser("sync", help="sync configured sources into Postgres")
    source_sync.set_defaults(func=cmd_source_sync)

    fetch = sub.add_parser("fetch", help="fetch one configured source")
    fetch.add_argument("--source", required=True)
    fetch.set_defaults(func=cmd_fetch)

    status = sub.add_parser("status", help="show database status")
    status.set_defaults(func=cmd_status)

    listing = sub.add_parser("listing", help="query stored listings")
    listing_sub = listing.add_subparsers(dest="listing_command", required=True)

    listing_search = listing_sub.add_parser("search", help="search stored listings")
    listing_search.add_argument("--source", help="filter by source id")
    listing_search.add_argument("--category", help="filter by source category")
    listing_search.add_argument("--min-price", type=int, help="minimum price")
    listing_search.add_argument("--max-price", type=int, help="maximum price")
    listing_search.add_argument("--district", help="case-insensitive district match")
    listing_search.add_argument("--text", help="case-insensitive title/description match")
    listing_search.add_argument("--changed-only", action="store_true", help="only listings with more than one version")
    listing_search.add_argument(
        "--sort",
        choices=["newest", "seen", "price_asc", "price_desc", "changed"],
        default="newest",
        help="result ordering",
    )
    listing_search.add_argument("--limit", type=int, default=25, help="maximum rows to return")
    listing_search.add_argument("--json", action="store_true", help="print JSON instead of a compact table")
    listing_search.set_defaults(func=cmd_listing_search)

    listing_summary = listing_sub.add_parser("summary", help="summarize stored listings by district")
    listing_summary.add_argument("--source", help="filter by source id")
    listing_summary.add_argument("--category", help="filter by source category")
    listing_summary.add_argument("--json", action="store_true", help="print JSON instead of a compact table")
    listing_summary.set_defaults(func=cmd_listing_summary)

    listing_price_changes = listing_sub.add_parser("price-changes", help="show listings with recorded price changes")
    listing_price_changes.add_argument("--source", help="filter by source id")
    listing_price_changes.add_argument("--drops-only", action="store_true", help="only show price drops")
    listing_price_changes.add_argument("--limit", type=int, default=25, help="maximum rows to return")
    listing_price_changes.add_argument("--json", action="store_true", help="print JSON instead of a compact table")
    listing_price_changes.set_defaults(func=cmd_listing_price_changes)

    observations = sub.add_parser("observation", help="query extracted observations")
    observations_sub = observations.add_subparsers(dest="observation_command", required=True)
    observation_counts = observations_sub.add_parser("counts", help="count observations by type")
    observation_counts.add_argument("--json", action="store_true", help="print JSON instead of a compact table")
    observation_counts.set_defaults(func=cmd_observation_counts)

    run_once_parser = sub.add_parser("run-once", help="sync sources and fetch due sources once")
    run_once_parser.add_argument("--all-enabled", action="store_true", help="fetch all enabled sources, ignoring intervals")
    run_once_parser.set_defaults(func=cmd_run_once)

    scheduler = sub.add_parser("scheduler", help="run the due-source scheduler loop")
    scheduler.set_defaults(func=cmd_scheduler)

    digest = sub.add_parser("digest", help="send Discord digests")
    digest_sub = digest.add_subparsers(dest="digest_command", required=True)
    digest_send = digest_sub.add_parser("send", help="send one or all daily digests")
    digest_send.add_argument(
        "--rule",
        choices=[*DAILY_RULES.keys(), "all"],
        default="all",
        help="digest rule to send",
    )
    digest_send.add_argument("--date", help="local digest date as YYYY-MM-DD; defaults to today")
    digest_send.add_argument("--force", action="store_true", help="send even if the digest was already recorded")
    digest_send.add_argument(
        "--include-recorder-investigations",
        action="store_true",
        help="also run immediate Recorder YouTube investigation alerts",
    )
    digest_send.set_defaults(func=cmd_digest_send)

    civic = sub.add_parser("civic", help="civic data maintenance commands")
    civic_sub = civic.add_subparsers(dest="civic_command", required=True)
    civic_backfill = civic_sub.add_parser("backfill", help="one-shot historical civic backfill")
    civic_backfill.add_argument("--source", default="cdep_final_votes", choices=["cdep_final_votes", "senat_final_votes"], help="civic source to backfill")
    civic_backfill.add_argument("--from", dest="from_date", required=True, help="start date as YYYY-MM-DD")
    civic_backfill.add_argument("--to", dest="to_date", required=True, help="end date as YYYY-MM-DD")
    civic_backfill.add_argument("--batch-days", type=int, default=7, help="number of dates fetched per ingest batch")
    civic_backfill.add_argument("--max-votes", type=int, default=500, help="max votes accepted per batch")
    civic_backfill.add_argument("--request-delay-seconds", type=float, help="override collector request delay")
    civic_backfill.add_argument("--dry-run", action="store_true", help="show planned batches without fetching")
    civic_backfill.add_argument("--stop-on-error", action="store_true", help="stop after the first failed batch")
    civic_backfill.set_defaults(func=cmd_civic_backfill)

    civic_cache = civic_sub.add_parser("cache", help="civic API cache maintenance")
    civic_cache_sub = civic_cache.add_subparsers(dest="civic_cache_command", required=True)
    civic_cache_refresh = civic_cache_sub.add_parser("refresh", help="refresh cached civic API payloads")
    civic_cache_refresh.add_argument(
        "--ttl-seconds",
        type=int,
        default=DEFAULT_TTL_SECONDS,
        help="cache freshness window; stale cache is still served if no refresh has run",
    )
    civic_cache_refresh.set_defaults(func=cmd_civic_cache_refresh)
    civic_cache_status = civic_cache_sub.add_parser("status", help="show civic API cache state")
    civic_cache_status.set_defaults(func=cmd_civic_cache_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
