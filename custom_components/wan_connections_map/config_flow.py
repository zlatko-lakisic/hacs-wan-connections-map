"""Config flow for WAN Connections Map."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback

from .const import (
    CONF_EXCLUDE_SOURCES,
    CONF_LOCAL_PREFIXES,
    CONF_MIKROTIK_ENTRY,
    CONF_TRAEFIK_HOST,
    CONF_TRAEFIK_LOG,
    CONF_TRAEFIK_PASSWORD,
    CONF_TRAEFIK_USERNAME,
    CONF_VPN_ENTITIES,
    DEFAULT_EXCLUDE_SOURCES,
    DEFAULT_LOCAL_PREFIXES,
    DEFAULT_TRAEFIK_LOG,
    DEFAULT_VPN_ENTITIES,
    DOMAIN,
)


def _mikrotik_entries(hass) -> dict[str, str]:
    entries = {}
    for entry in hass.config_entries.async_entries("mikrotik_router"):
        entries[entry.entry_id] = entry.title
    return entries


class WanConnectionsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        routers = _mikrotik_entries(self.hass)
        if not routers:
            return self.async_abort(reason="no_mikrotik")
        if user_input is not None:
            title = routers.get(user_input[CONF_MIKROTIK_ENTRY], "WAN Connections")
            return self.async_create_entry(
                title=f"WAN map ({title})",
                data={CONF_MIKROTIK_ENTRY: user_input[CONF_MIKROTIK_ENTRY]},
                options={
                    CONF_LOCAL_PREFIXES: user_input[CONF_LOCAL_PREFIXES],
                    CONF_EXCLUDE_SOURCES: user_input[CONF_EXCLUDE_SOURCES],
                    CONF_VPN_ENTITIES: user_input[CONF_VPN_ENTITIES],
                    CONF_TRAEFIK_HOST: user_input.get(CONF_TRAEFIK_HOST, ""),
                    CONF_TRAEFIK_USERNAME: user_input.get(CONF_TRAEFIK_USERNAME, ""),
                    CONF_TRAEFIK_PASSWORD: user_input.get(CONF_TRAEFIK_PASSWORD, ""),
                    CONF_TRAEFIK_LOG: user_input.get(CONF_TRAEFIK_LOG, DEFAULT_TRAEFIK_LOG),
                },
            )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MIKROTIK_ENTRY): vol.In(routers),
                    vol.Required(
                        CONF_LOCAL_PREFIXES, default=DEFAULT_LOCAL_PREFIXES
                    ): str,
                    vol.Required(
                        CONF_EXCLUDE_SOURCES, default=DEFAULT_EXCLUDE_SOURCES
                    ): str,
                    vol.Required(
                        CONF_VPN_ENTITIES, default=DEFAULT_VPN_ENTITIES
                    ): str,
                    vol.Optional(CONF_TRAEFIK_HOST, default=""): str,
                    vol.Optional(CONF_TRAEFIK_USERNAME, default=""): str,
                    vol.Optional(CONF_TRAEFIK_PASSWORD, default=""): str,
                    vol.Optional(CONF_TRAEFIK_LOG, default=DEFAULT_TRAEFIK_LOG): str,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        return WanConnectionsOptionsFlow()


class WanConnectionsOptionsFlow(OptionsFlow):
    """Edit prefixes, exclusions, and VPN peer entities."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOCAL_PREFIXES,
                        default=options.get(CONF_LOCAL_PREFIXES, DEFAULT_LOCAL_PREFIXES),
                    ): str,
                    vol.Required(
                        CONF_EXCLUDE_SOURCES,
                        default=options.get(CONF_EXCLUDE_SOURCES, DEFAULT_EXCLUDE_SOURCES),
                    ): str,
                    vol.Required(
                        CONF_VPN_ENTITIES,
                        default=options.get(CONF_VPN_ENTITIES, DEFAULT_VPN_ENTITIES),
                    ): str,
                    vol.Optional(
                        CONF_TRAEFIK_HOST,
                        default=options.get(CONF_TRAEFIK_HOST, ""),
                    ): str,
                    vol.Optional(
                        CONF_TRAEFIK_USERNAME,
                        default=options.get(CONF_TRAEFIK_USERNAME, ""),
                    ): str,
                    vol.Optional(
                        CONF_TRAEFIK_PASSWORD,
                        default=options.get(CONF_TRAEFIK_PASSWORD, ""),
                    ): str,
                    vol.Optional(
                        CONF_TRAEFIK_LOG,
                        default=options.get(CONF_TRAEFIK_LOG, DEFAULT_TRAEFIK_LOG),
                    ): str,
                }
            ),
        )
