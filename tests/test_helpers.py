"""Files, streamed bodies, and flashed messages."""

import pytest

from gromon import App, flash, get_flashed_messages, safe_join, send_file, session


@pytest.fixture
def application():
    fresh = App()
    load, save = session("a-secret-long-enough")
    fresh.use(load)
    fresh.after(save)
    return fresh


@pytest.fixture
def site(tmp_path):
    folder = tmp_path / "site"
    folder.mkdir()
    (folder / "note.txt").write_text("hello")
    return folder


def client_for(application):
    return application.test_client()


class TestSendFile:
    def test_the_file_is_returned_with_its_type(self, application, site):
        @application.route("/note")
        def note():
            return send_file(site / "note.txt")

        response = client_for(application).get("/note")
        assert (response.status_code, response.data) == (200, b"hello")
        assert response.get_header("Content-Type") == "text/plain"

    def test_caching_headers_come_with_it(self, application, site):
        @application.route("/note")
        def note():
            return send_file(site / "note.txt")

        headers = client_for(application).get("/note").headers
        assert headers["ETag"].startswith('"')
        assert headers["Last-Modified"].endswith("GMT")

    def test_a_matching_etag_is_304_with_no_body(self, application, site):
        @application.route("/note")
        def note():
            return send_file(site / "note.txt")

        client = client_for(application)
        etag = client.get("/note").headers["ETag"]
        response = client.open("/note", headers={"If-None-Match": etag})
        assert (response.status_code, response.data) == (304, b"")

    def test_if_modified_since_is_understood(self, application, site):
        @application.route("/note")
        def note():
            return send_file(site / "note.txt")

        response = client_for(application).open(
            "/note", headers={"If-Modified-Since": "Tue, 01 Jan 2030 00:00:00 GMT"}
        )
        assert response.status_code == 304

    def test_an_old_copy_still_gets_the_file(self, application, site):
        @application.route("/note")
        def note():
            return send_file(site / "note.txt")

        response = client_for(application).open(
            "/note", headers={"If-Modified-Since": "Tue, 01 Jan 2001 00:00:00 GMT"}
        )
        assert response.status_code == 200

    def test_conditional_can_be_switched_off(self, application, site):
        @application.route("/note")
        def note():
            return send_file(site / "note.txt", conditional=False)

        client = client_for(application)
        etag = client.get("/note").headers["ETag"]
        assert client.open("/note", headers={"If-None-Match": etag}).status_code == 200

    def test_a_missing_file_is_404(self, application, site):
        @application.route("/gone")
        def gone():
            return send_file(site / "nope.txt")

        assert client_for(application).get("/gone").status_code == 404

    def test_the_type_can_be_forced(self, application, site):
        @application.route("/note")
        def note():
            return send_file(site / "note.txt", mimetype="application/x-nonsense")

        assert client_for(application).get("/note").get_header("Content-Type") == (
            "application/x-nonsense"
        )

    def test_a_download_name_is_offered(self, application, site):
        @application.route("/note")
        def note():
            return send_file(site / "note.txt", download_name="greeting.txt")

        assert "greeting.txt" in client_for(application).get("/note").headers[
            "Content-Disposition"
        ]


class TestSafeJoin:
    def test_a_path_inside_is_kept(self, site):
        assert safe_join(site, "note.txt").name == "note.txt"

    def test_climbing_out_is_refused(self, site):
        from gromon import HTTPError

        (site.parent / "secret.txt").write_text("nope")
        with pytest.raises(HTTPError) as error:
            safe_join(site, "..", "secret.txt")
        assert error.value.status == 404


class TestStreaming:
    def test_a_generator_is_the_body(self, application):
        @application.route("/numbers")
        def numbers():
            return (str(number) for number in range(3))

        response = client_for(application).get("/numbers")
        assert response.data == b"012"

    def test_bytes_chunks_work_too(self, application):
        @application.route("/bytes")
        def chunks():
            return (b"a" for _ in range(3))

        assert client_for(application).get("/bytes").data == b"aaa"

    def test_a_generator_can_still_read_the_request(self, application):
        seen = []

        @application.route("/slow")
        def slow(request):
            def chunks():
                seen.append(request.path)
                yield "done"

            return chunks()

        assert client_for(application).get("/slow").data == b"done"
        assert seen == ["/slow"]

    def test_the_content_type_can_be_given(self, application):
        @application.route("/csv")
        def csv():
            return ((str(number) + "\n") for number in range(2)), 200, "text/csv"

        assert client_for(application).get("/csv").get_header("Content-Type") == "text/csv"

    def test_an_empty_generator_is_still_a_body(self, application):
        @application.route("/nothing")
        def nothing():
            return (chunk for chunk in [])

        assert client_for(application).get("/nothing").data == b""


class TestFlash:
    def build(self):
        application = App()
        load, save = session("a-secret-long-enough")
        application.use(load)
        application.after(save)

        @application.route("/save", methods=["POST"])
        def save_message(request):
            flash("Saved")
            return {"ok": True}

        @application.route("/messages")
        def messages():
            return {"messages": get_flashed_messages()}

        @application.route("/messages/categories")
        def with_categories():
            return {"messages": get_flashed_messages(with_categories=True)}

        @application.route("/save/category", methods=["POST"])
        def save_category(request):
            flash("Careful", "warning")
            return {"ok": True}

        return application

    def test_a_message_survives_to_the_next_call(self):
        client = client_for(self.build())
        client.post("/save")
        assert client.get("/messages").json == {"messages": ["Saved"]}

    def test_a_message_is_only_read_once(self):
        client = client_for(self.build())
        client.post("/save")
        client.get("/messages")
        assert client.get("/messages").json == {"messages": []}

    def test_categories_can_come_back_too(self):
        client = client_for(self.build())
        client.post("/save/category")
        assert client.get("/messages/categories").json == {
            "messages": [["warning", "Careful"]]
        }

    def test_many_messages_keep_their_order(self):
        application = self.build()

        @application.route("/save/two", methods=["POST"])
        def two(request):
            flash("One")
            flash("Two")
            return {"ok": True}

        client = client_for(application)
        client.post("/save/two")
        assert client.get("/messages").json == {"messages": ["One", "Two"]}

    def test_flash_outside_a_request_says_so(self):
        with pytest.raises(RuntimeError):
            flash("nobody listening")
