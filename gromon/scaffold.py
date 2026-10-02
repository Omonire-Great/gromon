"""The files `gromon new` writes, so a fresh app runs with no setup.

Kept as strings instead of package data on purpose: a scaffolded project should
never reach back into gromon/ for its own files, and it keeps every generated
file reviewable in one place.
"""

import keyword
import re
from pathlib import Path

NAME = re.compile(r"[A-Za-z][A-Za-z0-9._-]*")

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
    <script src="https://cdn.jsdelivr.net/npm/fscss@1.2.1/runtime.min.js" async></script>
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

## Styles

`static/site.fscss` is [FSCSS](https://fscss.devtem.org/), which compiles to
plain CSS. The page loads a small runtime that compiles it in the browser, so
there is no build step while you work.

To ship plain CSS instead, install the compiler and compile once:

    npm install -g fscss
    fscss static/site.fscss static/site.css

Then point the `site.fscss` link at `site.css`. Two FSCSS notes: `$name`
variables work anywhere, and an `@define` block reads its arguments with
`@use(name)`, so pass it plain values rather than `$variables`.
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


def unusable(name):
    """Why this cannot be a folder name, or None when it is fine."""
    if not name or not NAME.fullmatch(name):
        return "a project name starts with a letter and holds letters, digits, dots, dashes"
    if keyword.iskeyword(name):
        return f"{name} is a Python keyword"
    return None


def create(name):
    """Write a starter project into a folder named after it.

    An empty folder is fine to use, one with files in it is not: overwriting
    someone's work is not a default anybody wants.
    """
    problem = unusable(name)
    if problem:
        raise ValueError(problem)

    root = Path(name)
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"{name} already has files in it")

    written = []
    for relative, template in FILES.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(template.replace("{name}", name), encoding="utf-8")
        written.append(target)
    return written


def next_steps(name):
    """What to tell someone who just scaffolded a project."""
    return (
        f"\n  cd {name}\n"
        f"  pip install -r requirements.txt\n"
        f"  gromon run {name}\n\n"
        "Then open http://127.0.0.1:8000/"
    )
