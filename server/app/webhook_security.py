"""Outbound webhook URL security validation helpers."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
}


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def validate_webhook_target_url(
    target_url: str,
    *,
    allow_private_targets: bool,
    resolve_dns: bool,
) -> str:
    """Validate outbound webhook target URL to reduce SSRF risk."""
    parsed = urlparse(target_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("target_url must be a valid http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("target_url must not contain embedded credentials")

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("target_url host is required")
    if allow_private_targets:
        return target_url

    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith(".local"):
        raise ValueError("target_url host is not allowed")

    try:
        host_ip = ipaddress.ip_address(hostname)
    except ValueError:
        host_ip = None

    if host_ip is not None and _is_disallowed_ip(host_ip):
        raise ValueError("target_url host IP is not allowed")

    if resolve_dns and host_ip is None:
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            resolved = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError("target_url host could not be resolved") from exc

        for _, _, _, _, sockaddr in resolved:
            try:
                ip = ipaddress.ip_address(sockaddr[0])
            except ValueError:
                continue
            if _is_disallowed_ip(ip):
                raise ValueError("target_url resolves to a disallowed IP")

    return target_url
