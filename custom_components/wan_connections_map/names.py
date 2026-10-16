"""Map a local IPv4 address to a client hostname."""

from __future__ import annotations

import ipaddress
import re
from collections import defaultdict
from typing import Any

_MODEL_SUFFIX = re.compile(r"\s*\(([^)]*)\)\s*$")
_BRACKET_PREFIX = re.compile(r"^\[[^\]]+\]\s*")


def _disabled(value: Any) -> bool:
    if value is True:
        return True
    return str(value or "").strip().lower() in {"true", "yes", "on", "1"}


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"unknown", "none"}:
        return ""
    return text.split("#", 1)[0].strip()


def lease_address(row: dict[str, Any]) -> str:
    """The lease address the name map is keyed by."""
    address = str(row.get("address") or row.get("active-address") or "").split("/")[0].strip()
    if not address or address.lower() == "unknown":
        return ""
    return address


def normalize_mac(value: Any) -> str:
    """Return a lowercase colon-separated MAC, or an empty string."""
    hexes = re.sub(r"[^0-9a-fA-F]", "", str(value or ""))
    if len(hexes) != 12:
        return ""
    hexes = hexes.lower()
    return ":".join(hexes[i : i + 2] for i in range(0, 12, 2))


def lease_mac(row: dict[str, Any]) -> str:
    return normalize_mac(row.get("active-mac-address") or row.get("mac-address"))


def display_name(value: Any) -> str:
    """A name worth showing in place of a missing or shared hostname."""
    text = _clean(value)
    text = _BRACKET_PREFIX.sub("", text).strip()
    match = _MODEL_SUFFIX.search(text)
    if match:
        inner = match.group(1).strip()
        if inner.lower() == "unknown" or any(char.isdigit() for char in inner):
            text = text[: match.start()].strip()
    if not text or normalize_mac(text):
        return ""
    try:
        ipaddress.ip_address(text.split("/")[0])
    except ValueError:
        return text
    return ""


def known_ip_names(
    leases: list[dict[str, Any]] | None,
    entries: list[dict[str, Any]] | None,
    devices: list[dict[str, Any]] | None,
) -> dict[str, str]:
    """Map lease addresses to Home Assistant display names.

    A device MAC follows the current lease. An entry host is used when the
    lease table has no MAC to follow. A user-given device name outranks a
    discovered title. A model name is used only when one device has that model.
    """
    mac_to_ips: dict[str, list[str]] = defaultdict(list)
    for row in leases or []:
        if _disabled(row.get("disabled")):
            continue
        address = lease_address(row)
        mac = lease_mac(row)
        if address and mac and address not in mac_to_ips[mac]:
            mac_to_ips[mac].append(address)

    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for device in devices or []:
        model = str(device.get("model") or "").strip().lower()
        if model:
            by_model[model].append(device)

    records: list[dict[str, Any]] = []
    for device in devices or []:
        label = device.get("name_by_user") or device.get("name") or ""
        rank = 3 if device.get("name_by_user") else 1
        for mac in device.get("macs") or []:
            records.append({"ip": "", "mac": mac, "name": label, "rank": rank})

    for entry in entries or []:
        host = str(entry.get("host") or "")
        mac = str(entry.get("mac") or "")
        model = str(entry.get("model") or "").strip().lower()
        matches = by_model.get(model, []) if model else []
        if len(matches) == 1:
            device = matches[0]
            label = device.get("name_by_user") or device.get("name") or ""
            records.append(
                {
                    "ip": host,
                    "mac": mac,
                    "name": label,
                    "rank": 3 if device.get("name_by_user") else 2,
                }
            )
        records.append({"ip": host, "mac": mac, "name": entry.get("title") or "", "rank": 2})

    best: dict[str, tuple[int, str]] = {}
    for record in records:
        name = display_name(record.get("name"))
        if not name:
            continue
        rank = int(record.get("rank") or 1)
        mac = normalize_mac(record.get("mac"))
        if mac and mac in mac_to_ips:
            addresses = mac_to_ips[mac]
        else:
            addresses = [str(record.get("ip") or "")]
        for address in addresses:
            if not address:
                continue
            current = best.get(address)
            if current is None or rank > current[0] or (rank == current[0] and len(name) > len(current[1])):
                best[address] = (rank, name)
    return {address: name for address, (_rank, name) in best.items()}


def supplement_names(
    names: dict[str, str],
    leases: list[dict[str, Any]] | None,
    known: dict[str, str],
) -> dict[str, str]:
    """Fill unknown hostnames and split a label shared by several leases.

    A unique DHCP comment or hostname is left unchanged.
    """
    result = dict(names)
    by_label: dict[str, list[str]] = defaultdict(list)
    for address, label in result.items():
        if label:
            by_label[label.lower()].append(address)
    ambiguous = {address for group in by_label.values() if len(group) > 1 for address in group}

    for row in leases or []:
        if _disabled(row.get("disabled")):
            continue
        address = lease_address(row)
        if not address:
            continue
        current = result.get(address, "")
        if current and address not in ambiguous:
            continue
        replacement = known.get(address, "")
        if not replacement or replacement.lower() == current.lower():
            continue
        result[address] = replacement
    return result


def build_name_map(
    dhcp_rows: list[dict[str, Any]] | None,
    dns_rows: list[dict[str, Any]] | None,
) -> dict[str, str]:
    """Return address to hostname.

    Order matches the MikroTik Router integration: DHCP comment, DHCP
    host-name, static DNS comment, then static DNS name. Static leases live
    in the same DHCP lease table as dynamic ones.
    """
    names: dict[str, str] = {}

    for row in dhcp_rows or []:
        if _disabled(row.get("disabled")):
            continue
        address = lease_address(row)
        if not address:
            continue
        chosen = _clean(row.get("comment")) or _clean(row.get("host-name"))
        if chosen and address not in names:
            names[address] = chosen.split(".")[0]

    for row in dns_rows or []:
        address = str(row.get("address") or "").split("/")[0]
        if not address or address in names:
            continue
        chosen = _clean(row.get("comment")) or _clean(row.get("name"))
        if chosen:
            names[address] = chosen.split(".")[0]

    return names
