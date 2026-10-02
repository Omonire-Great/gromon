"""A bigger Gromon app: blueprint, middleware, error page, templates.

    gromon run examples/blog

Pages are styled with st-core.fscss, a pure CSS component library.
"""

from gromon import Blueprint, error, limiter, register, render, route, run, static, use

static()
use(limiter.limit(30))

POSTS = [
    {"id": 1, "title": "Less code", "body": "Gromon is small."},
    {"id": 2, "title": "No dependencies", "body": "Only the standard library."},
]

admin = Blueprint("admin", "/admin")


@admin.route("/stats")
def stats():
    return {"posts": len(POSTS)}


register(admin)


@use
def api_key(request):
    """Middleware. /admin needs ?key=secret, everything else is open."""
    if request.path.startswith("/admin") and request.query.get("key") != "secret":
        return {"error": "Bad key"}, 401


@route("/")
def home():
    return render("index.html", title="Gromon", posts=POSTS)


@route("/post/<id>")
def post(id):
    found = next((p for p in POSTS if p["id"] == int(id)), None)
    if found is None:
        return {"error": "No such post"}, 404
    return found


@error(404)
def missing(request):
    return render("404.html", title="Gromon", path=request.path)


if __name__ == "__main__":
    run()
