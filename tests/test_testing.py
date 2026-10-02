"""The test client: no socket, real handle(), real cookies."""

import pytest

from gromon import HTTPError, auth, redirect, session
from gromon.app import App, app


@pytest.fixture
def application():
    """A fresh application for every test, with sessions switched on."""
    fresh = App()
    load, save = session("a-secret-long-enough")
    fresh.use(load)
    fresh.after(save)

    @fresh.route("/")
    def home():
        return {"message": "Hello World"}

    @fresh.route("/user/<int:id>")
    def user(id):
        return {"id": id, "kind": type(id).__name__}

    @fresh.route("/boom")
    def boom():
        raise HTTPError(418, "I am a teapot")

    @fresh.route("/text")
    def text():
        return "plain"

    @fresh.route("/nothing")
    def nothing():
        return None

    @fresh.route("/echo", methods=["POST"])
    def echo(request):
        return {"body": request.json()}

    @fresh.route("/content-type", methods=["POST"])
    def content_type(request):
        return {"type": request.headers.get("Content-Type")}

    @fresh.route("/headers")
    def headers():
        return "hi", 200, "text/plain", {"X-Flavour": "vanilla"}

    @fresh.route("/go")
    def go():
        return redirect("/")

    @fresh.route("/whoami")
    def whoami(request):
        return {"user": request.session.get("user")}

    @fresh.route("/login", methods=["POST"])
    def login(request):
        request.session["user"] = request.json()["user"]
        return {"ok": True}

    @fresh.route("/logout")
    def logout():
        return auth.expired()()

    return fresh


@pytest.fixture
def client(application):
    return application.test_client()


class TestBasics:
    def test_get_returns_a_response(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert response.json == {"message": "Hello World"}

    def test_text_comes_back_as_text(self, client):
        response = client.get("/text")
        assert response.text == "plain"
        assert response.get_header("Content-Type") == "text/html; charset=utf-8"

    def test_a_204_has_no_body(self, client):
        response = client.get("/nothing")
        assert (response.status_code, response.data) == (204, b"")

    def test_headers_are_readable_whatever_the_case(self, client):
        assert client.get("/headers").get_header("x-flavour") == "vanilla"

    def test_a_missing_header_is_the_default(self, client):
        assert client.get("/headers").get_header("X-Nothing", "fallback") == "fallback"

    def test_the_response_repr_says_the_status(self, client):
        assert repr(client.get("/")) == "<Response 200>"


class TestMethods:
    def test_post_sends_json(self, client):
        response = client.post("/echo", data='{"a": 1}')
        assert response.json == {"body": {"a": 1}}

    def test_bytes_can_be_sent_too(self, client):
        assert client.post("/echo", data=b'{"a": 2}').json["body"] == {"a": 2}

    def test_the_content_type_can_be_set(self, client):
        response = client.post("/content-type", data=b"a=1", headers={"Content-Type": "text/plain"})
        assert response.json["type"] == "text/plain"

    def test_json_is_the_default_content_type(self, client):
        assert client.post("/echo", data='{"a": 1}').json["body"] == {"a": 1}

    def test_query_values_reach_the_url(self, client, application):
        @application.route("/search")
        def search(request):
            return request.query

        assert client.get("/search", query={"a": "1"}).json == {"a": "1"}

    def test_put_patch_delete_exist(self, client):
        assert client.put("/echo").status_code == 405
        assert client.patch("/echo").status_code == 405
        assert client.delete("/echo").status_code == 405

    def test_head_has_no_body(self, client):
        assert client.head("/").data == b""


class TestRoutes:
    def test_converters_run(self, client):
        assert client.get("/user/7").json == {"id": 7, "kind": "int"}

    def test_a_bad_converter_is_a_404(self, client):
        assert client.get("/user/seven").status_code == 404

    def test_errors_come_back_as_responses(self, client):
        response = client.get("/boom")
        assert (response.status_code, response.json) == (418, {"error": "I am a teapot"})

    def test_redirects_are_visible(self, client):
        response = client.get("/go")
        assert (response.status_code, response.get_header("Location")) == (302, "/")


class TestCookies:
    def test_a_login_is_still_there_on_the_next_call(self, client):
        client.post("/login", data='{"user": "ada"}')
        assert client.get("/whoami").json == {"user": "ada"}

    def test_logging_out_clears_it(self, client):
        client.post("/login", data='{"user": "ada"}')
        client.get("/logout")
        assert client.get("/whoami").json == {"user": None}

    def test_a_second_client_is_a_stranger(self, client, application):
        client.post("/login", data='{"user": "ada"}')
        with application.test_client() as other:
            assert other.get("/whoami").json == {"user": None}

    def test_the_context_manager_returns_the_client(self, application):
        with application.test_client() as client:
            assert client.get("/").status_code == 200


class TestSessionsThroughTheClient:
    def test_a_signed_session_round_trips(self):
        fresh = App()
        load, save = session("a-secret-long-enough")
        fresh.use(load)
        fresh.after(save)

        @fresh.route("/set", methods=["POST"])
        def set_name(request):
            request.session["name"] = "ada"
            return {"ok": True}

        @fresh.route("/get")
        def get_name(request):
            return {"name": request.session.get("name")}

        client = fresh.test_client()
        client.post("/set")
        assert client.get("/get").json == {"name": "ada"}

    def test_a_tampered_cookie_is_ignored(self):
        fresh = App()
        load, save = session("a-secret-long-enough")
        fresh.use(load)
        fresh.after(save)

        @fresh.route("/get")
        def get_name(request):
            return {"name": request.session.get("name")}

        client = fresh.test_client()
        client.cookies["session"] = auth.sign({"name": "root"}, "another-secret-here")
        assert client.get("/get").json == {"name": None}


def test_the_default_application_has_one_too():
    with app.test_client() as client:
        assert client.get("/does-not-exist").status_code == 404
