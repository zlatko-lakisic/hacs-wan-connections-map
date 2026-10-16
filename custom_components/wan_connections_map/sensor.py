"""WAN peer sensor."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the peer sensor."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([WanGeoSensor(coordinator, entry)])


class WanGeoSensor(CoordinatorEntity, SensorEntity):
    """Count of plotted WAN peers, with the map payload in attributes."""

    _attr_has_entity_name = False
    _attr_name = "WAN geo"
    _attr_suggested_object_id = "mikrotik_home_wan_geo"
    _attr_icon = "mdi:earth"
    _unrecorded_attributes = frozenset({"points", "home", "mostar"})

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}-wan-geo"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "WAN Connections Map",
            "manufacturer": "Mostar Designs",
        }

    @property
    def native_value(self) -> int:
        data = self.coordinator.data or {}
        if data.get("connections") is not None:
            return int(data.get("connections") or 0)
        return int(data.get("count") or 0)

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "points": data.get("points") or [],
            "home": data.get("home") or {},
            "mostar": data.get("mostar") or {},
            "stale": bool(data.get("stale")),
            "collected_utc": data.get("collected_utc") or "",
        }
