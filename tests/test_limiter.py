
from gromon import limiter
from gromon.limiter import limit
from gromon.http import Request

TOO_MANY = ({"error": "Too many requests"}, 429)


def get(path="/", client="1.2.3.4", headers=None):
    return Request("GET", path, headers or {}, b"", client)


def test_a_request_below_the_limit_passes():
    guard = limit(2, 60)
    assert guard(get()) is None
    assert guard(get()) is None


def test_the_third_request_is_rejected():
    guard = limit(2, 60)
    guard(get())
    guard(get())
    assert guard(get()) == TOO_MANY


def test_each_caller_has_its_own_count():
    guard = limit(1, 60)

    assert guard(get(client="1.1.1.1")) is None
    assert guard(get(client="2.2.2.2")) is None
    assert guard(get(client="1.1.1.1")) == TOO_MANY


def test_the_window_slides(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(limiter, "monotonic", lambda: now[0])
    guard = limit(2, 10)

    guard(get())
    guard(get())
    assert guard(get()) == TOO_MANY

    now[0] += 11
    assert guard(get()) is None


def test_a_proxy_address_is_used_when_present():
    guard = limit(1, 60)
    headers = {"X-Forwarded-For": "9.9.9.9, 10.0.0.1"}

    assert guard(get(client="1.1.1.1", headers=headers)) is None
    assert guard(get(client="1.1.1.1", headers=headers)) == TOO_MANY
    assert guard(get(client="2.2.2.2")) is None


def test_the_key_can_be_replaced():
    guard = limit(1, 60, key=lambda request: request.query.get("key", "?"))

    assert guard(get("/?key=a")) is None
    assert guard(get("/?key=b")) is None
    assert guard(get("/?key=a")) == TOO_MANY


def test_caller_falls_back_to_the_socket():
    assert limiter.caller(get(client="4.4.4.4")) == "4.4.4.4"
    assert limiter.caller(get(client="")) == "?"


def test_reset_clears_the_count():
    guard = limit(1, 60)
    guard(get())
    assert guard(get()) == TOO_MANY

    guard.reset()

    assert guard(get()) is None


def test_idle_callers_are_forgotten(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(limiter, "monotonic", lambda: now[0])
    guard = limit(1, 10)

    guard(get(client="1.1.1.1"))
    assert guard(get(client="2.2.2.2")) is None

    now[0] += 20
    guard(get(client="3.3.3.3"))

    assert guard(get(client="1.1.1.1")) is None


def test_limiter_works_as_an_app_middleware():
    from gromon import use
    from gromon.app import app

    app.routes.clear()
    app.middlewares.clear()
    use(limit(1, 60))

    try:
        @app.route("/")
        def home():
            return "ok"

        assert app.handle(get("/"))[0] == 200
        assert app.handle(get("/"))[0] == 429
    finally:
        app.middlewares.clear()
        app.routes.clear()
