"""Gromon - build Python applications with less code.

    from gromon import route, run

    @route("/")
    def home():
        return {"message": "Hello World"}

    run()
"""

from importlib import metadata as _metadata

from . import auth, limiter, payment
from .app import (
    App,
    Blueprint,
    Config,
    abort,
    after,
    error,
    redirect,
    register,
    render,
    route,
    run,
    static,
    teardown,
    url_defaults,
    url_for,
    use,
    websocket,
)
from .auth import session
from .context import request
from .errors import HTTPError
from .helpers import flash, get_flashed_messages, safe_join, send_file
from .http import Request
from .response import JSON
from .views import MethodView
from .wsgi import wsgi

try:
    __version__ = _metadata.version("gromon")
except _metadata.PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "JSON",
    "App",
    "Blueprint",
    "Config",
    "HTTPError",
    "MethodView",
    "Request",
    "__version__",
    "abort",
    "after",
    "auth",
    "error",
    "flash",
    "get_flashed_messages",
    "limiter",
    "payment",
    "redirect",
    "register",
    "render",
    "request",
    "route",
    "run",
    "safe_join",
    "send_file",
    "session",
    "static",
    "teardown",
    "url_defaults",
    "url_for",
    "use",
    "websocket",
    "wsgi",
]
