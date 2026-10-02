"""The command line: run, reload, and the routes table."""

import os
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

import pytest

APP = """
from gromon import App

app = App()


@app.route("/")
def home():
    return "home"


@app.route("/user/<int:id>", methods=["GET", "POST"])
def user(id):
    return str(id)


@app.route("/echo", methods=["POST"])
def echo():
    return "echo"
"""


def run(*arguments, cwd=None):
    finished = subprocess.run(
        [sys.executable, "-m", "gromon", *arguments],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=cwd,
    )
    return finished


class TestRoutesCommand:
    def table(self, source=APP):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "site.py"
            path.write_text(source)
            finished = run("routes", str(path))
        assert finished.returncode == 0, finished.stderr
        return finished.stdout

    def test_it_prints_a_header(self):
        assert "METHODS" in self.table()

    def test_every_route_is_listed(self):
        table = self.table()
        assert "/" in table
        assert "/user/<int:id>" in table
        assert "/echo" in table

    def test_the_methods_are_shown(self):
        table = self.table()
        assert "GET,HEAD" in table
        assert "POST" in table

    def test_the_endpoint_is_shown(self):
        assert "home" in self.table()

    def test_a_python_module_works_too(self):
        finished = run("routes", "examples/blog")
        assert finished.returncode == 0, finished.stderr
        assert "/admin/stats" in finished.stdout

    def test_a_missing_file_fails_clearly(self):
        finished = run("routes", "nope-does-not-exist.py")
        assert finished.returncode != 0
        assert "nope-does-not-exist.py" in finished.stderr


TWO_FILES = {
    "app.py": (
        "from gromon import App\n"
        "from views import extra\n"
        "\n"
        "app = App()\n"
        "app.register(extra)\n"
        "\n"
        "\n"
        "@app.route('/')\n"
        "def home():\n"
        "    return 'home'\n"
    ),
    "views.py": (
        "from gromon import Blueprint\n"
        "\n"
        "extra = Blueprint('extra', '/extra')\n"
        "\n"
        "\n"
        "@extra.route('/more')\n"
        "def more():\n"
        "    return 'more'\n"
    ),
}


class TestAnAppSplitOverFiles:
    """A folder of modules has to import as `python app.py` would."""

    def write(self, folder):
        from pathlib import Path

        for name, source in TWO_FILES.items():
            (Path(folder) / name).write_text(source)

    def test_routes_lists_both_files(self, tmp_path):
        self.write(tmp_path)
        finished = run("routes", str(tmp_path))
        assert finished.returncode == 0, finished.stderr
        assert "/extra/more" in finished.stdout

    def test_run_imports_the_sibling_module(self, tmp_path):
        self.write(tmp_path)
        finished = run("run", "--no-reload", str(tmp_path))
        assert finished.returncode == 0, finished.stderr

    def test_the_starter_example_imports_too(self):
        # examples/starter is our scratch app: it is not published, so it is
        # only here when we are working locally, and an emptied one is skipped
        # rather than failing the suite.
        if not Path("examples/starter/app.py").is_file():
            pytest.skip("examples/starter is not part of the published repo")
        finished = run("routes", "examples/starter")
        assert finished.returncode == 0, finished.stderr
        assert "/posts/<int:id>" in finished.stdout


MIXED = (
    "from gromon import App, register, route\n"
    "\n"
    "app = App()\n"
    "register(__import__('gromon').Blueprint('b', '/b'))\n"
    "\n"
    "\n"
    "@app.route('/mine')\n"
    "def mine():\n"
    "    return 'mine'\n"
    "\n"
    "\n"
    "@route('/theirs')\n"
    "def theirs():\n"
    "    return 'theirs'\n"
)


class TestMixingAppAndGlobals:
    def test_the_split_is_reported(self, tmp_path):
        from pathlib import Path

        (Path(tmp_path) / "app.py").write_text(MIXED)
        finished = run("routes", str(tmp_path))
        assert "warning" in finished.stderr
        assert "not both" in finished.stderr

    def test_the_named_app_is_still_listed(self, tmp_path):
        from pathlib import Path

        (Path(tmp_path) / "app.py").write_text(MIXED)
        finished = run("routes", str(tmp_path))
        assert "/mine" in finished.stdout


class TestNewProject:
    def scaffold(self, tmp_path, *arguments):
        return run("new", *arguments, cwd=str(tmp_path))

    def test_it_writes_a_project_that_runs(self, tmp_path):
        finished = self.scaffold(tmp_path, "myapp")
        assert finished.returncode == 0, finished.stderr

        project = Path(tmp_path) / "myapp"
        for relative in (
            "app.py",
            "requirements.txt",
            "README.md",
            ".gitignore",
            "templates/base.html",
            "templates/index.html",
            "templates/404.html",
            "static/site.fscss",
            "static/app.js",
            "static/fscss.min.js",
        ):
            assert (project / relative).is_file(), relative

        sys.path.insert(0, str(project))
        try:
            module = __import__("app")
            client = module.app.test_client()
            assert client.get("/").status_code == 200
            assert client.get("/api/hello").json == {"hello": "world", "visits": 2}
        finally:
            sys.path.remove(str(project))
            sys.modules.pop("app", None)

    def test_the_page_links_the_stylesheet_and_the_script(self, tmp_path):
        self.scaffold(tmp_path, "myapp")
        project = Path(tmp_path) / "myapp"
        base = (project / "templates" / "base.html").read_text()
        assert 'type="fscss"' in base
        assert "site.fscss" in base
        assert "app.js" in base

    def test_the_compiler_is_served_by_the_app_not_a_cdn(self, tmp_path):
        self.scaffold(tmp_path, "myapp")
        project = Path(tmp_path) / "myapp"

        base = (project / "templates" / "base.html").read_text()
        assert "fscss.min.js" in base
        assert "cdn.jsdelivr.net" not in base

        runtime = project / "static" / "fscss.min.js"
        assert runtime.stat().st_size > 1000

        sys.path.insert(0, str(project))
        try:
            module = __import__("app")
            served = module.app.test_client().get("/static/fscss.min.js")
            assert served.status_code == 200
            assert served.get_header("Content-Type") == "text/javascript"
        finally:
            sys.path.remove(str(project))
            sys.modules.pop("app", None)

    def test_the_stylesheet_is_fscss(self, tmp_path):
        self.scaffold(tmp_path, "myapp")
        styles = (Path(tmp_path) / "myapp" / "static" / "site.fscss").read_text()
        assert "@define card(" in styles
        # a $variable is only safe as a plain value, never as a @define argument
        assert "@use(pad)" in styles

    def test_it_refuses_a_folder_with_files_in_it(self, tmp_path):
        self.scaffold(tmp_path, "myapp")
        (Path(tmp_path) / "myapp" / "app.py").write_text("# mine\n")

        finished = self.scaffold(tmp_path, "myapp")
        assert finished.returncode != 0
        assert "already has files" in finished.stderr
        assert (Path(tmp_path) / "myapp" / "app.py").read_text() == "# mine\n"

    def test_it_uses_an_empty_folder(self, tmp_path):
        (Path(tmp_path) / "ready").mkdir()
        finished = self.scaffold(tmp_path, "ready")
        assert finished.returncode == 0, finished.stderr
        assert (Path(tmp_path) / "ready" / "app.py").is_file()

    def test_it_rejects_a_name_it_could_not_use(self, tmp_path):
        for name in ("9lives", "my app", "class"):
            finished = self.scaffold(tmp_path, name)
            assert finished.returncode != 0, name
            assert not (Path(tmp_path) / name).exists(), name

    def test_it_needs_a_name(self, tmp_path):
        finished = self.scaffold(tmp_path)
        assert finished.returncode != 0
        assert "needs a project name" in finished.stderr

    def test_it_prints_the_next_steps(self, tmp_path):
        finished = self.scaffold(tmp_path, "myapp")
        assert "pip install -r requirements.txt" in finished.stdout
        assert "gromon run myapp" in finished.stdout


class TestNewProjectFromATemplate:
    def template(self, tmp_path):
        source = Path(tmp_path) / "starter"
        (source / "api" / "{name}").mkdir(parents=True)
        (source / "tests").mkdir()
        (source / "app.py").write_text('"""A {name} starter."""\n')
        (source / "README.md").write_text("# {name}\n")
        (source / "api" / "{name}" / "__init__.py").write_text('NAME = "{name}"\n')
        (source / "tests" / "test_it.py").write_text("def test_it():\n    assert True\n")
        return source

    def start(self, tmp_path, *arguments):
        return run("new", *arguments, cwd=str(tmp_path))

    def test_the_template_becomes_the_project(self, tmp_path):
        source = self.template(tmp_path)
        finished = self.start(tmp_path, "shop", "--template", str(source))
        assert finished.returncode == 0, finished.stderr

        project = Path(tmp_path) / "shop"
        assert (project / "app.py").is_file()
        assert (project / "README.md").is_file()
        assert (project / "tests" / "test_it.py").is_file()

    def test_it_replaces_the_built_in_starter_rather_than_adding_to_it(self, tmp_path):
        source = self.template(tmp_path)
        self.start(tmp_path, "shop", "--template", str(source))

        project = Path(tmp_path) / "shop"
        assert not (project / "templates").exists()
        assert not (project / "static").exists()
        assert not (project / "requirements.txt").exists()

    def test_the_project_name_is_filled_in_files_and_paths(self, tmp_path):
        source = self.template(tmp_path)
        self.start(tmp_path, "shop", "--template", str(source))

        project = Path(tmp_path) / "shop"
        assert (project / "api" / "shop" / "__init__.py").is_file()
        assert 'NAME = "shop"' in (project / "api" / "shop" / "__init__.py").read_text()
        assert "shop" in (project / "README.md").read_text()
        assert "{name}" not in (project / "README.md").read_text()

    def test_it_leaves_out_junk_a_git_checkout_carries(self, tmp_path):
        source = self.template(tmp_path)
        (source / ".git").mkdir()
        (source / ".git" / "config").write_text("[core]\n")
        (source / "__pycache__").mkdir()
        (source / "__pycache__" / "stale.pyc").write_bytes(b"\x00stale")
        (source / "notes.pyc").write_bytes(b"\x00")

        self.start(tmp_path, "shop", "--template", str(source))

        project = Path(tmp_path) / "shop"
        assert not (project / ".git").exists()
        assert not (project / "__pycache__").exists()
        assert not (project / "notes.pyc").exists()

    def test_a_binary_file_is_copied_as_it_is(self, tmp_path):
        source = self.template(tmp_path)
        original = bytes([0, 1, 2, 255, 254, 66])
        (source / "logo.bin").write_bytes(original)

        self.start(tmp_path, "shop", "--template", str(source))
        assert (Path(tmp_path) / "shop" / "logo.bin").read_bytes() == original

    def test_the_next_steps_do_not_mention_a_file_it_did_not_write(self, tmp_path):
        source = self.template(tmp_path)
        finished = self.start(tmp_path, "shop", "--template", str(source))
        assert "requirements.txt" not in finished.stdout
        assert "pip install gromon" in finished.stdout

    def test_a_missing_template_folder_says_so(self, tmp_path):
        finished = self.start(tmp_path, "shop", "--template", str(tmp_path / "nope"))
        assert finished.returncode != 0
        assert "no template folder" in finished.stderr
        assert not (Path(tmp_path) / "shop").exists()

    def test_template_without_a_folder_says_so(self, tmp_path):
        finished = self.start(tmp_path, "shop", "--template")
        assert finished.returncode != 0
        assert "--template needs a folder" in finished.stderr

    def test_two_names_are_refused(self, tmp_path):
        finished = self.start(tmp_path, "one", "two")
        assert finished.returncode != 0
        assert "one project name" in finished.stderr

    def test_it_still_guards_the_target_folder(self, tmp_path):
        source = self.template(tmp_path)
        self.start(tmp_path, "shop", "--template", str(source))
        (Path(tmp_path) / "shop" / "app.py").write_text("# mine\n")

        finished = self.start(tmp_path, "shop", "--template", str(source))
        assert finished.returncode != 0
        assert "already has files" in finished.stderr


class TestTemplateOptionSpelling:
    def test_a_single_dash_t_is_the_same_flag(self, tmp_path):
        source = Path(tmp_path) / "starter"
        source.mkdir()
        (source / "app.py").write_text("# {name}\n")

        finished = run("new", "shop", "--t", str(source), cwd=str(tmp_path))
        assert finished.returncode == 0, finished.stderr
        assert (Path(tmp_path) / "shop" / "app.py").is_file()

    def test_the_template_can_be_written_with_an_equals_sign(self, tmp_path):
        source = Path(tmp_path) / "starter"
        source.mkdir()
        (source / "app.py").write_text("# {name}\n")

        finished = run("new", "shop", f"--template={source}", cwd=str(tmp_path))
        assert finished.returncode == 0, finished.stderr
        assert (Path(tmp_path) / "shop" / "app.py").is_file()

    def test_an_unknown_option_says_so_rather_than_reading_as_a_name(self, tmp_path):
        finished = run("new", "shop", "--tempo", ".", cwd=str(tmp_path))
        assert finished.returncode != 0
        assert "unknown option --tempo" in finished.stderr
        assert not (Path(tmp_path) / "shop").exists()

    def test_the_name_may_come_before_or_after_the_option(self, tmp_path):
        source = Path(tmp_path) / "starter"
        source.mkdir()
        (source / "app.py").write_text("# {name}\n")

        finished = run("new", "--t", str(source), "shop", cwd=str(tmp_path))
        assert finished.returncode == 0, finished.stderr
        assert (Path(tmp_path) / "shop" / "app.py").is_file()


class TestEmptyTemplate:
    def test_an_empty_template_folder_says_so(self, tmp_path):
        source = Path(tmp_path) / "starter"
        source.mkdir()

        finished = run("new", "shop", "--template", str(source), cwd=str(tmp_path))
        assert finished.returncode != 0
        assert "no files in the template folder" in finished.stderr
        assert "Traceback" not in finished.stderr

    def test_a_template_of_only_junk_is_treated_as_empty(self, tmp_path):
        source = Path(tmp_path) / "starter"
        (source / "__pycache__").mkdir(parents=True)
        (source / "__pycache__" / "stale.pyc").write_bytes(b"\x00")

        finished = run("new", "shop", "--template", str(source), cwd=str(tmp_path))
        assert finished.returncode != 0
        assert "no files in the template folder" in finished.stderr

    def test_an_empty_dot_template_does_not_crash(self, tmp_path):
        finished = run("createapp", "shop", "--template", ".", cwd=str(tmp_path))
        assert finished.returncode != 0
        assert "no files in the template folder" in finished.stderr
        assert "IndexError" not in finished.stderr


def serving(folder, name, tries=60):
    """Start `gromon run name` for real and return the status it answers with.

    The test apps here deliberately have no `app.run()`, so importing one proves
    nothing about the server. This actually boots it and asks it a question.
    """
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    child = subprocess.Popen(
        [sys.executable, "-m", "gromon", "run", name, "--no-reload", "--port", str(port)],
        cwd=str(folder),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        for _ in range(tries):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as reply:
                    return reply.status
            except OSError:
                if child.poll() is not None:
                    pytest.fail(f"the server stopped early: {child.communicate()[0]}")
                time.sleep(0.25)
        pytest.fail(f"the server never answered on port {port}")
    finally:
        child.terminate()
        child.wait(timeout=10)


class TestAnEntryPointIsAlwaysThere:
    def library(self, tmp_path):
        source = Path(tmp_path) / "lib"
        (source / "pkg").mkdir(parents=True)
        (source / "pyproject.toml").write_text("[project]\nname = 'thing'\n")
        (source / "pkg" / "__init__.py").write_text("VALUE = 1\n")
        return source

    def test_a_template_with_no_app_py_gets_one(self, tmp_path):
        source = self.library(tmp_path)
        finished = run("new", "shop", "--template", str(source), cwd=str(tmp_path))

        assert finished.returncode == 0, finished.stderr
        app = Path(tmp_path) / "shop" / "app.py"
        assert app.is_file()
        assert "shop" in app.read_text()

    def test_that_app_py_has_a_route(self, tmp_path):
        source = self.library(tmp_path)
        run("new", "shop", "--template", str(source), cwd=str(tmp_path))

        finished = run("routes", "shop", cwd=str(tmp_path))
        assert finished.returncode == 0, finished.stderr
        assert "/" in finished.stdout
        assert "/api/hello" in finished.stdout

    def test_that_app_py_actually_starts_the_server(self, tmp_path):
        source = self.library(tmp_path)
        run("new", "shop", "--template", str(source), cwd=str(tmp_path))
        assert serving(tmp_path, "shop") == 200

    def test_a_template_with_its_own_app_py_is_left_alone(self, tmp_path):
        source = self.library(tmp_path)
        (source / "app.py").write_text("# mine, {name}\n")

        run("new", "shop", "--template", str(source), cwd=str(tmp_path))
        assert (Path(tmp_path) / "shop" / "app.py").read_text() == "# mine, shop\n"

    def test_the_written_app_py_answers_requests(self, tmp_path):
        source = self.library(tmp_path)
        run("new", "shop", "--template", str(source), cwd=str(tmp_path))

        script = (
            "import runpy\n"
            "built = runpy.run_path('shop/app.py')['app']\n"
            "print(built.test_client().get('/').json)\n"
        )
        finished = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert finished.returncode == 0, finished.stderr
        assert "shop" in finished.stdout

    def test_the_built_in_starter_serves_too(self, tmp_path):
        run("new", "shop", cwd=str(tmp_path))
        assert serving(tmp_path, "shop") == 200

    def test_the_built_in_starter_does_not_gain_a_second_app_py(self, tmp_path):
        finished = run("new", "shop", cwd=str(tmp_path))
        assert finished.returncode == 0, finished.stderr
        assert (Path(tmp_path) / "shop" / "app.py").is_file()
        assert "app.run()" in (Path(tmp_path) / "shop" / "app.py").read_text()


class TestRunningAFolderThatIsNotAnApp:
    def make(self, tmp_path, name="shop"):
        folder = Path(tmp_path) / name
        folder.mkdir()
        return folder

    def test_a_library_folder_says_it_looks_like_a_library(self, tmp_path):
        folder = self.make(tmp_path)
        (folder / "pyproject.toml").write_text("[project]\nname = 'thing'\n")

        finished = run("run", "--no-reload", "shop", cwd=str(tmp_path))
        assert finished.returncode != 0
        assert "has no app.py" in finished.stderr
        assert "library rather than an app" in finished.stderr
        assert "Traceback" not in finished.stderr

    def test_a_folder_with_other_python_files_lists_them(self, tmp_path):
        folder = self.make(tmp_path)
        (folder / "main.py").write_text("print('hi')\n")
        (folder / "server.py").write_text("print('hi')\n")

        finished = run("run", "--no-reload", "shop", cwd=str(tmp_path))
        assert finished.returncode != 0
        assert "main.py, server.py" in finished.stderr

    def test_an_empty_folder_says_there_is_nothing_to_run(self, tmp_path):
        self.make(tmp_path)
        finished = run("run", "--no-reload", "shop", cwd=str(tmp_path))
        assert finished.returncode != 0
        assert "no .py files" in finished.stderr

    def test_routes_gives_the_same_explanation(self, tmp_path):
        folder = self.make(tmp_path)
        (folder / "pyproject.toml").write_text("[project]\n")

        finished = run("routes", "shop", cwd=str(tmp_path))
        assert finished.returncode != 0
        assert "library rather than an app" in finished.stderr

    def test_a_folder_with_app_py_still_works(self, tmp_path):
        folder = self.make(tmp_path)
        (folder / "app.py").write_text(APP)
        (folder / "requirements.txt").write_text("gromon\n")

        finished = run("run", "--no-reload", "shop", cwd=str(tmp_path))
        assert finished.returncode == 0, finished.stderr


class TestRunWithoutAFile:
    def test_it_finds_the_app_you_are_standing_in(self, tmp_path):
        (Path(tmp_path) / "app.py").write_text(APP)
        (Path(tmp_path) / "requirements.txt").write_text("gromon\n")

        finished = run("run", "--no-reload", cwd=str(tmp_path))
        assert finished.returncode == 0, finished.stderr

    def test_it_still_needs_a_file_when_there_is_no_app(self, tmp_path):
        finished = run("run", "--no-reload", cwd=str(tmp_path))
        assert finished.returncode != 0
        assert "needs a file" in finished.stderr

    def test_routes_still_needs_a_file(self, tmp_path):
        (Path(tmp_path) / "app.py").write_text(APP)
        finished = run("routes", cwd=str(tmp_path))
        assert finished.returncode != 0
        assert "needs a file" in finished.stderr


class TestOnlineTemplate:
    def leaf(self, tmp_path):
        here = Path(tmp_path) / "starter"
        (here / "api").mkdir(parents=True, exist_ok=True)
        (here / "app.py").write_text('"""A {name} starter."""\n')
        (here / "api" / "{name}.py").write_text('NAME = "{name}"\n')
        (here / "logo.bin").write_bytes(bytes([0, 1, 2, 255]))
        return here

    def targz(self, tmp_path, wrapped=True):
        archive = Path(tmp_path) / "starter.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(self.leaf(tmp_path), arcname="starter-main" if wrapped else ".")
        return archive

    def zip(self, tmp_path, wrapped=True):
        archive = Path(tmp_path) / "starter.zip"
        root = self.leaf(tmp_path)
        with zipfile.ZipFile(archive, "w") as zipped:
            for item in sorted(root.rglob("*")):
                if item.is_file():
                    inside = str(item.relative_to(root))
                    zipped.write(item, f"starter-main/{inside}" if wrapped else inside)
        return archive

    def start(self, tmp_path, template):
        return run("new", "shop", "--template", template, cwd=str(tmp_path))

    def test_a_tar_archive_over_file_url(self, tmp_path):
        finished = self.start(tmp_path, self.targz(tmp_path).as_uri())
        assert finished.returncode == 0, finished.stderr
        assert '"""A shop starter."""' in (Path(tmp_path) / "shop" / "app.py").read_text()

    def test_a_zip_archive_over_file_url(self, tmp_path):
        finished = self.start(tmp_path, self.zip(tmp_path).as_uri())
        assert finished.returncode == 0, finished.stderr
        assert (Path(tmp_path) / "shop" / "api" / "shop.py").is_file()

    def test_it_steps_into_the_folder_an_archive_wraps_itself_in(self, tmp_path):
        self.start(tmp_path, self.targz(tmp_path).as_uri())
        assert not (Path(tmp_path) / "shop" / "starter-main").exists()

    def test_an_archive_with_nothing_wrapping_it(self, tmp_path):
        finished = self.start(tmp_path, self.targz(tmp_path, wrapped=False).as_uri())
        assert finished.returncode == 0, finished.stderr
        assert (Path(tmp_path) / "shop" / "app.py").is_file()

    def test_a_binary_file_survives_the_round_trip(self, tmp_path):
        self.start(tmp_path, self.targz(tmp_path).as_uri())
        assert (Path(tmp_path) / "shop" / "logo.bin").read_bytes() == bytes([0, 1, 2, 255])

    def test_junk_in_an_archive_is_left_out(self, tmp_path):
        here = self.leaf(tmp_path)
        (here / "__pycache__").mkdir()
        (here / "__pycache__" / "stale.pyc").write_bytes(b"\x00")
        archive = Path(tmp_path) / "starter.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(here, arcname="starter-main")

        self.start(tmp_path, archive.as_uri())
        assert not (Path(tmp_path) / "shop" / "__pycache__").exists()

    def test_an_address_that_is_not_there_says_so(self, tmp_path):
        finished = self.start(tmp_path, "https://gromon.invalid/nope.tar.gz")
        assert finished.returncode != 0
        assert "could not fetch" in finished.stderr
        assert "Traceback" not in finished.stderr

    def test_something_that_is_not_an_archive_says_so(self, tmp_path):
        page = Path(tmp_path) / "page.html"
        page.write_text("<html>not an archive</html>")
        finished = self.start(tmp_path, page.as_uri())

        assert finished.returncode != 0
        assert "could not fetch" in finished.stderr
        assert "Traceback" not in finished.stderr

    def test_a_tar_cannot_write_outside_itself(self, tmp_path):
        archive = Path(tmp_path) / "evil.tar.gz"
        payload = Path(tmp_path) / "payload.txt"
        payload.write_text("gotcha")
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(payload, arcname="../../escaped.txt")

        finished = self.start(tmp_path, archive.as_uri())
        assert finished.returncode != 0
        assert "outside itself" in finished.stderr

    def test_a_zip_cannot_write_outside_itself(self, tmp_path):
        archive = Path(tmp_path) / "evil.zip"
        payload = Path(tmp_path) / "payload.txt"
        payload.write_text("gotcha")
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.write(payload, "../../escaped.txt")

        finished = self.start(tmp_path, archive.as_uri())
        assert finished.returncode != 0
        assert "outside itself" in finished.stderr

    def test_a_local_folder_wins_over_the_github_shorthand(self, tmp_path):
        source = Path(tmp_path) / "owner" / "repo"
        source.mkdir(parents=True)
        (source / "app.py").write_text("# {name}\n")

        finished = run("new", "shop", "--template", "owner/repo", cwd=str(tmp_path))
        assert finished.returncode == 0, finished.stderr
        assert (Path(tmp_path) / "shop" / "app.py").is_file()

    def test_a_github_shorthand_becomes_an_address(self):
        from gromon.scaffold import where

        assert where("someone/starter") == (
            "https://github.com/someone/starter/archive/refs/heads/main.tar.gz"
        )
        assert where("https://example.com/s.zip") == "https://example.com/s.zip"

    def test_a_git_url_is_left_alone(self):
        from gromon.scaffold import where

        assert where("https://github.com/someone/starter.git") == (
            "https://github.com/someone/starter.git"
        )


class TestUnsafeTemplates:
    def test_the_drive_root_is_refused(self):
        from gromon.scaffold import risky

        assert risky(Path(Path.cwd().anchor)) is True

    def test_the_home_folder_is_refused(self):
        from gromon.scaffold import risky

        assert risky(Path.home()) is True

    def test_an_ordinary_folder_is_fine(self, tmp_path):
        from gromon.scaffold import risky

        assert risky(Path(tmp_path)) is False

    def test_a_file_that_cannot_be_read_says_so(self, tmp_path):
        source = Path(tmp_path) / "starter"
        source.mkdir()
        locked = source / "locked.txt"
        locked.write_text("# {name}\n")
        locked.chmod(0o000)

        finished = run("new", "shop", "--template", str(source), cwd=str(tmp_path))
        readable = os.access(locked, os.R_OK)
        locked.chmod(0o644)
        if readable:
            pytest.skip("this user can still read a file with permissions removed")
        assert finished.returncode != 0
        assert "could not read" in finished.stderr
        assert "Traceback" not in finished.stderr

    def test_a_local_path_that_is_not_there_is_not_mistaken_for_an_address(self, tmp_path):
        finished = run("new", "shop", "--template", str(tmp_path / "nope"), cwd=str(tmp_path))
        assert finished.returncode != 0
        assert "no template folder" in finished.stderr
        assert "unknown url type" not in finished.stderr

    def test_the_drive_root_cannot_be_copied(self, tmp_path):
        finished = run("new", "shop", "--template", Path.cwd().anchor, cwd=str(tmp_path))
        assert finished.returncode != 0
        assert "too big to be a template" in finished.stderr
        assert not (Path(tmp_path) / "shop").exists()


class TestCls:
    def test_cls_says_nothing_and_succeeds(self):
        finished = run("cls")
        assert finished.returncode == 0, finished.stderr
        assert finished.stdout.strip() == ""

    def test_cls_is_not_an_unknown_command(self):
        assert "unknown command" not in run("cls").stderr


class TestCreateappSpelling:
    def test_createapp_scaffolds_like_new(self, tmp_path):
        finished = run("createapp", "shop", cwd=str(tmp_path))
        assert finished.returncode == 0, finished.stderr
        assert (Path(tmp_path) / "shop" / "app.py").is_file()

    def test_createapp_names_the_folder_it_wrote(self, tmp_path):
        finished = run("createapp", "shop", cwd=str(tmp_path))
        assert "Created shop/" in finished.stdout

    def test_new_still_works(self, tmp_path):
        finished = run("new", "shop", cwd=str(tmp_path))
        assert finished.returncode == 0, finished.stderr
        assert (Path(tmp_path) / "shop" / "app.py").is_file()


class TestTemplateFromTheCurrentFolder:
    def here(self, tmp_path):
        (tmp_path / "sub").mkdir(parents=True, exist_ok=True)
        (tmp_path / "app.py").write_text('"""A {name} starter."""\n')
        (tmp_path / "sub" / "helper.py").write_text("NAME = '{name}'\n")
        return tmp_path

    def test_a_dot_copies_the_folder_you_are_in(self, tmp_path):
        self.here(tmp_path)
        finished = run("createapp", "shop", "--template", ".", cwd=str(tmp_path))

        assert finished.returncode == 0, finished.stderr
        project = Path(tmp_path) / "shop"
        assert '"""A shop starter."""' in (project / "app.py").read_text()
        assert "NAME = 'shop'" in (project / "sub" / "helper.py").read_text()

    def test_a_dot_does_not_copy_the_folder_it_is_writing_into(self, tmp_path):
        self.here(tmp_path)
        finished = run("createapp", "shop", "--template", ".", cwd=str(tmp_path))

        assert finished.returncode == 0, finished.stderr
        project = Path(tmp_path) / "shop"
        assert not (project / "shop").exists()
        assert not (project / "sub" / "shop").exists()

    def test_a_dot_does_not_reach_a_folder_named_like_the_project(self, tmp_path):
        self.here(tmp_path)
        (Path(tmp_path) / "shop").mkdir()

        finished = run("createapp", "shop", "--template", ".", cwd=str(tmp_path))
        assert finished.returncode == 0, finished.stderr
        assert not (Path(tmp_path) / "shop" / "shop").exists()

    def test_a_dot_still_leaves_out_junk(self, tmp_path):
        self.here(tmp_path)
        (Path(tmp_path) / "__pycache__").mkdir()
        (Path(tmp_path) / "__pycache__" / "stale.pyc").write_bytes(b"\x00")

        run("createapp", "shop", "--template", ".", cwd=str(tmp_path))
        assert not (Path(tmp_path) / "shop" / "__pycache__").exists()
