"""WebSocket: the part of RFC 6455 that a chat needs.

    from gromon import websocket

    @websocket("/ws")
    def chat(connection):
        while True:
            message = connection.receive()
            if message is None:
                return
            connection.send(f"you said: {message}")

Text and binary messages, ping/pong, close, and fragments. No extensions, and
one thread per connection.
"""

import base64
import struct
from hashlib import sha1
from json import dumps

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

TEXT, BINARY, CLOSE, PING, PONG = 0x1, 0x2, 0x8, 0x9, 0xA


def accept_key(key):
    """The Sec-WebSocket-Accept value that answers a client key."""
    return base64.b64encode(sha1((key + GUID).encode()).digest()).decode()


class Connection:
    """One live WebSocket. A handler gets one and talks until it closes."""

    def __init__(self, handler):
        self.handler = handler
        self.open = True

    def accept(self):
        """Complete the handshake."""
        key = self.handler.headers.get("Sec-WebSocket-Key", "")
        self.handler.wfile.write(
            f"HTTP/1.1 101 Switching Protocols\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key(key)}\r\n"
            f"\r\n".encode()
        )
        self.handler.wfile.flush()

    def send(self, message):
        """Send a str as text, or bytes as binary."""
        if isinstance(message, bytes):
            self._frame(BINARY, message)
        else:
            self._frame(TEXT, str(message).encode())

    def send_json(self, data):
        """Send any JSON serialisable value."""
        self.send(dumps(data))

    def close(self, code=1000, reason=""):
        """Say goodbye, once."""
        if self.open:
            self._frame(CLOSE, struct.pack("!H", code) + reason.encode())
            self.open = False

    def receive(self):
        """Block for the next message: str for text, bytes for binary.

        Returns None once the other side has closed.
        """
        parts, text = [], None

        while True:
            header = self._read(2)
            if not header:
                self.open = False
                return None

            final, opcode = bool(header[0] & 0x80), header[0] & 0x0F
            payload = self._payload(header[1])

            if opcode == CLOSE:
                self.close()
                return None
            if opcode == PING:
                self._frame(PONG, payload)
                continue
            if opcode == PONG:
                continue

            if opcode:
                parts, text = [], opcode == TEXT
            parts.append(payload)
            if final:
                message = b"".join(parts)
                return message.decode("utf-8", "replace") if text else message

    def _frame(self, opcode, payload):
        """Write one unmasked frame, with the shortest length that fits."""
        header = bytearray([0x80 | opcode])
        size = len(payload)

        if size < 126:
            header.append(size)
        elif size < 65536:
            header.append(126)
            header += struct.pack("!H", size)
        else:
            header.append(127)
            header += struct.pack("!Q", size)

        self.handler.wfile.write(bytes(header) + payload)
        self.handler.wfile.flush()

    def _payload(self, second):
        """Read one frame payload, undoing the client mask if there is one."""
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read(8))[0]

        mask = self._read(4) if second & 0x80 else b""
        payload = self._read(length)
        if mask:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return payload

    def _read(self, size):
        """Read exactly size bytes, or fewer if the client has hung up."""
        return self.handler.rfile.read(size) or b""
