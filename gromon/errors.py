"""The one exception Gromon gives you."""

STATUSES = {
    400: "Bad request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not found",
    405: "Method not allowed",
    409: "Conflict",
    410: "Gone",
    413: "Payload too large",
    415: "Unsupported media type",
    418: "I'm a teapot",
    422: "Unprocessable entity",
    429: "Too many requests",
    500: "Internal server error",
    501: "Not implemented",
    503: "Service unavailable",
}


class HTTPError(Exception):
    """Raise inside a handler to send an error response.

        raise HTTPError(404, "User not found")
    """

    def __init__(self, status=500, message=None):
        message = message if message is not None else STATUSES.get(status, "Error")
        super().__init__(f"{status} {message}")
        self.status = status
        self.message = message
