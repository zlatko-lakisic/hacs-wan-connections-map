"""DB-IP City Lite download and lookup."""

from __future__ import annotations

import gzip
import logging
from datetime import datetime
from pathlib import Path

import maxminddb

_LOGGER = logging.getLogger(__name__)

_URL = "https://download.db-ip.com/free/dbip-city-lite-{ym}.mmdb.gz"
_ASN_URL = "https://download.db-ip.com/free/dbip-asn-lite-{ym}.mmdb.gz"


def database_path(config_dir: str) -> Path:
    """Path of the local city database."""
    return _folder(config_dir) / "dbip-city-lite.mmdb"


def asn_database_path(config_dir: str) -> Path:
    """Path of the local ASN database."""
    return _folder(config_dir) / "dbip-asn-lite.mmdb"


def _folder(config_dir: str) -> Path:
    folder = Path(config_dir) / "wan_connections_map"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


async def async_download(hass, dest: Path) -> bool:
    """Download the current month's city database. Keep dest on failure."""
    return await _async_download(hass, dest, _URL)


async def async_download_asn(hass, dest: Path) -> bool:
    """Download the current month's ASN database. Keep dest on failure."""
    return await _async_download(hass, dest, _ASN_URL)


async def _async_download(hass, dest: Path, template: str) -> bool:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    session = async_get_clientsession(hass)
    now = datetime.now()
    months = [now]
    if now.month == 1:
        months.append(now.replace(year=now.year - 1, month=12))
    else:
        months.append(now.replace(month=now.month - 1))

    for moment in months:
        url = template.format(ym=moment.strftime("%Y-%m"))
        try:
            async with session.get(
                url,
                timeout=120,
                headers={"User-Agent": "HomeAssistant-wan_connections_map"},
            ) as response:
                if response.status != 200:
                    _LOGGER.debug("GeoIP download %s returned %s", url, response.status)
                    continue
                payload = await response.read()
        except Exception as err:  # noqa: BLE001 - keep the previous file
            _LOGGER.warning("GeoIP download failed: %s", err)
            continue
        try:
            raw = gzip.decompress(payload)
        except OSError:
            raw = payload
        if not raw.startswith(b"\xab\xcd\xefMaxMind.com"):
            # MMDB files start with a metadata marker near the end, not the head.
            # Accept any non-trivial payload that maxminddb can open.
            pass
        tmp = dest.with_suffix(".mmdb.tmp")
        tmp.write_bytes(raw)
        try:
            with maxminddb.open_database(str(tmp)) as reader:
                reader.get("8.8.8.8")
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Downloaded GeoIP file is unreadable: %s", err)
            tmp.unlink(missing_ok=True)
            continue
        tmp.replace(dest)
        _LOGGER.info("Updated GeoIP database from %s", url)
        return True
    return False


def lookup(dest: Path, ip: str) -> tuple[float, float, str, str] | None:
    """Return lat, lon, city, country for an IPv4 address."""
    if not dest.is_file():
        return None
    try:
        with maxminddb.open_database(str(dest)) as reader:
            record = reader.get(ip)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(record, dict):
        return None
    location = record.get("location") or {}
    lat = location.get("latitude")
    lon = location.get("longitude")
    if lat is None or lon is None:
        return None
    city = ((record.get("city") or {}).get("names") or {}).get("en") or ""
    country = ((record.get("country") or {}).get("names") or {}).get("en") or ""
    return float(lat), float(lon), city, country


def lookup_organizations(dest: Path, ips: list[str]) -> dict[str, str]:
    """Return ASN organization names for the given addresses."""
    if not dest.is_file():
        return {}
    found: dict[str, str] = {}
    try:
        reader = maxminddb.open_database(str(dest))
    except Exception:  # noqa: BLE001
        return {}
    try:
        for ip in ips:
            try:
                record = reader.get(ip)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(record, dict):
                continue
            org = str(record.get("autonomous_system_organization") or "").strip()
            if org:
                found[ip] = org
    finally:
        reader.close()
    return found
