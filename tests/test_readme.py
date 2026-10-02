"""The examples in README.md, run for real so they cannot rot."""

from gromon import (
    App,
    MethodView,
    flash,
    get_flashed_messages,
    redirect,
    request,
    route,
    session,
)


def test_the_quickstart_builds_an_app():
    application = App()

    @application.route("/")
    def home():
        return {"message": "Hello World"}

    assert application.test_client().get("/").json == {"message": "Hello World"}


def test_the_methodview_example():
    application = App()

    @application.route("/users")
    class Users(MethodView):
        def get(self):
            return []

        def post(self, request):
            return {"created": True}, 201

    @application.route("/users/<int:id>", methods=["DELETE"])
    class User(MethodView):
        def delete(self, id):
            return None

    client = application.test_client()
    assert client.get("/users").json == []
    assert client.post("/users", json={"name": "ada"}).json == {"created": True}
    assert client.delete("/users/7").status_code == 204


def test_the_testing_example():
    application = App()

    load, save = session("a-long-random-secret")
    application.use(load)
    application.after(save)

    @application.route("/")
    def home():
        return "home"

    @application.route("/users", methods=["POST"])
    def create(request):
        request.session["name"] = request.json()["name"]
        return {"created": True}

    @application.route("/me")
    def me():
        return {"name": request.session["name"]}

    client = application.test_client()

    assert client.get("/").status_code == 200
    assert client.post("/users", json={"name": "ada"}).json["created"]

    response = client.get("/me")
    assert response.json["name"] == "ada"


def test_the_flash_example():
    application = App()

    load, save = session("a-long-random-secret")
    application.use(load)
    application.after(save)

    @application.route("/save", methods=["POST"])
    def save():
        flash("Saved", "info")
        return redirect("/")

    @application.route("/")
    def home():
        return get_flashed_messages(with_categories=True)

    client = application.test_client()
    client.post("/save")
    assert client.get("/").json == [["info", "Saved"]]
    assert client.get("/").json == []


def test_the_streaming_example():
    application = App()

    @application.route("/events")
    def events():
        def stream():
            for tick in range(3):
                yield f"data: {tick}\n\n"

        return stream()

    client = application.test_client()
    assert client.get("/events").text == "data: 0\n\ndata: 1\n\ndata: 2\n\n"


def test_the_config_example():
    application = App()
    application.config["DEBUG"] = True

    @application.route("/debug")
    def debug():
        return {"debug": application.config["DEBUG"]}

    assert application.test_client().get("/debug").json == {"debug": True}


def test_the_teardown_example():
    application = App()

    @application.route("/")
    def home():
        return "home"

    @application.teardown
    def close(request):
        application.closed = True

    assert application.test_client().get("/").status_code == 200
    assert application.closed is True


def test_the_url_for_extras_example():
    application = App()

    @application.route("/users/<int:id>")
    @application.route("/users/<int:id>/delete", methods=["DELETE"])
    def user(id):
        return application.url_for("user", id=id, _method="delete")

    assert application.test_client().get("/users/7").text == "/users/7/delete"


def test_the_url_defaults_example():
    application = App()

    @application.route("/<lang>/page")
    def page(lang):
        return lang

    @application.url_defaults
    def language(endpoint, values):
        values.setdefault("lang", "en")

    assert application.url_for("page") == "/en/page"
    assert application.url_for("page", lang="fr") == "/fr/page"
    assert application.url_for("page", _anchor="top") == "/en/page#top"


def test_the_json_provider_example():
    from gromon import JSON

    application = App()
    application.json = JSON(indent=4, sort_keys=True)

    @application.route("/")
    def home():
        return {"b": 1, "a": 2}

    assert application.test_client().get("/").text == '{\n    "a": 2,\n    "b": 1\n}'


def test_the_config_loading_example(tmp_path):
    import json as json_module
    import os

    settings = tmp_path / "settings.py"
    settings.write_text("DEBUG = True\nGREETING = 'hi'\n")
    os.environ["GROMON_DEMO__HOST"] = "example.com"
    try:
        application = App()
        application.config.from_env("GROMON_")
        os.environ["GROMON_TEST_SETTINGS"] = str(settings)
        application.config.from_envvar("GROMON_TEST_SETTINGS")

        assert application.config["DEMO"] == {"HOST": "example.com"}

        data = tmp_path / "settings.json"
        data.write_text(json_module.dumps({"PORT": 8000}))
        application.config.from_file(data, json_module.load)
        assert application.config["PORT"] == 8000

        class Settings:
            SECRET_NAME = "from-object"

        application.config.from_object(Settings)
        assert application.config["SECRET_NAME"] == "from-object"
        assert application.config["GREETING"] == "hi"
    finally:
        os.environ.pop("GROMON_DEMO__HOST", None)
        os.environ.pop("GROMON_TEST_SETTINGS", None)


def test_options_is_answered_without_being_written():
    application = App()

    @application.route("/users", methods=["GET", "POST"])
    def users():
        return []

    response = application.test_client().open("/users", "OPTIONS")
    assert response.status_code == 200
    assert "POST" in response.get_header("Allow")


def test_the_config_table_example():
    application = App()

    @application.route("/", methods=["POST"])
    def home(request):
        return {"ok": True}

    application.config["MAX_CONTENT_LENGTH"] = 10
    client = application.test_client()
    assert client.post("/", json={"padding": "x" * 40}).status_code == 413
    assert client.post("/", json={"ok": 1}).status_code == 200

    application.config["TRUSTED_HOSTS"] = ["example.com"]
    assert client.get("/", headers={"Host": "evil.test"}).status_code == 400


def test_the_two_apps_in_one_file_example():
    api = App()

    @api.route("/ping")
    def ping():
        return "pong"

    assert api.test_client().get("/ping").text == "pong"


def test_the_routes_table_matches_the_documented_output():
    application = App()

    @application.route("/")
    def home():
        return "home"

    @application.route("/user/<int:id>")
    def user(id):
        return str(id)

    @application.route("/echo", methods=["POST"])
    def echo():
        return "echo"

    lines = application.routes_table().splitlines()
    assert lines[0].split() == ["METHODS", "PATH", "ENDPOINT"]
    assert lines[1].split() == ["GET,HEAD", "/", "home"]
    assert lines[2].split() == ["GET,HEAD", "/user/<int:id>", "user"]
    assert lines[3].split() == ["POST", "/echo", "echo"]


def test_the_global_decorators_work_on_a_methodview():
    from gromon.app import app

    app.routes.clear()

    @route("/readme-users")
    class ReadmeUsers(MethodView):
        def get(self):
            return ["ok"]

    try:
        assert app.test_client().get("/readme-users").json == ["ok"]
    finally:
        app.routes.clear()
