"""A signed cookie session over a real socket: log in, come back, log out."""

import http.client
import threading
from http.server import ThreadingHTTPServer
from json import loads

import pytest

from gromon import auth
from gromon.app import app
from gromon.server import handler_for

SECRET = "a-secret-long-enough-for-tests"


@pytest.fixture
def port():
    app.routes.clear()
    app.middlewares.clear()
    app.on_response.clear()

    login, save = auth.session(SECRET)
    app.use(login)
    app.after(save)

    @app.route("/login", methods=["POST"])
    def do_login(request):
        if request.json().get("password") != "hunter2":
            return {"error": "Wrong password"}, 403
        request.session["user"] = "ada"
        return {"ok": True}

    @app.route("/whoami")
    def whoami(request):
        return {"user": request.session.get("user")}

    @app.route("/logout")
    def do_logout():
        return auth.expired()()

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(app.handle))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()
    app.routes.clear()
    app.middlewares.clear()
    app.on_response.clear()


def call(port, method="GET", path="/", body=None, cookie=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Cookie": cookie} if cookie else {}
    connection.request(method, path, body, headers)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response, data


def test_logging_in_sets_a_cookie(port):
    response, body = call(port, "POST", "/login", b'{"password": "hunter2"}')
    assert response.status == 200
    assert loads(body) == {"ok": True}
    assert response.getheader("Set-Cookie").startswith("session=")


def test_the_cookie_carries_the_session_to_the_next_call(port):
    response, _ = call(port, "POST", "/login", b'{"password": "hunter2"}')
    token = response.getheader("Set-Cookie").split(";")[0]
    _, body = call(port, path="/whoami", cookie=token)
    assert loads(body) == {"user": "ada"}


def test_a_wrong_password_sets_no_cookie(port):
    response, body = call(port, "POST", "/login", b'{"password": "nope"}')
    assert response.status == 403
    assert response.getheader("Set-Cookie") is None


def test_a_stranger_is_nobody(port):
    _, body = call(port, path="/whoami")
    assert loads(body) == {"user": None}


def test_a_forged_cookie_is_nobody(port):
    forged = auth.sign({"user": "root"}, "some-other-secret-here")
    _, body = call(port, path="/whoami", cookie=f"session={forged}")
    assert loads(body) == {"user": None}


def test_logging_out_clears_the_cookie(port):
    response, _ = call(port, path="/logout")
    assert response.getheader("Set-Cookie") == "session=; Path=/; Max-Age=0"
