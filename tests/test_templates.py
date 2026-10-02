from gromon import App
from gromon.templates import render


def page(folder, name, body):
    (folder / name).write_text(body)


def test_renders_a_template(tmp_path):
    page(tmp_path, "hi.html", "<h1>Hello {{ name }}</h1>")
    assert render("hi.html", folder=str(tmp_path), name="Ada") == "<h1>Hello Ada</h1>"


def test_escapes_html_by_default(tmp_path):
    page(tmp_path, "x.html", "{{ value }}")
    assert render("x.html", folder=str(tmp_path), value="<script>") == "&lt;script&gt;"


def test_environment_is_reused(tmp_path):
    page(tmp_path, "a.html", "A")
    assert render("a.html", folder=str(tmp_path)) == "A"
    assert render("a.html", folder=str(tmp_path)) == "A"


def test_app_render_uses_its_template_folder(tmp_path):
    page(tmp_path, "b.html", "Hi {{ n }}")
    app = App(template_folder=str(tmp_path))
    assert app.render("b.html", n=1) == "Hi 1"


def test_url_for_is_always_in_a_template(tmp_path):
    """Templates ask for routes by name, so url_for is a global, not a value."""
    app = App(template_folder=str(tmp_path))
    page(tmp_path, "link.html", """<a href="{{ url_for('home') }}">home</a>""")

    @app.route("/")
    def home():
        return app.render("link.html")

    assert app.test_client().get("/").text == '<a href="/">home</a>'


def test_url_for_follows_the_app_serving_the_request(tmp_path):
    app = App(template_folder=str(tmp_path))
    page(tmp_path, "bp.html", "{{ url_for('posts.post', id=2) }}")

    from gromon import Blueprint

    posts = Blueprint("posts", "/posts")

    @posts.route("/<int:id>")
    def post(id):
        return str(id)

    app.register(posts)

    @app.route("/")
    def home():
        return app.render("bp.html")

    assert app.test_client().get("/").text == "/posts/2"


def test_the_request_is_always_in_a_template(tmp_path):
    app = App(template_folder=str(tmp_path))
    page(tmp_path, "path.html", "{{ request.path }}")

    @app.route("/where")
    def where():
        return app.render("path.html")

    assert app.test_client().get("/where").text == "/where"
