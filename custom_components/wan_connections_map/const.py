"""Constants for the WAN Connections Map integration."""

DOMAIN = "wan_connections_map"

CONF_MIKROTIK_ENTRY = "mikrotik_entry"
CONF_LOCAL_PREFIXES = "local_prefixes"
CONF_EXCLUDE_SOURCES = "exclude_sources"
CONF_VPN_ENTITIES = "vpn_entities"
CONF_TRAEFIK_HOST = "traefik_host"
CONF_TRAEFIK_USERNAME = "traefik_username"
CONF_TRAEFIK_PASSWORD = "traefik_password"
CONF_TRAEFIK_LOG = "traefik_log"

DEFAULT_SCAN_INTERVAL = 30
DEFAULT_LOCAL_PREFIXES = "\n".join(
    [
        "10.0.10.0/24",
        "192.168.89.0/24",
        "192.168.90.0/24",
        "172.16.90.0/24",
        "172.16.55.0/29",
        "172.16.91.0/27",
        "172.16.100.0/24",
        "172.16.101.0/24",
        "192.168.88.0/24",
        "192.168.100.0/24",
    ]
)
DEFAULT_EXCLUDE_SOURCES = "172.16.55.2"
DEFAULT_TORRENT_SOURCES = "172.16.55.2"
DEFAULT_VPN_ENTITIES = "sensor.mikrotik_mostar_environment_publicip"
DEFAULT_TRAEFIK_LOG = "/etc/traefik/access.log"
TRAEFIK_ACCESS_TOPIC = "traefik/access"
MIKROTIK_SNAPSHOT_TOPIC = "mikrotik/snapshot"

CARD_URL = "/wan_connections_map/wan-connections-map.js?v=37"
MAX_PEERS = 250
MAX_FLOWS = 30
