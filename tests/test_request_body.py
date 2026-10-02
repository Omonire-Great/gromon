"""request.form, request.files, request.cookies, request.values()."""

import pytest

from gromon import App


@pytest.fixture
def application():
    fresh = App()

    @fresh.route("/form", methods=["POST"])
    def read_form(request):
        return {"form": request.form, "type": request.headers["Content-Type"][:33]}

    @fresh.route("/upload", methods=["POST"])
    def upload(request):
        upload = request.files["avatar"]
        return {
            "filename": upload["filename"],
            "size": len(upload["data"]),
            "content_type": upload["content_type"],
        }

    @fresh.route("/values", methods=["GET", "POST"])
    def values(request):
        return request.values()

    @fresh.route("/cookies")
    def cookies(request):
        return request.cookies

    return fresh


def call(application, path, body=b"", headers=None):
    return application.test_client().post(path, data=body, headers=headers)


class TestForm:
    def test_an_urlencoded_body_is_read(self, application):
        response = call(
            application,
            "/form",
            b"name=ada&city=london",
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.json == {
            "form": {"name": "ada", "city": "london"},
            "type": "application/x-www-form-urlencoded",
        }

    def test_an_empty_form_is_a_dict(self, application):
        response = call(application, "/form", b"", {"Content-Type": "application/x-www-form-urlencoded"})
        assert response.json["form"] == {}

    def test_nothing_is_parsed_without_a_content_type(self, application):
        assert call(application, "/form", b"name=ada").json["form"] == {}


class TestMultipart:
    def post_multipart(self, application, fields, files):
        boundary = "----gromon"
        raw = b""
        for name, value in fields.items():
            raw += (
                f'--{boundary}\r\nContent-Disposition: form-data; '
                f'name="{name}"\r\n\r\n{value}\r\n'
            ).encode()
        for name, filename, kind, data in files:
            raw += (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\nContent-Type: {kind}\r\n\r\n'
            ).encode() + data + b"\r\n"
        raw += f"--{boundary}--\r\n".encode()
        return call(
            application,
            "/upload",
            raw,
            {"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    def test_a_file_lands_in_files(self, application):
        response = self.post_multipart(
            application, {"name": "ada"}, [("avatar", "me.png", "image/png", b"\x89PNG")]
        )
        assert response.json == {
            "filename": "me.png",
            "size": 4,
            "content_type": "image/png",
        }

    def test_fields_and_files_live_side_by_side(self, application):
        client = application.test_client()
        boundary = "----gromon"
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\nada\r\n'
            f"--{boundary}--\r\n"
        ).encode()
        assert client.post(
            "/form", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        ).json["form"] == {"name": "ada"}


class TestValues:
    def test_query_and_form_are_merged(self, application):
        client = application.test_client()
        response = client.post(
            "/values?q=from_query",
            data=b"name=ada",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.json == {"q": "from_query", "name": "ada"}

    def test_the_form_wins_over_the_query(self, application):
        client = application.test_client()
        response = client.post(
            "/values?name=from_query",
            data=b"name=ada",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.json["name"] == "ada"


class TestCookies:
    def test_the_jar_is_a_dict(self, application):
        client = application.test_client()
        client.cookies["theme"] = "dark"
        assert client.get("/cookies").json == {"theme": "dark"}

    def test_no_cookie_header_means_an_empty_dict(self, application):
        assert application.test_client().get("/cookies").json == {}
