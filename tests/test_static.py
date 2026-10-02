import pytest

from gromon import App
from gromon.http import Request


@pytest.fixture
def application():
    """An empty application, so each test starts clean."""
    return App()


@pytest.fixture
def files(tmp_path):
    folder = tmp_path / "static"
    folder.mkdir()
    (folder / "site.css").write_text("body {}")
    return folder


def get(path):
    return Request("GET", path, {}, b"")


def test_static_file_is_served(application, files):
    application.static(files)
    status, kind, body, headers = application.handle(get("/static/site.css"))
    assert (status, kind, body) == (200, "text/css", b"body {}")
    assert "ETag" in headers and "Last-Modified" in headers


def test_static_answers_304_when_the_copy_is_fresh(application, files):
    application.static(files)
    _, _, _, headers = application.handle(get("/static/site.css"))
    again = Request("GET", "/static/site.css", {"If-None-Match": headers["ETag"]}, b"")
    assert application.handle(again) == (304, "text/plain", b"", {})


def test_static_answers_304_for_an_old_last_modified(application, files):
    application.static(files)
    later = Request(
        "GET",
        "/static/site.css",
        {"If-Modified-Since": "Tue, 01 Jan 2030 00:00:00 GMT"},
        b"",
    )
    assert application.handle(later)[0] == 304


def test_static_prefix_can_change(application, files):
    application.static(files, prefix="/assets")
    assert application.handle(get("/assets/site.css"))[0] == 200


def test_missing_static_file_is_404(application, files):
    application.static(files)
    assert application.handle(get("/static/nope.css"))[0] == 404


def test_missing_static_folder_is_404(application):
    assert application.handle(get("/static/site.css"))[0] == 404


def test_static_cannot_escape_its_folder(application, files):
    (files.parent / "secret.txt").write_text("top secret")
    application.static(files)
    assert application.handle(get("/static/../secret.txt"))[0] == 404


def test_static_folder_follows_the_working_directory(tmp_path, monkeypatch):
    folder = tmp_path / "static"
    folder.mkdir()
    (folder / "note.txt").write_text("hello")
    application = App()

    monkeypatch.chdir(tmp_path)  # what `gromon run` does
    application.static()

    assert application.handle(get("/static/note.txt"))[:3] == (200, "text/plain", b"hello")


def test_static_uses_the_folder_given_to_the_app(tmp_path):
    folder = tmp_path / "public"
    folder.mkdir()
    (folder / "note.txt").write_text("hello")
    application = App(static_folder=str(folder))

    application.static()

    assert application.handle(get("/static/note.txt"))[2] == b"hello"
