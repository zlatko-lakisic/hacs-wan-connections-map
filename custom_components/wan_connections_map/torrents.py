"""Match qBittorrent peers to the torrent they belong to."""

from __future__ import annotations

from typing import Any


def active_torrents(torrents: dict[str, Any] | None, limit: int = 25) -> list[tuple[str, str]]:
    """Return the busiest torrents as (hash, name)."""
    ranked: list[tuple[int, str, str]] = []
    for torrent_hash, torrent in (torrents or {}).items():
        if not isinstance(torrent, dict):
            continue
        try:
            speed = int(torrent.get("dl_speed") or 0) + int(torrent.get("up_speed") or 0)
            peers = int(torrent.get("num_leechs") or 0) + int(torrent.get("num_seeds") or 0)
        except (TypeError, ValueError):
            continue
        if speed <= 0 and peers <= 0:
            continue
        name = str(torrent.get("name") or "").strip()
        if not name:
            continue
        ranked.append((speed, str(torrent_hash), name))
    ranked.sort(reverse=True)
    return [(torrent_hash, name) for _, torrent_hash, name in ranked[:limit]]


def index_torrent_peers(named_payloads: list[tuple[str, dict]]) -> dict[str, list[str]]:
    """Map a peer address to the torrent names that list it."""
    found: dict[str, list[str]] = {}
    for name, payload in named_payloads:
        peers = (payload or {}).get("peers") or {}
        if not isinstance(peers, dict):
            continue
        for peer in peers.values():
            if not isinstance(peer, dict):
                continue
            ip = _peer_ip(peer.get("ip"))
            if not ip:
                continue
            names = found.setdefault(ip, [])
            if name not in names:
                names.append(name)
    return found


def _peer_ip(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("[") and "]" in text:
        return text[1 : text.index("]")]
    if text.count(":") == 1:
        return text.split(":", 1)[0]
    return text.split("%", 1)[0]
