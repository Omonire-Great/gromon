"""The application: routes, middleware, error handlers, static files.

Most applications never build an App. They use the functions in gromon:
route, use, error, static, register, render, run.
"""

import os
import traceback
from collections.abc import Iterator
from inspect import signature
from pathlib import Path

from .context import current_app
from .context import pop as pop_context
from .context import push as push_context
from .errors import STATUSES, HTTPError
from .helpers import safe_join, send_file
from .response import JSON, make_response
from .router import allow, build, compile_path, match
from .templates import render as render_template


def bind(handler, name="request"):
    """Wrap a handler so it receives exactly what it declares by name.

    The names it declares decide what it gets: the object (`request`, or
    `connection` for a socket), any route parameters such as `id`, or the
    `error` of an error handler. A handler taking `**kwargs` gets everything.
    """
    parameters = signature(handler).parameters
    names = set(parameters)
    takes_anything = any(
        parameter.kind is parameter.VAR_KEYWORD for parameter in parameters.values()
    )

    def call(context, params):
        arguments = dict(params) if takes_anything else {
            key: value for key, value in params.items() if key in names
        }
        if name in parameters:
            arguments[name] = context
        return handler(**arguments)

    return call


def allowed_methods(methods):
    """Uppercase, and GET answers HEAD as well."""
    allowed = {method.upper() for method in methods}
    if "GET" in allowed:
        allowed.add("HEAD")
    return allowed


def _answers(methods, wanted):
    """True when a rule's methods cover the verb being asked about."""
    return wanted in methods or (wanted == "HEAD" and "GET" in methods)


def add_route(routes, path, handler, methods, prefix="", name="request", endpoint=None):
    """Append one compiled route to a route list."""
    template = prefix + path
    routes.append(
        (
            compile_path(template),
            bind(handler, name),
            allowed_methods(methods),
            endpoint or handler.__name__,
            template,
        )
    )
    return handler


class Config(dict):
    """The settings an app reads, plus ways to load them.

        app.config.from_envvar("GROMON_SETTINGS")
        app.config.from_object(settings)

    Keys come out of the environment as `GROMON_DEBUG=1`, and `__` nests:
    `GROMON_MAIL__HOST=...` gives `config["MAIL"]["host"]`.
    """

    def __init__(self, defaults=None):
        super().__init__(defaults or {})

    def from_object(self, obj):
        """Take every UPPERCASE name from an object, module or dotted path."""
        if isinstance(obj, str):
            from importlib import import_module

            obj = import_module(obj)
        for key in dir(obj):
            if key.isupper():
                self[key] = getattr(obj, key)
        return True

    def from_mapping(self, mapping=None, **kwargs):
        """Take the UPPERCASE keys from a dict."""
        for source in (mapping or {}, kwargs):
            for key, value in source.items():
                if key.isupper():
                    self[key] = value
        return True

    def from_envvar(self, variable, silent=False):
        """Load a .py settings file named by an environment variable."""
        import os

        target = os.environ.get(variable)
        if not target:
            if not silent:
                raise RuntimeError(f"{variable} is not set, so settings were not loaded")
            return False
        return self.from_pyfile(target)

    def from_pyfile(self, filename, silent=False):
        """Run a .py file and take its UPPERCASE names."""

        try:
            text = Path(filename).read_text()
        except OSError:
            if not silent:
                raise
            return False
        return self.from_namespace({"__file__": str(filename)}, text)

    def from_file(self, filename, load, silent=False):
        """Load settings from a file with the loader you give: json.load, yaml."""

        try:
            with Path(filename).open() as handle:
                return self.from_mapping(load(handle))
        except OSError:
            if not silent:
                raise
            return False

    def from_env(self, prefix="GROMON_", loads=None):
        """Take settings from the environment: GROMON_DEBUG=1, GROMON_X__Y=2."""
        import os
        from json import loads as json_loads

        loads = loads or json_loads
        prefix = prefix.rstrip("_") + "_"
        for name in sorted(os.environ):
            if not name.startswith(prefix):
                continue
            value = os.environ[name]
            try:
                value = loads(value)
            except ValueError:
                pass  # not JSON, keep it as the string it is
            key = name[len(prefix) :]
            if "__" not in key:
                self[key] = value
                continue
            *parts, tail = key.split("__")
            here = self
            for part in parts:
                here = here.setdefault(part, {})
            here[tail] = value
        return True

    def from_namespace(self, namespace, text):
        """Execute settings text as if it were a module."""
        exec(compile(text, namespace.get("__file__", "<settings>"), "exec"), namespace)
        return self.from_object(type("Settings", (), namespace))


class Blueprint:
    """A named group of routes under a prefix.

        admin = Blueprint("admin", "/admin")

        @admin.route("/users")
        def users():
            return []

        register(admin)
    """

    def __init__(self, name, prefix=""):
        self.name = name
        self.prefix = prefix
        self.routes = []
        self.middlewares = []
        self.on_response = []
        self.teardowns = []
        self.defaults = []

    def route(self, path, methods=None, endpoint=None):
        """Register a handler: @admin.route("/users")

        A MethodView class is asked which verbs it has, and a fresh instance
        handles each request, exactly as on an App.
        """

        def register(handler):
            from .views import verbs, view_for

            allowed = methods
            if isinstance(handler, type):
                allowed = methods or verbs(handler)
                handler = view_for(handler)
            return add_route(
                self.routes,
                path,
                handler,
                allowed or ("GET",),
                self.prefix,
                endpoint=f"{self.name}.{endpoint or handler.__name__}",
            )

        return register

    def use(self, middleware):
        """Add middleware. It runs for every request, like Flask's before_request.

        Use `after` instead when a hook should stay inside this blueprint.
        """
        self.middlewares.append(middleware)
        return middleware

    def after(self, callback):
        """Add a fn(request, headers) for this blueprint's responses."""
        self.on_response.append((self.name, callback))
        return callback

    def teardown(self, callback):
        """Add fn(request) to run after every response."""
        self.teardowns.append(callback)
        return callback

    def url_defaults(self, callback):
        """Add fn(endpoint, values) to fill in url_for arguments."""
        self.defaults.append((self.name, callback))
        return callback

    def register(self, blueprint):
        """Mount another blueprint under this one's prefix and name."""
        for _, handler, methods, endpoint, template in blueprint.routes:
            template = self.prefix + template
            self.routes.append(
                (
                    compile_path(template),
                    handler,
                    methods,
                    self.under(blueprint.name, endpoint),
                    template,
                )
            )
        self.middlewares.extend(blueprint.middlewares)
        self.on_response.extend(
            (self.under(blueprint.name, owner), callback)
            for owner, callback in blueprint.on_response
            if owner
        )
        self.teardowns.extend(blueprint.teardowns)
        self.defaults.extend(
            (self.under(blueprint.name, owner), callback)
            for owner, callback in blueprint.defaults
        )
        return self

    def under(self, name, endpoint):
        """A child's endpoint becomes 'parent.child', Flask's way."""
        return f"{self.name}.{endpoint}"


class App:
    """One application. Use the gromon functions unless you need a second one."""

    def __init__(self, static_folder="static", template_folder="templates"):
        self.routes = []
        self.sockets = []
        self.middlewares = []
        self.errors = {}
        self.on_response = []
        self.teardowns = []
        self.defaults = []
        self.static_folder = static_folder
        self.template_folder = template_folder
        self.json = JSON()
        self.config = Config(
            dict(
                DEBUG=False,
                TESTING=False,
                TRUSTED_HOSTS=None,
                MAX_CONTENT_LENGTH=32 * 1024 * 1024,
                MAX_FORM_MEMORY_SIZE=500_000,
                MAX_FORM_PARTS=1_000,
                SESSION_COOKIE_NAME="session",
                SESSION_COOKIE_PATH="/",
                SESSION_COOKIE_HTTPONLY=True,
                SESSION_COOKIE_SAMESITE="Lax",
                SESSION_COOKIE_SECURE=False,
                PERMANENT_SESSION_LIFETIME=30 * 24 * 60 * 60,
            )
        )

    def routes_table(self):
        """The routes as a table: the way `gromon routes` prints them."""
        lines = [f"{'METHODS':14}{'PATH':44}ENDPOINT"]
        for _, _, methods, endpoint, template in self.routes:
            lines.append(f"{','.join(sorted(methods)):14}{template:44}{endpoint}")
        return "\n".join(lines)

    def route(self, path, methods=None, endpoint=None):
        """Register a handler: @route("/user/<int:id>"), or a MethodView class.

        Methods default to GET, or to the verbs a MethodView subclass writes.
        """

        def register(handler):
            from .views import verbs, view_for

            allowed = methods
            if isinstance(handler, type):
                allowed = methods or verbs(handler)
                handler = view_for(handler)
            return add_route(self.routes, path, handler, allowed or ("GET",), endpoint=endpoint)

        return register

    def websocket(self, path, endpoint=None):
        """Register a socket handler: @websocket("/ws")"""

        def register(handler):
            return add_route(
                self.sockets, path, handler, ("GET",), name="connection", endpoint=endpoint
            )

        return register

    def use(self, middleware):
        """Add middleware: fn(request) -> None to continue, or a response to stop."""
        self.middlewares.append(middleware)
        return middleware

    def error(self, status):
        """Register an error handler: @error(404)"""

        def register(handler):
            self.errors[status] = bind(handler)
            return handler

        return register

    def register(self, blueprint):
        """Mount a blueprint: its routes, middleware, hooks and teardowns."""
        self.routes.extend(blueprint.routes)
        self.middlewares.extend(blueprint.middlewares)
        self.on_response.extend(blueprint.on_response)
        self.teardowns.extend(bind(teardown) for teardown in blueprint.teardowns)
        self.defaults.extend(blueprint.defaults)
        return blueprint

    def url_for(self, endpoint, _external=False, _anchor=None, _method=None, **values):
        """The path for an endpoint: url_for("user", id=7) -> '/user/7'.

        Values the rule does not name become a query string. `_external=True`
        gives a full URL, `_anchor="top"` adds a fragment, and `_method="delete"`
        picks the other rule registered for that endpoint:

            @route("/users/<int:id>")
            @route("/users/<int:id>/delete", methods=["DELETE"])
            def user(id):
                ...

        `@url_defaults` gets to fill in whatever the rule needs that you did not
        pass.
        """
        wanted, found = None, None
        if _method:
            wanted = _method.upper()

        for _pattern, _handler, methods, name, template in self.routes:
            if name != endpoint:
                continue
            if wanted and not _answers(methods, wanted):
                if found is None:
                    found = template
                continue
            for owner, callback in self.defaults:
                if not owner or endpoint.startswith(f"{owner}."):
                    callback(endpoint, values)
            return build(template, values, _external, _anchor)

        if wanted:
            raise HTTPError(
                500, f"No route named {endpoint!r} answers {wanted}, only {found or endpoint}"
            )
        raise HTTPError(500, f"No route named {endpoint!r}")

    def teardown(self, callback):
        """Add fn(request) to run after every response, streaming included.

        This is where a database connection or a file handle goes back:

            @teardown
            def close(request):
                request.db.close()
        """
        self.teardowns.append(bind(callback))
        return callback

    def url_defaults(self, callback):
        """Add fn(endpoint, values) that can fill in url_for arguments.

            @url_defaults
            def language(endpoint, values):
                values.setdefault("lang", request.query.get("lang", "en"))
        """
        self.defaults.append(("", callback))
        return callback

    def redirect(self, location, status=302):
        """The classic 'go elsewhere' response."""
        return "", status, "text/html", {"Location": location}

    def abort(self, status, message=None):
        """Stop here: abort(404) or abort(403, 'Not for you')."""
        raise HTTPError(status, message or STATUSES.get(status, "Error"))

    def static(self, folder=None, prefix="/static"):
        """Serve a folder of files, ./static by default. Call it once: static()"""
        folder = folder or self.static_folder

        @self.route(f"{prefix}/<path:path>")
        def serve(path):
            return send_file(safe_join(folder, path), max_age=self.config.get("STATIC_MAX_AGE"))

        return serve

    def render(self, template, **context):
        """Render a Jinja2 template. Needs pip install gromon[templates]."""
        return render_template(template, folder=self.template_folder, **context)

    def after(self, callback):
        """Add a fn(request, headers) that can add response headers: @after

        A blueprint's version runs only for that blueprint's own routes.
        """
        self.on_response.append(("", callback))
        return callback

    def test_client(self):
        """A client for testing this application, no socket involved."""
        from .testing import Client

        return Client(self)

    @property
    def wsgi(self):
        """This app as a WSGI application, for gunicorn, uWSGI or waitress.

            application = app.wsgi
            gunicorn wsgi:application
        """
        from .wsgi import wsgi

        return wsgi(self)

    def openapi(self, title="API", version="1.0.0"):
        """An OpenAPI 3.1 document describing every route this app answers."""
        from .openapi import document

        return document(self, title, version)

    def handle(self, request):
        """Turn a Request into a (status, content_type, body, headers) response."""
        push_context(request, self)
        try:
            try:
                response = self.dispatch(request)
            except HTTPError as error:
                response = self.error_response(error, request)
            except Exception:
                traceback.print_exc()
                response = self.error_response(HTTPError(500), request)
            return self.settle(self.finish(self.live(response, request), request), request)
        finally:
            pop_context()

    def dispatch(self, request):
        """Middleware, then the route. Raises HTTPError when nothing answers."""
        self.json.pretty = bool(self.config["DEBUG"] or self.config["TESTING"])
        request.limits = {
            "MAX_FORM_PARTS": self.config["MAX_FORM_PARTS"],
            "MAX_FORM_MEMORY_SIZE": self.config["MAX_FORM_MEMORY_SIZE"],
        }
        limit = self.config["MAX_CONTENT_LENGTH"]
        if limit and len(request.body) > limit:
            raise HTTPError(413, "Request body too large")

        trusted = self.config["TRUSTED_HOSTS"]
        if trusted and request.headers.get("Host", "").split(":")[0] not in trusted:
            raise HTTPError(400, "Host not trusted")

        for middleware in self.middlewares:
            value = middleware(request)
            if value is not None:
                return make_response(value, self.json)

        try:
            handler, params, endpoint = match(self.routes, request.path, request.method)
        except HTTPError as error:
            allowed = (
                allow(self.routes, request.path)
                if error.status == 405 and request.method == "OPTIONS"
                else set()
            )
            if not allowed:
                raise
            methods = ", ".join(sorted(allowed | {"OPTIONS"}))
            return 200, "text/plain", b"", {"Allow": methods}

        request.endpoint = endpoint
        return make_response(handler(request, params), self.json)

    def live(self, response, request):
        """Keep the request readable while a generator body is being written."""
        if not isinstance(response[2], Iterator):
            return response
        status, kind, body, headers = response

        def chunks():
            push_context(request, self)
            try:
                yield from body
            finally:
                pop_context()

        return status, kind, chunks(), headers

    def settle(self, response, request):
        """Run teardowns: now for a body, once a stream has been consumed."""
        if not self.teardowns:
            return response

        status, kind, body, headers = response
        if not isinstance(body, Iterator):
            self.close(request)
            return status, kind, body, headers

        def chunks():
            try:
                yield from body
            finally:
                self.close(request)

        return status, kind, chunks(), headers

    def close(self, request):
        """Run every teardown, carrying on if one of them fails."""
        for callback in self.teardowns:
            try:
                callback(request, {})
            except Exception:
                traceback.print_exc()

    def finish(self, response, request):
        """Let everything registered with @after look at the response."""
        if not self.on_response:
            return response
        status, kind, body, headers = response
        endpoint = request.endpoint
        for owner, callback in self.on_response:
            if not owner or (endpoint and endpoint.startswith(f"{owner}.")):
                callback(request, headers)
        return status, kind, body, headers

    def handle_socket(self, request, connection):
        """Hand a WebSocket to its handler. False when the path has none."""
        try:
            handler, params, _endpoint = match(self.sockets, request.path, request.method)
        except HTTPError:
            return False

        connection.accept()
        try:
            handler(connection, params)
        except Exception:
            traceback.print_exc()
        finally:
            connection.close()
        return True

    def error_response(self, error, request):
        """Answer with the registered handler for this status, or plain JSON."""
        handler = self.errors.get(error.status)
        if handler is None:
            return make_response(({"error": error.message}, error.status), self.json)
        value = handler(request, {"error": error})
        return make_response(value if isinstance(value, tuple) else (value, error.status), self.json)

    def run(self, host=None, port=None):
        """Serve forever. Ctrl+C to stop."""
        from .server import serve  # here to avoid a circular import

        serve(
            self.handle,
            self.handle_socket,
            host or os.environ.get("GROMON_HOST", "127.0.0.1"),
            int(port or os.environ.get("GROMON_PORT", "8000")),
        )


app = App()

route = app.route
websocket = app.websocket
use = app.use
error = app.error
static = app.static
register = app.register
render = app.render
after = app.after
teardown = app.teardown
url_defaults = app.url_defaults


def url_for(endpoint, _external=False, _anchor=None, _method=None, **values):
    """The path for an endpoint, built by the app serving this request.

    Inside a request that is whichever App is handling it, so the same
    `url_for` works for the global app and for an App you built yourself.
    Outside one it is the global app.
    """
    target = current_app()
    if target is None:
        target = app
    return target.url_for(endpoint, _external=_external, _anchor=_anchor, _method=_method, **values)


redirect = app.redirect
abort = app.abort
run = app.run
