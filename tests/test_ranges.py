"""Range requests on send_file, and MAX_CONTENT_LENGTH actually refusing."""

import pytest

from gromon import App, send_file
from gromon.helpers import _range


@pytest.fixture
def application(tmp_path):
    fresh = App()
    target = tmp_path / "data.bin"
    target.write_bytes(b"0123456789")

    @fresh.route("/file")
    def download():
        return send_file(target)

    return fresh


def get(application, path="/file", headers=None):
    return application.test_client().get(path, headers=headers or {})


class TestRange:
    def test_a_window_is_206_with_just_those_bytes(self, application):
        response = get(application, headers={"Range": "bytes=2-5"})
        assert response.status_code == 206
        assert response.data == b"2345"

    def test_the_content_range_says_what_was_sent(self, application):
        response = get(application, headers={"Range": "bytes=2-5"})
        assert response.get_header("Content-Range") == "bytes 2-5/10"

    def test_ranges_are_advertised(self, application):
        assert get(application).get_header("Accept-Ranges") == "bytes"

    def test_an_open_end_runs_to_the_end_of_the_file(self, application):
        assert get(application, headers={"Range": "bytes=7-"}).data == b"789"

    def test_the_last_bytes_can_be_asked_for(self, application):
        assert get(application, headers={"Range": "bytes=-3"}).data == b"789"

    def test_a_past_the_end_offset_is_416(self, application):
        response = get(application, headers={"Range": "bytes=99-"})
        assert response.status_code == 416
        assert response.get_header("Content-Range") == "bytes */10"

    def test_a_backwards_range_is_ignored(self, application):
        response = get(application, headers={"Range": "bytes=5-2"})
        assert response.status_code == 200

    def test_rubbish_is_ignored(self, application):
        response = get(application, headers={"Range": "kilobytes=1-2"})
        assert response.status_code == 200

    def test_a_whole_file_request_still_works(self, application):
        assert get(application).data == b"0123456789"

    def test_a_conditional_still_wins_over_a_range(self, application):
        etag = get(application).get_header("ETag")
        response = get(application, headers={"Range": "bytes=0-1", "If-None-Match": etag})
        assert response.status_code == 304


class TestRangeParsing:
    def test_a_plain_window(self):
        assert _range("bytes=0-99", 1000) == (0, 100)

    def test_an_open_end_means_the_end_of_the_file(self):
        assert _range("bytes=990-", 1000) == (990, 1000)

    def test_the_end_is_inclusive(self):
        assert _range("bytes=0-0", 1000) == (0, 1)

    def test_the_end_is_capped_at_the_size(self):
        assert _range("bytes=0-9999", 1000) == (0, 1000)

    def test_the_last_n_bytes(self):
        assert _range("bytes=-100", 1000) == (900, 1000)

    def test_more_than_the_file_has_is_the_whole_tail(self):
        assert _range("bytes=-9999", 1000) == (0, 1000)

    def test_starting_past_the_end_is_unsatisfiable(self):
        assert _range("bytes=1000-", 1000) == "unsatisfiable"

    def test_nonsense_gives_nothing(self):
        assert _range("bytes=abc", 1000) is None

    def test_no_header_gives_nothing(self):
        assert _range("", 1000) is None

    def test_two_ranges_are_refused_rather_than_guessed(self):
        assert _range("bytes=0-1,4-5", 1000) is None


class TestOverASocket:
    """The bytes on the wire, not just what handle() returned."""

    @pytest.fixture
    def port(self, application, tmp_path):
        import threading
        from http.server import ThreadingHTTPServer

        from gromon.server import handler_for

        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(application.handle))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        yield server.server_address[1]
        server.shutdown()
        server.server_close()

    def call(self, port, headers=None):
        import http.client

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", "/file", headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response, body

    def test_the_length_header_matches_the_slice(self, port):
        response, body = self.call(port, {"Range": "bytes=3-6"})
        assert response.status == 206
        assert response.getheader("Content-Length") == "4"
        assert response.getheader("Content-Range") == "bytes 3-6/10"
        assert body == b"3456"

    def test_a_416_goes_out_with_no_body(self, port):
        response, body = self.call(port, {"Range": "bytes=50-"})
        assert response.status == 416
        assert response.getheader("Content-Length") == "0"
        assert response.getheader("Content-Range") == "bytes */10"
        assert body == b""

    def test_two_calls_on_one_connection_agree(self, port):
        import http.client

        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", "/file", headers={"Range": "bytes=0-0"})
        first = connection.getresponse()
        assert first.status == 206
        first.read()
        connection.request("GET", "/file", headers={"Range": "bytes=9-9"})
        second = connection.getresponse()
        assert second.status == 206
        assert second.read() == b"9"
        connection.close()


class TestContentLength:
    def build(self, limit):
        fresh = App()
        fresh.config["MAX_CONTENT_LENGTH"] = limit

        @fresh.route("/upload", methods=["POST"])
        def upload(request):
            return {"size": len(request.body)}

        return fresh

    def test_a_body_under_the_limit_arrives(self):
        response = self.build(100).test_client().post("/upload", data=b"x" * 99)
        assert response.json == {"size": 99}

    def test_a_body_over_the_limit_is_refused(self):
        response = self.build(100).test_client().post("/upload", data=b"x" * 101)
        assert response.status_code == 413

    def test_the_limit_can_be_lifted(self):
        fresh = self.build(0)
        assert fresh.test_client().post("/upload", data=b"x" * 5000).status_code == 200

    def test_the_default_is_generous(self):
        assert App().config["MAX_CONTENT_LENGTH"] == 32 * 1024 * 1024
