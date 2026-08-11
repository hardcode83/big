"""The guest portal's two rate limits (R2.4, design D6).

Built on the **shape** of `app/integrations/infrastructure/throttle.py` but not on its class,
and the reason is vocabulary rather than taste: `RedisWebhookThrottle` speaks of provider
deliveries and endpoints. Neither exists here — what is counted is a guest opening their own
link, not a provider posting. Sharing the class would mean a second meaning for every method.

**Two limits, because they defend against opposite failures** (D6):

- **By token, generous**, charged *after* a successful authorisation. This is the one that
  matters more here than it does for webhooks: a valid token can `POST /guest/incident`
  indefinitely, so this is the only thing bounding how many `incidents` rows one stay
  produces — the change deliberately does not make that endpoint idempotent (D13).
- **By IP, strict, and counted only when authorisation FAILS.** This is what makes guessing
  a token cost something.

The asymmetry is the design, and the obvious simplification is the one thing that cannot be
done: a single per-IP limit over all traffic would put every guest of a hotel behind one
address into the same bucket, so sized for one guest it throttles the hotel and sized for the
hotel it stops being a defence.

**Both keys use the digest, never the token.** These keys can end up in a Redis `KEYS` dump,
a `MONITOR` stream or a memory snapshot, and R1.2's whole point is that the credential cannot
be recovered from somewhere it was incidentally written down. The authoriser already holds
the digest, so nothing is lost — and note the corollary the design states explicitly: the
per-token limit is charged with the hash **already in hand**, never by re-hashing the path
segment, which would put the cleartext back into circulation for no reason.

Fixed window, not sliding — the same `ASSUMPTION` the login and webhook throttles record: at
a minute boundary a caller can get up to twice the limit in quick succession. That is
acceptable because neither limit is the primary defence; 256 bits of CSPRNG is.

**Second `ASSUMPTION`, and it belongs written down rather than discovered**: the probe limit
asks (`_count`, a plain read) and charges (`_hit`) in two separate steps, so under
concurrency the real ceiling is "the configured limit **plus whatever is already in flight**"
rather than the limit exactly. Requests that pass `probe_allowed` before any of them reaches
`record_failed_authorisation` all get served.

That split is deliberate and required: D6 forbids charging on the question, because otherwise
a guest's ordinary successful traffic would eat the probe budget and the two limits would
collapse into the single per-IP one that puts a hotel's whole WiFi in one bucket. It is also
exactly the shape `RedisWebhookThrottle` has, which D6 told this class to copy — the
single-`INCR` alternative is `RedisLoginThrottle`, whose counter means *attempts* rather than
*failures*, so it is not the same primitive. Raised by the section 5 security panel, which
read the login shape onto the webhook one; recorded here rather than diverging from the
precedent unilaterally, because closing it means an atomic check-and-charge (Lua) for both
throttles at once, which is a change to `reservations-webhooks`' surface too.

What bounds the damage: the burst costs the attacker nothing they did not already have —
guessing a 256-bit token is infeasible either way — so what is left is a load concern on the
authorising path, not a guessing one.
"""

from redis.asyncio import Redis

WINDOW_SECONDS = 60


class RedisGuestPortalThrottle:
    """Counts authorised requests per token and failed authorisations per IP."""

    def __init__(
        self, redis: Redis, *, requests_per_minute: int, probes_per_minute: int
    ) -> None:
        self._redis = redis
        self._requests_per_minute = requests_per_minute
        self._probes_per_minute = probes_per_minute

    async def request_allowed(self, token_hash: str) -> bool:
        """Whether this stay may make another authorised request this minute (R2.4).

        Charged **after** authorising, with the digest the authoriser resolved. This one
        *is* the attempt, so it counts itself: `<=` allows exactly `limit` per window, the
        same arithmetic the webhook and login throttles use.
        """
        hits = await self._hit(f"guest_portal:token:{token_hash}")
        return hits <= self._requests_per_minute

    async def probe_allowed(self, client_ip: str) -> bool:
        """Whether this IP may attempt an authorisation at all (R2.4).

        Asked before any **lookup**, so a caller spending their budget on guesses cannot make
        the server resolve stays for them. On `POST /guest/checkin` the request body is parsed
        and validated ahead of this — FastAPI does it while solving dependencies — so a
        malformed body is a `422` that never asks. Bounded by the shared body ceiling and
        identical whatever the token, but worth saying: the guarantee is over queries, not
        over every byte of work.

        Strictly `<`, unlike `request_allowed`, because the counter means something different:
        it holds the failures **already** made, not this request. After `limit` failures the
        budget is spent, so the next attempt is refused rather than granted as a `limit + 1`-th.
        """
        return await self._count(f"guest_portal:probe:{client_ip}") < self._probes_per_minute

    async def record_failed_authorisation(self, client_ip: str) -> None:
        """One more failed authorisation from this IP (R2.4).

        Deliberately counts **failures only**. Counting every request would collapse the two
        limits into one and put the hotel-WiFi case back — and it would also make the probe
        counter a side channel, since a caller could learn from their own throttling whether
        somebody else's token had resolved.
        """
        await self._hit(f"guest_portal:probe:{client_ip}")

    async def _hit(self, key: str) -> int:
        # The TTL is re-asserted on EVERY hit rather than only when INCR returns 1, and `nx`
        # keeps the window from sliding forward. This is the correction both sibling
        # throttles carry, and the reason bears repeating: INCR and EXPIRE are two round
        # trips, so if the second never runs — process death, timeout, a failover in between
        # — the key survives with no TTL and that counter never lapses. Here that would mean
        # a guest locked out of their own check-in until somebody deletes a Redis key by hand.
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, WINDOW_SECONDS, nx=True)
            hits, _ = await pipe.execute()
        return hits

    async def _count(self, key: str) -> int:
        """Reads the counter WITHOUT incrementing it.

        Separate from `_hit` because `probe_allowed` is a question, not an attempt: if asking
        "may this IP proceed?" also incremented, a guest's ordinary traffic would count
        against the probe limit and the distinction that makes D6 work would be gone.
        """
        current = await self._redis.get(key)
        return int(current) if current is not None else 0
