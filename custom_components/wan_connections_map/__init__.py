"""WAN Connections Map integration."""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change

from .const import CARD_URL, DOMAIN
from .coordinator import WanConnectionsCoordinator
from .geoip import async_download, async_download_asn, asn_database_path, database_path

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one WAN map from a MikroTik router entry."""
    await _async_register_card(hass)
    dest = database_path(hass.config.path())
    asn_dest = asn_database_path(hass.config.path())
    if not dest.is_file():
        await async_download(hass, dest)
    if not asn_dest.is_file():
        await async_download_asn(hass, asn_dest)

    async def _refresh_at_4(_now: datetime) -> None:
        await async_download(hass, dest)
        await async_download_asn(hass, asn_dest)

    unsub_time = async_track_time_change(
        hass, _refresh_at_4, hour=4, minute=0, second=0
    )

    coordinator = WanConnectionsCoordinator(hass, entry)
    await coordinator.async_subscribe_access()
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "unsub_time": unsub_time,
    }
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    entry.async_on_unload(coordinator.async_unsubscribe_access)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    stored = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if stored and stored.get("unsub_time"):
        stored["unsub_time"]()
    return await hass.config_entries.async_unload_platforms(entry, ["sensor"])


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the bundled card and add it as a Lovelace module once."""
    if hass.data.get(f"{DOMAIN}_frontend"):
        return
    hass.data[f"{DOMAIN}_frontend"] = True

    from homeassistant.components.http import StaticPathConfig

    folder = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths(
        [StaticPathConfig("/wan_connections_map", str(folder), False)]
    )

    try:
        lovelace = hass.data.get("lovelace")
        resources = getattr(lovelace, "resources", None)
        if resources is None:
            _LOGGER.warning("Lovelace resources are not available; add the card resource manually")
            return
        if not resources.loaded:
            await resources.async_load()
        url = CARD_URL
        path = url.split("?", 1)[0]
        for item in resources.async_items():
            current = str(item.get("url", ""))
            if current == url:
                return
            if current.startswith(path):
                await resources.async_update_item(
                    item["id"], {"res_type": "module", "url": url}
                )
                return
        await resources.async_create_item({"res_type": "module", "url": url})
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not register the WAN map card resource: %s", err)
