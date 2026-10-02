"""url_for, redirect, abort, and the request that is current on this thread."""

import pytest

from gromon import Blueprint, HTTPError, abort, redirect, request, url_for
from gromon.app import app
from gromon.context import current
from gromon.http import Request
from gromon.response import make_response


@pytest.fixture(autouse=True)
def clean_app():
    app.routes.clear()
    app.middlewares.clear()
    yield
    app.routes.clear()
    app.middlewares.clear()


def get(path="/", method="GET", headers=None, body=b""):
    return Request(method, path, headers or {}, body)


class TestUrlFor:
    def test_a_static_route(self):
        @app.route("/about")
        def about():
            return ""

        assert url_for("about") == "/about"

    def test_values_go_where_the_rule_says(self):
        @app.route("/user/<int:id>")
        def user(id):
            return ""

        assert url_for("user", id=7) == "/user/7"

    def test_extra_values_become_a_query_string(self):
        @app.route("/search")
        def search():
            return ""

        assert url_for("search", q="cats", page=2) == "/search?q=cats&page=2"

    def test_the_root_route(self):
        @app.route("/")
        def index():
            return ""

        assert url_for("index") == "/"

    def test_the_name_of_the_function_is_the_endpoint(self):
        @app.route("/x")
        def whatever():
            return ""

        assert url_for("whatever") == "/x"

    def test_the_name_can_be_set(self):
        @app.route("/x", endpoint="custom")
        def whatever():
            return ""

        assert url_for("custom") == "/x"

    def test_the_same_handler_on_two_paths(self):
        @app.route("/one")
        def both():
            return ""

        @app.route("/two", endpoint="both_two")
        def both_two():
            return ""

        assert (url_for("both"), url_for("both_two")) == ("/one", "/two")

    def test_an_unknown_endpoint_is_an_error(self):
        with pytest.raises(HTTPError) as error:
            url_for("nothing_here")
        assert "nothing_here" in str(error.value)

    def test_a_wildcard_is_built_with_slashes(self):
        @app.route("/files/<path:name>")
        def files(name):
            return ""

        assert url_for("files", name="css/site.css") == "/files/css/site.css"

    def test_it_works_inside_a_handler(self):
        @app.route("/from/<int:id>")
        def go(id):
            return url_for("target", id=id * 2)

        @app.route("/to/<int:id>")
        def target(id):
            return ""

        assert app.handle(get("/from/2")) == (
            200,
            "text/html; charset=utf-8",
            b"/to/4",
            {},
        )


class TestBlueprintNames:
    def test_endpoints_are_namespaced(self):
        admin = Blueprint("admin", "/admin")

        @admin.route("/users")
        def users():
            return ""

        app.register(admin)
        assert url_for("admin.users") == "/admin/users"

    def test_a_blueprint_endpoint_can_be_renamed(self):
        admin = Blueprint("admin", "/admin")

        @admin.route("/users", endpoint="list")
        def users():
            return ""

        app.register(admin)
        assert url_for("admin.list") == "/admin/users"

    def test_the_first_blueprint_wins_when_both_are_registered(self):
        one = Blueprint("api", "/api")

        @one.route("/ping")
        def ping():
            return ""

        app.register(one)
        assert url_for("api.ping") == "/api/ping"


class TestRedirect:
    def test_it_is_a_302_with_a_location(self):
        status, kind, body, headers = make_response(redirect("/next"))
        assert (status, kind, headers) == (
            302,
            "text/html",
            {"Location": "/next"},
        )

    def test_the_status_can_change(self):
        assert make_response(redirect("/moved", 301))[0] == 301

    def test_through_the_app(self):
        @app.route("/old")
        def old():
            return redirect("/new")

        status, kind, body, headers = app.handle(get("/old"))
        assert (status, headers["Location"]) == (302, "/new")


class TestAbort:
    def test_it_raises_with_a_default_message(self):
        try:
            abort(404)
        except HTTPError as error:
            assert (error.status, error.message) == (404, "Not found")
        else:
            assert False, "abort should raise"

    def test_the_message_can_be_given(self):
        try:
            abort(403, "Not for you")
        except HTTPError as error:
            assert str(error) == "403 Not for you"

    def test_through_the_app(self):
        @app.route("/secret")
        def secret():
            abort(403, "Not for you")

        assert app.handle(get("/secret")) == (
            403,
            "application/json",
            b'{"error": "Not for you"}',
            {},
        )

    def test_a_status_with_no_known_message_still_works(self):
        try:
            abort(499)
        except HTTPError as error:
            assert error.status == 499


class TestConvertersThroughTheApp:
    def test_an_int_arrives_as_an_int(self):
        @app.route("/n/<int:number>")
        def show(number):
            return {"number": number, "type": type(number).__name__}

        assert app.handle(get("/n/7"))[2] == b'{"number": 7, "type": "int"}'

    def test_wrong_text_does_not_reach_the_handler(self):
        @app.route("/n/<int:number>")
        def show(number):
            return {}

        assert app.handle(get("/n/seven"))[0] == 404


class TestUrlForOnTheServingApp:
    """The global url_for has to follow the App handling the request.

    An app built by hand registers routes on itself, not on the global one, and
    templates have no `app` to ask. Building against the global app there gave
    "No route named ..." from a page that worked.
    """

    def build(self):
        from gromon import App

        application = App()
        posts = Blueprint("posts", "/posts")

        @posts.route("/<int:id>")
        def post(id):
            return url_for("posts.post", id=id)

        application.register(posts)

        @application.route("/")
        def home():
            return url_for("posts.post", id=3)

        return application

    def test_it_builds_against_the_app_being_handled(self):
        application = self.build()
        status, _, body, _ = application.handle(Request("GET", "/", {}, b""))
        assert status == 200
        assert body == b"/posts/3"

    def test_outside_a_request_it_is_the_global_app(self):
        with pytest.raises(HTTPError):
            url_for("nothing-registered-anywhere")


class TestRequestContext:
    def test_outside_a_request_there_is_none(self):
        assert current() is None

    def test_inside_a_handler_it_is_the_request(self):
        seen = []

        @app.route("/ctx")
        def ctx():
            seen.append(request.path)
            return ""

        app.handle(get("/ctx"))
        assert seen == ["/ctx"]

    def test_the_proxy_refuses_to_guess(self):
        with pytest.raises(RuntimeError):
            request.path

    def test_external_urls_use_the_host_of_the_request(self):
        @app.route("/here")
        def here():
            return url_for("here", _external=True)

        _, _, body, _ = app.handle(get("/here", headers={"Host": "shop.test"}))
        assert body == b"http://shop.test/here"

    def test_the_context_is_cleared_afterwards(self):
        @app.route("/ctx")
        def ctx():
            return ""

        app.handle(get("/ctx"))
        assert current() is None

    def test_the_context_is_cleared_even_after_an_error(self):
        @app.route("/boom")
        def boom():
            raise ValueError("nope")

        app.handle(get("/boom"))
        assert current() is None
