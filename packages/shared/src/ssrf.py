"""SSRF (Server-Side Request Forgery) protection for webhook destinations."""

import ipaddress
import socket
from urllib.parse import urlparse
from typing import Tuple


BLOCKED_CIDRS = [
    # IPv4 Private / Loopback / Link-Local / Carrier-Grade / Cloud Metadata
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),          # RFC1918 private
    ipaddress.ip_network("100.64.0.0/10"),       # Shared address space / CGNAT
    ipaddress.ip_network("127.0.0.0/8"),         # Loopback
    ipaddress.ip_network("169.254.0.0/16"),      # Link-local & cloud metadata (e.g. 169.254.169.254)
    ipaddress.ip_network("172.16.0.0/12"),       # RFC1918 private
    ipaddress.ip_network("192.0.0.0/24"),        # IETF protocol assignments
    ipaddress.ip_network("192.0.2.0/24"),        # Documentation TEST-NET-1
    ipaddress.ip_network("192.168.0.0/16"),      # RFC1918 private
    ipaddress.ip_network("198.18.0.0/15"),       # Benchmarking
    ipaddress.ip_network("198.51.100.0/24"),     # Documentation TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),      # Documentation TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),         # Multicast
    ipaddress.ip_network("240.0.0.0/4"),         # Reserved
    ipaddress.ip_network("255.255.255.255/32"),  # Broadcast
    # IPv6 Loopback / Private / Link-Local / Unique Local
    ipaddress.ip_network("::1/128"),             # Loopback
    ipaddress.ip_network("::/128"),              # Unspecified
    ipaddress.ip_network("fc00::/7"),            # Unique Local Address (ULA)
    ipaddress.ip_network("fe80::/10"),           # Link-local unicast
    ipaddress.ip_network("ff00::/8"),            # Multicast
]


def validate_destination_url(url: str, allow_localhost: bool = False) -> Tuple[bool, str]:
    """
    Validate that an outbound URL is safe against SSRF attacks.
    - Requires http or https scheme.
    - Resolves hostname to all IP addresses.
    - Rejects any address in private, loopback, or cloud-metadata ranges unless explicitly allowed.
    """
    try:
        parsed = urlparse(url)
    except Exception as e:
        return False, f"Malformed URL: {str(e)}"

    if parsed.scheme not in ("http", "https"):
        return False, f"Unsupported scheme '{parsed.scheme}': only http and https are permitted."

    hostname = parsed.hostname
    if not hostname:
        return False, "Destination URL has no valid hostname."

    # If localhost is explicitly allowed (e.g. during local tests)
    if allow_localhost and hostname in ("localhost", "127.0.0.1", "::1"):
        return True, "Allowed by local development setting"

    # Block explicit localhost names
    if hostname.lower() in ("localhost", "localhost.localdomain", "127.0.0.1", "::1"):
        return False, "Destination points to loopback/localhost."

    # Resolve all DNS IP addresses for this hostname
    try:
        # getaddrinfo returns tuples of (family, type, proto, canonname, sockaddr)
        addr_info = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as e:
        return False, f"DNS resolution failed: {str(e)}"

    resolved_ips = set()
    for item in addr_info:
        ip_str = item[4][0]
        resolved_ips.add(ip_str)

    if not resolved_ips:
        return False, "Could not resolve hostname to any IP addresses."

    for ip_str in resolved_ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"Invalid resolved IP address: {ip_str}"

        # Check loopback, private, link-local directly from ipaddress properties
        if ip.is_loopback:
            if not allow_localhost:
                return False, f"Destination resolves to loopback IP: {ip_str}"
        elif ip.is_private and not allow_localhost:
            return False, f"Destination resolves to private IP: {ip_str}"
        elif ip.is_link_local:
            return False, f"Destination resolves to link-local IP: {ip_str}"
        elif ip.is_multicast or ip.is_reserved:
            return False, f"Destination resolves to reserved/multicast IP: {ip_str}"

        # Check against explicitly blocked CIDRs
        for blocked_net in BLOCKED_CIDRS:
            if ip in blocked_net:
                if allow_localhost and (ip.is_loopback or str(ip) in ("127.0.0.1", "::1")):
                    continue
                return False, f"Destination IP {ip_str} belongs to blocked subnet {blocked_net}"

    return True, "Safe"
