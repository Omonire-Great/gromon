"""Authentication primitives. Gromon does not run an OAuth server.

    from gromon import auth, session, use

    use(auth.require("a-long-random-token"))     # Authorization: Bearer ...
    use(session("a-long-random-secret"))        # request.session, a dict

    hashed = auth.hash_password("hunter2")       # store this, not the password
    auth.check_password("hunter2", hashed)
"""

import base64
import hashlib
import hmac
import json
import secrets
import time

SCRYPT = {"n": 2**14, "r": 8, "p": 1}
DAY = 86400


def hash_password(password, salt=None):
    """Hash a password with scrypt. Returns text you can store in a database."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=salt.encode(), **SCRYPT)
    return f"scrypt${salt}${digest.hex()}"


def check_password(password, hashed):
    """True when the password matches the stored hash. Never raises."""
    try:
        scheme, salt, expected = hashed.split("$")
    except (AttributeError, ValueError):
        return False
    if scheme != "scrypt":
        return False
    given = hash_password(password, salt)
    return hmac.compare_digest(given, f"scrypt${salt}${expected}")


def bearer(request):
    """The token from an 'Authorization: Bearer <token>' header, or ''."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def require(token):
    """Middleware that only passes requests carrying this bearer token."""
    expected = token.encode()

    def middleware(request):
        if not hmac.compare_digest(bearer(request).encode(), expected):
            return {"error": "Unauthorized"}, 401
        return None

    middleware.token = token
    return middleware


def session(
    secret,
    name=None,
    max_age=None,
    secure=None,
    path=None,
    samesite=None,
    httponly=None,
    config=None,
):
    """Middleware giving every request a signed `request.session` dict.

    Read it and change it as you would any dict. When the handler is done, a
    fresh signed cookie goes out if the dict changed at all, so clearing it
    logs the client out. Each cookie carries the time it was signed, so one
    older than `max_age` seconds reads as an empty session.

    Give it `config=app.config` and the cookie follows those settings:

        load, save = session(SECRET, config=app.config)

    Anything you pass explicitly wins over the config.
    """
    if len(secret) < 16:
        raise ValueError("session secret must be at least 16 characters")

    name = _setting(config, "SESSION_COOKIE_NAME", name, "session")
    path = _setting(config, "SESSION_COOKIE_PATH", path, "/")
    same = _setting(config, "SESSION_COOKIE_SAMESITE", samesite, "Lax")
    hidden = _setting(config, "SESSION_COOKIE_HTTPONLY", httponly, True)
    secure = _setting(config, "SESSION_COOKIE_SECURE", secure, False)
    max_age = _setting(config, "PERMANENT_SESSION_LIFETIME", max_age, 30 * DAY)

    def middleware(request):
        request.loaded_session = read(cookie(request, name), secret, max_age)
        request.session = dict(request.loaded_session)

    def save(request, headers):
        if request.session == request.loaded_session:
            return
        cookie_header = f"{name}={sign(request.session, secret)}; Path={path}"
        cookie_header += f"; Max-Age={int(max_age)}"
        if hidden:
            cookie_header += "; HttpOnly"
        if same:
            cookie_header += f"; SameSite={same}"
        if secure:
            cookie_header += "; Secure"
        headers["Set-Cookie"] = cookie_header

    middleware.name, middleware.max_age = name, max_age
    return middleware, save


def _setting(config, key, given, fallback):
    """What you passed, else the app setting, else the default."""
    if given is not None:
        return given
    if config is not None and config.get(key) is not None:
        return config[key]
    return fallback


def sign(value, secret, when=None):
    """base64url(payload).stamp.hmac, safe to put in a cookie."""
    stamp = base64.urlsafe_b64encode(str(int(when or time.time())).encode()).rstrip(b"=")
    payload = base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=")
    body = payload + b"." + stamp
    signature = base64.urlsafe_b64encode(hmac.digest(secret.encode(), body, "sha256")).rstrip(b"=")
    return f"{payload.decode()}.{stamp.decode()}.{signature.decode()}"


def read(token, secret, max_age=None):
    """The value behind a signed token, or {} when it is forged or too old."""
    try:
        payload, stamp, signature = token.split(".")
        body = f"{payload}.{stamp}"
        expected = base64.urlsafe_b64encode(
            hmac.digest(secret.encode(), body.encode(), "sha256")
        )
        if not hmac.compare_digest(signature.encode().rstrip(b"="), expected.rstrip(b"=")):
            return {}
        if max_age is not None and time.time() - _stamp(stamp) > max_age:
            return {}
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (AttributeError, ValueError):
        return {}


def _stamp(text):
    """The seconds a token was signed at."""
    padded = text + "=" * (-len(text) % 4)
    return int(base64.urlsafe_b64decode(padded.encode()))


def cookie(request, name):
    """The raw value of one cookie from the Cookie header, or ''."""
    header = request.headers.get("Cookie", "")
    for part in header.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return ""


def expired(name="session"):
    """Drop a session cookie. Return this from a handler to log the client out.

    The session is emptied as well, so the cookie that comes back is the
    expiring one and not a fresh copy of what you just logged out of.
    """
    from .context import current

    def handler():
        request = current()
        if request is not None:
            request.session.clear()
        return "", 200, "text/plain", {"Set-Cookie": f"{name}=; Path=/; Max-Age=0"}

    handler.__name__ = "expired"
    return handler
