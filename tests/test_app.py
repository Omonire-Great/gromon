import pytest

from gromon import Blueprint, HTTPError, after
from gromon.app import app
from gromon.http import Request


@pytest.fixture(autouse=True)
def clean_app():
    """Every test starts with an empty application."""
    app.routes.clear()
    app.middlewares.clear()
    app.errors.clear()
    app.on_response.clear()
    yield
    app.routes.clear()
    app.middlewares.clear()
    app.errors.clear()
    app.on_response.clear()


def get(path="/", method="GET", body=b""):
    return Request(method, path, {}, body)


def test_dict_return_is_json():
    @app.route("/")
    def home():
        return {"message": "Hello World"}

    assert app.handle(get()) == (200, "application/json", b'{"message": "Hello World"}', {})


def test_url_parameters_become_arguments():
    @app.route("/user/<id>")
    def user(id):
        return {"id": int(id)}

    assert app.handle(get("/user/7")) == (200, "application/json", b'{"id": 7}', {})


def test_handler_gets_the_request_when_it_asks():
    @app.route("/echo", methods=["POST"])
    def echo(request):
        return {"body": request.json(), "q": request.query["q"]}

    status, kind, body, headers = app.handle(get("/echo?q=hi", method="POST", body=b'{"a":1}'))
    assert (status, kind, body, headers) == (
        200,
        "application/json",
        b'{"body": {"a": 1}, "q": "hi"}',
        {},
    )


def test_handler_and_url_parameters_together():
    @app.route("/user/<id>")
    def user(request, id):
        return {"path": request.path, "id": id}

    assert app.handle(get("/user/7")) == (
        200,
        "application/json",
        b'{"path": "/user/7", "id": "7"}',
        {},
    )


def test_status_code_from_tuple():
    @app.route("/")
    def home():
        return {"created": True}, 201

    assert app.handle(get())[0] == 201


def test_get_route_answers_head():
    @app.route("/")
    def home():
        return "hi"

    assert app.handle(get(method="HEAD"))[0] == 200


def test_route_returns_the_handler_unchanged():
    @app.route("/")
    def home():
        return "called directly"

    assert home() == "called directly"


# middleware


def test_middleware_runs_before_the_handler():
    calls = []

    @app.use
    def note(request):
        calls.append(request.path)

    @app.route("/")
    def home():
        return {"ok": True}

    assert app.handle(get("/"))[0] == 200
    assert calls == ["/"]


def test_middleware_can_stop_the_request():
    @app.use
    def token(request):
        if not request.headers.get("X-Token"):
            return {"error": "Unauthorized"}, 401

    @app.route("/")
    def home():
        return {"secret": True}

    assert app.handle(get("/")) == (401, "application/json", b'{"error": "Unauthorized"}', {})


def test_middleware_can_raise_http_error():
    @app.use
    def guard(request):
        raise HTTPError(403, "Forbidden")

    @app.route("/")
    def home():
        return "never"

    assert app.handle(get("/")) == (403, "application/json", b'{"error": "Forbidden"}', {})


def test_middlewares_run_in_order():
    order = []

    @app.use
    def first(request):
        order.append("first")

    @app.use
    def second(request):
        order.append("second")

    app.handle(get("/"))

    assert order == ["first", "second"]


# error handlers


def test_unknown_path_is_404_json():
    assert app.handle(get("/nope")) == (404, "application/json", b'{"error": "Not found"}', {})


def test_wrong_method_is_405_json():
    @app.route("/")
    def home():
        return {}

    assert app.handle(get(method="POST")) == (
        405,
        "application/json",
        b'{"error": "Method not allowed"}',
        {},
    )


def test_http_error_from_handler():
    @app.route("/user/<id>")
    def user(id):
        raise HTTPError(404, "User not found")

    assert app.handle(get("/user/9")) == (
        404,
        "application/json",
        b'{"error": "User not found"}',
        {},
    )


def test_unexpected_error_is_500():
    @app.route("/")
    def home():
        raise ValueError("boom")

    assert app.handle(get()) == (
        500,
        "application/json",
        b'{"error": "Internal server error"}',
        {},
    )


def test_custom_error_handler():
    @app.error(404)
    def missing(request):
        return "Nothing here"

    assert app.handle(get("/nope")) == (404, "text/html; charset=utf-8", b"Nothing here", {})


def test_custom_error_handler_gets_the_error():
    @app.error(404)
    def missing(error):
        return {"what": error.message}, 404

    assert app.handle(get("/nope")) == (404, "application/json", b'{"what": "Not found"}', {})


def test_custom_error_handler_for_500():
    @app.error(500)
    def broken(request):
        return "Oops", 500

    @app.route("/")
    def home():
        raise ValueError("boom")

    assert app.handle(get()) == (500, "text/html; charset=utf-8", b"Oops", {})


# blueprints


def test_blueprint_routes_are_mounted():
    admin = Blueprint("admin", "/admin")

    @admin.route("/users")
    def users():
        return [{"id": 1}]

    app.register(admin)

    assert app.handle(get("/admin/users")) == (200, "application/json", b'[{"id": 1}]', {})
    assert app.handle(get("/users"))[0] == 404


def test_blueprint_without_prefix():
    api = Blueprint("api")

    @api.route("/ping")
    def ping():
        return "pong"

    app.register(api)

    assert app.handle(get("/ping")) == (200, "text/html; charset=utf-8", b"pong", {})

class TestResponseHeaders:
    def test_the_fourth_item_reaches_the_client(self):
        @app.route("/")
        def home():
            return "hi", 200, "text/plain", {"X-Frame-Options": "DENY"}

        assert app.handle(get())[3] == {"X-Frame-Options": "DENY"}

    def test_after_adds_headers_to_a_normal_response(self):
        @after
        def stamp(request, headers):
            headers["X-Gromon"] = "1.0"

        @app.route("/")
        def home():
            return "hi"

        assert app.handle(get())[3] == {"X-Gromon": "1.0"}

    def test_after_sees_the_request(self):
        seen = []

        @after
        def remember(request, headers):
            seen.append(request.path)

        @app.route("/x")
        def home():
            return "hi"

        app.handle(get("/x"))
        assert seen == ["/x"]

    def test_after_also_runs_on_an_error(self):
        @after
        def stamp(request, headers):
            headers["X-Gromon"] = "1.0"

        assert app.handle(get("/nope"))[3] == {"X-Gromon": "1.0"}

    def test_after_also_runs_when_middleware_stops_the_request(self):
        @after
        def stamp(request, headers):
            headers["X-Gromon"] = "1.0"

        @app.use
        def guard(request):
            return {"error": "No"}, 403

        assert app.handle(get())[3] == {"X-Gromon": "1.0"}

    def test_after_runs_in_order(self):
        @after
        def first(request, headers):
            headers["X-N"] = "1"

        @after
        def second(request, headers):
            headers["X-N"] += "2"

        @app.route("/")
        def home():
            return "hi"

        assert app.handle(get())[3] == {"X-N": "12"}
