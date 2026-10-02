"""Rate limiting, built on middleware and kept in memory.

    from gromon import limiter, use

    use(limiter.limit(60))        # 60 requests a minute per caller
    use(limiter.limit(5, 1, key=lambda r: r.query.get("key")))

One process, one window. Behind more than one worker, count in the database
instead.
"""

from time import monotonic


def caller(request):
    """Who to count: the forwarded address if a proxy set one, else the socket."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    return (forwarded.split(",")[0] or request.client or "?").strip()


def limit(per=60, window=60.0, key=None):
    """Middleware that lets `per` requests through per `window` seconds.

    Answers {"error": "Too many requests"} with status 429 once the caller is
    over the limit. `key` replaces the default caller identity.
    """
    identify = key or caller
    times, swept = {}, [0.0]

    def middleware(request):
        now = monotonic()
        name = identify(request)
        recent = [moment for moment in times.get(name, ()) if now - moment < window]

        if len(recent) >= per:
            return {"error": "Too many requests"}, 429

        recent.append(now)
        times[name] = recent
        if now - swept[0] > window:
            swept[0] = now
            for idle in [n for n, hits in times.items() if not hits or now - hits[-1] > window]:
                del times[idle]
        return None

    middleware.reset = lambda: times.clear()
    return middleware
