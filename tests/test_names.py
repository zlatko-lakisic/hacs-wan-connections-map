"""Hostname supplement checks that do not need Home Assistant."""

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "wan_connections_map"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


names = _load("names")


def test_unique_dhcp_name_is_kept():
    leases = [{"address": "192.168.89.25", "host-name": "ha-box", "comment": "Home Assistant"}]
    dhcp = names.build_name_map(leases, [])
    known = names.known_ip_names(
        leases,
        [{"title": "Something Else", "host": "192.168.89.25", "mac": "", "model": ""}],
        [],
    )
    assert names.supplement_names(dhcp, leases, known)["192.168.89.25"] == "Home Assistant"


def test_shared_samsung_hostname_uses_home_assistant_names():
    leases = [
        {"address": "192.168.89.24", "host-name": "Samsung", "mac-address": "F8:4E:58:6A:20:9D"},
        {"address": "192.168.89.18", "host-name": "Samsung", "mac-address": "10:2B:41:BA:DA:BF"},
    ]
    dhcp = names.build_name_map(leases, [])
    known = names.known_ip_names(
        leases,
        [
            {
                "title": "Living room Tv (UN86TU9010FXZA)",
                "host": "192.168.89.24",
                "mac": "f8:4e:58:6a:20:9d",
                "model": "UN86TU9010FXZA",
            },
            {
                "title": "Master Bedroom TV (QN65Q60AAFXZA)",
                "host": "192.168.89.18",
                "mac": "10:2b:41:ba:da:bf",
                "model": "QN65Q60AAFXZA",
            },
        ],
        [
            {"name": "Living room Tv", "name_by_user": "Living Room TV", "model": "UN86TU9010FXZA", "macs": []},
            {"name": "Master Bedroom TV", "name_by_user": "Master Bedroom TV", "model": "QN65Q60AAFXZA", "macs": []},
        ],
    )
    supplemented = names.supplement_names(dhcp, leases, known)
    assert supplemented["192.168.89.24"] == "Living Room TV"
    assert supplemented["192.168.89.18"] == "Master Bedroom TV"


def test_missing_hostname_uses_device_mac_name():
    leases = [{"address": "192.168.89.40", "mac-address": "CC:A7:C1:69:FA:07"}]
    dhcp = names.build_name_map(leases, [])
    known = names.known_ip_names(
        leases,
        [],
        [
            {"name": "cc:a7:c1:69:fa:07", "name_by_user": "", "model": "Topaz-2.33", "macs": ["cc:a7:c1:69:fa:07"]},
            {"name": "Nest Protect (Kitchen)", "name_by_user": "", "model": "Topaz-2.33", "macs": ["cc:a7:c1:69:fa:07"]},
        ],
    )
    assert names.supplement_names(dhcp, leases, known)["192.168.89.40"] == "Nest Protect (Kitchen)"


def test_same_model_does_not_cross_assign():
    leases = [
        {"address": "192.168.89.11", "host-name": "axis"},
        {"address": "192.168.89.31", "host-name": "axis"},
    ]
    known = names.known_ip_names(
        leases,
        [
            {"title": "Driveway camera", "host": "192.168.89.11", "mac": "", "model": "P3375-VE"},
            {"title": "East camera", "host": "192.168.89.31", "mac": "", "model": "P3375-VE"},
        ],
        [
            {"name": "Driveway", "name_by_user": "Driveway", "model": "P3375-VE", "macs": []},
            {"name": "East", "name_by_user": "East", "model": "P3375-VE", "macs": []},
        ],
    )
    assert known["192.168.89.11"] == "Driveway camera"
    assert known["192.168.89.31"] == "East camera"


def test_shared_label_without_a_better_name_stays():
    leases = [
        {"address": "172.16.90.100", "host-name": "Google-Nest-Mini", "mac-address": "BC:DF:58:0A:1B:A0"},
        {"address": "172.16.90.118", "host-name": "Google-Nest-Mini", "mac-address": "CC:F4:11:B6:B5:7E"},
    ]
    dhcp = names.build_name_map(leases, [])
    known = names.known_ip_names(
        leases,
        [],
        [
            {"name": "Google-Nest-Mini", "name_by_user": "", "model": "", "macs": ["bc:df:58:0a:1b:a0"]},
            {"name": "Google-Nest-Mini", "name_by_user": "", "model": "", "macs": ["cc:f4:11:b6:b5:7e"]},
        ],
    )
    supplemented = names.supplement_names(dhcp, leases, known)
    assert supplemented["172.16.90.100"] == "Google-Nest-Mini"
    assert supplemented["172.16.90.118"] == "Google-Nest-Mini"


def test_mac_on_the_lease_wins_over_a_stale_entry_host():
    leases = [{"address": "192.168.89.50", "host-name": "Samsung", "mac-address": "F8:4E:58:6A:20:9D"}]
    known = names.known_ip_names(
        leases,
        [{"title": "Living room Tv", "host": "192.168.89.24", "mac": "f8:4e:58:6a:20:9d", "model": ""}],
        [],
    )
    assert known["192.168.89.50"] == "Living room Tv"
    assert "192.168.89.24" not in known
