"""Guard for URLs that users give the server to contact (push endpoints,
Apprise targets).

Without it any account could make the worker send requests into the private
network: the Compose services, the host, or the LAN. A host is refused when
it resolves to a private, loopback, link-local, multicast or reserved
address. Names that do not resolve pass: several Apprise schemes put a token
or topic where a host would be, and an unresolvable host cannot be reached
anyway. Delivery checks again before sending, so a DNS answer that changes
after validation is caught as well. Webhooks go one step further and connect
through ``public_http_transport``, which checks the address it actually
connects to (no second lookup an attacker's DNS could answer differently).
"""

import ipaddress
import socket
from urllib.parse import urlsplit

import httpcore
import httpx

from config.settings import settings


class BlockedDestination(ValueError):
    pass


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    return ip.is_global and not ip.is_multicast


def check_public_host(host: str | None) -> None:
    """Raise BlockedDestination if ``host`` resolves to a non-public address."""
    if not host or settings.NOTIFY_ALLOW_PRIVATE_HOSTS:
        return
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return
    for info in infos:
        if not _is_public(info[4][0]):
            raise BlockedDestination(f"{host} is not a public internet address")


def check_public_url(url: str) -> None:
    try:
        host = urlsplit(url.strip()).hostname
    except ValueError as exc:
        raise BlockedDestination("Invalid URL") from exc
    check_public_host(host)


def _public_address(host: str) -> str:
    """Resolve ``host`` once and return an address to connect to; every answer must be public."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as exc:
        raise httpcore.ConnectError(f"Could not resolve {host}") from exc
    addresses = [info[4][0] for info in infos]
    if not addresses:
        raise httpcore.ConnectError(f"Could not resolve {host}")
    for address in addresses:
        if not _is_public(address):
            raise BlockedDestination(f"{host} is not a public internet address")
    return addresses[0]


class _PublicOnlyBackend(httpcore.SyncBackend):
    """Connects only to public addresses, checked at connect time (DNS rebinding)."""

    def __init__(self, force_public=False):
        self.force_public = force_public

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if self.force_public or not settings.NOTIFY_ALLOW_PRIVATE_HOSTS:
            # TLS still verifies against the original name: httpcore passes
            # the origin host as server_hostname, not the address.
            host = _public_address(host)
        return super().connect_tcp(host, port, timeout=timeout, local_address=local_address, socket_options=socket_options)


def public_http_transport(*, force_public=False) -> httpx.HTTPTransport:
    transport = httpx.HTTPTransport()
    transport._pool._network_backend = _PublicOnlyBackend(force_public=force_public)  # pylint: disable=protected-access
    return transport
