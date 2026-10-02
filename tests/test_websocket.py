"""WebSocket over a real socket: handshake, framing, ping, close, fragments."""

import base64
import os
import socket
import struct
import threading
from http.server import ThreadingHTTPServer
from json import loads

import pytest

from gromon.app import app
from gromon.server import handler_for
from gromon.websocket import GUID, accept_key

TEXT, BINARY, CLOSE, PING = 0x1, 0x2, 0x8, 0x9


def frame(opcode, payload=b"", final=True, mask=True):
    """Build a client frame. Clients must mask, so that is the default."""
    head = bytearray([(0x80 if final else 0) | opcode])
    size = len(payload)
    if size < 126:
        head.append((0x80 if mask else 0) | size)
    elif size < 65536:
        head.append((0x80 if mask else 0) | 126)
        head += struct.pack("!H", size)
    else:
        head.append((0x80 if mask else 0) | 127)
        head += struct.pack("!Q", size)
    if mask:
        key = os.urandom(4)
        head += key
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return bytes(head) + payload


class Client:
    """A tiny WebSocket client, so the server is tested the way it is used."""

    def __init__(self, port, path="/ws"):
        self.socket = socket.create_connection(("127.0.0.1", port), timeout=5)
        key = base64.b64encode(os.urandom(16)).decode()
        self.socket.sendall(
            f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        self.buffer = b""
        while b"\r\n\r\n" not in self.buffer:
            self.buffer += self.socket.recv(4096)
        head, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
        self.head = head
        self.status = head.split(b"\r\n")[0]
        self.key = key

    def read(self, size):
        while len(self.buffer) < size:
            chunk = self.socket.recv(4096)
            if not chunk:
                break
            self.buffer += chunk
        out, self.buffer = self.buffer[:size], self.buffer[size:]
        return out

    def send(self, message, opcode=TEXT, final=True):
        payload = message.encode() if isinstance(message, str) else message
        self.socket.sendall(frame(opcode, payload, final))

    def receive(self):
        head = self.read(2)
        if not head:
            return None
        opcode = head[0] & 0x0F
        size = head[1] & 0x7F
        if size == 126:
            size = struct.unpack("!H", self.read(2))[0]
        elif size == 127:
            size = struct.unpack("!Q", self.read(8))[0]
        payload = self.read(size)
        return opcode, (payload.decode("utf-8", "replace") if opcode == TEXT else payload)

    def close(self):
        self.socket.close()


@pytest.fixture
def serve():
    app.routes.clear()
    app.sockets.clear()

    @app.websocket("/ws")
    def chat(connection):
        while True:
            message = connection.receive()
            if message is None:
                return
            connection.send(f"echo: {message}" if isinstance(message, str) else message[::-1])

    @app.websocket("/ws/room/<room>")
    def room(connection, room):
        connection.send_json({"room": room})

    @app.websocket("/ws/boom")
    def boom(connection):
        raise ValueError("boom")

    @app.websocket("/ws/json")
    def json_socket(connection):
        connection.send_json({"hello": ["world", 1]})

    @app.route("/")
    def home():
        return {"message": "Hello World"}

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(app.handle, app.handle_socket))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()
    app.routes.clear()
    app.sockets.clear()


def test_the_handshake_answers_with_the_accept_key(serve):
    client = Client(serve)
    try:
        assert client.status == b"HTTP/1.1 101 Switching Protocols"
        assert f"Sec-WebSocket-Accept: {accept_key(client.key)}".encode() in client.head
    finally:
        client.close()


def test_text_round_trip(serve):
    client = Client(serve)
    try:
        client.send("hello")
        assert client.receive() == (TEXT, "echo: hello")
    finally:
        client.close()


def test_binary_round_trip(serve):
    client = Client(serve)
    try:
        client.send(b"\x00\x01\x02", opcode=BINARY)
        assert client.receive() == (BINARY, b"\x02\x01\x00")
    finally:
        client.close()


def test_a_long_message_uses_the_wider_length(serve):
    client = Client(serve)
    try:
        client.send("x" * 5000)
        assert client.receive()[1] == "echo: " + "x" * 5000
    finally:
        client.close()


def test_fragments_are_rejoined(serve):
    client = Client(serve)
    try:
        client.send("one ", final=False)
        client.send("two ", opcode=0x0, final=False)
        client.send("three", opcode=0x0, final=True)
        assert client.receive()[1] == "echo: one two three"
    finally:
        client.close()


def test_a_ping_is_answered_with_a_pong(serve):
    client = Client(serve)
    try:
        client.send(b"ping me", opcode=PING)
        assert client.receive()[0] == 0xA
    finally:
        client.close()


def test_closing_ends_the_handler(serve):
    client = Client(serve)
    try:
        client.send(b"", opcode=CLOSE)
        assert client.receive()[0] == CLOSE
    finally:
        client.close()


def test_a_path_parameter_reaches_the_handler(serve):
    client = Client(serve, "/ws/room/lobby")
    try:
        assert client.receive()[1] == '{"room": "lobby"}'
    finally:
        client.close()


def test_json_is_sent_as_text(serve):
    client = Client(serve, "/ws/json")
    try:
        opcode, payload = client.receive()
        assert (opcode, loads(payload)) == (TEXT, {"hello": ["world", 1]})
    finally:
        client.close()


def test_a_broken_handler_does_not_take_the_server_down(serve):
    client = Client(serve, "/ws/boom")
    try:
        assert client.receive()[0] == CLOSE
        second = Client(serve)
        second.send("still here")
        assert second.receive()[1] == "echo: still here"
        second.close()
    finally:
        client.close()


def test_an_unknown_socket_path_is_an_http_404(serve):
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", serve, timeout=5)
    connection.request(
        "GET",
        "/nope",
        headers={"Upgrade": "websocket", "Connection": "Upgrade", "Sec-WebSocket-Key": "x"},
    )
    response = connection.getresponse()
    body = response.read()
    connection.close()

    assert response.status == 404
    assert loads(body) == {"error": "Not found"}


def test_normal_requests_still_work(serve):
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", serve, timeout=5)
    connection.request("GET", "/")
    response = connection.getresponse()
    body = response.read()
    connection.close()

    assert loads(body) == {"message": "Hello World"}


def test_accept_key_is_the_sha1_of_key_plus_guid():
    assert accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def test_guid_is_the_rfc_value():
    assert GUID == "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
