"""Read-only MikroTik API helpers."""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

from librouteros import connect
from librouteros.exceptions import LibRouterosError

_LOGGER = logging.getLogger(__name__)

_CONN_FIELDS = (
    "src-address",
    "dst-address",
    "src-port",
    "dst-port",
    "protocol",
    "orig-rate",
    "repl-rate",
)


def open_api(host: str, username: str, password: str, port: int):
    """Open a RouterOS API session. Port 0 uses the API default."""
    kwargs: dict[str, Any] = {}
    if port:
        kwargs["port"] = port
    try:
        return connect(host, username, password, **kwargs)
    except TypeError:
        return connect(
            host=host,
            username=username,
            password=password,
            **kwargs,
        )


def _rows(api, path: str, *fields: str) -> list[dict[str, Any]]:
    try:
        query = api.path(path)
        if fields and hasattr(query, "select"):
            return [dict(row) for row in query.select(*fields)]
        return [dict(row) for row in query]
    except (LibRouterosError, OSError, TypeError, ValueError) as err:
        _LOGGER.warning("MikroTik query %s failed: %s", path, err)
        return []


def fetch_snapshot(api) -> dict[str, Any]:
    """Pull the tables needed for one map update."""
    return {
        "connections": _rows(api, "/ip/firewall/connection", *_CONN_FIELDS),
        "addresses": _rows(api, "/ip/address", "address", "interface"),
        "dhcp": _rows(
            api,
            "/ip/dhcp-server/lease",
            "address",
            "active-address",
            "host-name",
            "comment",
            "mac-address",
            "active-mac-address",
            "disabled",
        ),
        "dns": _rows(api, "/ip/dns/static", "name", "address", "comment"),
        "ppp": _rows(api, "/ppp/active", "caller-id", "address", "name"),
    }


def wan_address(addresses: list[dict[str, Any]]) -> ipaddress.IPv4Address | None:
    """Return the IPv4 address on ether1, the home WAN port."""
    for row in addresses:
        interface = str(row.get("interface") or "").lower()
        if "ether1" not in interface:
            continue
        text = str(row.get("address") or "").split("/")[0]
        try:
            return ipaddress.IPv4Address(text)
        except ipaddress.AddressValueError:
            continue
    return None


def ppp_caller_ips(rows: list[dict[str, Any]]) -> set[ipaddress.IPv4Address]:
    """Public caller addresses of active PPP, L2TP, and OpenVPN sessions."""
    from .classify import parse_endpoint

    found: set[ipaddress.IPv4Address] = set()
    for row in rows:
        ip, _ = parse_endpoint(row.get("caller-id"))
        if ip is not None and not ip.is_private:
            found.add(ip)
    return found
