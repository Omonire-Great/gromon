# Gromon

**Gromon lets you build Python applications with less code.**

```python
from gromon import route, run

@route("/")
def home():
    return {"message": "Hello World"}

run()
```

That is a complete web application. No app object to build, no config file, no
extensions. Return a dict and you get JSON back.

## Install

```bash
pip install gromon
```

No dependencies. Python 3.9+. It runs on the standard library.

Add templates when you need them:

```bash
pip install gromon[templates]
```

## Why

Most Python web frameworks make you repeat yourself. Gromon removes what you
never needed:

| Flask | Gromon |
| --- | --- |
| `app = Flask(__name__)` | nothing |
| `@app.route("/")` | `@route("/")` |
| `return jsonify({...})` | `return {...}` |
| `@app.errorhandler(404)` | `@error(404)` or `raise HTTPError(404, ...)` |
| `@app.before_request` | `@use` |
| `@app.after_request` | `@after`, with the headers dict |
| `class Users(View)` | `@route("/users")` on a `MethodView` |
| `app.test_client()` | the same, without the socket |
| `flask-limiter`, `flask-login` | `gromon.limiter`, `gromon.auth`, both just `use` |
| blueprints, extensions, app factories, `asyncio` variants | not required |

Gromon is not a Flask clone. It is one router, one request object, one return
value convention, one middleware hook, and one exception.

## Routing

A path is a string, a handler is a function.

```python
@route("/")                     # static
@route("/user/<id>")            # <id> arrives as an argument
@route("/user/<int:id>/post/<post>")
def post(id, post):
    return {"user": id, "post": post}
```

A converter does the casting, and a wrong value is a 404 rather than a crash:

| Converter | Matches | Arrives as |
| --- | --- | --- |
| `<name>`, `<string:name>` | one segment | `str` |
| `<int:id>` | `-?\d+` | `int` |
| `<float:score>` | `-?\d+(\.\d+)?` | `float` |
| `<uuid:id>` | a uuid | `UUID` |
| `<path:path>` | the rest, slashes included | `str` |

Restrict methods when you need to. `GET` also answers `HEAD`.

```python
@route("/user", methods=["POST"])
def create():
    return {"created": True}, 201
```

### url_for

Every route has an endpoint, by default the name of the function:

```python
@route("/user/<int:id>")
def user(id):
    return url_for("user", id=id)              # "/user/7"

@route("/user/<int:id>", endpoint="profile")
def user_detail(id):
    return url_for("profile", id=7, _external=True)   # "http://host/user/7"
```

Values the rule does not name become a query string, so
`url_for("search", q="cats")` gives `/search?q=cats`. Blueprints namespace
their endpoints: `url_for("admin.users")`, and a nested one is
`url_for("api.v1.users")`.

`_anchor="top"` adds a fragment, and `_method="delete"` picks the rule you
registered for another verb:

```python
@route("/users/<int:id>")
@route("/users/<int:id>/delete", methods=["DELETE"])
def user(id):
    return url_for("user", id=id, _method="delete")   # "/users/7/delete"
```

When a rule needs an argument you did not pass, `@url_defaults` fills it in:

```python
@url_defaults
def language(endpoint, values):
    values.setdefault("lang", "en")

@route("/<lang>/page")
def page(lang):
    return url_for("page")                # "/en/page"
```

## Responses

Whatever a handler returns becomes the response:

| Return value | Response |
| --- | --- |
| `dict` or `list` | `200 application/json` |
| `str` | `200 text/html; charset=utf-8` |
| `bytes` | `200 application/octet-stream` |
| `None` | `204`, empty |
| `(value, 201)` | any of the above with a status code |
| `(bytes, 200, "image/png")` | ... and with a content type |
| `(value, 200, "text/html", {"X-Frame-Options": "DENY"})` | ... and with headers |

`redirect("/next")` is the short way to answer 302 with a `Location`, and
`abort(404)` raises on the spot.

## The request

A handler receives what it declares by name, so simple handlers stay tiny.

```python
@route("/echo", methods=["POST"])
def echo(request):
    return {
        "body": request.json(),
        "query": request.query,
        "header": request.headers.get("X-Token"),
        "method": request.method,
        "path": request.path,
    }
```

`@route("/user/<id>")` with `def user(id)` gets `id`; `def user(request, id)`
gets both.

Inside a handler the request is also available as a global, the way Flask does
it, and it raises outside one rather than guessing:

```python
from gromon import request

@route("/where")
def where():
    return {"path": request.path}
```

`request.form` and `request.files` read urlencoded and multipart bodies,
`request.cookies` is a dict, and `request.values()` merges query and form.

## Response headers

Headers come from the fourth item of the return value, or from `@after`, which
sees every response including errors and short circuits:

```python
@after
def headers(request, headers):
    headers["X-Frame-Options"] = "DENY"
```

## Middleware

One decorator. Return `None` to continue, or a response to stop the request.

```python
@use
def api_key(request):
    if request.path.startswith("/admin") and request.query.get("key") != "secret":
        return {"error": "Bad key"}, 401
```

Middleware is how auth, rate limits, and CORS stay out of the core.

## Teardown

Where a database connection or a file handle goes back. It runs after every
response, errors and middleware short circuits included, and once a streamed
body has been consumed rather than before:

```python
@teardown
def close(request):
    request.db.close()
```

If one teardown raises, the rest still run and the traceback is printed.

## Config

There is no app object to configure, so settings live on the app when you build
one, and can be loaded from the environment, a file or an object:

```python
from gromon import App

app = App()
app.config["DEBUG"] = True
app.config.from_env("GROMON_")            # GROMON_DEBUG=1, GROMON_MAIL__HOST=...
app.config.from_envvar("GROMON_SETTINGS") # a .py file of UPPERCASE names
app.config.from_object("myproject.settings")
app.config.from_file("settings.json", json.load)
```

| Key | Default | What it does |
| --- | --- | --- |
| `DEBUG` | `False` | pretty JSON bodies |
| `TESTING` | `False` | pretty JSON bodies, for tests |
| `TRUSTED_HOSTS` | `None` | a list of `Host` names to accept, `None` for any |
| `MAX_CONTENT_LENGTH` | 32 MB | a body over it is `413`, `0` lifts it |
| `MAX_FORM_MEMORY_SIZE` | 500 KB | how much text a multipart form may hold |
| `MAX_FORM_PARTS` | 1000 | how many parts a multipart form may have |
| `PERMANENT_SESSION_LIFETIME` | 30 days | how long a signed session cookie lives |
| `SESSION_COOKIE_*` | see below | `NAME`, `PATH`, `HTTPONLY`, `SAMESITE`, `SECURE` |

`OPTIONS` is answered automatically with an `Allow` header, so a CORS preflight
or a client asking what a path accepts gets an answer without you writing one.

## Errors

One exception. Raise it and Gromon answers with JSON.

```python
from gromon import HTTPError

@route("/user/<id>")
def user(id):
    if id != "1":
        raise HTTPError(404, "User not found")
    return {"id": id}
```

```json
{"error": "User not found"}
```

Swap the whole page for a status:

```python
@error(404)
def missing(request):
    return render("404.html", path=request.path)
```

An error handler returns a normal response; if it does not name a status code,
the error's own status is used. Declare `error` in the arguments to read the
message. Unknown paths give `404`, wrong methods `405`, and anything unexpected
prints a traceback and gives `500`.

## Static files

```python
from gromon import static

static()                        # ./static at /static
static("public", "/assets")     # ./public at /assets
```

## Templates

Jinja2, optional and lazily imported.

```python
from gromon import render

@route("/")
def home():
    return render("index.html", posts=posts)
```

`./templates` is the folder. Autoescaping is on. `folder` is keyword only so
template variables can be called anything.

## Blueprints

A named group of routes under a prefix.

```python
from gromon import Blueprint, register

admin = Blueprint("admin", "/admin")

@admin.route("/stats")
def stats():
    return {"posts": 2}

register(admin)
```

## Rate limiting

`gromon.limiter` is middleware, so it adds nothing to the core.

```python
from gromon import limiter, use

use(limiter.limit(60))                  # 60 requests a minute per caller
use(limiter.limit(5, 60, key=lambda r: r.query.get("key")))
```

Over the limit you get `{"error": "Too many requests"}` and `429`. The caller is
the `X-Forwarded-For` address when a proxy sets one, otherwise the socket
address. Counts live in the memory of one process: behind more than one worker,
count in the database instead.

## Authentication

`gromon.auth` gives you primitives, not an OAuth server.

```python
from gromon import auth, use

use(auth.require("a-long-random-token"))     # Authorization: Bearer <token>

hashed = auth.hash_password("hunter2")       # store this, never the password
auth.check_password("hunter2", hashed)       # True / False
```

Passwords are hashed with scrypt from the standard library. Tokens are compared
with `hmac.compare_digest`, so a wrong guess never leaks timing.

### Sessions

A session is a signed cookie: `session(secret)` gives you two things to
register, and `request.session` is then a plain dict to read and change.

```python
from gromon import after, session, use

load, save = session("a-long-random-secret")
use(load)
after(save)

@route("/login", methods=["POST"])
def login(request):
    request.session["user"] = "ada"      # the cookie is signed back for you

@route("/me")
def me(request):
    return {"user": request.session.get("user")}
```

Hand it the config and the cookie follows `SESSION_COOKIE_NAME`, `_PATH`,
`_SAMESITE`, `_HTTPONLY`, `_SECURE` and `PERMANENT_SESSION_LIFETIME`. Anything
passed to `session()` still wins:

```python
load, save = session("a-long-random-secret", config=app.config)
```

Nothing is stored on the server, so the cookie has to stay small, and anyone
holding the secret can read it: keep it out of the code. Each cookie carries the
time it was signed, so one older than `max_age` seconds (30 days by default)
reads as an empty session rather than a stale one. A tampered cookie does the
same instead of raising. To log someone out, `request.session.clear()` and send
nothing, or return `auth.expired()`.

## Payments

`gromon.payment` is a REST client for Stripe, no SDK, no dependencies.

```python
from gromon import payment

stripe = payment.Client("sk_live_...")

@route("/buy")
def buy():
    checkout = stripe.checkout("price_123", url="https://shop.example/thanks")
    return redirect(checkout["url"])

@route("/webhook", methods=["POST"])
def webhook(request):
    if not payment.verify(request.body, request.headers["Stripe-Signature"], secret):
        return {"error": "Bad signature"}, 400
    fulfill(request.json())
```

`verify` is the part that matters: the browser can be faked, the signature
cannot. A `402` from the provider raises `payment.PaymentError` carrying the
status and the code.

## WebSocket

```python
from gromon import websocket

@websocket("/ws")
def chat(connection):
    while True:
        message = connection.receive()      # str, bytes, or None when closed
        if message is None:
            return
        connection.send(f"you said: {message}")
```

`connection.send_json(value)`, `connection.close()`, path parameters by name
(`@websocket("/ws/room/<room>")`), ping/pong and fragments all work. One thread
per connection, no extensions.

## Class based views

Subclass `MethodView` when one resource wants more than one verb, and route the
class. The method name is the verb, and the verbs you write are the ones the
route answers:

```python
from gromon import MethodView

@route("/users")
class Users(MethodView):
    def get(self):
        return []

    def post(self, request):
        return {"created": True}, 201
```

A second route for the same resource, with its own path:

```python
@route("/users/<int:id>", methods=["DELETE"])
class User(MethodView):
    def delete(self, id):
        return None
```

A verb you did not write is a `405`. Path parameters arrive by name, `request`
arrives if you ask for it, `**params` collects everything, and the instance is
made fresh for each request.

## Testing

`app.test_client()` calls the same `handle()` the server does, with no socket,
and keeps cookies between calls, so a login in one call is a session in the next:

```python
def test_signup():
    load, save = session("a-long-random-secret")   # see Sessions above
    app.use(load)
    app.after(save)
    client = app.test_client()

    assert client.get("/").status_code == 200
    assert client.post("/users", json={"name": "ada"}).json["created"]

    response = client.get("/me")
    assert response.json["name"] == "ada"
```

`get`, `post`, `put`, `patch`, `delete` and `head` all take `data=`, `headers=`
and `query=`. The response has `status_code`, `headers`, `text`, `json`,
`get_header()` and `data`, and it works as a context manager. A streamed body is
read to the end for you, like a browser would.

## Flash messages

Flashes ride in the session, so wire one first (see [Sessions](#sessions)):

```python
from gromon import flash, get_flashed_messages

@route("/save", methods=["POST"])
def save():
    flash("Saved", "info")
    return redirect("/")

@route("/")
def home():
    return {
        "messages": get_flashed_messages(),                  # ["Saved"]
        "pairs": get_flashed_messages(with_categories=True),  # [("info", "Saved")]
    }
```

They survive one redirect and are read once.

## Streaming

Return a generator and the response is chunked, with the request still alive
while it runs:

```python
@route("/events")
def events():
    def stream():
        for tick in range(3):
            yield f"data: {tick}\n\n"

    return stream()
```

`send_file(path, ...)` serves a file with `ETag`, `Last-Modified`, `Accept-Ranges`
and range requests, so a browser can seek in a video or resume a download, and
`304` handling for `If-None-Match` and `If-Modified-Since`. `@static()` uses it,
so static files get all of that without a line of your code.

## Config

Settings live on the app when you build one, and can be loaded from the
environment, a file or an object:

```python
from gromon import App

app = App()
app.config["DEBUG"] = True
app.config.from_env("GROMON_")             # GROMON_DEBUG=1, GROMON_MAIL__HOST=...
app.config.from_envvar("GROMON_SETTINGS")  # a .py file of UPPERCASE names
app.config.from_object("myproject.settings")
app.config.from_file("settings.json", json.load)
```

| Key | Default | What it does |
| --- | --- | --- |
| `DEBUG` | `False` | pretty JSON bodies |
| `TESTING` | `False` | pretty JSON bodies, for tests |
| `TRUSTED_HOSTS` | `None` | `Host` names to accept, `None` for any |
| `MAX_CONTENT_LENGTH` | 32 MB | a body over it is `413`, `0` lifts it |
| `MAX_FORM_MEMORY_SIZE` | 500 KB | how much text a multipart form may hold |
| `MAX_FORM_PARTS` | 1000 | how many parts a multipart form may have |
| `PERMANENT_SESSION_LIFETIME` | 30 days | how long a signed session cookie lives |
| `SESSION_COOKIE_*` | `session`, `/`, on, `Lax`, off | the cookie itself |

`app.json` decides how values become JSON, and `DEBUG` or `TESTING` pretty
prints it:

```python
from gromon import JSON

app.json = JSON(indent=4, sort_keys=True)
```

## Start a project

```bash
gromon new myapp
cd myapp
pip install -r requirements.txt
gromon run myapp
```

Then open http://127.0.0.1:8000/ It writes ten files that work together:

```
app.py                 routes, the App object, one JSON endpoint
templates/base.html    the layout every page extends
templates/index.html   the page at /
templates/404.html     what an unknown path answers
static/site.fscss      styles, in FSCSS
static/app.js          calls /api/hello when you click
static/fscss.min.js    the FSCSS compiler, served by your own app
README.md  requirements.txt  .gitignore
```

Styles are [FSCSS](https://fscss.devtem.org/), which compiles to plain CSS.
`static/fscss.min.js` does that in the browser, so edits show up on a refresh
and there is no build step. Because your own app serves it, a scaffolded project
needs neither npm nor a network connection.

To ship plain CSS, compile it once and point the link in `base.html` at the
result. That step does need npm:

```bash
npm install -g fscss
fscss static/site.fscss static/site.css
```

### Your own starter

A template is just a folder, so a team can keep its shape in git and scaffold
from that instead of the built-in one:

```bash
gromon new shop --template ./gromon-starter
gromon createapp shop --template ./gromon-starter   # same thing
```

The folder becomes the project. It **replaces** the built-in starter rather than
adding to it, so your template decides everything. Every `{name}` in a file, or
in a path, becomes the project name:

```
gromon-starter/
  app.py                     """A {name} starter."""
  README.md                  # {name}
  api/{name}/__init__.py     NAME = "{name}"
```

Use `.` to start from the folder you are standing in, which is handy when the
shape already exists and you only want the new name filled in:

```bash
cd my-current-app
gromon createapp shop --template .
# -> ./shop/, with {name} already replaced by shop
```

Gromon reads the folder before it writes anything, so pointing it at `.` cannot
end up copying the new project into itself.

`.git`, `__pycache__`, `node_modules`, `*.pyc` and similar are left out, so it
works straight from a git checkout. Binary files are copied untouched.

## Run it

```bash
gromon run app.py              # or a folder: gromon run .
```

The server restarts when any `.py` file next to your app changes, so there is
no manual restarting. Options:

```
gromon run --host 0.0.0.0 --port 5000 app.py
gromon run --no-reload app.py
```

To see what an application answers, without starting it:

```bash
gromon routes app.py
```

```
METHODS       PATH                                        ENDPOINT
GET,HEAD      /                                           home
GET,HEAD      /user/<int:id>                              user
POST          /echo                                       echo
```

`./static` and `./templates` are resolved relative to the file you run. Without
the CLI, `python app.py` and `run()` do the same job with no reloading.

## Two applications in one file

`gromon` works on one default application so you never build one. When you do
need a second, build an `App`:

```python
from gromon import App

api = App()

@api.route("/ping")
def ping():
    return "pong"

api.run(port=8001)
```

## Examples

`examples/hello.py` is the whole framework in twenty lines.

`examples/blog/` is a small application with a blueprint, middleware, a custom
404 page, templates and static files. Its pages are styled with
[st-core.fscss](https://github.com/fscss-ttr/st-core.fscss), a pure CSS
component library.

```bash
gromon run examples/blog
```

`examples/chat.py` is a WebSocket chat in about forty lines, with the browser
client written in three lines of JavaScript. Open it in two windows.

```bash
gromon run examples/chat.py
```

## Project structure

```
gromon/
    __init__.py    the public API
    app.py         App, Blueprint, route, use, error, static, render, url_for, run
    auth.py        passwords, bearer tokens, sessions
    cli.py         gromon run, gromon routes
    context.py     the request being handled, and the request proxy
    errors.py      HTTPError, abort
    helpers.py     send_file, conditional requests, flash
    http.py        the Request
    limiter.py     rate limiting middleware
    payment.py     Stripe without the SDK
    response.py    return value -> response
    router.py      converters, matching, url_for
    server.py      the HTTP server, streaming, WebSocket upgrade
    templates.py   Jinja2, optional
    testing.py     app.test_client()
    views.py       MethodView
    websocket.py   WebSocket
tests/
examples/
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## Roadmap

The goal is everything Flask does, written the way this is written. Done:
routing with converters, reverse routing with anchors, url defaults and method
rules, blueprints including nested ones, middleware, teardown hooks, error
handlers, static files with conditional and range requests, templates, sessions
that expire, auth, rate limiting, payments, WebSocket, class based views, a test
client, streaming, flashing, automatic `OPTIONS`, trusted hosts, a swappable JSON
provider, config loaded from the environment, the CLI with reloading, and
`gromon routes`.

Still open, roughly in order of how much a real application feels the absence:

- `g`, for a place to hang things that are neither in nor out of a request
- `request.files` streaming to disk instead of memory for big uploads
- an `asgiref`-free async view, if it can stay as small as the rest
- signals, for letting a plugin hook into an event

`url_defaults`, `url_for` and the request global inside templates are done, and
one style per app is enforced: an `App` you build yourself and the global
`route` register on different objects, so `gromon routes` warns when it sees
both.

## License

MIT
