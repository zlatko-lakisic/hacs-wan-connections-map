"""Polling coordinator for WAN connection peers."""

from __future__ import annotations

from datetime import timedelta
import logging
from pathlib import Path
import time

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .classify import aggregate_connections, parse_endpoint, parse_ip_set, parse_networks, ppp_session_names
from .const import (
    CONF_EXCLUDE_SOURCES,
    CONF_LOCAL_PREFIXES,
    CONF_TRAEFIK_HOST,
    CONF_TRAEFIK_LOG,
    CONF_TRAEFIK_PASSWORD,
    CONF_TRAEFIK_USERNAME,
    CONF_VPN_ENTITIES,
    DEFAULT_EXCLUDE_SOURCES,
    DEFAULT_LOCAL_PREFIXES,
    DEFAULT_TORRENT_SOURCES,
    DEFAULT_TRAEFIK_LOG,
    DEFAULT_VPN_ENTITIES,
    DOMAIN,
    MAX_FLOWS,
    MAX_PEERS,
    MIKROTIK_SNAPSHOT_TOPIC,
    TRAEFIK_ACCESS_TOPIC,
)
from .geoip import asn_database_path, database_path, lookup, lookup_organizations
from .ha_names import known_names
from .names import build_name_map, supplement_names
from .network import classify
from .router import wan_address
from .snapshot import is_stale, parse_snapshot
from .torrents import active_torrents, index_torrent_peers
from .traefik_hosts import apply_hostnames, prune, remember
from .traefik_ssh import read_access_log

_LOGGER = logging.getLogger(__name__)


class WanConnectionsCoordinator(DataUpdateCoordinator):
    """Fetch and classify WAN peers."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,
            config_entry=entry,
        )
        self.entry = entry
        self.db_path = database_path(hass.config.path())
        self.asn_path = asn_database_path(hass.config.path())
        self._hosts: dict = {}
        self._seen_ips: set[str] = set()
        self._extra_networks = []
        self._wan = None
        self._mqtt_unsub = None
        self._snapshot_unsub = None
        self._stale_unsub = None
        self._torrent_unsub = None
        self._torrent_names: dict[str, list[str]] = {}
        self._torrent_at = 0.0
        self._mqtt_ready = False
        self._applying = False
        self._pending_payload: str | None = None

    async def _async_update_data(self) -> dict:
        """The first refresh waits for MQTT. Later snapshots replace this."""
        if self.data:
            return self.data
        return {
            "points": [],
            "home": _home_point(self.hass),
            "mostar": {"lat": None, "lon": None},
            "count": 0,
            "connections": 0,
            "stale": True,
            "collected_utc": "",
        }

    async def _async_build(self, snapshot: dict) -> dict:
        options = self.entry.options or self.entry.data
        self._extra_networks = parse_networks(
            options.get(CONF_LOCAL_PREFIXES, DEFAULT_LOCAL_PREFIXES)
        )
        vpn_ips = set()
        for entity_id in _lines(options.get(CONF_VPN_ENTITIES, DEFAULT_VPN_ENTITIES)):
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            ip, _ = parse_endpoint(state.state)
            if ip is not None:
                vpn_ips.add(ip)

        self._wan = wan_address(snapshot["addresses"])
        session_names = ppp_session_names(snapshot["ppp"])
        for text in session_names:
            ip, _ = parse_endpoint(text)
            if ip is not None:
                vpn_ips.add(ip)
        names = build_name_map(snapshot["dhcp"], snapshot["dns"])
        try:
            names = supplement_names(names, snapshot["dhcp"], known_names(self.hass, snapshot["dhcp"]))
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Home Assistant device names were not applied", exc_info=True)
        peers = aggregate_connections(
            snapshot["connections"],
            extra_networks=self._extra_networks,
            exclude_sources=parse_ip_set(
                options.get(CONF_EXCLUDE_SOURCES, DEFAULT_EXCLUDE_SOURCES)
            ),
            wan=self._wan,
            vpn_ips=vpn_ips,
            torrent_ips=parse_ip_set(DEFAULT_TORRENT_SOURCES),
            names=names,
            max_peers=MAX_PEERS,
            max_flows=MAX_FLOWS,
        )
        for peer in peers:
            if peer.get("kind") == "vpn":
                session = session_names.get(peer["ip"])
                if session:
                    peer["ppp_name"] = session
        if self._mqtt_ready:
            apply_hostnames(peers, self._hosts)
        else:
            await _attach_traefik(
                self.hass,
                self.db_path,
                options,
                peers,
                self._extra_networks,
                self._wan,
            )

        db_path = self.db_path
        placed = []
        for peer in peers:
            geo = await self.hass.async_add_executor_job(lookup, db_path, peer["ip"])
            if geo is None:
                continue
            lat, lon, city, country = geo
            peer["lat"] = lat
            peer["lon"] = lon
            peer["city"] = city
            peer["country"] = country
            placed.append(peer)

        orgs = await self.hass.async_add_executor_job(
            lookup_organizations, self.asn_path, [peer["ip"] for peer in placed]
        )
        for peer in placed:
            peer["operator"] = classify(orgs.get(peer["ip"], ""), incoming=peer.get("kind") == "in")
        if any(peer.get("kind") == "torrent" for peer in placed):
            await self._async_attach_torrents(placed)

        if self._mqtt_ready:
            active = {peer["ip"] for peer in placed if peer.get("kind") == "in"}
            prune(self._hosts, active, self._seen_ips)
            self._seen_ips = active

        mostar = _mostar_point(self.hass, options, placed)
        if mostar["lat"] is None:
            mostar_ip = mostar.get("ip")
            if mostar_ip:
                geo = await self.hass.async_add_executor_job(lookup, db_path, mostar_ip)
                if geo is not None:
                    mostar = {"lat": geo[0], "lon": geo[1]}
        mostar.pop("ip", None)
        collected = snapshot.get("collected_utc") or ""
        return {
            "points": placed,
            "home": _home_point(self.hass),
            "mostar": mostar,
            "count": len(placed),
            "connections": sum(int(peer.get("count") or 0) for peer in placed),
            "stale": is_stale(collected),
            "collected_utc": collected,
        }

    async def async_subscribe_access(self) -> None:
        """Listen for Traefik access lines and MikroTik snapshots."""
        if "mqtt" not in self.hass.config.components:
            _LOGGER.warning("MQTT is not loaded; the WAN map has no router snapshot")
            return
        from homeassistant.components import mqtt

        try:
            self._mqtt_unsub = await mqtt.async_subscribe(
                self.hass, TRAEFIK_ACCESS_TOPIC, self._on_access, qos=0
            )
            self._mqtt_ready = True
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not subscribe to Traefik access: %s", err)
        try:
            self._snapshot_unsub = await mqtt.async_subscribe(
                self.hass, MIKROTIK_SNAPSHOT_TOPIC, self._on_snapshot, qos=0
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not subscribe to the MikroTik snapshot: %s", err)
        self._stale_unsub = async_track_time_interval(
            self.hass, self._async_mark_stale, timedelta(seconds=15)
        )
        self._torrent_unsub = async_track_time_interval(
            self.hass, self._async_refresh_torrents, timedelta(seconds=2)
        )

    @callback
    def _on_snapshot(self, message) -> None:
        self._pending_payload = str(getattr(message, "payload", "") or "")
        if not self._applying:
            self.hass.async_create_task(self._async_drain_snapshot())

    async def _async_drain_snapshot(self) -> None:
        self._applying = True
        try:
            while self._pending_payload is not None:
                payload = self._pending_payload
                self._pending_payload = None
                snapshot = await self.hass.async_add_executor_job(parse_snapshot, payload)
                if snapshot is None:
                    _LOGGER.warning("Ignored a MikroTik snapshot that was not a JSON object")
                    continue
                self.async_set_updated_data(await self._async_build(snapshot))
        finally:
            self._applying = False
            if self._pending_payload is not None:
                self.hass.async_create_task(self._async_drain_snapshot())

    @callback
    def _async_mark_stale(self, _now) -> None:
        data = self.data
        if not data:
            return
        stale = is_stale(str(data.get("collected_utc") or ""))
        if stale != bool(data.get("stale")):
            data["stale"] = stale
            self.async_set_updated_data(data)

    @callback
    def _on_access(self, message) -> None:
        changed = remember(
            self._hosts,
            getattr(message, "payload", ""),
            extra_networks=self._extra_networks,
            wan=self._wan,
        )
        points = (self.data or {}).get("points") if self.data else None
        if changed and points and apply_hostnames(points, self._hosts):
            self.async_set_updated_data(self.data)

    @callback
    def _async_refresh_torrents(self, _now) -> None:
        if not self.data or not any(peer.get("kind") == "torrent" for peer in self.data.get("points") or []):
            return
        self.hass.async_create_task(self._async_apply_fresh_torrents())

    async def _async_apply_fresh_torrents(self) -> None:
        data = self.data
        if not data:
            return
        points = data.get("points") or []
        names = await self._async_torrent_names()
        changed = False
        for peer in points:
            if peer.get("kind") != "torrent":
                continue
            nxt = list(names.get(peer["ip"]) or [])
            if peer.get("torrents") != nxt:
                peer["torrents"] = nxt
                changed = True
        if changed:
            self.async_set_updated_data(data)

    async def _async_attach_torrents(self, peers: list) -> None:
        names = await self._async_torrent_names()
        for peer in peers:
            if peer.get("kind") == "torrent":
                peer["torrents"] = list(names.get(peer["ip"]) or [])

    async def _async_torrent_names(self) -> dict[str, list[str]]:
        now = time.monotonic()
        if self._torrent_at and now - self._torrent_at < 2:
            return self._torrent_names
        coord = _qbittorrent(self.hass)
        if coord is None:
            return self._torrent_names
        torrents = dict((coord.data or {}).get("torrents") or {})
        client = getattr(getattr(coord, "api", None), "client", None)
        chosen = active_torrents(torrents)

        def fetch() -> dict[str, list[str]]:
            method = getattr(client, "sync_torrent_peers", None)
            if method is None:
                return {}
            payloads = []
            for torrent_hash, name in chosen:
                try:
                    payloads.append((name, dict(method(torrent_hash=torrent_hash, rid=0) or {})))
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("Could not read peers for a torrent", exc_info=True)
            return index_torrent_peers(payloads)

        try:
            names = await self.hass.async_add_executor_job(fetch)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Torrent peer lookup failed", exc_info=True)
            return self._torrent_names
        self._torrent_names = names
        self._torrent_at = time.monotonic()
        return names

    @callback
    def async_unsubscribe_access(self) -> None:
        for unsub_name in ("_mqtt_unsub", "_snapshot_unsub", "_stale_unsub", "_torrent_unsub"):
            unsub = getattr(self, unsub_name, None)
            if unsub:
                unsub()
                setattr(self, unsub_name, None)
        self._mqtt_ready = False


def _home_point(hass: HomeAssistant) -> dict:
    zone = hass.states.get("zone.home")
    if zone is None:
        return {"lat": None, "lon": None}
    return {
        "lat": zone.attributes.get("latitude"),
        "lon": zone.attributes.get("longitude"),
    }


def _mostar_point(hass: HomeAssistant, options: dict, placed: list) -> dict:
    """Coordinates of the Mostar VPN peer, where torrent arcs start."""
    mostar_ip = ""
    for entity_id in _lines(options.get(CONF_VPN_ENTITIES, DEFAULT_VPN_ENTITIES)):
        state = hass.states.get(entity_id)
        if state is None:
            continue
        ip, _ = parse_endpoint(state.state)
        if ip is not None:
            mostar_ip = str(ip)
            break
    for peer in placed:
        if peer.get("ip") == mostar_ip and peer.get("lat") is not None:
            return {"lat": peer["lat"], "lon": peer["lon"]}
    return {"lat": None, "lon": None, "ip": mostar_ip}


def _lines(text: str) -> list[str]:
    return [part.strip() for part in str(text or "").replace(",", "\n").splitlines() if part.strip()]


def _qbittorrent(hass: HomeAssistant):
    """The qBittorrent coordinator, when that integration is loaded."""
    entries = hass.config_entries.async_entries("qbittorrent_plus")
    for entry in entries:
        runtime = getattr(entry, "runtime_data", None)
        if runtime is not None and getattr(runtime, "data", None):
            return runtime
    return None


async def _attach_traefik(hass: HomeAssistant, db_path, options: dict, peers: list, extra_networks, wan) -> None:
    host = str(options.get(CONF_TRAEFIK_HOST) or "").strip()
    username = str(options.get(CONF_TRAEFIK_USERNAME) or "").strip()
    password = str(options.get(CONF_TRAEFIK_PASSWORD) or "")
    log_path = str(options.get(CONF_TRAEFIK_LOG) or DEFAULT_TRAEFIK_LOG).strip()
    if not host or not username or not password:
        return
    known = Path(db_path).parent / "traefik_known_hosts"

    def _read() -> str:
        return read_access_log(
            host,
            username,
            password,
            log_path,
            known_hosts=known,
        )

    try:
        payload = await hass.async_add_executor_job(_read)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Traefik access log was not read: %s", err)
        return
    store: dict = {}
    for line in payload.splitlines():
        remember(store, line, extra_networks=extra_networks, wan=wan)
    apply_hostnames(peers, store)
