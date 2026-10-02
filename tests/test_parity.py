"""Teardowns, url_defaults, automatic OPTIONS, trusted hosts, JSON provider."""

import pytest

from gromon import App, Blueprint
from gromon.response import JSON


@pytest.fixture
def application():
    return App()


def get(application, path, method="GET", **headers):
    client = application.test_client()
    if method == "GET":
        return client.get(path, headers=headers)
    return client.open(path, method, headers=headers)


class TestTeardown:
    def build(self):
        application = App()
        application.closed = []

        @application.route("/")
        def home():
            return "home"

        @application.route("/boom")
        def boom():
            raise ValueError("nope")

        @application.teardown
        def close(request):
            application.closed.append(request.path)

        return application

    def test_it_runs_after_a_normal_response(self):
        application = self.build()
        get(application, "/")
        assert application.closed == ["/"]

    def test_it_runs_after_an_error_response(self):
        application = self.build()
        get(application, "/boom")
        assert application.closed == ["/boom"]

    def test_it_runs_after_a_404(self):
        application = self.build()
        get(application, "/nothing")
        assert application.closed == ["/nothing"]

    def test_it_runs_after_middleware_stops_the_request(self):
        application = self.build()

        @application.use
        def stop(request):
            return {"error": "no"}, 403

        assert get(application, "/").status_code == 403
        assert application.closed == ["/"]

    def test_it_runs_after_a_stream_has_been_consumed(self):
        application = App()
        seen = []

        @application.route("/events")
        def events():
            def stream():
                yield "one"
                seen.append("mid")
                yield "two"

            return stream()

        @application.teardown
        def close(request):
            seen.append("teardown")

        response = application.test_client().get("/events")
        assert response.text == "onetwo"
        assert seen == ["mid", "teardown"]

    def test_several_run_in_order(self):
        application = App()
        order = []

        @application.route("/")
        def home():
            return "x"

        @application.teardown
        def first(request):
            order.append("first")

        @application.teardown
        def second(request):
            order.append("second")

        get(application, "/")
        assert order == ["first", "second"]

    def test_one_that_raises_does_not_stop_the_others(self):
        application = self.build()

        @application.teardown
        def broken(request):
            raise ValueError("teardown failed")

        assert get(application, "/").status_code == 200
        assert application.closed == ["/"]

    def test_it_may_ask_for_the_request(self):
        application = App()
        seen = []

        @application.route("/")
        def home():
            return "x"

        @application.teardown
        def close(request):
            seen.append(request.method)

        get(application, "/")
        assert seen == ["GET"]

    def test_a_blueprint_teardown_comes_along(self):
        application = App()
        seen = []
        api = Blueprint("api", "/api")

        @api.route("/ping")
        def ping():
            return "pong"

        @api.teardown
        def close(request):
            seen.append(request.path)

        application.register(api)
        get(application, "/api/ping")
        assert seen == ["/api/ping"]


class TestUrlDefaults:
    def test_a_default_fills_in_a_missing_value(self):
        application = App()

        @application.route("/<lang>/page")
        def page(lang):
            return lang

        @application.url_defaults
        def language(endpoint, values):
            values.setdefault("lang", "en")

        assert application.url_for("page") == "/en/page"
        assert application.url_for("page", lang="fr") == "/fr/page"

    def test_it_is_called_with_the_endpoint(self):
        application = App()
        seen = []

        @application.route("/page")
        def page():
            return "x"

        @application.url_defaults
        def watch(endpoint, values):
            seen.append(endpoint)

        application.url_for("page")
        assert seen == ["page"]

    def test_a_blueprint_default_only_touches_its_own_endpoints(self):
        application = App()
        api = Blueprint("api", "/api")

        @application.route("/page")
        def page():
            return "x"

        @api.route("/<lang>/page")
        def api_page(lang):
            return lang

        @api.url_defaults
        def language(endpoint, values):
            values.setdefault("lang", "en")

        application.register(api)
        assert application.url_for("api.api_page") == "/api/en/page"
        assert application.url_for("page") == "/page"

    def test_it_can_be_used_from_inside_a_request(self):
        application = App()

        @application.route("/page")
        def page():
            return {"here": application.url_for("page")}

        @application.url_defaults
        def nothing(endpoint, values):
            pass

        assert get(application, "/page").json == {"here": "/page"}


class TestUrlForExtras:
    def build(self):
        application = App()

        @application.route("/users/<int:id>")
        @application.route("/users/<int:id>/delete", methods=["DELETE"])
        def user(id):
            return str(id)

        @application.route("/post/<int:id>")
        def post(id):
            return str(id)

        return application

    def test_an_anchor_becomes_a_fragment(self):
        assert self.build().url_for("post", id=1, _anchor="top") == "/post/1#top"

    def test_no_anchor_means_no_fragment(self):
        assert self.build().url_for("post", id=1) == "/post/1"

    def test_an_empty_anchor_is_still_a_fragment(self):
        assert self.build().url_for("post", id=1, _anchor="") == "/post/1#"

    def test_another_method_picks_the_other_rule(self):
        assert self.build().url_for("user", id=3, _method="delete") == "/users/3/delete"

    def test_without_it_the_first_rule_registered_wins(self):
        # decorators run bottom up, so the delete rule is registered first
        assert self.build().url_for("user", id=3) == "/users/3/delete"

    def test_asking_for_a_method_no_rule_answers_fails(self):
        with pytest.raises(Exception):
            self.build().url_for("user", id=3, _method="put")

    def test_a_route_named_after_a_verb_is_left_alone(self):
        assert self.build().url_for("post", id=1, _method="get") == "/post/1"


class TestAutomaticOptions:
    def build(self):
        application = App()

        @application.route("/users", methods=["GET", "POST"])
        def users():
            return []

        return application

    def test_options_is_answered(self):
        assert self.build().test_client().open("/users", "OPTIONS").status_code == 200

    def test_the_allow_header_lists_the_methods(self):
        response = self.build().test_client().open("/users", "OPTIONS")
        assert set(response.get_header("Allow").split(", ")) == {"GET", "HEAD", "OPTIONS", "POST"}

    def test_there_is_no_body(self):
        assert self.build().test_client().open("/users", "OPTIONS").data == b""

    def test_an_unknown_path_is_still_a_404(self):
        assert self.build().test_client().open("/nothing", "OPTIONS").status_code == 404

    def test_a_path_with_only_get_offers_get(self):
        application = App()

        @application.route("/one")
        def one():
            return "one"

        response = application.test_client().open("/one", "OPTIONS")
        assert set(response.get_header("Allow").split(", ")) == {"GET", "HEAD", "OPTIONS"}


class TestTrustedHosts:
    def test_an_unknowable_host_is_refused(self):
        application = App()
        application.config["TRUSTED_HOSTS"] = ["example.com"]

        @application.route("/")
        def home():
            return "home"

        response = application.test_client().get("/", headers={"Host": "evil.test"})
        assert response.status_code == 400

    def test_a_trusted_host_gets_through(self):
        application = App()
        application.config["TRUSTED_HOSTS"] = ["example.com"]

        @application.route("/")
        def home():
            return "home"

        assert application.test_client().get("/", headers={"Host": "example.com"}).status_code == 200

    def test_a_port_does_not_matter(self):
        application = App()
        application.config["TRUSTED_HOSTS"] = ["example.com"]

        @application.route("/")
        def home():
            return "home"

        response = application.test_client().get("/", headers={"Host": "example.com:8000"})
        assert response.status_code == 200

    def test_no_list_means_any_host(self):
        application = App()

        @application.route("/")
        def home():
            return "home"

        assert application.test_client().get("/", headers={"Host": "anything.test"}).status_code == 200


class TestJSONProvider:
    def test_json_is_on_the_app(self):
        assert isinstance(App().json, JSON)

    def test_it_can_be_replaced(self):
        application = App()
        application.json = JSON(indent=4)

        @application.route("/")
        def home():
            return {"a": 1}

        assert application.test_client().get("/").text == '{\n    "a": 1\n}'

    def test_keys_can_be_sorted(self):
        application = App()
        application.json = JSON(sort_keys=True)

        @application.route("/")
        def home():
            return {"b": 1, "a": 2}

        assert application.test_client().get("/").text == '{"a": 2, "b": 1}'

    def test_debug_pretty_prints(self):
        application = App()
        application.config["DEBUG"] = True

        @application.route("/")
        def home():
            return {"a": 1}

        assert application.test_client().get("/").text == '{\n  "a": 1\n}'

    def test_testing_pretty_prints(self):
        application = App()
        application.config["TESTING"] = True

        @application.route("/")
        def home():
            return {"a": 1}

        assert application.test_client().get("/").text == '{\n  "a": 1\n}'

    def test_it_reads_json_back(self):
        assert JSON().loads('{"a": 1}') == {"a": 1}


class TestFormLimits:
    def build(self, parts=10, memory=1_000):
        application = App()
        application.config["MAX_FORM_PARTS"] = parts
        application.config["MAX_FORM_MEMORY_SIZE"] = memory

        @application.route("/form", methods=["POST"])
        def read(request):
            return {"keys": len(request.form)}

        return application

    def multipart(self, fields):
        boundary = "----gromon"
        raw = b""
        for key, value in fields.items():
            raw += (
                f'--{boundary}\r\nContent-Disposition: form-data; '
                f'name="{key}"\r\n\r\n{value}\r\n'
            ).encode()
        raw += f"--{boundary}--\r\n".encode()
        return raw, {"Content-Type": f"multipart/form-data; boundary={boundary}"}

    def post(self, application, fields):
        body, headers = self.multipart(fields)
        return application.test_client().post("/form", data=body, headers=headers)

    def test_a_small_form_goes_through(self):
        assert self.post(self.build(), {"a": "1", "b": "2"}).json == {"keys": 2}

    def test_too_many_parts_is_413(self):
        application = self.build(parts=3)
        assert self.post(application, {"a": "1", "b": "2", "c": "3", "d": "4"}).status_code == 413

    def test_too_much_text_is_413(self):
        application = self.build(memory=10)
        assert self.post(application, {"note": "x" * 100}).status_code == 413

    def test_the_limit_can_be_lifted(self):
        application = self.build(parts=0, memory=0)
        assert self.post(application, {"a": "1"}).status_code == 200
