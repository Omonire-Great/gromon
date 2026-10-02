"""Class based views: subclass it, write get and post, then route it."""

from inspect import signature

from .errors import HTTPError

VERBS = ("get", "post", "put", "patch", "delete", "head", "options")


class MethodView:
    """One class, one resource, one method per verb.

        @route("/users")
        class Users(MethodView):
            def get(self):
                return []

            def post(self, request):
                return {"created": True}, 201

    The verb is the method name, and the verbs you write are the ones the route
    answers. Route parameters arrive by name, `request` arrives if you ask for
    it, and the instance is made fresh for every request.
    """

    def dispatch(self, **params):
        """Send the request to the method named after its verb."""
        from .context import current

        request = current()
        method = getattr(self, request.method.lower(), None)
        if method is None:
            raise HTTPError(405, "Method not allowed")

        wanted = signature(method).parameters
        takes_anything = any(
            parameter.kind is parameter.VAR_KEYWORD for parameter in wanted.values()
        )
        arguments = dict(params) if takes_anything else {
            key: value for key, value in params.items() if key in wanted
        }
        if "request" in wanted:
            arguments["request"] = request
        return method(**arguments)


def verbs(klass):
    """The HTTP verbs a MethodView subclass answers."""
    return tuple(verb.upper() for verb in VERBS if callable(getattr(klass, verb, None)))


def view_for(klass):
    """Turn a MethodView subclass into something route() can register."""

    def view(**params):
        return klass().dispatch(**params)

    view.__name__ = klass.__name__
    return view
