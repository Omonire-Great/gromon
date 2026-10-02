"""Testing an application without a socket.

    with app.test_client() as client:
        assert client.get("/").json == {"message": "Hello World"}

The client calls the same handle() the server does, and keeps cookies between
calls, so a login in one call is a session in the next.
"""

from http.cookies import SimpleCookie
from json import loads


class Response:
    """What a call gave back, in the shape Flask's test response uses."""

    __slots__ = ("data", "headers", "status_code")

    def __init__(self, status_code, headers, data):
        self.status_code = status_code
        self.headers = headers
        self.data = data

    @property
    def text(self):
        """The body as text."""
        return self.data.decode("utf-8", "replace")

    @property
    def json(self):
        """The body parsed as JSON."""
        return loads(self.data)

    def get_header(self, name, default=None):
        """One header, whatever case it was sent in."""
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return default

    def __repr__(self):
        return f"<Response {self.status_code}>"


class Client:
    """Calls an App the way a browser would, with a cookie jar."""

    def __init__(self, app):
        self.app = app
        self.cookies = {}

    def open(self, path="/", method="GET", data=None, headers=None, query=None, json=None):
        """Make one call and return the Response."""
        if query:
            from urllib.parse import urlencode

            path = f"{path}{'&' if '?' in path else '?'}{urlencode(query)}"

        headers = dict(headers or {})
        # HTTP/1.1 requires Host on every request, and without it TRUSTED_HOSTS
        # rejects the call as 400 even though a real client would have sent one.
        headers.setdefault("Host", "127.0.0.1")
        if json is not None:
            from json import dumps

            data = dumps(json)
            headers.setdefault("Content-Type", "application/json")
        elif isinstance(data, str):
            data = data.encode()
        if data is not None and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())

        from .http import Request

        request = Request(method, path, headers, data or b"", client="127.0.0.1")
        status, kind, body, sent = self.app.handle(request)

        if not isinstance(body, (bytes, bytearray)):
            # a streamed body is read to the end, like a browser would
            body = b"".join(
                chunk.encode() if isinstance(chunk, str) else chunk for chunk in body
            )

        for name, value in sent.items():
            if name.lower() == "set-cookie":
                self._store(value)

        merged = {"Content-Type": kind, **sent}
        return Response(status, merged, b"" if method == "HEAD" else body)

    def get(self, path="/", **kwargs):
        return self.open(path, "GET", **kwargs)

    def post(self, path="/", **kwargs):
        return self.open(path, "POST", **kwargs)

    def put(self, path="/", **kwargs):
        return self.open(path, "PUT", **kwargs)

    def patch(self, path="/", **kwargs):
        return self.open(path, "PATCH", **kwargs)

    def delete(self, path="/", **kwargs):
        return self.open(path, "DELETE", **kwargs)

    def head(self, path="/", **kwargs):
        return self.open(path, "HEAD", **kwargs)

    def _store(self, header):
        """Remember a Set-Cookie, and forget it when it expires."""
        jar = SimpleCookie()
        jar.load(header)
        for name, morsel in jar.items():
            if morsel["max-age"] == "0" or morsel.value == "":
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = morsel.value

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
