"""Match Traefik access messages to incoming peers."""

from __future__ import annotations

import re

from datetime import datetime, timedelta, timezone
import ipaddress
import json
from typing import Any

Record = dict[str, Any]
Store = dict[str, Record]

HOSTNAME_MAX_AGE = timedelta(minutes=10)
HOSTNAME_GRACE = timedelta(seconds=75)
RESOURCE_MIN_BPS = 500_000
MAX_RESOURCES = 15

_PRIVATE = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
]


def remember(
    store: Store,
    payload: str,
    *,
    now: datetime | None = None,
    max_age: timedelta = HOSTNAME_MAX_AGE,
    extra_networks: list[ipaddress.IPv4Network] | None = None,
    wan: ipaddress.IPv4Address | None = None,
) -> bool:
    """Keep the newest RequestHost for a public ClientHost, including an open transfer."""
    parsed = _parse_message(payload)
    if parsed is None:
        return False
    client, when, host, method, path, size, bot, started = parsed
    if _is_local(client, extra_networks or [], wan):
        return False
    moment = now or datetime.now(timezone.utc)
    if when < moment - max_age:
        return False
    key = str(client)
    current = store.get(key)
    changed = False
    if current is None:
        current = {"at": when, "host": host, "resources": [], "bot": bot}
        store[key] = current
        changed = True
    elif when >= current["at"]:
        if current["host"] != host or current.get("bot") != bot:
            changed = True
        current["at"] = when
        current["host"] = host
        current["bot"] = bot
    if _add_resource(current, when, host, method, path, size, started):
        changed = True
    return changed


def apply_hostnames(
    peers: list[dict[str, Any]],
    store: Store,
    *,
    now: datetime | None = None,
    max_age: timedelta = HOSTNAME_MAX_AGE,
) -> bool:
    """Label an incoming peer with the newest recent RequestHost for its IP."""
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - max_age
    changed = False
    for peer in peers:
        host = ""
        bot = ""
        resources: list[dict[str, Any]] | None = None
        if peer.get("kind") == "in":
            record = store.get(str(peer.get("ip") or ""))
            fresh = record if record is not None and record["at"] >= cutoff else None
            if fresh is not None:
                host = fresh["host"]
                bot = fresh.get("bot") or ""
            if (peer.get("rate_bps") or 0) > RESOURCE_MIN_BPS:
                resources = _public_resources(fresh) if fresh is not None else []
        names = [host] if host else []
        if peer.get("hostnames") != names:
            peer["hostnames"] = names
            changed = True
        if peer.get("bot") != bot:
            peer["bot"] = bot
            changed = True
        if resources is None:
            if "resources" in peer:
                peer.pop("resources")
                changed = True
        elif peer.get("resources") != resources:
            peer["resources"] = resources
            changed = True
        for flow in peer.get("flows") or []:
            if flow.get("hostname") != host:
                flow["hostname"] = host
                changed = True
    return changed


def prune(
    store: Store,
    active_ips: set[str],
    seen_ips: set[str],
    *,
    now: datetime | None = None,
    max_age: timedelta = HOSTNAME_MAX_AGE,
    grace: timedelta = HOSTNAME_GRACE,
) -> None:
    """Drop a record after its peer leaves, or after its request is older than the peer lifetime."""
    moment = now or datetime.now(timezone.utc)
    stale = moment - max_age
    fresh = moment - grace
    for ip in list(store):
        when = store[ip]["at"]
        if when < stale or (ip not in active_ips and (ip in seen_ips or when < fresh)):
            del store[ip]


def _parse_message(
    payload: str,
) -> tuple[ipaddress.IPv4Address, datetime, str, str, str, int, str, bool] | None:
    text = str(payload or "").strip()
    if not text.startswith("{"):
        return None
    try:
        row = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(row, dict):
        return None
    fields = row.get("fields") if isinstance(row.get("fields"), dict) else row
    host = str(fields.get("RequestHost") or "").strip().lower().rstrip(".")
    if not host or host == "-":
        return None
    try:
        client = ipaddress.IPv4Address(str(fields.get("ClientHost") or "").strip())
    except ipaddress.AddressValueError:
        return None
    when = _parse_time(fields.get("StartUTC"))
    if when is None:
        return None
    started = str(fields.get("AccessEvent") or "").strip().lower() == "start"
    return (
        client,
        when,
        host,
        _method(fields.get("RequestMethod")),
        _path(fields.get("RequestPath")),
        _size(fields.get("DownstreamContentSize")),
        _bot(_user_agent(fields)),
        started,
    )


_BOTS = (
    ("homeassistant/", "Home Assistant"),
    ("aiohttp/", "Script"),
    ("googlebot", "Googlebot"),
    ("bingbot", "Bingbot"),
    ("duckduckbot", "DuckDuckBot"),
    ("baiduspider", "Baiduspider"),
    ("yandexbot", "YandexBot"),
    ("ahrefsbot", "AhrefsBot"),
    ("semrushbot", "SemrushBot"),
    ("petalbot", "PetalBot"),
    ("bytespider", "Bytespider"),
    ("gptbot", "GPTBot"),
    ("claudebot", "ClaudeBot"),
    ("amazonbot", "Amazonbot"),
    ("applebot", "Applebot"),
    ("facebookexternalhit", "Facebook"),
    ("twitterbot", "Twitterbot"),
    ("slackbot", "Slackbot"),
    ("discordbot", "Discordbot"),
    ("mj12bot", "MJ12bot"),
    ("dotbot", "DotBot"),
    ("python-requests", "Script"),
    ("curl/", "Script"),
    ("wget/", "Script"),
    ("go-http-client", "Script"),
    ("scrapy", "Script"),
    ("zgrab", "Scanner"),
    ("nuclei", "Scanner"),
    ("masscan", "Scanner"),
    ("sqlmap", "Scanner"),
    ("nikto", "Scanner"),
    ("libwww-perl", "Script"),
)
_BOT_WORD = re.compile(r"\b(bot|crawler|spider)\b", re.IGNORECASE)


def _user_agent(fields: dict[str, Any]) -> str:
    for key, value in fields.items():
        folded = str(key).lower().replace("_", "-")
        if folded in {"request-user-agent", "user-agent"}:
            return str(value or "")
    return ""


def _bot(user_agent: str) -> str:
    text = str(user_agent or "").strip().lower()
    if not text:
        return ""
    for needle, label in _BOTS:
        if needle in text:
            return label
    if _BOT_WORD.search(text):
        return "Bot"
    return ""


def _add_resource(
    entry: Record,
    when: datetime,
    host: str,
    method: str,
    path: str,
    size: int,
    started: bool,
) -> bool:
    """Record a path. A start is open; a finish with the same StartUTC closes it."""
    if not path:
        return False
    for item in entry["resources"]:
        if item["method"] == method and item["path"] == path and item["host"] == host:
            if when < item["at"]:
                return False
            changed = False
            if when > item["at"]:
                item["at"] = when
                item["open"] = started
                if started:
                    item["bytes"] = 0
                changed = True
            if not started:
                if item.get("open", True):
                    item["open"] = False
                    changed = True
                if size != item["bytes"]:
                    item["bytes"] = size
                    changed = True
            return changed
    entry["resources"].append(
        {
            "method": method,
            "path": path,
            "host": host,
            "at": when,
            "bytes": 0 if started else size,
            "open": started,
        }
    )
    entry["resources"].sort(key=lambda item: item["at"], reverse=True)
    del entry["resources"][MAX_RESOURCES:]
    return True


def _public_resources(record: Record) -> list[dict[str, Any]]:
    ordered = sorted(
        record["resources"],
        key=lambda item: (bool(item.get("open")), item["bytes"], item["at"]),
        reverse=True,
    )
    return [
        {
            "method": item["method"],
            "path": item["path"],
            "host": item["host"],
            "bytes": item["bytes"],
            "open": bool(item.get("open")),
        }
        for item in ordered
    ]


def _method(value: Any) -> str:
    text = str(value or "GET").strip().upper()
    return text or "GET"


def _path(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text == "-":
        return ""
    return text[:300]


def _size(value: Any) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _is_local(
    ip: ipaddress.IPv4Address,
    extra: list[ipaddress.IPv4Network],
    wan: ipaddress.IPv4Address | None,
) -> bool:
    if wan is not None and ip == wan:
        return True
    if any(ip in net for net in _PRIVATE):
        return True
    return any(ip in net for net in extra)


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    if "." in text:
        head, frac = text.split(".", 1)
        digits = []
        suffix = ""
        for index, char in enumerate(frac):
            if char.isdigit() and len(digits) < 6:
                digits.append(char)
            elif not char.isdigit():
                suffix = frac[index:]
                break
        text = f"{head}.{''.join(digits) or '0'}{suffix}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
