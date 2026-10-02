"""The HTTP server, built on the standard library.

serve(handle, upgrade, host, port) works with any callable that takes a Request
and returns (status, content_type, body), so the server knows nothing about App.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .http import Request
from .websocket import Connection


def handler_for(handle, upgrade=None):
    """Build a request handler class that sends every request to handle()."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def respond(self):
            length = int(self.headers.get("Content-Length") or 0)
            request = Request(
                self.command, self.path, self.headers, self.rfile.read(length), self.client_address[0]
            )
            if self._upgrades(request, upgrade):
                self.close_connection = True
                return
            status, kind, body, headers = handle(request)
            streamed = not isinstance(body, (bytes, bytearray))
            self.send_response(status)
            self.send_header("Content-Type", kind)
            if streamed:
                self.send_header("Transfer-Encoding", "chunked")
            else:
                self.send_header("Content-Length", str(len(body)))
            for name, value in headers.items():
                self.send_header(name, value)
            self.end_headers()

            if self.command == "HEAD":
                return
            if streamed:
                for chunk in body:
                    piece = chunk.encode() if isinstance(chunk, str) else chunk
                    self.wfile.write(b"%x\r\n%s\r\n" % (len(piece), piece))
                self.wfile.write(b"0\r\n\r\n")
            else:
                self.wfile.write(body)

        def _upgrades(self, request, upgrade):
            """True when a WebSocket handler took the connection over."""
            if upgrade is None or "websocket" not in (self.headers.get("Upgrade") or "").lower():
                return False
            return upgrade(request, Connection(self))

    Handler.do_GET = Handler.do_HEAD = Handler.do_POST = Handler.do_PUT = (
        Handler.do_PATCH
    ) = Handler.do_DELETE = Handler.do_OPTIONS = Handler.respond

    return Handler


def serve(handle, upgrade=None, host="127.0.0.1", port=8000):
    """Serve forever with handle(request). Ctrl+C to stop."""
    server = ThreadingHTTPServer((host, port), handler_for(handle, upgrade))
    print(f"Gromon running on http://{host}:{port}", flush=True)  # flushed: logs are files too
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
