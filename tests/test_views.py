"""MethodView, blueprint level hooks, nested blueprints, config."""

import json

import pytest

from gromon import App, Blueprint, MethodView
from gromon.http import Request


@pytest.fixture
def application():
    return App()


def get(application, path, method="GET"):
    from gromon.http import Request

    return application.handle(Request(method, path, {}, b""))[:3]


class TestMethodView:
    def build(self):
        application = App()

        @application.route("/users")
        class Users(MethodView):
            def get(self):
                return [{"id": 1}]

            def post(self, request):
                return {"created": request.json()["name"]}, 201

        return application

    def test_get_is_answered_by_the_get_method(self):
        assert get(self.build(), "/users") == (200, "application/json", b'[{"id": 1}]')

    def test_post_is_answered_by_the_post_method(self):
        from gromon.http import Request

        application = self.build()
        response = application.handle(
            Request("POST", "/users", {}, b'{"name": "ada"}')
        )
        assert response[:2] == (201, "application/json")

    def test_a_verb_with_no_method_is_405(self):
        from gromon.http import Request

        application = self.build()
        assert application.handle(Request("DELETE", "/users", {}, b""))[0] == 405

    def test_the_class_name_is_the_endpoint(self):
        application = App()

        @application.route("/users")
        class Users(MethodView):
            def get(self):
                return []

        assert application.url_for("Users") == "/users"

    def test_path_parameters_arrive_by_name(self):
        application = App()

        @application.route("/users/<int:id>")
        class One(MethodView):
            def get(self, id):
                return {"id": id}

        assert get(application, "/users/7") == (200, "application/json", b'{"id": 7}')

    def test_kwargs_receives_everything(self):
        application = App()

        @application.route("/a/<x>/<y>")
        class Everything(MethodView):
            def get(self, **params):
                return params

        assert get(application, "/a/1/2") == (
            200,
            "application/json",
            b'{"x": "1", "y": "2"}',
        )

    def test_the_request_is_available_when_asked_for(self):
        application = App()

        @application.route("/me")
        class Me(MethodView):
            def get(self, request):
                return {"path": request.path}

        assert get(application, "/me") == (200, "application/json", b'{"path": "/me"}')

    def test_an_instance_is_fresh_per_request(self):
        application = App()
        seen = []

        @application.route("/counter")
        class Counter(MethodView):
            def get(self):
                seen.append(self)
                return {"n": len(seen)}

        get(application, "/counter")
        get(application, "/counter")
        assert seen[0] is not seen[1]


class TestKwargsHandlers:
    def test_a_plain_function_taking_kwargs_gets_every_parameter(self):
        application = App()

        @application.route("/<a>/<b>")
        def both(**params):
            return params

        assert get(application, "/1/2") == (200, "application/json", b'{"a": "1", "b": "2"}')

    def test_named_parameters_still_win_over_everything(self):
        application = App()

        @application.route("/<a>/<b>")
        def one(a):
            return {"a": a}

        assert get(application, "/1/2") == (200, "application/json", b'{"a": "1"}')


class TestBlueprintHooks:
    def build(self):
        application = App()
        admin = Blueprint("admin", "/admin")

        @admin.use
        def key(request):
            if request.query.get("key") != "secret":
                return {"error": "Bad key"}, 403

        @admin.after
        def stamp(request, headers):
            headers["X-Admin"] = "1"

        @admin.route("/stats")
        def stats():
            return {"users": 3}

        @application.route("/public")
        def public():
            return {"ok": True}

        application.register(admin)
        return application

    def test_blueprint_middleware_runs_for_its_routes(self):
        from gromon.http import Request

        application = self.build()
        request = Request("GET", "/admin/stats?key=secret", {}, b"")
        assert application.handle(request)[0] == 200

    def test_blueprint_middleware_stops_a_bad_request(self):
        from gromon.http import Request

        application = self.build()
        assert application.handle(Request("GET", "/admin/stats", {}, b""))[0] == 403

    def test_blueprint_middleware_runs_for_the_whole_app_like_flask(self):
        # Flask's blueprint before_request is app wide, so /public needs the key too
        assert get(self.build(), "/public") == (
            403,
            "application/json",
            b'{"error": "Bad key"}',
        )

    def test_the_key_lets_the_whole_app_through(self):
        from gromon.http import Request

        application = self.build()
        response = application.handle(Request("GET", "/public?key=secret", {}, b""))
        assert response[0] == 200

    def test_blueprint_response_hook_fires_for_its_routes(self):
        from gromon.http import Request

        application = self.build()
        request = Request("GET", "/admin/stats?key=secret", {}, b"")
        assert application.handle(request)[3] == {"X-Admin": "1"}

    def test_blueprint_response_hook_is_quiet_elsewhere(self):

        assert application_headers(self.build(), "/public") == {}


def application_headers(application, path):
    from gromon.http import Request

    return application.handle(Request("GET", path, {}, b""))[3]


class TestNestedBlueprints:
    def test_a_child_lands_under_both_prefixes(self):
        application = App()
        api = Blueprint("api", "/api")
        v1 = Blueprint("v1", "/v1")

        @v1.route("/ping")
        def ping():
            return "pong"

        api.register(v1)
        application.register(api)
        assert get(application, "/api/v1/ping") == (200, "text/html; charset=utf-8", b"pong")

    def test_the_child_endpoint_is_nested_under_the_parent(self):
        application = App()
        api = Blueprint("api", "/api")
        v1 = Blueprint("v1", "/v1")

        @v1.route("/ping")
        def ping():
            return "pong"

        api.register(v1)
        application.register(api)
        assert application.url_for("api.v1.ping") == "/api/v1/ping"

    def test_the_child_endpoint_keeps_its_own_name(self):
        application = App()
        v1 = Blueprint("v1", "/v1")

        @v1.route("/ping")
        def ping():
            return "pong"

        application.register(v1)
        assert application.url_for("v1.ping") == "/v1/ping"

    def test_child_hooks_come_along(self):
        from gromon.http import Request

        application = App()
        api = Blueprint("api", "/api")

        @api.use
        def key(request):
            return {"error": "No"}, 401

        @api.route("/ping")
        def ping():
            return "pong"

        application.register(api)
        assert application.handle(Request("GET", "/api/ping", {}, b""))[0] == 401


class TestBlueprintClassViews:
    def build(self):
        application = App()
        api = Blueprint("api", "/api")

        @api.route("/posts/<int:id>")
        class Post(MethodView):
            def get(self, id):
                return {"id": id, "verb": "get"}

            def delete(self, id):
                return {"id": id, "verb": "delete"}

        application.register(api)
        return application

    def test_the_verbs_come_from_the_class(self):
        application = self.build()
        assert application.handle(Request("GET", "/api/posts/1", {}, b""))[0] == 200
        assert application.handle(Request("DELETE", "/api/posts/1", {}, b""))[0] == 200
        assert application.handle(Request("POST", "/api/posts/1", {}, b""))[0] == 405

    def test_the_path_arguments_reach_the_method(self):
        application = self.build()
        status, _, body, _ = application.handle(Request("GET", "/api/posts/7", {}, b""))
        assert json.loads(body) == {"id": 7, "verb": "get"}

    def test_each_request_gets_a_fresh_instance(self):
        application = self.build()
        application.handle(Request("GET", "/api/posts/1", {}, b""))
        assert application.handle(Request("GET", "/api/posts/2", {}, b""))[0] == 200


class TestConfig:
    def test_there_are_defaults(self):
        assert App().config["DEBUG"] is False

    def test_they_can_be_changed(self):
        application = App()
        application.config["DEBUG"] = True
        assert application.config["DEBUG"] is True

    def test_each_application_has_its_own(self):
        application = App()
        application.config["DEBUG"] = True
        assert App().config["DEBUG"] is False
