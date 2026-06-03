from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import SourceConfig


CONFIG_DIR = Path(os.getenv("TRESOR_INDEX_CONFIG_DIR", "/config"))
SOURCES_FILE = Path(os.getenv("TRESOR_INDEX_SOURCES_FILE", CONFIG_DIR / "sources.yml"))


def database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is not configured")
    return value


def public_database_url() -> str:
    value = os.getenv("TRESOR_INDEX_PUBLIC_DATABASE_URL", "").strip()
    if value:
        return value
    return database_url()


def scheduler_interval_seconds() -> int:
    return int(os.getenv("TRESOR_INDEX_SCHEDULER_INTERVAL_SECONDS", "300"))


def load_sources(path: Path = SOURCES_FILE) -> list[SourceConfig]:
    if not path.exists():
        return []
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_sources = payload.get("sources", [])
    sources: list[SourceConfig] = []
    errors: list[str] = []
    for idx, raw in enumerate(raw_sources, start=1):
        try:
            sources.append(SourceConfig.model_validate(raw))
        except ValidationError as exc:
            errors.append(f"source #{idx}: {exc}")
    if errors:
        raise ValueError("invalid sources.yml:\n" + "\n".join(errors))
    return sources
