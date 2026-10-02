"""The command line: run, reload, and the routes table."""

import subprocess
import sys
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
        # only here when we are working locally.
        if not Path("examples/starter").is_dir():
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
