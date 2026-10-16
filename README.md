# WAN Connections Map

Home Assistant integration that reads a MikroTik connection table and draws live WAN peers on a deck.gl map.

Outgoing peers use the theme info color, incoming peers use success, and VPN peers use error. Circles scale with the live rate, up to 28 px at 20 Mbit/s. Several flows to the same address share one arc.

The city database is DB-IP City Lite. It downloads on first start if missing, then every day at 04:00 local time.

## Card

```yaml
type: custom:wan-connections-map
entity: sensor.mikrotik_home_wan_geo
```

IP Geolocation by [DB-IP](https://db-ip.com).
