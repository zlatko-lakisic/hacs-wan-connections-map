"""Parse a MikroTik snapshot published on MQTT."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

STALE_AFTER_SECONDS = 60


def parse_snapshot(payload: str) -> dict[str, Any] | None:
    """Return the router tables from one mikrotik/snapshot message."""
    try:
        data = json.loads(payload)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {
        "collected_utc": str(data.get("collected_utc") or ""),
        "connections": _rows(data.get("connection")),
        "addresses": _rows(data.get("address")),
        "dhcp": _rows(data.get("dhcp_lease")),
        "dns": _rows(data.get("dns_static")),
        "ppp": _rows(data.get("ppp_active")),
    }


def is_stale(collected_utc: str, now: datetime | None = None, max_age: int = STALE_AFTER_SECONDS) -> bool:
    """A snapshot is stale when its collection time is missing or too old."""
    when = _collected_at(collected_utc)
    if when is None:
        return True
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (current - when).total_seconds() > max_age


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _collected_at(text: str) -> datetime | None:
    if not text:
        return None
    try:
        when = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when
