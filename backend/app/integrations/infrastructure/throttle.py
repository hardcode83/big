"""The two webhook rate limiters of rule 12(c) (`reservations-webhooks` R3.1, R3.3, R3.4, D6).

Built on the shape of `app/auth/infrastructure/throttle.py` but **not** on its class, and the
reason is vocabulary rather than taste: `RedisLoginThrottle` speaks of login attempts, account
lockout and `user_id`. None of those exist here — there is no account to lock, and the thing being
counted is a provider's delivery, not a person's password guess. Reusing it would have meant either
a second meaning for its methods or a shared base class that is only a `pipeline` call.

**Two limits, because they defend against opposite failures** (D6):

- **By token, generous.** A provider whose retry loop runs away must not be able to fill
  `webhook_events`. Keyed by the token hash, so the unit is the tenant.
- **By IP, strict, and only counted when authentication FAILS.** This is what makes guessing a
  route token cost something (R3.4).

The asymmetry is the whole design. A single per-IP limit over *all* traffic would be the obvious
simplification and is the one thing that cannot be done: a provider delivers from a handful of IPs
on behalf of **many** tenants, so a per-IP ceiling sized for one tenant throttles every tenant at
once, and sized for all of them stops being a defence.

Fixed window, not sliding — the same `ASSUMPTION` the login throttle records, and for the same
reason: at a minute boundary a caller can get up to twice the limit in quick succession. That
matters less here than it does for login, because neither limit is the primary defence; the token
and the header secret are.
"""

from redis.asyncio import Redis

WINDOW_SECONDS = 60


class RedisWebhookThrottle:
    """Counts deliveries per token and failed authentications per IP.

    Takes the **token hash** and never the token: this object's keys can end up in a Redis
    `KEYS`/`MONITOR` dump or a memory snapshot, and rule 12(b)'s whole value is that the route
    cannot be recovered from somewhere it was incidentally written down. The hash is already what
    the lookup uses, so nothing is lost.
    """

    def __init__(
        self, redis: Redis, *, deliveries_per_minute: int, probes_per_minute: int
    ) -> None:
        self._redis = redis
        self._deliveries_per_minute = deliveries_per_minute
        self._probes_per_minute = probes_per_minute

    async def delivery_allowed(self, token_hash: str) -> bool:
        """Whether this tenant's endpoint may accept another delivery this minute (R3.1).

        This one **is** the attempt, so it counts itself: `<=` allows exactly `limit` deliveries
        per window, the same arithmetic `RedisLoginThrottle.ip_attempt_allowed` uses.
        """
        hits = await self._hit(f"webhook:token:{token_hash}")
        return hits <= self._deliveries_per_minute

    async def probe_allowed(self, client_ip: str) -> bool:
        """Whether this IP may make another attempt at all (R3.4).

        Asked **before** the work of authenticating, and incremented only by
        `record_failed_attempt`, so a legitimate provider — which never fails — never approaches
        it no matter how much traffic it sends.

        Strictly `<`, unlike `delivery_allowed`, because the counter means something different
        here: it holds the failures **already** made, not this request. After `limit` failures the
        budget is spent, so the next attempt is refused rather than granted as a `limit + 1`-th.
        """
        return await self._count(f"webhook:probe:{client_ip}") < self._probes_per_minute

    async def record_failed_attempt(self, client_ip: str) -> None:
        """One more failed authentication from this IP (R3.4).

        Deliberately counts **failures only**. Counting every request here would collapse the two
        limits into one and reintroduce exactly the cross-tenant throttling D6 rejects.
        """
        await self._hit(f"webhook:probe:{client_ip}")

    async def _hit(self, key: str) -> int:
        # The TTL is re-asserted on EVERY hit rather than only when INCR returns 1, and `nx` keeps
        # the window from sliding forward. This is the correction `RedisLoginThrottle` already
        # carries and the reason is worth repeating: INCR and EXPIRE are two round trips, so if
        # the second never runs — process death, timeout, a failover in between — the key survives
        # with no TTL and that counter never lapses. Here that would mean a tenant's webhooks
        # refused permanently, recoverable only by deleting a Redis key by hand.
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, WINDOW_SECONDS, nx=True)
            hits, _ = await pipe.execute()
        return hits

    async def _count(self, key: str) -> int:
        """Reads the counter WITHOUT incrementing it.

        Separate from `_hit` because `probe_allowed` is a question, not an attempt: if asking
        "may this IP proceed?" also incremented, then a legitimate provider's ordinary traffic
        would count against the probe limit and the distinction that makes D6 work would be gone.
        """
        current = await self._redis.get(key)
        return int(current) if current is not None else 0
