"""Turn a MikroTik connection table into grouped public peers."""

from __future__ import annotations

import ipaddress
import re
from typing import Any

_BUILTIN = [
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

_RATE_SUFFIXES = (
    ("gbps", 1_000_000_000),
    ("mbps", 1_000_000),
    ("kbps", 1_000),
    ("bps", 1),
)


def parse_rate(value: Any) -> int:
    """Parse a RouterOS orig-rate / repl-rate into bits per second."""
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip().lower().replace(" ", "").replace(",", "")
    if not text or text in {"0", "none", "unknown"}:
        return 0
    mult = 1
    for suffix, factor in _RATE_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            mult = factor
            break
    try:
        return max(0, int(float(text) * mult))
    except ValueError:
        return 0


def parse_endpoint(value: Any) -> tuple[ipaddress.IPv4Address | None, int | None]:
    """Split a RouterOS address field into an IPv4 address and port."""
    if not value:
        return None, None
    text = str(value).strip()
    if text.startswith("["):
        return None, None
    if ":" not in text:
        try:
            return ipaddress.IPv4Address(text), None
        except ipaddress.AddressValueError:
            return None, None
    host, _, port_text = text.rpartition(":")
    try:
        ip = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError:
        return None, None
    try:
        port = int(port_text)
    except ValueError:
        port = None
    return ip, port


def parse_networks(text: str) -> list[ipaddress.IPv4Network]:
    """Parse a newline or comma separated prefix list."""
    nets: list[ipaddress.IPv4Network] = []
    for part in re.split(r"[\s,;]+", text or ""):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue
    return nets


def parse_ip_set(text: str) -> set[ipaddress.IPv4Address]:
    """Parse a list of host addresses."""
    found: set[ipaddress.IPv4Address] = set()
    for part in re.split(r"[\s,;]+", text or ""):
        part = part.strip()
        if not part:
            continue
        ip, _ = parse_endpoint(part)
        if ip is not None:
            found.add(ip)
    return found


def ppp_session_names(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Map a public PPP caller address to the active session name."""
    found: dict[str, str] = {}
    for row in rows:
        ip, _ = parse_endpoint(row.get("caller-id"))
        name = str(row.get("name") or "").strip()
        if ip is None or ip.is_private or not name:
            continue
        found[str(ip)] = name
    return found


def is_ignored(
    ip: ipaddress.IPv4Address | None,
    extra: list[ipaddress.IPv4Network],
    wan: ipaddress.IPv4Address | None,
) -> bool:
    """Return True when an address must not be plotted."""
    if ip is None:
        return True
    if wan is not None and ip == wan:
        return True
    if any(ip in net for net in _BUILTIN):
        return True
    return any(ip in net for net in extra)


def _port(value: Any) -> int | None:
    """Parse a RouterOS port field. Addresses may already carry the port."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    if 0 <= port <= 65535:
        return port
    return None


def _protocol(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"6", "tcp"}:
        return "tcp"
    if text in {"17", "udp"}:
        return "udp"
    return text or "ip"


def aggregate_connections(
    rows: list[dict[str, Any]],
    *,
    extra_networks: list[ipaddress.IPv4Network],
    exclude_sources: set[ipaddress.IPv4Address],
    wan: ipaddress.IPv4Address | None,
    vpn_ips: set[ipaddress.IPv4Address],
    torrent_ips: set[ipaddress.IPv4Address] | None = None,
    names: dict[str, str],
    max_peers: int,
    max_flows: int,
) -> list[dict[str, Any]]:
    """Group live public peers. One dict per remote IPv4 address."""
    torrent_ips = torrent_ips or set()
    groups: dict[str, dict[str, Any]] = {}

    for row in rows:
        orig = parse_rate(row.get("orig-rate"))
        repl = parse_rate(row.get("repl-rate"))
        rate = orig + repl
        if rate <= 0:
            continue
        src_ip, src_port = parse_endpoint(row.get("src-address"))
        dst_ip, dst_port = parse_endpoint(row.get("dst-address"))
        if src_port is None:
            src_port = _port(row.get("src-port"))
        if dst_port is None:
            dst_port = _port(row.get("dst-port"))
        if src_ip is None or dst_ip is None:
            continue
        if src_ip in exclude_sources and src_ip not in torrent_ips:
            continue

        src_local = is_ignored(src_ip, extra_networks, wan)
        dst_local = is_ignored(dst_ip, extra_networks, wan)
        if src_local and not dst_local:
            kind = "out"
            remote = dst_ip
            local = src_ip
            local_port = src_port
            remote_port = dst_port
        elif dst_local and not src_local:
            kind = "in"
            remote = src_ip
            local = dst_ip
            local_port = dst_port
            remote_port = src_port
        else:
            continue

        if is_ignored(remote, extra_networks, wan):
            continue
        direction = kind
        if direction == "in":
            leech, seed = orig, repl
        else:
            seed, leech = orig, repl
        if remote in vpn_ips:
            kind = "vpn"
        elif local in torrent_ips:
            kind = "torrent"

        key = str(remote)
        group = groups.get(key)
        if group is None:
            group = {
                "ip": key,
                "kind": kind,
                "count": 0,
                "rate_bps": 0,
                "seed_bps": 0,
                "leech_bps": 0,
                "flows": [],
            }
            groups[key] = group
        elif kind == "vpn":
            group["kind"] = "vpn"
        elif kind == "torrent" and group["kind"] != "vpn":
            group["kind"] = "torrent"
        group["count"] += 1
        group["rate_bps"] += rate
        group["seed_bps"] += seed
        group["leech_bps"] += leech
        group["flows"].append(
            {
                "protocol": _protocol(row.get("protocol")),
                "local_address": str(local),
                "local_name": names.get(str(local), ""),
                "local_port": local_port,
                "remote_port": remote_port,
                "inbound": direction == "in",
                "rate_bps": rate,
                "seed_bps": seed,
                "leech_bps": leech,
            }
        )

    peers = sorted(groups.values(), key=lambda item: item["rate_bps"], reverse=True)
    peers = peers[:max_peers]
    for peer in peers:
        peer["flows"].sort(key=lambda item: item["rate_bps"], reverse=True)
        peer["flows"] = peer["flows"][:max_flows]
    return peers
