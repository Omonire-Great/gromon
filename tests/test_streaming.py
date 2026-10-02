"""A streamed body over a real socket, with real chunked encoding."""

import http.client
import threading
from http.server import ThreadingHTTPServer

import pytest

from gromon import App, request
from gromon.server import handler_for


@pytest.fixture
def streaming():
    app = App()

    @app.route("/numbers")
    def numbers():
        return (f"{number}\n" for number in range(5))

    @app.route("/who")
    def who():
        def chunks():
            yield f"path={request.path} "
            yield "done"

        return chunks()

    @app.route("/plain")
    def plain():
        return "not streamed"

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(app.handle))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def call(port, path):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("GET", path)
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response, body


def test_a_generator_is_written_as_it_is_made(streaming):
    response, body = call(streaming, "/numbers")
    assert response.status == 200
    assert body == b"0\n1\n2\n3\n4\n"


def test_a_streamed_body_is_chunked(streaming):
    response, _ = call(streaming, "/numbers")
    assert response.getheader("Transfer-Encoding") == "chunked"
    assert response.getheader("Content-Length") is None


def test_a_normal_body_still_has_a_length(streaming):
    response, body = call(streaming, "/plain")
    assert response.getheader("Content-Length") == str(len(body))
    assert response.getheader("Transfer-Encoding") is None


def test_a_generator_can_read_the_request_while_it_runs(streaming):
    _, body = call(streaming, "/who")
    assert body == b"path=/who done"


def test_the_connection_stays_usable_after_streaming(streaming):
    connection = http.client.HTTPConnection("127.0.0.1", streaming, timeout=5)
    try:
        for _ in range(3):
            connection.request("GET", "/numbers")
            assert connection.getresponse().read() == b"0\n1\n2\n3\n4\n"
    finally:
        connection.close()


def test_head_on_a_streamed_route_sends_no_chunks(streaming):
    connection = http.client.HTTPConnection("127.0.0.1", streaming, timeout=5)
    try:
        connection.request("HEAD", "/numbers")
        response = connection.getresponse()
        assert response.read() == b""
    finally:
        connection.close()
