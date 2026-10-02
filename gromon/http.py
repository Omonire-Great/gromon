from json import loads
from urllib.parse import parse_qs, unquote, urlsplit

from .errors import HTTPError


class Request:
    """The incoming request. Handlers that ask for it get one for free."""

    __slots__ = (
        "_files",
        "_form",
        "body",
        "client",
        "cookies",
        "endpoint",
        "headers",
        "limits",
        "loaded_session",
        "method",
        "path",
        "query",
        "scheme",
        "session",
    )

    def __init__(self, method, target, headers, body, client=""):
        parts = urlsplit(target)
        self.method = method
        self.path = unquote(parts.path) or "/"
        self.query = {key: value[0] for key, value in parse_qs(parts.query).items()}
        self.headers = headers
        self.body = body
        self.client = client
        self.session = {}
        self.loaded_session = None
        self.endpoint = None
        self.scheme = "http"
        self.cookies = _cookies(headers.get("Cookie", ""))
        self._form, self._files = None, None
        self.limits = None

    def json(self):
        """Parse the body as JSON."""
        return loads(self.body)

    @property
    def form(self):
        """The form fields. Reading it parses the body, once."""
        if self._form is None:
            self.parse_form()
        return self._form

    @property
    def files(self):
        """The uploaded files. Reading it parses the body, once."""
        if self._files is None:
            self.parse_form()
        return self._files

    def values(self):
        """Query and form together, for handlers that accept either."""
        return {**self.query, **self.form}

    def parse_form(self):
        """Fill `form` and `files` from an urlencoded or multipart body."""
        self._form, self._files = {}, {}
        kind = self.headers.get("Content-Type", "")
        if kind.startswith("application/x-www-form-urlencoded"):
            self._form = {
                key: value[0] for key, value in parse_qs(self.body.decode()).items()
            }
        elif kind.startswith("multipart/form-data"):
            _parse_multipart(self, kind)
        return self._form


def _cookies(header):
    """'a=1; b=2' -> {'a': '1', 'b': '2'}"""
    jar = {}
    for part in header.split(";"):
        key, _, value = part.strip().partition("=")
        if key:
            jar[key] = value
    return jar


def _parse_multipart(request, kind):
    """Fill request.form and request.files from a multipart body."""
    boundary = kind.split("boundary=")[-1].strip('"')
    marker = f"--{boundary}".encode()
    fields = 0

    for part in request.body.split(marker):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        fields += 1
        if fields > _limit(request, "MAX_FORM_PARTS", 1_000):
            raise HTTPError(413, "Too many form parts")
        head, _, content = part.partition(b"\r\n\r\n")
        headers = {}
        for line in head.split(b"\r\n"):
            key, _, value = line.decode(errors="replace").partition(":")
            headers[key.strip().lower()] = value.strip()
        disposition = headers.get("content-disposition", "")
        name = _between(disposition, 'name="')
        if not name:
            continue
        filename = _between(disposition, 'filename="')
        if filename:
            request.files[name] = {
                "filename": filename,
                "content_type": headers.get("content-type", "application/octet-stream"),
                "data": content,
            }
        else:
            request.form[name] = content.decode(errors="replace")

    if len(request.form) and sum(len(v) for v in request.form.values()) > _limit(
        request, "MAX_FORM_MEMORY_SIZE", 500_000
    ):
        raise HTTPError(413, "Form too large")


def _limit(request, key, fallback):
    """A limit from the config the app left on the request, or the default."""
    limits = request.limits or {}
    return limits.get(key) or fallback


def _between(text, marker):
    """The quoted part of a header value, '' when it is not there."""
    _, _, rest = text.partition(marker)
    return rest.split('"')[0] if rest else ""
