"""Routing: static segments, `<name>` parameters, `<int:id>` converters.

    /users/<int:id>          id arrives as an int, "abc" is a 404
    /files/<path:name>       the wildcard spans slashes

Every route also carries an endpoint, so a URL can be rebuilt from a name:
`url_for("user", id=7)` -> "/users/7".
"""

from urllib.parse import quote, unquote, urlencode

from .errors import HTTPError


def _number(value, cast):
    try:
        return cast(value)
    except ValueError:
        return None


def _uuid(value):
    from uuid import UUID

    try:
        return UUID(value)
    except ValueError:
        return None


# name -> (to_python, to_url, greedy)
CONVERTERS = {
    "string": (str, str, False),
    "int": (lambda value: _number(value, int), str, False),
    "float": (lambda value: _number(value, float), str, False),
    "uuid": (_uuid, str, False),
    "path": (str, str, True),
}


def split_path(path):
    """'/user/<int:id>' -> ['user', '<int:id>'], '/' -> []"""
    return [segment for segment in path.split("/") if segment]


def compile_segment(segment):
    """One segment -> (name, converter name). 'users' -> ('users', None)."""
    if segment.startswith("<") and segment.endswith(">"):
        inside = segment[1:-1]
        kind, colon, name = inside.partition(":")
        return (name, kind) if colon else (inside, "string")
    return segment, None


def compile_path(path):
    """A path -> [(name, converter name)], ready for match_path."""
    compiled = []
    for segment in split_path(path):
        name, kind = compile_segment(segment)
        if kind and kind not in CONVERTERS:
            raise HTTPError(500, f"Unknown converter <{kind}:...> in {path}")
        compiled.append((name, kind))
    return compiled


def match_path(pattern, segments):
    """The parameters if pattern matches segments, else None."""
    params, index = {}, 0

    for name, kind in pattern:
        converter = CONVERTERS[kind] if kind else None
        if converter and converter[2]:
            params[name] = "/".join(segments[index:])
            return params
        if index == len(segments):
            return None

        value = segments[index]
        if converter:
            converted = converter[0](value)
            if converted is None:
                return None
            params[name] = converted
        elif name != value:
            return None
        index += 1

    return params if index == len(segments) else None


def match(routes, path, method):
    """Return the (handler, params, endpoint) of the first route matching."""
    segments = split_path(unquote(path))
    allowed = set()

    for pattern, handler, methods, endpoint, _template in routes:
        params = match_path(pattern, segments)
        if params is None:
            continue
        if method in methods:
            return handler, params, endpoint
        allowed |= methods

    if allowed:
        raise HTTPError(405, "Method not allowed")
    raise HTTPError(404, "Not found")


def allow(routes, path):
    """The methods a path answers, whatever method was asked for."""
    segments = split_path(unquote(path))
    methods = set()

    for pattern, _handler, allowed, _endpoint, _template in routes:
        if match_path(pattern, segments) is not None:
            methods |= allowed
    return methods


def build(template, values, external=False, anchor=None):
    """Turn '/user/<int:id>' plus {'id': 7} into '/user/7', query string included."""
    used, parts = set(), []

    for segment in split_path(template):
        name, kind = compile_segment(segment)
        if not kind:
            parts.append(quote(name, safe="/:"))
            continue
        if name not in values:
            raise HTTPError(500, f"Cannot build {template}, no value for {name!r}")
        if values[name] is None:
            raise HTTPError(500, f"Cannot build {template}, {name!r} is None")
        used.add(name)
        parts.append(quote(str(values[name]), safe="/" if kind == "path" else ""))

    leftover = {key: value for key, value in values.items() if key not in used}
    path = "/" + "/".join(parts)
    if leftover:
        path = f"{path}?{urlencode(leftover)}"
    if anchor is not None:
        path = f"{path}#{quote(str(anchor), safe='')}"

    if not external:
        return path
    from .context import url_root

    return f"{url_root()}{path}"
