from __future__ import annotations

import pytest

from browser_hitl.egress_proxy import ProxyDenied, hostname_allowed, parse_authority, resolve_public


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "renato.localhost",
        "host.docker.internal",
        "service.local",
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "::1",
        "fc00::1",
    ],
)
def test_private_and_host_local_destinations_are_blocked(host: str) -> None:
    assert hostname_allowed(host) is False


def test_public_hostnames_and_ips_are_allowed() -> None:
    assert hostname_allowed("example.com") is True
    assert hostname_allowed("1.1.1.1") is True
    assert hostname_allowed("2606:4700:4700::1111") is True


@pytest.mark.asyncio
async def test_proxy_rejects_non_web_ports() -> None:
    with pytest.raises(ProxyDenied):
        await resolve_public("example.com", 22)


def test_authority_parser_handles_ipv4_and_ipv6() -> None:
    assert parse_authority("example.com:443", 443) == ("example.com", 443)
    assert parse_authority("[2606:4700:4700::1111]:443", 443) == (
        "2606:4700:4700::1111",
        443,
    )
