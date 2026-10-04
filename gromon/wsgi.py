"""Running a Gromon app under any WSGI server.

Gromon serves itself through gromon/server.py, which is fine while you are
writing. To put it in front of real traffic you want a WSGI server such as
gunicorn, uWSGI or waitress, and that needs an `application` callable:

    # wsgi.py
    from app import app
    from gromon import wsgi

    application = wsgi(app)

    gunicorn wsgi:application

`app.wsgi` does the same thing in one line:

    from app import app

    application = app.wsgi

WebSocket routes do not come through here. WSGI has no way to take a connection
over for an upgrade, so serve those from gromon's own server instead.
"""

from http import HTTPStatus

from .http import Request

HOP_BY_HOP = (
    "connection",
    "content-length",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
)


def wsgi(app):
    """Wrap an App as a WSGI `application` callable."""

    def application(environ, start_response):
        request = build(environ)
        status, kind, body, headers = app.handle(request)

        sent = [("Content-Type", kind)]
        sent += [(name, str(value)) for name, value in headers.items()]
        sent = [(name, value) for name, value in sent if name.lower() not in HOP_BY_HOP]

        start_response(f"{status} {reason(status)}", sent)

        if environ["REQUEST_METHOD"] == "HEAD":
            return []
        if isinstance(body, (bytes, bytearray)):
            return [bytes(body)]
        return body

    return application


def build(environ):
    """Turn a WSGI environ into the Request the app expects."""
    target = environ.get("PATH_INFO", "/") or "/"
    if environ.get("QUERY_STRING"):
        target = f"{target}?{environ['QUERY_STRING']}"

    length = int(environ.get("CONTENT_LENGTH") or 0)
    body = b""
    if length:
        # Only read when CONTENT_LENGTH says there is a body: a GET leaves
        # wsgi.input sitting on the socket, and read() would wait for a close
        # that is never coming.
        body = environ["wsgi.input"].read(length)

    headers = {}
    for name, value in environ.items():
        if name.startswith("HTTP_"):
            headers[name[5:].replace("_", "-").title()] = value
    if environ.get("CONTENT_TYPE"):
        headers["Content-Type"] = environ["CONTENT_TYPE"]
    if length:
        headers["Content-Length"] = str(length)

    request = Request(
        environ.get("REQUEST_METHOD", "GET"),
        target,
        headers,
        body,
        environ.get("REMOTE_ADDR", ""),
    )
    request.scheme = environ.get("wsgi.url_scheme", "http")
    return request


def reason(status):
    """'200' -> 'OK', for the status line a WSGI server writes."""
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "Unknown"
