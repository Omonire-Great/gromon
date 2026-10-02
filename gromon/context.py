"""The request being handled right now, on this thread.

Flask keeps this in a context so `url_for` and friends can find it. Ours is one
thread local and a proxy, which is all a threaded server needs.
"""

from threading import local

_state = local()


def current():
    """The Request being handled on this thread, or None."""
    return getattr(_state, "request", None)


def current_app():
    """The App handling this request, or None."""
    return getattr(_state, "app", None)


def push(request, app=None):
    """Make this request the current one, remembering the one before it."""
    previous = current()
    _state.request = request
    _state.app = app if app is not None else getattr(request, "app", None)
    return previous


def pop():
    """Forget the current request."""
    _state.request = None
    _state.app = None


def url_root():
    """'http://127.0.0.1:8000' for the request being handled, '' outside one."""
    request = current()
    if request is None:
        return ""
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    return f"{scheme}://{request.headers.get('Host', 'localhost')}"


class _Proxy:
    """Forwards attribute access to the request being handled."""

    __slots__ = ()

    def __getattr__(self, name):
        request = current()
        if request is None:
            raise RuntimeError("Working outside of a request: no request on this thread")
        return getattr(request, name)

    def __repr__(self):
        return repr(current())


request = _Proxy()
