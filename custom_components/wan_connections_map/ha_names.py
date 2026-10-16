"""Names Home Assistant already learned for local devices."""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

from .names import known_ip_names, normalize_mac


def known_names(hass, leases: list[dict[str, Any]] | None) -> dict[str, str]:
    """Return lease address to a Home Assistant display name."""
    return known_ip_names(leases, _entry_views(_all_entries(hass)), _device_views(_all_devices(hass)))


def _all_entries(hass) -> list[Any]:
    method = hass.config_entries.async_entries
    try:
        return list(method(include_ignore=True, include_disabled=True))
    except TypeError:
        return list(method())


def _all_devices(hass) -> list[Any]:
    from homeassistant.helpers import device_registry as dr

    return list(dr.async_get(hass).devices.values())


def _host_address(value: Any) -> str:
    text = str(value or "").strip()
    if "://" in text:
        text = urlparse(text).hostname or ""
    text = text.split("/")[0]
    if text.count(":") == 1:
        text = text.split(":", 1)[0]
    try:
        address = ipaddress.IPv4Address(text)
    except ValueError:
        return ""
    if address.is_private or address.is_link_local:
        return str(address)
    return ""


def _entry_views(entries: list[Any]) -> list[dict[str, str]]:
    views = []
    for entry in entries:
        data = getattr(entry, "data", None) or {}
        host = _host_address(data.get("host") or data.get("ip") or data.get("ip_address"))
        mac = normalize_mac(data.get("mac"))
        if not host and not mac:
            continue
        views.append(
            {
                "title": str(getattr(entry, "title", "") or ""),
                "host": host,
                "mac": mac,
                "model": str(data.get("model") or ""),
            }
        )
    return views


def _device_views(devices: list[Any]) -> list[dict[str, Any]]:
    views = []
    for device in devices:
        macs = []
        for kind, value in getattr(device, "connections", ()) or ():
            if kind != "mac":
                continue
            mac = normalize_mac(value)
            if mac:
                macs.append(mac)
        views.append(
            {
                "name": str(getattr(device, "name", "") or ""),
                "name_by_user": str(getattr(device, "name_by_user", "") or ""),
                "model": str(getattr(device, "model", "") or ""),
                "macs": macs,
            }
        )
    return views
