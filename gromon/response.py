"""A handler's return value becomes the HTTP response.

    dict / list                 -> application/json
    str                         -> text/html
    bytes                       -> application/octet-stream
    None                        -> 204, empty
    (value, 201)                -> ... with a status code
    (value, 201, "image/png")   -> ... and a content type
    (value, 201, "image/png", {"Cache-Control": "max-age=60"})  -> ... and headers

make_response turns any of those into (status, content_type, body, headers).
"""

from collections.abc import Iterator
from json import dumps, loads


class JSON:
    """How Python values become JSON. Replace `app.json` to change the format.

        app.json = JSON(indent=4)

    `pretty` is set for you when DEBUG or TESTING is on, so a failing test shows
    a body you can read.
    """

    def __init__(self, indent=None, sort_keys=False, separators=None):
        self.indent, self.sort_keys, self.pretty = indent, sort_keys, False
        self.separators = separators or (", ", ": ")

    def dumps(self, value):
        """The JSON text for a value."""
        if self.pretty or self.indent:
            return dumps(value, indent=self.indent or 2, sort_keys=self.sort_keys)
        return dumps(value, separators=self.separators, sort_keys=self.sort_keys)

    def loads(self, text):
        """A value from JSON text."""
        return loads(text)


def make_response(value, json=None):
    """Turn a return value into (status, content_type, body, headers)."""
    kind, status, headers, rest = None, 200, {}, []
    if isinstance(value, tuple):
        value, *rest = value
        status = rest[0] if rest else status
        kind = rest[1] if len(rest) > 1 else kind
        headers = rest[2] if len(rest) > 2 else headers

    if value is None:
        # a bare None means "no content", but an explicit status is respected
        return (status if rest else 204), kind or "text/plain", b"", headers

    if isinstance(value, (dict, list)):
        body, kind = (json or JSON()).dumps(value).encode(), kind or "application/json"
    elif isinstance(value, bytes):
        body, kind = value, kind or "application/octet-stream"
    elif isinstance(value, Iterator):
        return status, kind or "text/plain; charset=utf-8", value, headers
    else:
        body, kind = str(value).encode(), kind or "text/html; charset=utf-8"

    return status, kind, body, headers
