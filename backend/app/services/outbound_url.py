"""Guard for URLs that users give the server to contact (push endpoints,
Apprise targets).

Without it any account could make the worker send requests into the private
network: the Compose services, the host, or the LAN. A host is refused when
it resolves to a private, loopback, link-local, multicast or reserved
address. Names that do not resolve pass: several Apprise schemes put a token
or topic where a host would be, and an unresolvable host cannot be reached
anyway. Delivery checks again before sending, so a DNS answer that changes
after validation is caught as well.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

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
