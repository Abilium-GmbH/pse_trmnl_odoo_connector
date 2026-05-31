"""TRMNL network and URL reachability utilities.

Pure-Python helpers with no Odoo or PIL dependencies.  Used by the device
model layer (trmnl_device_display, trmnl_profile) to determine whether a
base URL is reachable by a physical TRMNL device on the local network.

Design notes
------------
Normal LAN ranges (10.x, 192.168.x, 172.16–31.x) are intentionally NOT
blocked.  A configured LAN IP is a valid device target regardless of whether
it falls inside RFC-1918 space.  Docker bridge IPs (commonly 172.17.0.x)
overlap with legitimate corporate LAN ranges and cannot be excluded reliably
by pattern alone; operators should set ``trmnl.public_base_url`` explicitly
when ``web.base.url`` resolves to a container-internal address.

The libvirt/KVM virbr0 bridge (192.168.122.x) is blocked because it is a
VM-internal address that physical devices on the LAN cannot reach.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

# Hosts/IPs that are never reachable by a physical device on the LAN.
INTERNAL_HOST_RE = re.compile(
    r"^("
    r"localhost"
    r"|0\.0\.0\.0"
    r"|127(?:\.\d+){3}"
    r"|::1"
    r"|192\.168\.122\.\d+"
    r")$",
    re.IGNORECASE,
)

_IPV4_RE = re.compile(
    r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$"
)


def _ipv4_octets(host_or_ip: str) -> tuple[int, ...] | None:
    """Return ``(a, b, c, d)`` for a dotted IPv4 string, else ``None``."""
    if not host_or_ip:
        return None
    match = _IPV4_RE.match(str(host_or_ip).strip())
    if not match:
        return None
    octets = tuple(int(g) for g in match.groups())
    if any(o < 0 or o > 255 for o in octets):
        return None
    return octets


def _private_subnet_key(octets: tuple[int, ...]) -> tuple:
    """Grouping key for RFC-1918-style LAN reachability heuristics."""
    if octets[0] == 10:
        return ("10", octets[1], octets[2])
    if octets[0] == 192 and octets[1] == 168:
        return ("192.168", octets[2])
    if octets[0] == 172 and 16 <= octets[1] <= 31:
        return ("172", octets[1])
    return octets[:3]


def client_can_reach_host(client_ip: str, host: str) -> bool:
    """Return ``True`` when a TRMNL on ``client_ip`` can plausibly reach ``host``.

    Uses a /24-level subnet heuristic for IPv4 LAN addresses.  Non-IPv4
    hostnames are treated as reachable (DNS / mDNS setups).
    """
    client = _ipv4_octets(client_ip)
    if not client:
        return True
    target = _ipv4_octets(host)
    if not target:
        return True
    return _private_subnet_key(client) == _private_subnet_key(target)


def is_device_reachable_base_url(url: str) -> bool:
    """Return ``True`` if ``url``'s host is reachable by a physical LAN device.

    Rejects loopback (localhost / 127.x / ::1 / 0.0.0.0) and the libvirt
    KVM virbr0 bridge (192.168.122.x).  Empty or unparseable URLs return
    ``False``.
    """
    try:
        host = urlparse(url).hostname or ""
        return bool(host) and not INTERNAL_HOST_RE.match(host)
    except Exception:
        return False
