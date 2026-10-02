"""The files `gromon new` writes, so a fresh app runs with no setup.

Kept as strings instead of package data on purpose: a scaffolded project should
never reach back into gromon/ for its own files, and it keeps every generated
file reviewable in one place.
"""

import contextlib
import keyword
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

NAME = re.compile(r"[A-Za-z][A-Za-z0-9._-]*")
GITHUB = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
ONLINE = ("http://", "https://", "file://", "git@", "ssh://")
ROOM = 200 * 1024 * 1024

# A template is usually a git checkout, so these are never part of the project.
SKIP = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".DS_Store",
}

APP = '''"""{name} - a Gromon app.

    gromon run {name}
    python app.py

Then open http://127.0.0.1:8000/
"""

from pathlib import Path

from gromon import App

HERE = Path(__file__).parent

app = App(static_folder=str(HERE / "static"), template_folder=str(HERE / "templates"))
app.config["TRUSTED_HOSTS"] = ["127.0.0.1", "localhost", "testserver"]

app.static()

visits = 0


@app.use
def count(request):
    """Middleware runs for every request. Returning None carries on."""
    global visits
    visits += 1


@app.route("/")
def home():
    return app.render("index.html", title="{name}", visits=visits)


@app.route("/api/hello")
def hello():
    return {"hello": "world", "visits": visits}


@app.error(404)
def missing(request):
    return app.render("404.html", title="{name}", path=request.path), 404


if __name__ == "__main__":
    app.run()
'''

BASE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ title }}</title>
    <link type="fscss" rel="stylesheet" href="{{ url_for('serve', path='site.fscss') }}">
    <script src="{{ url_for('serve', path='fscss.min.js') }}" async></script>
  </head>
  <body>
    <div class="shell">
      <nav><a class="brand" href="{{ url_for('home') }}">{{ title }}</a></nav>
      {% block body %}{% endblock %}
    </div>
    <script src="{{ url_for('serve', path='app.js') }}"></script>
  </body>
</html>
"""

INDEX = """{% extends "base.html" %}
{% block body %}
  <div class="card">
    <h1>{{ title }} is running</h1>
    <p class="muted">
      Gromon served this page from <code>templates/index.html</code> and styled it
      from <code>static/site.fscss</code>.
    </p>
    <p>Requests seen: <span id="visits">{{ visits }}</span></p>
    <button class="btn" id="ping" type="button">Call /api/hello</button>
    <pre id="out">static/app.js calls the API when you click.</pre>
  </div>
{% endblock %}
"""

NOT_FOUND = """{% extends "base.html" %}
{% block body %}
  <div class="card">
    <h1>404</h1>
    <p class="muted">Nothing is routed at <code>{{ path }}</code>.</p>
    <p><a class="btn" href="{{ url_for('home') }}">Back home</a></p>
  </div>
{% endblock %}
"""

SCRIPT = """const visits = document.querySelector("#visits");
const output = document.querySelector("#out");
const button = document.querySelector("#ping");

if (button) {
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const response = await fetch("/api/hello");
      const data = await response.json();
      if (visits) visits.textContent = data.visits;
      output.textContent = JSON.stringify(data, null, 2);
    } catch (error) {
      output.textContent = String(error);
    } finally {
      button.disabled = false;
    }
  });
}
"""

# FSCSS, not SCSS. @define blocks take their arguments by @use(name), and only
# plain values: passing a $variable there emits an undefined var() reference.
STYLES = """$ink: #0f172a;
$muted: #64748b;
$line: #e2e8f0;
$accent: #2563eb;
$shell: 44rem;

@define card(pad){
  background: #ffffff;
  border: 1px solid $line;
  border-radius: 12px;
  padding: @use(pad);
}

* { box-sizing: border-box; }

body {
  margin: 0;
  color: $ink;
  font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
  background: #f8fafc;
}

.shell { max-width: $shell; margin: 0 auto; padding: 3rem 1.25rem; }
nav { margin-bottom: 2rem; }
.brand { color: $accent; font-weight: 700; font-size: 1.1rem; text-decoration: none; }
.card { @card(1.5rem) }
.card h1 { margin-top: 0; }
.muted { color: $muted; }
.btn { background: $accent; color: #ffffff; border: 0; border-radius: 10px; padding: 0.7rem 1.3rem; font: inherit; font-weight: 600; cursor: pointer; }
.btn:hover { filter: brightness(1.08); }
a.btn { display: inline-block; text-decoration: none; }
code { background: #eef2ff; border-radius: 6px; padding: 0.15rem 0.4rem; font-size: 0.9em; }
pre { background: $ink; color: $line; padding: 1rem; border-radius: 10px; overflow-x: auto; }
pre code { background: none; color: inherit; padding: 0; }
"""

README = """# {name}

Built with [Gromon](https://github.com/Omonire-Great/gromon).

    pip install -r requirements.txt
    gromon run {name}

Then open http://127.0.0.1:8000/

## The files

    app.py               routes, the App object, one JSON endpoint
    templates/base.html  the layout every page extends
    templates/index.html the page at /
    static/site.fscss    styles, in FSCSS
    static/app.js        talks to /api/hello
    static/fscss.min.js  the FSCSS compiler, served from your own app

## Styles

`static/site.fscss` is [FSCSS](https://fscss.devtem.org/), which compiles to
plain CSS. `static/fscss.min.js` compiles it in the browser, so edits show up on
a refresh and there is no build step. Both files are served by your own app, so
this works offline and does not need npm.

To ship plain CSS instead, compile it once and point the link in `base.html` at
the result. That step does need npm:

    npm install -g fscss
    fscss static/site.fscss static/site.css

Two FSCSS notes: `$name` variables work anywhere, and an `@define` block reads
its arguments with `@use(name)`, so pass it plain values rather than `$variables`.
`static/fscss.min.js` is FSCSS 1.2.1 (MIT), from
https://cdn.jsdelivr.net/npm/fscss@1.2.1/runtime.min.js
"""

IGNORE = """__pycache__/
*.py[cod]
.venv/
.env
dist/
build/
*.egg-info/
"""

REQUIREMENTS = """gromon[templates]>=0.1.0
"""

FILES = {
    "app.py": APP,
    "templates/base.html": BASE,
    "templates/index.html": INDEX,
    "templates/404.html": NOT_FOUND,
    "static/site.fscss": STYLES,
    "static/app.js": SCRIPT,
    "README.md": README,
    ".gitignore": IGNORE,
    "requirements.txt": REQUIREMENTS,
}

# What a project gets: the nine files above, plus the runtime next to them.


def unusable(name):
    """Why this cannot be a folder name, or None when it is fine."""
    if not name or not NAME.fullmatch(name):
        return "a project name starts with a letter and holds letters, digits, dots, dashes"
    if keyword.iskeyword(name):
        return f"{name} is a Python keyword"
    return None


def compiler():
    """The FSCSS runtime that compiles a .fscss stylesheet in the browser.

    Copied into each project rather than pulled from a CDN, so a scaffolded app
    styles itself offline. FSCSS 1.2.1, MIT, from
    https://cdn.jsdelivr.net/npm/fscss@1.2.1/runtime.min.js
    """
    return Path(__file__).parent / "assets" / "fscss-runtime.min.js"


def create(name, template=None):
    """Write a starter project into a folder named after it.

    `template` is where to get the shape of the project from, so a team can keep
    it in git and scaffold from that instead of the built-in starter. It is a
    folder, or something online to fetch: an archive over http, https or file, a
    git repository, or a `owner/repo` shorthand. An empty target folder is fine
    to use, one with files in it is not: overwriting someone's work is not a
    default anybody wants.
    """
    problem = unusable(name)
    if problem:
        raise ValueError(problem)

    root = Path(name)
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"{name} already has files in it")

    if not template:
        return builtin(name, root)

    if Path(template).is_dir():
        source = Path(template)
        if risky(source):
            raise ValueError(f"{source} is too big to be a template, copy the part you want")
        return from_folder(name, root, source)

    if not online(template):
        raise ValueError(f"no template folder at {template}")

    with fetched(template) as folder:
        return from_folder(name, root, topmost(folder))


def online(template):
    """True when a template is somewhere to fetch rather than a folder here."""
    return template.startswith(ONLINE) or template.endswith(".git") or bool(GITHUB.fullmatch(template))


def risky(source):
    """True for a folder nobody meant to copy wholesale by accident."""
    here = source.resolve()
    return here == Path(here.anchor) or here == Path.home()


@contextlib.contextmanager
def fetched(template):
    """A local copy of a template from somewhere else, tidied up afterwards."""
    with tempfile.TemporaryDirectory() as scratch:
        folder = Path(scratch) / "template"
        folder.mkdir()
        try:
            if template.endswith(".git") or template.startswith(("git@", "ssh://")):
                clone(template, folder)
            else:
                unpack(download(where(template)), folder)
        except (OSError, zipfile.BadZipFile, tarfile.TarError) as problem:
            raise ValueError(f"could not fetch {template}: {problem}") from None
        yield folder


def where(template):
    """The address to fetch, turning `owner/repo` into a GitHub archive."""
    if "://" not in template and GITHUB.fullmatch(template):
        return f"https://github.com/{template}/archive/refs/heads/main.tar.gz"
    return template


def download(url):
    """Fetch an archive to a file on disk."""
    request = urllib.request.Request(url, headers={"User-Agent": "gromon"})
    kind = ".zip" if Path(url).suffix == ".zip" else ".tar.gz"
    with contextlib.closing(urllib.request.urlopen(request, timeout=60)) as reply:
        with tempfile.NamedTemporaryFile(delete=False, suffix=kind) as handle:
            shutil.copyfileobj(reply, handle, ROOM)
            return Path(handle.name)


def clone(url, folder):
    """A shallow copy of a git repository."""
    done = subprocess.run(
        ["git", "clone", "--depth", "1", "--quiet", url, str(folder)],
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if done.returncode:
        said = (done.stderr or done.stdout).strip().splitlines()
        raise ValueError(f"could not clone {url}: {said[-1] if said else 'git failed'}")


def unpack(archive, folder):
    """Take an archive apart, refusing to write outside `folder`."""
    spent = 0
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                spent += member.file_size
                if spent > ROOM:
                    raise ValueError("the template is larger than gromon will unpack")
                target = landing(folder, member.filename)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(member) as reader:
                    target.write_bytes(reader.read())
        return

    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            spent += member.size
            if spent > ROOM:
                raise ValueError("the template is larger than gromon will unpack")
            reader = tar.extractfile(member)
            if reader is None:
                continue
            target = landing(folder, member.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(reader.read())


def landing(folder, member):
    """The one place an archive entry is allowed to land."""
    target = (folder / member).resolve()
    if target != folder.resolve() and folder.resolve() not in target.parents:
        raise ValueError(f"the template tries to write outside itself: {member}")
    return target


def topmost(folder):
    """Archives wrap everything in one folder, so step into it."""
    entries = [item for item in folder.iterdir() if item.name != "__MACOSX"]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return folder


def builtin(name, root):
    """The starter Gromon ships with."""
    written = []
    for relative, template in FILES.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(template.replace("{name}", name), encoding="utf-8")
        written.append(target)

    runtime = root / "static" / "fscss.min.js"
    runtime.write_bytes(compiler().read_bytes())
    written.append(runtime)
    return written


def from_folder(name, root, source):
    """Copy a template folder into a project, filling in {name}."""
    if not source.is_dir():
        raise ValueError(f"no template folder at {source}")

    # Taken before anything is written, so `--template .` cannot walk into the
    # very folder it is creating.
    items = sorted(source.rglob("*"))
    written = []
    for item in items:
        relative = item.relative_to(source)
        if ignored(relative) or inside(relative, root):
            continue

        target = root / str(relative).replace("{name}", name)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_bytes(fill(item.read_bytes(), name))
        except OSError as problem:
            raise ValueError(f"could not read {item}: {problem.strerror}") from None
        written.append(target)

    if not written:
        raise ValueError(f"no files in the template folder {source}")
    return written


def inside(relative, root):
    """True when a template entry is the project folder, or sits under it."""
    target = (root.parent / relative).resolve()
    return target == root.resolve() or root.resolve() in target.parents


def ignored(relative):
    """True for the parts of a template nobody means to copy."""
    parts = relative.parts
    if SKIP.intersection(parts):
        return True
    return relative.name.endswith((".pyc", ".pyo", ".swp"))


def fill(content, name):
    """Put the project name into a template file, leaving binaries alone."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content
    return text.replace("{name}", name).encode("utf-8")


def next_steps(root):
    """What to tell someone who just scaffolded a project."""
    install = (
        "  pip install -r requirements.txt"
        if (root / "requirements.txt").is_file()
        else "  pip install gromon"
    )
    return f"\n  cd {root.name}\n{install}\n  gromon run {root.name}\n\nThen open http://127.0.0.1:8000/"
