"""An OpenAPI document built from the routes an app already has.

    app.openapi()                      # a dict
    app.openapi("My API", "2.1.0")     # with your own title and version

Because it reads the routes rather than asking you to keep a second description
in step by hand, it cannot drift. A path converter becomes a typed parameter:
`<int:id>` is an integer, `<uuid:id>` a uuid, `<path:rest>` a string.

Response bodies are not described. That needs to know what your handlers
return, and a wrong guess in a spec is worse than no spec: point a tool at the
paths, the parameters and the operation ids.
"""

SCHEMAS = {
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "uuid": {"type": "string", "format": "uuid"},
    "string": {"type": "string"},
    "path": {"type": "string"},
}


def document(app, title="API", version="1.0.0"):
    """The OpenAPI document for an App."""
    paths = {}

    for pattern, _handler, methods, endpoint, template in app.routes:
        path, parameters = describe(pattern)
        entry = paths.setdefault(path, {})
        for method in sorted(methods):
            if method in ("HEAD", "OPTIONS"):
                continue
            entry[method.lower()] = {
                "operationId": endpoint,
                "parameters": parameters,
                "responses": {"200": {"description": "Success"}},
            }

    return {
        "openapi": "3.1.0",
        "info": {"title": title, "version": version},
        "paths": dict(sorted(paths.items())),
    }


def describe(pattern):
    """'/user/<int:id>' -> ('/user/{id}', [a parameter])

    A compiled segment is (name, kind), and kind is None when the segment is
    plain text rather than a converter, which is how the two are told apart.
    """
    parts, parameters = [], []

    for name, kind in pattern:
        if kind is None:
            parts.append(name)
            continue

        parts.append("{%s}" % name)
        parameters.append(
            {
                "name": name,
                "in": "path",
                "required": True,
                "schema": dict(SCHEMAS.get(kind, SCHEMAS["string"])),
            }
        )

    return "/" + "/".join(parts) or "/", parameters
