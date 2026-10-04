"""Version, WSGI, caching headers, OpenAPI, and `gromon test`."""

import io
import subprocess
import sys
from pathlib import Path
from wsgiref.util import setup_testing_defaults

import pytest

from gromon import App, __version__, wsgi

APP = """
from gromon import App, request

app = App()


@app.route("/")
def home():
    return "home"


@app.route("/json")
def as_json():
    return {"ok": True}


@app.route("/user/<int:id>")
def user(id):
    return str(id)


@app.route("/echo", methods=["POST"])
def echo():
    return {"body": request.body.decode(), "q": request.query.get("q")}
"""


def run(*arguments, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "gromon", *arguments],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=cwd,
    )


def environ(path="/", method="GET", body=b"", **headers):
    """A WSGI environ, the way a real server would hand one over."""
    settings = {}
    setup_testing_defaults(settings)
    settings["PATH_INFO"] = path
    settings["REQUEST_METHOD"] = method
    settings["wsgi.input"] = io.BytesIO(body)
    if body:
        settings["CONTENT_LENGTH"] = str(len(body))
    for name, value in headers.items():
        settings["HTTP_" + name.upper().replace("-", "_")] = value
    if "?" in path:
        settings["PATH_INFO"], settings["QUERY_STRING"] = path.split("?", 1)
    else:
        settings["QUERY_STRING"] = ""
    return settings


def call(application, **kwargs):
    """Run a WSGI app and collect what it produced."""
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = headers

    body = b"".join(application(environ(**kwargs), start_response))
    return captured, body


class TestTheVersionFlag:
    def test_it_prints_the_version(self):
        finished = run("--version")
        assert finished.returncode == 0, finished.stderr
        assert finished.stdout.strip() == f"gromon {__version__}"

    def test_the_short_flag_works_too(self):
        assert run("-V").stdout == run("--version").stdout

    def test_it_is_the_installed_version(self):
        from importlib import metadata

        assert __version__ == metadata.version("gromon")

    def test_the_help_mentions_it(self):
        assert "--version" in run("--help").stdout


class TestTheWSGIEntryPoint:
    def test_wsgi_is_exported(self):
        assert callable(wsgi)
        assert "wsgi" in __import__("gromon").__all__

    def test_an_app_can_be_a_wsgi_app(self):
        app = self.load()
        assert callable(app.wsgi)

    def test_it_answers_a_request(self):
        captured, body = call(self.load().wsgi)
        assert captured["status"].startswith("200")
        assert body == b"home"

    def test_the_status_line_has_a_reason(self):
        captured, _ = call(self.load().wsgi, path="/nowhere")
        assert captured["status"] == "404 Not Found"

    def test_a_json_route_keeps_its_content_type(self):
        captured, body = call(self.load().wsgi, path="/json")
        headers = dict(captured["headers"])
        assert "json" in headers["Content-Type"]
        assert body == b'{"ok": true}'

    def test_a_path_parameter_is_converted(self):
        _, body = call(self.load().wsgi, path="/user/42")
        assert body == b"42"

    def test_the_query_string_reaches_the_handler(self):
        _, body = call(self.load().wsgi, path="/echo?q=hi", method="POST", body=b"hello")
        assert b"hi" in body and b"hello" in body

    def test_it_does_not_hang_when_there_is_no_body(self):
        # A GET leaves wsgi.input on the socket. Reading it anyway waits for a
        # close that never comes, which is a hang rather than an error.
        captured, body = call(self.load().wsgi)
        assert captured["status"].startswith("200")
        assert body

    def test_hop_by_hop_headers_are_left_out(self):
        captured, _ = call(self.load().wsgi, connection="keep-alive")
        names = {name.lower() for name, _ in captured["headers"]}
        assert "connection" not in names
        assert "transfer-encoding" not in names

    def test_the_content_type_is_sent(self):
        captured, _ = call(self.load().wsgi)
        names = {name.lower() for name, _ in captured["headers"]}
        assert "content-type" in names

    def test_it_serves_over_a_real_wsgi_server(self):
        import threading
        import urllib.error
        import urllib.request
        from wsgiref.simple_server import make_server

        server = make_server("127.0.0.1", 0, self.load().wsgi)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as reply:
                assert reply.status == 200
                assert reply.read() == b"home"
                assert reply.headers["Content-Type"].startswith("text/html")
            with pytest.raises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/nowhere", timeout=10)
            assert caught.value.code == 404
        finally:
            server.shutdown()

    def test_wsgi_works_without_a_server_too(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "site.py"
            path.write_text(APP)
            app = self.imported(path)
            captured, body = call(wsgi(app))
        assert captured["status"].startswith("200")
        assert body == b"home"

    def load(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "site.py"
            path.write_text(APP)
            return self.imported(path)

    def imported(self, path):
        import runpy

        sys.path.insert(0, str(path.parent))
        try:
            return runpy.run_path(str(path))["app"]
        finally:
            sys.path.remove(str(path.parent))


class TestCacheControl:
    def build(self, name="site.fscss", max_age=None, config=None):
        from gromon import send_file

        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / name
            path.write_text("body{}")
            return send_file(path, max_age=max_age)[3]

    def test_a_plain_file_is_cached_for_an_hour(self):
        assert self.build()["Cache-Control"] == "public, max-age=3600"

    def test_a_fingerprinted_name_is_cached_forever(self):
        headers = self.build("app.9f2c1a4b.js")
        assert headers["Cache-Control"] == "public, max-age=31536000, immutable"

    def test_a_dashed_fingerprint_counts_too(self):
        headers = self.build("app-9f2c1a4b3d.css")
        assert "immutable" in headers["Cache-Control"]

    def test_a_name_without_a_hash_is_not_immutable(self):
        assert "immutable" not in self.build("app.js")["Cache-Control"]

    def test_max_age_zero_turns_caching_off(self):
        assert self.build(max_age=0)["Cache-Control"] == "public, max-age=0"

    def test_a_short_max_age_is_not_immutable(self):
        assert self.build(max_age=60)["Cache-Control"] == "public, max-age=60"

    def test_the_other_caching_headers_are_kept(self):
        headers = self.build()
        assert "ETag" in headers
        assert "Last-Modified" in headers
        assert headers["Accept-Ranges"] == "bytes"

    def test_a_304_still_carries_the_cache_header(self):
        from gromon import send_file

        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "site.fscss"
            path.write_text("body{}")
            first = send_file(path)[3]
            again = send_file(path, conditional=True)[3]
        assert first["Cache-Control"] == again["Cache-Control"]

    def test_static_honours_the_config(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "site.css").write_text("body{}")
            app = App(__name__)
            app.config["STATIC_MAX_AGE"] = 0
            app.static(folder=folder)
            reply = app.test_client().get("/static/site.css")
        assert reply.headers["Cache-Control"] == "public, max-age=0"

    def test_static_caches_for_an_hour_by_default(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "site.css").write_text("body{}")
            app = App(__name__)
            app.static(folder=folder)
            reply = app.test_client().get("/static/site.css")
        assert reply.headers["Cache-Control"] == "public, max-age=3600"


class TestOpenAPI:
    def build(self):
        app = App(__name__)

        @app.route("/")
        def home():
            return "home"

        @app.route("/user/<int:id>")
        def user(id):
            return str(id)

        @app.route("/thing/<uuid:key>")
        def thing(key):
            return key

        @app.route("/files/<path:rest>")
        def files(rest):
            return rest

        @app.route("/tag/<slug>")
        def tag(slug):
            return slug

        @app.route("/both", methods=["GET", "POST"])
        def both():
            return "both"

        return app

    def test_it_is_a_valid_envelope(self):
        document = self.build().openapi()
        assert document["openapi"].startswith("3.")
        assert document["info"] == {"title": "API", "version": "1.0.0"}

    def test_the_title_and_version_can_be_given(self):
        document = self.build().openapi("Shop", "2.1.0")
        assert document["info"] == {"title": "Shop", "version": "2.1.0"}

    def test_every_route_becomes_a_path(self):
        paths = self.build().openapi()["paths"]
        assert set(paths) == {"/", "/user/{id}", "/thing/{key}", "/files/{rest}", "/tag/{slug}", "/both"}

    def test_a_plain_segment_is_not_a_parameter(self):
        operation = self.build().openapi()["paths"]["/user/{id}"]["get"]
        assert [p["name"] for p in operation["parameters"]] == ["id"]

    def test_the_home_page_has_no_parameters(self):
        assert self.build().openapi()["paths"]["/"]["get"]["parameters"] == []

    def test_an_int_converter_becomes_an_integer(self):
        parameter = self.build().openapi()["paths"]["/user/{id}"]["get"]["parameters"][0]
        assert parameter["schema"] == {"type": "integer"}
        assert parameter["in"] == "path"
        assert parameter["required"] is True

    def test_a_uuid_converter_keeps_its_format(self):
        parameter = self.build().openapi()["paths"]["/thing/{key}"]["get"]["parameters"][0]
        assert parameter["schema"] == {"type": "string", "format": "uuid"}

    def test_a_float_converter_becomes_a_number(self):
        app = App(__name__)

        @app.route("/n/<float:value>")
        def number(value):
            return str(value)

        parameter = app.openapi()["paths"]["/n/{value}"]["get"]["parameters"][0]
        assert parameter["schema"] == {"type": "number"}

    def test_a_bare_name_is_a_string(self):
        parameter = self.build().openapi()["paths"]["/tag/{slug}"]["get"]["parameters"][0]
        assert parameter["schema"] == {"type": "string"}

    def test_a_path_converter_is_a_string(self):
        parameter = self.build().openapi()["paths"]["/files/{rest}"]["get"]["parameters"][0]
        assert parameter["schema"] == {"type": "string"}

    def test_head_and_options_are_left_out(self):
        app = App(__name__)

        @app.route("/thing", methods=["GET", "HEAD", "OPTIONS"])
        def thing():
            return "thing"

        assert list(app.openapi()["paths"]["/thing"]) == ["get"]

    def test_several_methods_share_one_path(self):
        assert set(self.build().openapi()["paths"]["/both"]) == {"get", "post"}

    def test_the_endpoint_becomes_the_operation_id(self):
        assert self.build().openapi()["paths"]["/user/{id}"]["get"]["operationId"] == "user"

    def test_every_operation_says_it_can_succeed(self):
        for path in self.build().openapi()["paths"].values():
            for operation in path.values():
                assert "200" in operation["responses"]

    def test_the_document_survives_json(self):
        from json import dumps

        assert dumps(self.build().openapi())

    def test_an_app_with_no_routes_is_still_a_document(self):
        assert App(__name__).openapi()["paths"] == {}


class TestTheOpenAPIFlag:
    def document(self, *flags):
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "site.py"
            path.write_text(APP)
            finished = run("routes", str(path), *flags)
        assert finished.returncode == 0, finished.stderr
        return json.loads(finished.stdout)

    def test_it_prints_a_document(self):
        document = self.document("--openapi")
        assert document["openapi"].startswith("3.")
        assert "/" in document["paths"]

    def test_json_prints_the_routes(self):
        routes = self.document("--json")
        assert {route["path"] for route in routes} == {"/", "/json", "/user/<int:id>", "/echo"}

    def test_json_names_the_parameters(self):
        routes = {route["path"]: route for route in self.document("--json")}
        assert routes["/user/<int:id>"]["parameters"] == [{"name": "id", "converter": "int"}]

    def test_json_leaves_plain_segments_out(self):
        routes = {route["path"]: route for route in self.document("--json")}
        assert routes["/json"]["parameters"] == []

    def test_json_lists_the_methods(self):
        routes = {route["path"]: route for route in self.document("--json")}
        assert routes["/echo"]["methods"] == ["POST"]

    def test_the_table_is_still_the_default(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "site.py"
            path.write_text(APP)
            finished = run("routes", str(path))
        assert "METHODS" in finished.stdout


class TestTheTestCommand:
    PASSING = """
import unittest

from app import app

client = app.test_client()


class TestThing(unittest.TestCase):
    def test_it_answers(self):
        self.assertEqual(client.get("/").status_code, 200)
"""

    FAILING = """
import unittest


class TestThing(unittest.TestCase):
    def test_it_fails(self):
        self.assertEqual(1, 2)
"""

    def project(self, body, folder="tests"):
        import tempfile

        holder = tempfile.TemporaryDirectory()
        root = Path(holder.name)
        (root / "app.py").write_text(APP)
        (root / folder).mkdir()
        (root / folder / "test_thing.py").write_text(body)
        return holder, root

    def test_passing_tests_succeed(self):
        holder, root = self.project(self.PASSING)
        try:
            finished = run("test", str(root))
        finally:
            holder.cleanup()
        assert finished.returncode == 0, finished.stdout + finished.stderr
        assert "OK" in finished.stderr

    def test_failing_tests_fail(self):
        holder, root = self.project(self.FAILING)
        try:
            finished = run("test", str(root))
        finally:
            holder.cleanup()
        assert finished.returncode == 1
        assert "FAILED" in finished.stderr

    def test_it_looks_in_the_folder_you_are_in(self):
        holder, root = self.project(self.PASSING)
        try:
            finished = run("test", cwd=str(root))
        finally:
            holder.cleanup()
        assert finished.returncode == 0, finished.stdout + finished.stderr

    def test_a_single_folder_is_also_found(self):
        holder, root = self.project(self.PASSING, folder="test")
        try:
            finished = run("test", str(root))
        finally:
            holder.cleanup()
        assert finished.returncode == 0, finished.stdout + finished.stderr

    def test_no_test_folder_says_so(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            finished = run("test", folder)
        assert finished.returncode != 0
        assert "no test folder" in finished.stderr

    def test_an_empty_test_folder_says_so(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "tests").mkdir()
            finished = run("test", folder)
        assert finished.returncode != 0
        assert "no tests found" in finished.stderr

    def test_a_test_that_will_not_import_is_reported(self):
        holder, root = self.project("import a_module_that_is_not_there\n")
        try:
            finished = run("test", str(root))
        finally:
            holder.cleanup()
        assert finished.returncode != 0
        assert "ModuleNotFoundError" in finished.stderr or "could not load" in finished.stderr


class TestTheStarterHasTests:
    def test_a_new_project_can_test_itself(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            created = run("new", "shop", cwd=folder)
            assert created.returncode == 0, created.stderr
            assert (Path(folder) / "shop" / "tests" / "test_app.py").is_file()

            finished = run("test", str(Path(folder) / "shop"))
        assert finished.returncode == 0, finished.stdout + finished.stderr
        assert "Ran 5 tests" in finished.stderr

    def test_the_test_count_grew_by_one(self):
        import tempfile

        from gromon.scaffold import FILES

        with tempfile.TemporaryDirectory() as folder:
            run("new", "shop", cwd=folder)
            written = sum(1 for path in (Path(folder) / "shop").rglob("*") if path.is_file())
        assert written == len(FILES) + 1
