"""Which address the per-IP limit counts against, and who is allowed to say so.

Covers R4.1-R4.4 of change `api-ingress-routing`. The resolution moved OUT of
`get_client_ip` and into uvicorn's `ProxyHeadersMiddleware` (design D3), so testing
`get_client_ip` alone would no longer test the guarantee: it would test one link of a
two-link chain and miss the link that decides whether to trust anybody.

So these tests drive the middleware, which is what runs in front of the app in the
deployed environment. They also pin upstream behaviour this topology now depends on —
notably that a **hostname** in the trusted list is compared as a literal string and
never resolved, which is why design D4 pins a static address instead of trusting the
name `frontend`.

History worth keeping: the first version of `get_client_ip` took the LEFT-most hop of
`X-Forwarded-For`, believing that was conservative. It is the opposite — a proxy that
appends leaves the value the CLIENT sent at the left. uvicorn walks the chain from the
right and stops at the first untrusted hop, which is why delegating is also a
correctness win and not only less code.
"""

import ipaddress

import pytest
from starlette.requests import Request
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.audit.domain.services import MAX_ACTOR_IP_LENGTH
from app.auth.api.dependencies import (
    LOOPBACK,
    MAX_CLIENT_IP_LENGTH,
    get_client_ip,
)

# A stand-in for "the one trusted peer". It happens to be the address the deploy compose
# assigns the frontend, but nothing here depends on that: these tests exercise the
# mechanism, and the real value is guaranteed by the YAML anchor that feeds both
# `ipv4_address` and `--forwarded-allow-ips` in docker-compose.deploy.yml (design D4).
# Restating it here as a claim about the deployment would be a fourth uncoupled copy.
PROXY = "10.89.0.10"
# Anything else that can open a socket to the backend: another container on `private`,
# or the bridge gateway that connections through the published loopback port are
# SNATed to. Explicitly NOT trusted — that is the point of the /32 in design D4.
UNTRUSTED_PEER = "10.89.0.1"
REAL_CLIENT = "203.0.113.9"


def _scope(peer: str | None, headers: list[tuple[bytes, bytes]] | None = None) -> dict:
    return {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers or [],
        "client": (peer, 4242) if peer else None,
    }


async def _receive() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _send(message: dict) -> None:  # pragma: no cover - the app never responds
    return None


async def _through_proxy_middleware(
    peer: str,
    headers: list[tuple[bytes, bytes]] | None = None,
    trusted: str = PROXY,
) -> str:
    """What `get_client_ip` sees once uvicorn's middleware has had its say."""
    seen: dict[str, str] = {}

    async def app(scope: dict, receive, send) -> None:
        seen["ip"] = get_client_ip(Request(scope, receive))

    await ProxyHeadersMiddleware(app, trusted_hosts=trusted)(
        _scope(peer, headers), _receive, _send
    )
    return seen["ip"]


# --- get_client_ip on its own: the socket peer, and nothing else (R3.1) ---


def test_it_returns_the_socket_peer() -> None:
    assert get_client_ip(Request(_scope(REAL_CLIENT))) == REAL_CLIENT


def test_it_ignores_forwarding_headers_entirely() -> None:
    """No header reading here at all — that is design D3's single-mechanism rule.

    Without the middleware in front, a forged header changes nothing.
    """
    request = Request(
        _scope(
            UNTRUSTED_PEER,
            [(b"x-forwarded-for", b"1.2.3.4"), (b"cf-connecting-ip", b"5.6.7.8")],
        )
    )

    assert get_client_ip(request) == UNTRUSTED_PEER


def test_no_client_at_all_falls_back_to_loopback() -> None:
    # ASGI allows `client` to be absent (in-process transports, some servers).
    assert get_client_ip(Request(_scope(None))) == LOOPBACK


# --- The chain: trusted peer, untrusted peer, and the bypass (R4.1, R4.2) ---


@pytest.mark.asyncio
async def test_a_trusted_proxy_can_report_the_real_client() -> None:
    ip = await _through_proxy_middleware(
        PROXY, [(b"x-forwarded-for", REAL_CLIENT.encode())]
    )

    assert ip == REAL_CLIENT


@pytest.mark.asyncio
async def test_an_untrusted_peer_sending_the_same_header_is_ignored() -> None:
    """R4.2, and the reason the whole change needs a trusted list.

    Identical header, different peer. With the API reachable from the internet, a
    caller who could pick their own bucket would hand themselves a fresh 10/min
    budget per request.
    """
    ip = await _through_proxy_middleware(
        UNTRUSTED_PEER, [(b"x-forwarded-for", REAL_CLIENT.encode())]
    )

    assert ip == UNTRUSTED_PEER


@pytest.mark.asyncio
async def test_a_caller_rotating_the_header_cannot_choose_its_bucket() -> None:
    """The bypass, stated as the property that must hold: same peer, same bucket."""
    first = await _through_proxy_middleware(
        UNTRUSTED_PEER, [(b"x-forwarded-for", b"1.1.1.1")]
    )
    second = await _through_proxy_middleware(
        UNTRUSTED_PEER, [(b"x-forwarded-for", b"9.9.9.9")]
    )

    assert first == second == UNTRUSTED_PEER


@pytest.mark.asyncio
async def test_a_client_supplied_hop_behind_the_proxy_is_not_believed() -> None:
    """R4.3 with the real shape: the proxy appends, so the client's value is at the
    left. uvicorn walks from the right and stops at the first untrusted hop."""
    ip = await _through_proxy_middleware(
        PROXY, [(b"x-forwarded-for", f"1.2.3.4, {REAL_CLIENT}".encode())]
    )

    assert ip == REAL_CLIENT


@pytest.mark.asyncio
async def test_several_occurrences_of_the_header_are_joined_not_picked() -> None:
    ip = await _through_proxy_middleware(
        PROXY,
        [(b"x-forwarded-for", b"1.2.3.4"), (b"x-forwarded-for", REAL_CLIENT.encode())],
    )

    assert ip == REAL_CLIENT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        b"not-an-ip",
        b"",
        b"   ",
        b"999.1.1.1",
        b"0177.0.0.1",
        b"<script>alert(1)</script>",
        # 60 characters: past the 45 that `audit_logs.actor_ip` holds, which is the
        # case that turns a forged header into a FAILED audited write rather than
        # merely a wrong one (app/audit/domain/services.py raises past the limit).
        b"a" * 60,
    ],
)
async def test_a_value_that_is_not_an_ip_never_reaches_the_application(
    raw: bytes,
) -> None:
    """R4.4, and the guard is OURS, not uvicorn's — measured, not assumed.

    `ProxyHeadersMiddleware` picks the right hop but never checks it is an address:
    `get_trusted_client_address` returns the first entry not in the trusted set, so a
    junk string becomes `scope["client"][0]` verbatim. Delegating the hop selection
    (design D3) did NOT come with validation.

    The property asserted is the one that protects the two consumers: what reaches the
    application is **always a valid IP**, so nothing junk can become a throttle key or
    an `actor_ip`. Which valid address it falls back to depends on how far uvicorn got
    —an empty header leaves the trusted peer in place, a junk one is replaced and then
    rejected here— and pinning each case would be pinning uvicorn's internals rather
    than our contract.
    """
    ip = await _through_proxy_middleware(PROXY, [(b"x-forwarded-for", raw)])

    assert _is_ip(ip)
    assert ip != raw.decode()
    assert ip in {LOOPBACK, PROXY}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "raw"),
    [
        # Every one of these PARSES as an IP address, which is why "parses" was not a
        # sufficient guard. All three were measured against the real sinks.
        ("long zone id", b"fe80::1%" + b"z" * 100),
        ("zone id with CRLF", b"fe80::1%a\r\nX-Injected: 1"),
        ("zone id with LF", b"fe80::1%a\nb"),
        ("short zone id", b"fe80::1%eth0"),
    ],
)
async def test_a_scoped_ipv6_address_is_rejected(label: str, raw: bytes) -> None:
    """The hole that "it parses as an IP" left open, and it had three separate sinks.

    A zone identifier is link-local scoping meaningful on ONE host, so it can never
    legitimately describe a remote client — and its content is almost unconstrained.
    Measured consequences of letting it through:

      * a rotating zone id is a fresh `login:ip:*` bucket per request, defeating the
        10/min limit of rule 7 of steering/security.md and growing Redis without bound;
      * a CR/LF zone forges lines in the login log an operator reads during an incident
        (`app/auth/application/use_cases.py` logs the value with `%s`);
      * a zone over the length bound raises `AuditContractError`, aborting the
        transaction of the audited operation in flight — not merely recording it wrong.
    """
    ip = await _through_proxy_middleware(PROXY, [(b"x-forwarded-for", raw)])

    assert ip == LOOPBACK
    assert "%" not in ip
    assert "\n" not in ip and "\r" not in ip
    assert len(ip) <= MAX_CLIENT_IP_LENGTH


@pytest.mark.asyncio
async def test_a_rotating_zone_id_cannot_multiply_throttle_buckets() -> None:
    """The property, stated as the attack it prevents: one peer, one bucket."""
    first = await _through_proxy_middleware(
        PROXY, [(b"x-forwarded-for", b"fe80::1%aaaa")]
    )
    second = await _through_proxy_middleware(
        PROXY, [(b"x-forwarded-for", b"fe80::1%bbbb")]
    )

    assert first == second == LOOPBACK


@pytest.mark.asyncio
async def test_an_ipv4_mapped_address_collapses_onto_its_ipv4_form() -> None:
    """`::ffff:1.2.3.4` and `1.2.3.4` are one client, so they must be one bucket."""
    mapped = await _through_proxy_middleware(
        PROXY, [(b"x-forwarded-for", b"::ffff:203.0.113.9")]
    )
    plain = await _through_proxy_middleware(
        PROXY, [(b"x-forwarded-for", REAL_CLIENT.encode())]
    )

    assert mapped == plain == REAL_CLIENT


def test_the_length_bound_matches_the_column_it_exists_for() -> None:
    """`MAX_CLIENT_IP_LENGTH` is a local copy on purpose — importing the audit domain
    from the auth API layer would cross a boundary — so something has to keep the two
    honest. This is that something."""
    assert MAX_CLIENT_IP_LENGTH == MAX_ACTOR_IP_LENGTH


@pytest.mark.asyncio
async def test_whatever_is_returned_is_short_enough_for_the_audit_column() -> None:
    """The invariant every consumer depends on, asserted once over the nasty inputs."""
    for raw in (
        b"fe80::1%" + b"z" * 100,
        b"2001:0db8:0000:0000:0000:0000:0000:0001",
        b"::ffff:203.0.113.9",
        b"a" * 200,
        b"1.2.3.4:80",
    ):
        ip = await _through_proxy_middleware(PROXY, [(b"x-forwarded-for", raw)])

        assert len(ip) <= MAX_ACTOR_IP_LENGTH, raw


@pytest.mark.asyncio
async def test_a_hop_carrying_a_port_is_parsed_and_not_rejected() -> None:
    """`X-Forwarded-For: 1.2.3.4:80` is a legal shape, and uvicorn splits it.

    Worth pinning because the obvious assumption is the opposite — that a colon makes
    the value unparseable and the client falls back. It does not: the address survives
    and the port is dropped, which is what the throttle wants.
    """
    ip = await _through_proxy_middleware(PROXY, [(b"x-forwarded-for", b"1.2.3.4:80")])

    assert ip == "1.2.3.4"


@pytest.mark.asyncio
async def test_ipv6_is_canonicalised_into_a_single_bucket() -> None:
    """Two spellings of one address must not be two rate-limit budgets."""
    verbose = await _through_proxy_middleware(
        PROXY, [(b"x-forwarded-for", b"2001:0db8:0000:0000:0000:0000:0000:0001")]
    )
    terse = await _through_proxy_middleware(
        PROXY, [(b"x-forwarded-for", b"2001:db8::1")]
    )

    assert verbose == terse == "2001:db8::1"


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


# --- Upstream behaviour this topology depends on (design D4) ---


@pytest.mark.asyncio
async def test_a_hostname_in_the_trusted_list_is_a_literal_and_never_resolved() -> None:
    """Why D4 pins a static address instead of trusting the name `frontend`.

    uvicorn turns anything that is not a valid IP or network into an exact-string
    comparison, silently. A hostname therefore matches no peer, ever: the trusted
    list would be empty in practice and the throttle would count the whole
    deployment in one bucket, with nothing failing to say so.
    """
    ip = await _through_proxy_middleware(
        PROXY, [(b"x-forwarded-for", REAL_CLIENT.encode())], trusted="frontend"
    )

    assert ip == PROXY


@pytest.mark.asyncio
async def test_cidr_notation_is_honoured() -> None:
    """The /32 of design D4 relies on network notation being parsed as a network."""
    ip = await _through_proxy_middleware(
        PROXY, [(b"x-forwarded-for", REAL_CLIENT.encode())], trusted=f"{PROXY}/32"
    )

    assert ip == REAL_CLIENT


@pytest.mark.asyncio
async def test_the_bridge_gateway_is_outside_a_32_and_stays_untrusted() -> None:
    """The single material difference between a /32 and trusting the whole subnet.

    Connections arriving through the published `127.0.0.1:8000` are SNATed by Docker
    to the bridge gateway, which sits inside the subnet. A /32 on the frontend
    excludes it, so an operator with SSH cannot forge a client address.
    """
    ip = await _through_proxy_middleware(
        UNTRUSTED_PEER,
        [(b"x-forwarded-for", REAL_CLIENT.encode())],
        trusted=f"{PROXY}/32",
    )

    assert ip == UNTRUSTED_PEER
