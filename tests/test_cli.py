"""The command line: run, reload, and the routes table."""

import subprocess
import sys

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


def run(*arguments):
    finished = subprocess.run(
        [sys.executable, "-m", "gromon", *arguments],
        capture_output=True,
        text=True,
        timeout=60,
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
