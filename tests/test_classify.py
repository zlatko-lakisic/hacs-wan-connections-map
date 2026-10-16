"""Classifier checks that do not need Home Assistant."""

import importlib.util
import ipaddress
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "wan_connections_map"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


classify = _load("classify")
names_mod = _load("names")
traefik_hosts = _load("traefik_hosts")
network = _load("network")
aggregate_connections = classify.aggregate_connections
parse_networks = classify.parse_networks
parse_rate = classify.parse_rate
build_name_map = names_mod.build_name_map


def test_parse_rate():
    assert parse_rate(1500) == 1500
    assert parse_rate("2Mbps") == 2_000_000
    assert parse_rate(0) == 0
    assert parse_rate("0") == 0


def test_groups_same_ip_and_drops_idle_and_local():
    peers = aggregate_connections(
        [
            {
                "src-address": "192.168.89.25:1111",
                "dst-address": "1.1.1.1:443",
                "protocol": "tcp",
                "orig-rate": 1000,
                "repl-rate": 0,
            },
            {
                "src-address": "192.168.89.30:2222",
                "dst-address": "1.1.1.1:443",
                "protocol": "udp",
                "orig-rate": 500,
                "repl-rate": 0,
            },
            {
                "src-address": "192.168.89.25:3333",
                "dst-address": "8.8.8.8:53",
                "protocol": "udp",
                "orig-rate": 0,
                "repl-rate": 0,
            },
            {
                "src-address": "192.168.89.25:1",
                "dst-address": "192.168.89.2:2",
                "protocol": "tcp",
                "orig-rate": 999,
                "repl-rate": 0,
            },
            {
                "src-address": "9.9.9.9:4000",
                "dst-address": "192.168.89.25:8123",
                "protocol": "tcp",
                "orig-rate": 2000,
                "repl-rate": 0,
            },
            {
                "src-address": "172.16.55.2:1",
                "dst-address": "4.4.4.4:1",
                "protocol": "tcp",
                "orig-rate": 9000,
                "repl-rate": 0,
            },
        ],
        extra_networks=parse_networks("192.168.89.0/24\n172.16.55.0/29"),
        exclude_sources={ipaddress.IPv4Address("172.16.55.2")},
        wan=ipaddress.IPv4Address("203.0.113.5"),
        vpn_ips={ipaddress.IPv4Address("77.78.225.118")},
        names={"192.168.89.25": "ha", "192.168.89.30": "phone"},
        max_peers=250,
        max_flows=30,
    )
    by_ip = {peer["ip"]: peer for peer in peers}
    assert set(by_ip) == {"1.1.1.1", "9.9.9.9"}
    assert by_ip["1.1.1.1"]["count"] == 2
    assert by_ip["1.1.1.1"]["rate_bps"] == 1500
    assert by_ip["1.1.1.1"]["kind"] == "out"
    assert by_ip["1.1.1.1"]["flows"][0]["local_name"] in {"ha", "phone"}
    assert by_ip["9.9.9.9"]["kind"] == "in"
    assert by_ip["9.9.9.9"]["flows"][0]["local_address"] == "192.168.89.25"
    assert by_ip["9.9.9.9"]["flows"][0]["local_port"] == 8123
    assert by_ip["9.9.9.9"]["flows"][0]["local_name"] == "ha"


def test_incoming_port_from_separate_field():
    peers = aggregate_connections(
        [
            {
                "src-address": "9.9.9.9",
                "src-port": "51515",
                "dst-address": "203.0.113.5",
                "dst-port": "443",
                "protocol": "tcp",
                "orig-rate": 2000,
                "repl-rate": 0,
            }
        ],
        extra_networks=[],
        exclude_sources=set(),
        wan=ipaddress.IPv4Address("203.0.113.5"),
        vpn_ips=set(),
        names={},
        max_peers=10,
        max_flows=5,
    )
    flow = peers[0]["flows"][0]
    assert peers[0]["kind"] == "in"
    assert flow["local_port"] == 443
    assert flow["remote_port"] == 51515


def test_torrent_uses_mostar_host_and_keeps_direction():
    torrent = ipaddress.IPv4Address("172.16.55.2")
    peers = aggregate_connections(
        [
            {
                "src-address": "198.51.100.8",
                "src-port": "40000",
                "dst-address": "172.16.55.2",
                "dst-port": "6881",
                "protocol": "udp",
                "orig-rate": 1000,
                "repl-rate": 0,
            },
            {
                "src-address": "172.16.55.2",
                "src-port": "6881",
                "dst-address": "198.51.100.9",
                "dst-port": "51413",
                "protocol": "tcp",
                "orig-rate": 2000,
                "repl-rate": 0,
            },
        ],
        extra_networks=[],
        exclude_sources={torrent},
        wan=ipaddress.IPv4Address("203.0.113.5"),
        vpn_ips={ipaddress.IPv4Address("77.78.225.118")},
        torrent_ips={torrent},
        names={},
        max_peers=10,
        max_flows=5,
    )
    by_ip = {peer["ip"]: peer for peer in peers}
    assert set(by_ip) == {"198.51.100.8", "198.51.100.9"}
    assert by_ip["198.51.100.8"]["kind"] == "torrent"
    assert by_ip["198.51.100.8"]["flows"][0]["local_port"] == 6881
    assert by_ip["198.51.100.8"]["flows"][0]["inbound"] is True
    assert by_ip["198.51.100.8"]["leech_bps"] == 1000
    assert by_ip["198.51.100.8"]["seed_bps"] == 0
    assert by_ip["198.51.100.9"]["kind"] == "torrent"
    assert by_ip["198.51.100.9"]["flows"][0]["inbound"] is False
    assert by_ip["198.51.100.9"]["seed_bps"] == 2000
    assert by_ip["198.51.100.9"]["leech_bps"] == 0


def test_ppp_session_name_matches_public_caller():
    names = classify.ppp_session_names(
        [
            {"caller-id": "198.51.100.5", "name": "l2tp-mostar-kuca", "service": "l2tp"},
            {"caller-id": "10.0.0.5", "name": "lan-user"},
            {"caller-id": "203.0.113.9", "name": ""},
        ]
    )
    assert names == {"198.51.100.5": "l2tp-mostar-kuca"}


def test_live_snapshot_shape_keeps_torrent_and_session_name():
    snapshot = _load("snapshot")
    router = _load("router")
    payload = json.dumps(
        {
            "collected_utc": "2026-10-09T22:11:00Z",
            "connection": [
                {
                    "src-address": "198.51.100.8",
                    "dst-address": "172.16.55.2",
                    "src-port": "40000",
                    "dst-port": "6881",
                    "protocol": "udp",
                    "orig-rate": "1000",
                    "repl-rate": "0",
                }
            ],
            "address": [{"address": "203.0.113.10/22", "interface": "ether1"}],
            "dhcp_lease": [
                {
                    "address": "192.168.89.25",
                    "host-name": "ha.lan",
                    "comment": "Home Assistant",
                    "disabled": "false",
                }
            ],
            "dns_static": [],
            "ppp_active": [
                {"caller-id": "198.51.100.50", "name": "l2tp-mostar-kuca", "address": "172.16.55.1"}
            ],
        }
    )
    parsed = snapshot.parse_snapshot(payload)
    collected = datetime(2026, 10, 9, 22, 11, tzinfo=timezone.utc)
    assert snapshot.is_stale(parsed["collected_utc"], now=collected + timedelta(seconds=30)) is False
    assert snapshot.is_stale(parsed["collected_utc"], now=collected + timedelta(seconds=90)) is True
    assert str(router.wan_address(parsed["addresses"])) == "203.0.113.10"
    assert build_name_map(parsed["dhcp"], parsed["dns"])["192.168.89.25"] == "Home Assistant"
    peers = aggregate_connections(
        parsed["connections"],
        extra_networks=[],
        exclude_sources={ipaddress.IPv4Address("172.16.55.2")},
        wan=ipaddress.IPv4Address("203.0.113.10"),
        vpn_ips={ipaddress.IPv4Address("198.51.100.50")},
        torrent_ips={ipaddress.IPv4Address("172.16.55.2")},
        names={},
        max_peers=10,
        max_flows=5,
    )
    assert peers[0]["kind"] == "torrent"
    assert peers[0]["flows"][0]["local_port"] == 6881
    assert classify.ppp_session_names(parsed["ppp"]) == {"198.51.100.50": "l2tp-mostar-kuca"}


def test_vpn_wins():
    peers = aggregate_connections(
        [
            {
                "src-address": "77.78.225.118:500",
                "dst-address": "203.0.113.5:500",
                "protocol": "udp",
                "orig-rate": 100,
                "repl-rate": 0,
            }
        ],
        extra_networks=[],
        exclude_sources=set(),
        wan=ipaddress.IPv4Address("203.0.113.5"),
        vpn_ips={ipaddress.IPv4Address("77.78.225.118")},
        names={},
        max_peers=10,
        max_flows=5,
    )
    assert peers[0]["kind"] == "vpn"


def test_names_prefer_dhcp_comment():
    names = build_name_map(
        [{"address": "192.168.89.25", "host-name": "ha-box", "comment": "Home Assistant"}],
        [{"address": "192.168.89.25", "name": "ignored.lan"}],
    )
    assert names["192.168.89.25"] == "Home Assistant"


def _message(host, start, client="203.0.113.8", path="", method="GET", size=0):
    fields = {
        "ClientHost": client,
        "ClientAddr": f"{client}:52352",
        "RequestHost": host,
        "StartUTC": start,
    }
    if path:
        fields["RequestPath"] = path
        fields["RequestMethod"] = method
        fields["DownstreamContentSize"] = size
    return json.dumps({"name": "traefik_access_mqtt", "timestamp": 1760039183, "fields": fields})


def test_traefik_hostname_uses_latest_client_host():
    now = datetime.now(timezone.utc)
    earlier = (now - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    later = now.strftime("%Y-%m-%dT%H:%M:%S.%f000Z")
    store = {}
    assert traefik_hosts.remember(store, _message("old.example", earlier), now=now)
    assert traefik_hosts.remember(store, _message("Nextcloud.MostarDesigns.com", later), now=now)
    assert not traefik_hosts.remember(store, _message("older.example", earlier), now=now)
    peers = [{"ip": "203.0.113.8", "kind": "in", "flows": [{"remote_port": 111}, {"remote_port": 222}]}]
    traefik_hosts.apply_hostnames(peers, store, now=now)
    assert peers[0]["hostnames"] == ["nextcloud.mostardesigns.com"]
    assert peers[0]["flows"][0]["hostname"] == "nextcloud.mostardesigns.com"
    assert peers[0]["flows"][1]["hostname"] == "nextcloud.mostardesigns.com"


def test_traefik_ignores_lan_and_stale_and_gone_peers():
    now = datetime.now(timezone.utc)
    fresh = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale = (now - timedelta(minutes=11)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    store = {}
    assert not traefik_hosts.remember(store, _message("lan.example", fresh, "192.168.89.10"), now=now)
    assert not traefik_hosts.remember(store, _message("old.example", stale), now=now)
    assert traefik_hosts.remember(store, _message("live.example", fresh), now=now)
    assert "203.0.113.8" in store
    peers = [{"ip": "198.51.100.9", "kind": "in", "flows": [{}]}]
    traefik_hosts.apply_hostnames(peers, store, now=now)
    assert peers[0]["hostnames"] == []
    traefik_hosts.prune(store, set(), set(), now=now)
    assert "203.0.113.8" in store


def test_traefik_drops_hostname_when_peer_disappears():
    now = datetime.now(timezone.utc)
    fresh = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    store = {}
    traefik_hosts.remember(store, _message("live.example", fresh), now=now)
    traefik_hosts.prune(store, set(), {"203.0.113.8"}, now=now)
    assert store == {}


def test_traefik_lists_resources_only_while_incoming_rate_is_high():
    now = datetime.now(timezone.utc)
    earlier = (now - timedelta(seconds=20)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    later = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    store = {}
    traefik_hosts.remember(
        store,
        _message("nextcloud.mostardesigns.com", earlier, path="/apps/files", size=400),
        now=now,
    )
    traefik_hosts.remember(
        store,
        _message("nextcloud.mostardesigns.com", later, path="/remote.php/dav/files/a.bin", method="GET", size=80_000_000),
        now=now,
    )
    traefik_hosts.remember(
        store,
        _message("nextcloud.mostardesigns.com", later, path="/remote.php/dav/files/a.bin", method="GET", size=80_000_000),
        now=now,
    )
    quiet = [{"ip": "203.0.113.8", "kind": "in", "rate_bps": 100_000, "flows": [{}]}]
    busy = [{"ip": "203.0.113.8", "kind": "in", "rate_bps": 600_000, "flows": [{}]}]
    outgoing = [{"ip": "203.0.113.8", "kind": "out", "rate_bps": 9_000_000, "flows": [{}]}]
    traefik_hosts.apply_hostnames(quiet, store, now=now)
    traefik_hosts.apply_hostnames(busy, store, now=now)
    traefik_hosts.apply_hostnames(outgoing, store, now=now)
    assert "resources" not in quiet[0]
    assert "resources" not in outgoing[0]
    assert [item["path"] for item in busy[0]["resources"]] == [
        "/remote.php/dav/files/a.bin",
        "/apps/files",
    ]
    assert busy[0]["resources"][0]["bytes"] == 80_000_000
    missing = [{"ip": "198.51.100.20", "kind": "in", "rate_bps": 600_000, "flows": [{}]}]
    traefik_hosts.apply_hostnames(missing, store, now=now)
    assert missing[0]["resources"] == []


def test_network_labels_services_and_residences():
    assert network.classify("AMAZON-02", incoming=False) == "Amazon Web Services"
    assert network.classify("AMAZON-02", incoming=True) == "Server farm · Amazon Web Services"
    assert network.classify("NETFLIX STREAMING SERVICES", incoming=False) == "Netflix"
    assert network.classify("COMCAST CABLE COMMUNICATIONS", incoming=False) == "Residential"
    assert network.classify("GOOGLE FIBER", incoming=False) == "Residential"
    assert network.classify("MICROSOFT AZURE", incoming=False) == "Azure"
    assert network.classify("MICROSOFT CORPORATION", incoming=False) == "Microsoft"
    assert network.classify("GOOGLE", incoming=False) == "Google"
    assert network.classify("GOOGLE", incoming=True) == "Server farm · Google"
    assert network.classify("HETZNER ONLINE", incoming=True) == "Server farm · Hetzner"
    assert network.classify("", incoming=True) == ""


def test_torrent_peer_names():
    torrents = _load("torrents")
    ranked = torrents.active_torrents(
        {
            "aaa": {"name": "Idle", "dl_speed": 0, "up_speed": 0, "num_leechs": 0, "num_seeds": 0},
            "bbb": {"name": "Show", "dl_speed": 5000, "up_speed": 0, "num_leechs": 3, "num_seeds": 1},
            "ccc": {"name": "Movie", "dl_speed": 0, "up_speed": 9000, "num_leechs": 0, "num_seeds": 2},
        }
    )
    assert ranked[0] == ("ccc", "Movie")
    names = torrents.index_torrent_peers(
        [
            ("Show", {"peers": {"a": {"ip": "198.51.100.8"}, "b": {"ip": "198.51.100.9:51413"}}}),
            ("Movie", {"peers": {"c": {"ip": "198.51.100.8"}}}),
        ]
    )
    assert names["198.51.100.8"] == ["Show", "Movie"]
    assert names["198.51.100.9"] == ["Show"]


def test_traefik_marks_known_bots():
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    store = {}
    payload = json.dumps(
        {
            "fields": {
                "ClientHost": "203.0.113.8",
                "RequestHost": "nextcloud.mostardesigns.com",
                "StartUTC": stamp,
                "request_User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            }
        }
    )
    browser = json.dumps(
        {
            "fields": {
                "ClientHost": "203.0.113.9",
                "RequestHost": "nextcloud.mostardesigns.com",
                "StartUTC": stamp,
                "request_User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
            }
        }
    )
    traefik_hosts.remember(store, payload, now=now)
    traefik_hosts.remember(store, browser, now=now)
    peers = [
        {"ip": "203.0.113.8", "kind": "in", "rate_bps": 1, "flows": [{}]},
        {"ip": "203.0.113.9", "kind": "in", "rate_bps": 1, "flows": [{}]},
    ]
    traefik_hosts.apply_hostnames(peers, store, now=now)
    assert peers[0]["bot"] == "Googlebot"
    assert peers[1]["bot"] == ""
    assert traefik_hosts._bot("HomeAssistant/2026.10.0 aiohttp/3.14.4 Python/3.14") == "Home Assistant"
    assert traefik_hosts._bot("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0") == ""


def test_traefik_start_labels_an_open_transfer():
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    earlier = (now - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    store = {}
    start = {
        "fields": {
            "AccessEvent": "start",
            "ClientHost": "203.0.113.10",
            "ClientAddr": "203.0.113.10:58118",
            "RequestHost": "tourguidemostar.com",
            "RequestPath": "/video.mp4",
            "RequestMethod": "GET",
            "StartUTC": stamp,
            "request_User-Agent": "Mozilla/5.0 Chrome/120.0.0.0",
        }
    }
    bot_start = {
        "fields": {
            "AccessEvent": "start",
            "ClientHost": "203.0.113.11",
            "RequestHost": "tourguidemostar.com",
            "RequestPath": "/",
            "RequestMethod": "GET",
            "StartUTC": stamp,
            "request_User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)",
        }
    }
    assert traefik_hosts.remember(store, json.dumps(start), now=now)
    assert not traefik_hosts.remember(store, json.dumps(start), now=now)
    assert traefik_hosts.remember(store, json.dumps(bot_start), now=now)
    peers = [
        {"ip": "203.0.113.10", "kind": "in", "rate_bps": 2_000_000, "flows": [{}]},
        {"ip": "203.0.113.11", "kind": "in", "rate_bps": 1, "flows": [{}]},
    ]
    traefik_hosts.apply_hostnames(peers, store, now=now)
    assert peers[0]["hostnames"] == ["tourguidemostar.com"]
    assert peers[0]["bot"] == ""
    assert peers[0]["resources"] == [
        {
            "method": "GET",
            "path": "/video.mp4",
            "host": "tourguidemostar.com",
            "bytes": 0,
            "open": True,
        }
    ]
    assert peers[1]["bot"] == "Googlebot"
    assert "resources" not in peers[1]

    older = {
        "fields": {
            "AccessEvent": "start",
            "ClientHost": "203.0.113.10",
            "RequestHost": "old.example",
            "RequestPath": "/old",
            "RequestMethod": "GET",
            "StartUTC": earlier,
        }
    }
    finish_old = {
        "fields": {
            "ClientHost": "203.0.113.10",
            "RequestHost": "old.example",
            "RequestPath": "/old",
            "RequestMethod": "GET",
            "StartUTC": earlier,
            "DownstreamContentSize": 9_000_000,
            "DownstreamStatus": 200,
        }
    }
    finish = {
        "fields": {
            "ClientHost": "203.0.113.10",
            "RequestHost": "tourguidemostar.com",
            "RequestPath": "/video.mp4",
            "RequestMethod": "GET",
            "StartUTC": stamp,
            "DownstreamContentSize": 50_000_000,
            "DownstreamStatus": 200,
            "request_User-Agent": "Mozilla/5.0 Chrome/120.0.0.0",
        }
    }
    assert traefik_hosts.remember(store, json.dumps(older), now=now)
    assert store["203.0.113.10"]["host"] == "tourguidemostar.com"
    traefik_hosts.remember(store, json.dumps(finish_old), now=now)
    assert store["203.0.113.10"]["host"] == "tourguidemostar.com"
    assert traefik_hosts.remember(store, json.dumps(finish), now=now)
    traefik_hosts.apply_hostnames(peers[:1], store, now=now)
    assert peers[0]["hostnames"] == ["tourguidemostar.com"]
    assert peers[0]["bot"] == ""
    video = next(item for item in peers[0]["resources"] if item["path"] == "/video.mp4")
    assert video["open"] is False
    assert video["bytes"] == 50_000_000
    old = next(item for item in peers[0]["resources"] if item["path"] == "/old")
    assert old["bytes"] == 9_000_000
    assert old["open"] is False


if __name__ == "__main__":
    test_parse_rate()
    test_groups_same_ip_and_drops_idle_and_local()
    test_vpn_wins()
    test_names_prefer_dhcp_comment()
    test_traefik_hostname_uses_latest_client_host()
    test_traefik_ignores_lan_and_stale_and_gone_peers()
    test_traefik_drops_hostname_when_peer_disappears()
    test_traefik_lists_resources_only_while_incoming_rate_is_high()
    test_network_labels_services_and_residences()
    test_torrent_peer_names()
    test_traefik_marks_known_bots()
    test_traefik_start_labels_an_open_transfer()
    print("ok")
