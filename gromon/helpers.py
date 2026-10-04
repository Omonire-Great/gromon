"""What Flask keeps in flask/helpers.py: sending files, streaming, flashing.

    from gromon import flash, get_flashed_messages, send_file

    @route("/report.pdf")
    def report():
        return send_file("reports/q3.pdf")

    @route("/numbers")
    def numbers():
        return (chunk for chunk in range(10))          # streamed as it is made

    @route("/save", methods=["POST"])
    def save():
        flash("Saved")
        return redirect("/")
"""

from email.utils import formatdate, parsedate_to_datetime
from mimetypes import guess_type
from pathlib import Path
import re

from .errors import HTTPError

# FSCSS has no registered media type, and mimetypes guesses nothing for it, so
# a stylesheet would reach the browser as application/octet-stream.
KINDS = {".fscss": "text/fscss"}

# app.9f2c1a.js, app-9f2c1a4b.css, bundle.9f2c1a4b3d.js: a content hash in the
# name, which means the bytes behind it will never change again.
FINGERPRINT = re.compile(r"[.-][0-9a-f]{8,}\.")


def kind_of(name, mimetype=None):
    """The content type for a file name, or None when nothing fits."""
    if mimetype:
        return mimetype
    return KINDS.get(Path(name).suffix.lower()) or guess_type(name)[0]


def send_file(path, mimetype=None, conditional=True, download_name=None, max_age=None):
    """Return the value that serves a file, with caching headers.

    With `conditional` on, a request carrying a matching `If-None-Match` or
    `If-Modified-Since` gets `304 Not Modified` and no body, which is what
    browsers and CDNs ask for. A `Range` request gets `206 Partial Content` with
    just the bytes it asked for.

    `max_age` sets Cache-Control in seconds. A file whose name carries a content
    hash, the way `app.9f2c1a.js` does, is cached for a year and marked
    immutable, because a new hash means a new name.
    """
    target = Path(path)
    if not target.is_file():
        raise HTTPError(404, "Not found")

    details = target.stat()
    kind = kind_of(target.name, mimetype) or "application/octet-stream"
    headers = {
        "ETag": f'"{details.st_mtime_ns:x}-{details.st_size:x}"',
        "Last-Modified": formatdate(details.st_mtime, usegmt=True),
        "Accept-Ranges": "bytes",
        "Cache-Control": cache_for(target.name, max_age),
    }
    if download_name:
        headers["Content-Disposition"] = f'attachment; filename="{download_name}"'

    from .context import current

    request = current()
    if conditional and request is not None and _unchanged(request, headers, details.st_mtime):
        return None, 304

    if conditional and request is not None:
        span = _range(request.headers.get("Range", ""), details.st_size)
        if span == "unsatisfiable":
            headers["Content-Range"] = f"bytes */{details.st_size}"
            return None, 416, kind, headers
        if span:
            start, stop = span
            headers["Content-Range"] = f"bytes {start}-{stop - 1}/{details.st_size}"
            with target.open("rb") as handle:
                handle.seek(start)
                return handle.read(stop - start), 206, kind, headers

    return target.read_bytes(), 200, kind, headers


def cache_for(name, max_age=None):
    """The Cache-Control for a file: a year when the name carries a hash."""
    if max_age is None:
        max_age = 31_536_000 if FINGERPRINT.search(name) else 3600
    return f"public, max-age={int(max_age)}" + (", immutable" if max_age > 86_400 else "")


def _range(header, size):
    """'bytes=0-99' -> (0, 100). The last byte, None when unusable."""
    if not header.startswith("bytes=") or "," in header:
        return None
    first, _, last = header[6:].partition("-")
    try:
        if not first:  # bytes=-100, the final 100 bytes
            length = int(last)
            return (max(0, size - length), size) if length > 0 else None
        start = int(first)
        stop = size if not last else min(int(last) + 1, size)
    except ValueError:
        return None

    if start >= size:
        return "unsatisfiable"
    return (start, stop) if stop > start else None


def _unchanged(request, headers, mtime):
    """True when the copy the browser holds is the one we would send."""
    if request.headers.get("If-None-Match") == headers["ETag"]:
        return True
    try:
        since = parsedate_to_datetime(request.headers.get("If-Modified-Since", ""))
        return since.tzinfo is not None and since.timestamp() >= mtime
    except (TypeError, ValueError):
        return False


def flash(message, category="message"):
    """Put a message in the session for the next request to read."""
    request = _current_or_die("flash")
    request.session.setdefault("_flashes", []).append((category, message))


def get_flashed_messages(with_categories=False):
    """Take the flashed messages, leaving the session without them."""
    request = _current_or_die("get_flashed_messages")
    messages = request.session.pop("_flashes", [])
    return messages if with_categories else [text for _, text in messages]


def _current_or_die(what):
    from .context import current

    request = current()
    if request is None:
        raise RuntimeError(f"{what}() needs a request, like Flask's")
    return request


def safe_join(folder, *parts):
    """Join a path inside folder, refusing anything that climbs out."""
    root = Path(folder).resolve()
    target = root.joinpath(*parts).resolve()
    if root not in target.parents:
        raise HTTPError(404, "Not found")
    return target
