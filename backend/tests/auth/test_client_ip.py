"""Which address the per-IP limit counts against (R5.1, design D12).

The first version of `get_client_ip` took the LEFT-most hop of `X-Forwarded-For`,
believing that was the conservative choice. It is the opposite: a proxy that appends
(nginx's `$proxy_add_x_forwarded_for`, and any conforming implementation) leaves the
value the CLIENT sent at the left. Reading it hands an attacker a fresh 10/min budget
per request, which is exactly the bypass D12 exists to prevent.
"""

import pytest
from starlette.requests import Request

from app.auth.api.dependencies import LOOPBACK, get_client_ip
from app.core.config import settings

PEER = "198.51.100.7"
HEADER = "x-forwarded-for"


def _request(headers: list[tuple[bytes, bytes]] | None = None, client=(PEER, 4242)) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers or [],
        "client": client,
    }
    return Request(scope)


@pytest.fixture
def trusted(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "trusted_client_ip_header", "X-Forwarded-For")


def test_without_the_setting_the_header_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "trusted_client_ip_header", "")

    assert get_client_ip(_request([(HEADER.encode(), b"1.2.3.4")])) == PEER


def test_the_socket_peer_is_used_when_the_header_is_absent(trusted) -> None:
    assert get_client_ip(_request()) == PEER


def test_the_rightmost_hop_wins(trusted) -> None:
    # The client sent 1.2.3.4; the proxy appended what it actually saw.
    request = _request([(HEADER.encode(), b"1.2.3.4, 203.0.113.9")])

    assert get_client_ip(request) == "203.0.113.9"


def test_the_last_occurrence_of_the_header_wins(trusted) -> None:
    # Two header lines: the later one is the one the nearest proxy added.
    request = _request(
        [(HEADER.encode(), b"9.9.9.9"), (HEADER.encode(), b"203.0.113.9")]
    )

    assert get_client_ip(request) == "203.0.113.9"


def test_a_spoofed_chain_cannot_choose_the_bucket(trusted) -> None:
    """The whole point: a caller rotating the value must not get a new budget."""
    first = get_client_ip(_request([(HEADER.encode(), b"10.0.0.1, 203.0.113.9")]))
    second = get_client_ip(_request([(HEADER.encode(), b"10.0.0.99, 203.0.113.9")]))

    assert first == second == "203.0.113.9"


@pytest.mark.parametrize(
    "raw",
    [b"not-an-ip", b"", b"   ", b"1.2.3.4:80", b"0177.0.0.1", b"1.2.3.4, ", b"999.1.1.1"],
)
def test_a_value_that_is_not_an_ip_falls_back_to_the_peer(trusted, raw: bytes) -> None:
    assert get_client_ip(_request([(HEADER.encode(), raw)])) == PEER


def test_a_single_replaced_header_works_too(trusted) -> None:
    # Cloudflare's CF-Connecting-IP replaces rather than appends: one hop, and the
    # right-most of one is that one.
    assert get_client_ip(_request([(HEADER.encode(), b"203.0.113.9")])) == "203.0.113.9"


def test_ipv6_is_canonicalised(trusted) -> None:
    request = _request([(HEADER.encode(), b"2001:0db8:0000:0000:0000:0000:0000:0001")])

    assert get_client_ip(request) == "2001:db8::1"


def test_whitespace_around_the_hop_is_tolerated(trusted) -> None:
    assert get_client_ip(_request([(HEADER.encode(), b"1.2.3.4,\t203.0.113.9  ")])) == "203.0.113.9"


def test_no_client_at_all_falls_back_to_loopback(trusted) -> None:
    # ASGI allows `client` to be absent (in-process transports, some servers).
    assert get_client_ip(_request(client=None)) == LOOPBACK


def test_only_the_configured_header_is_consulted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "trusted_client_ip_header", "CF-Connecting-IP")
    request = _request(
        [(b"x-forwarded-for", b"1.2.3.4"), (b"cf-connecting-ip", b"203.0.113.9")]
    )

    assert get_client_ip(request) == "203.0.113.9"
