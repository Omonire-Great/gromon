from gromon.response import make_response


def test_dict_is_json():
    assert make_response({"a": 1}) == (200, "application/json", b'{"a": 1}', {})


def test_list_is_json():
    assert make_response([1, 2]) == (200, "application/json", b"[1, 2]", {})


def test_str_is_html():
    assert make_response("hi") == (200, "text/html; charset=utf-8", b"hi", {})


def test_bytes_are_sent_as_is():
    assert make_response(b"\x00\x01") == (200, "application/octet-stream", b"\x00\x01", {})


def test_none_is_204_empty():
    status, kind, body, headers = make_response(None)
    assert (status, body, headers) == (204, b"", {})


def test_tuple_sets_the_status():
    assert make_response(({"a": 1}, 201)) == (201, "application/json", b'{"a": 1}', {})


def test_tuple_wraps_any_value():
    assert make_response(("hi", 302)) == (302, "text/html; charset=utf-8", b"hi", {})


def test_tuple_sets_the_content_type():
    assert make_response((b"\x89PNG", 200, "image/png")) == (200, "image/png", b"\x89PNG", {})


def test_content_type_override_keeps_json_body():
    assert make_response(({"a": 1}, 200, "application/vnd.api+json")) == (
        200,
        "application/vnd.api+json",
        b'{"a": 1}',
        {},
    )


def test_the_fourth_item_sets_headers():
    assert make_response(("hi", 200, "text/plain", {"X-Frame-Options": "DENY"})) == (
        200,
        "text/plain",
        b"hi",
        {"X-Frame-Options": "DENY"},
    )


def test_none_content_type_falls_back_to_the_default():
    assert make_response(("hi", 200, None, {"Location": "/next"})) == (
        200,
        "text/html; charset=utf-8",
        b"hi",
        {"Location": "/next"},
    )
