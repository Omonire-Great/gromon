"""End to end: a real server on a real socket."""

import http.client
import threading
from http.server import ThreadingHTTPServer
from json import loads

import pytest

from gromon import HTTPError
from gromon.app import app
from gromon.server import handler_for


@pytest.fixture
def port():
    app.routes.clear()

    @app.route("/")
    def home():
        return {"message": "Hello World"}

    @app.route("/user/<id>")
    def user(id):
        return {"id": int(id)}

    @app.route("/echo", methods=["POST"])
    def echo(request):
        return {"body": request.json(), "q": request.query.get("q")}

    @app.route("/boom")
    def boom():
        raise HTTPError(418, "I am a teapot")

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(app.handle))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()
    app.routes.clear()


def call(port, method="GET", path="/", body=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(method, path, body)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response, data


def test_get_returns_json(port):
    response, body = call(port)
    assert response.status == 200
    assert response.getheader("Content-Type") == "application/json"
    assert loads(body) == {"message": "Hello World"}


def test_path_parameters_over_http(port):
    _, body = call(port, path="/user/7")
    assert loads(body) == {"id": 7}


def test_post_body_and_query_over_http(port):
    _, body = call(port, "POST", "/echo?q=hi", b'{"a": 1}')
    assert loads(body) == {"body": {"a": 1}, "q": "hi"}


def test_404_over_http(port):
    response, body = call(port, path="/nope")
    assert (response.status, loads(body)) == (404, {"error": "Not found"})


def test_http_error_status_over_http(port):
    response, body = call(port, path="/boom")
    assert (response.status, loads(body)) == (418, {"error": "I am a teapot"})


def test_head_has_no_body(port):
    response, body = call(port, "HEAD")
    assert response.status == 200
    assert body == b""


def test_keep_alive_reuses_one_connection(port):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    for _ in range(3):
        connection.request("GET", "/")
        assert connection.getresponse().read() == b'{"message": "Hello World"}'
    connection.close()
