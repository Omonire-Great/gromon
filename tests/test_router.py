import pytest

from gromon import HTTPError
from gromon.router import build, compile_path, match, match_path, split_path


def root(request, params):
    return "root"


def users(request, params):
    return "users"


def post(request, params):
    return "post"


def files(request, params):
    return "files"


def route(handler, path, methods=("GET",)):
    """A route in the shape App.route puts it in."""
    return (compile_path(path), handler, set(methods), handler.__name__, path)


ROUTES = [
    route(root, "/"),
    route(users, "/users", ("GET", "POST")),
    route(post, "/users/<int:id>/posts/<post>"),
    route(files, "/static/<path:path>"),
]


def test_root_matches_root():
    assert match(ROUTES, "/", "GET") == (root, {}, "root")


def test_static_path():
    assert match(ROUTES, "/users", "POST") == (users, {}, "users")


def test_named_parameters():
    assert match(ROUTES, "/users/7/posts/hello", "GET") == (
        post,
        {"id": 7, "post": "hello"},
        "post",
    )


def test_trailing_slash_is_the_same_path():
    assert match(ROUTES, "/users/", "GET") == (users, {}, "users")


def test_path_parameter_spans_slashes():
    assert match(ROUTES, "/static/css/site.css", "GET") == (
        files,
        {"path": "css/site.css"},
        "files",
    )


def test_path_parameter_takes_the_rest_including_nothing():
    pattern = compile_path("/<path:path>")
    assert match_path(pattern, []) == {"path": ""}
    assert match_path(compile_path("/a/<path:path>"), ["a", "b", "c"]) == {"path": "b/c"}


class TestConverters:
    def test_int_converts(self):
        assert match(ROUTES, "/users/7/posts/hello", "GET")[1]["id"] == 7

    def test_int_refuses_text(self):
        with pytest.raises(HTTPError) as error:
            match(ROUTES, "/users/seven/posts/hello", "GET")
        assert error.value.status == 404

    def test_int_allows_a_minus(self):
        assert match(ROUTES, "/users/-7/posts/hello", "GET")[1]["id"] == -7

    def test_float_converts(self):
        assert match([route(root, "/<float:score>")], "/1.5", "GET")[1] == {"score": 1.5}

    def test_float_refuses_a_second_dot(self):
        with pytest.raises(HTTPError):
            match([route(root, "/<float:score>")], "/1.5.2", "GET")

    def test_uuid_accepts_a_uuid(self):
        value = "123e4567-e89b-12d3-a456-426614174000"
        assert match([route(root, "/<uuid:id>")], f"/{value}", "GET")[1]["id"].hex

    def test_uuid_refuses_a_word(self):
        with pytest.raises(HTTPError):
            match([route(root, "/<uuid:id>")], "/not-a-uuid", "GET")

    def test_string_is_the_default(self):
        assert match([route(root, "/<name>")], "/7", "GET")[1] == {"name": "7"}

    def test_string_never_spans_a_slash(self):
        with pytest.raises(HTTPError):
            match([route(root, "/<name>")], "/a/b", "GET")

    def test_an_unknown_converter_is_refused_at_registration(self):
        with pytest.raises(HTTPError) as error:
            compile_path("/<money:id>")
        assert "money" in str(error.value)


class TestBuild:
    def test_a_static_path(self):
        assert build("/", {}) == "/"

    def test_parameters_go_where_they_belong(self):
        assert build("/users/<int:id>/posts/<post>", {"id": 7, "post": "hi"}) == "/users/7/posts/hi"

    def test_extra_values_become_a_query_string(self):
        assert build("/search", {"q": "hi"}) == "/search?q=hi"

    def test_a_wildcard_keeps_its_slashes(self):
        assert build("/files/<path:name>", {"name": "css/site.css"}) == "/files/css/site.css"

    def test_values_are_quoted(self):
        assert build("/tag/<name>", {"name": "a b"}) == "/tag/a%20b"

    def test_a_slash_in_a_value_is_escaped(self):
        assert build("/tag/<name>", {"name": "a/b"}) == "/tag/a%2Fb"

    def test_a_missing_value_is_an_error(self):
        with pytest.raises(HTTPError) as error:
            build("/user/<int:id>", {})
        assert "id" in str(error.value)

    def test_a_none_value_is_an_error(self):
        with pytest.raises(HTTPError):
            build("/user/<int:id>", {"id": None})

    def test_external_needs_a_request(self):
        assert build("/", {}, external=True) == "/"


def test_split_path_keeps_the_raw_segments():
    assert split_path("/a/<int:b>") == ["a", "<int:b>"]


def test_unknown_path_is_404():
    with pytest.raises(HTTPError) as error:
        match(ROUTES, "/nope", "GET")
    assert error.value.status == 404


def test_missing_segment_is_404():
    with pytest.raises(HTTPError) as error:
        match(ROUTES, "/users/7/posts", "GET")
    assert error.value.status == 404


def test_wrong_method_is_405():
    with pytest.raises(HTTPError) as error:
        match(ROUTES, "/", "POST")
    assert error.value.status == 405
