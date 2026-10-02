import base64
import time

from gromon import Request, auth
from gromon.response import make_response

SECRET = "a-long-random-secret"


def get(headers=None, target="/", method="GET", body=b""):
    return Request(method, target, headers or {}, body)


def test_passwords_hash_and_verify():
    hashed = auth.hash_password("hunter2")
    assert auth.check_password("hunter2", hashed)
    assert not auth.check_password("hunter3", hashed)


def test_two_hashes_of_one_password_differ():
    assert auth.hash_password("hunter2") != auth.hash_password("hunter2")


def test_the_same_salt_gives_the_same_hash():
    assert auth.hash_password("hunter2", "abc") == auth.hash_password("hunter2", "abc")


def test_the_scheme_is_in_the_hash():
    assert auth.hash_password("hunter2").startswith("scrypt$")


def test_a_missing_hash_is_not_a_crash():
    assert not auth.check_password("hunter2", None)
    assert not auth.check_password("hunter2", "nonsense")


def test_another_scheme_is_refused():
    assert not auth.check_password("hunter2", "pbkdf2$1$2$deadbeef")


def test_the_wrong_salt_is_refused():
    assert not auth.check_password("hunter2", auth.hash_password("hunter3"))


class TestBearer:
    def test_the_token_is_taken_from_the_header(self):
        assert auth.bearer(get({"Authorization": "Bearer abc123"})) == "abc123"

    def test_the_scheme_is_not_case_sensitive(self):
        assert auth.bearer(get({"Authorization": "bearer abc123"})) == "abc123"

    def test_another_scheme_is_ignored(self):
        assert auth.bearer(get({"Authorization": "Basic abc123"})) == ""

    def test_no_header_is_an_empty_token(self):
        assert auth.bearer(get()) == ""


class TestRequire:
    def test_the_right_token_passes(self):
        middleware = auth.require("secret-token")
        assert middleware(get({"Authorization": "Bearer secret-token"})) is None

    def test_a_wrong_token_is_refused(self):
        middleware = auth.require("secret-token")
        assert middleware(get({"Authorization": "Bearer nope"})) == (
            {"error": "Unauthorized"},
            401,
        )

    def test_no_token_is_refused(self):
        middleware = auth.require("secret-token")
        assert middleware(get()) == ({"error": "Unauthorized"}, 401)


class TestSignature:
    def test_a_value_survives_the_round_trip(self):
        token = auth.sign({"user": "ada", "admin": True}, SECRET)
        assert auth.read(token, SECRET) == {"user": "ada", "admin": True}

    def test_the_token_survives_a_cookie_trip(self):
        # a cookie only carries latin-1, so the token has to stay ascii
        token = auth.sign({"note": "café 1 €"}, SECRET)
        assert all(ord(char) < 128 for char in token)

    def test_a_tampered_value_is_refused(self):
        payload, stamp, signature = auth.sign({"user": "ada"}, SECRET).split(".")
        assert auth.read(f"{payload}x.{stamp}.{signature}", SECRET) == {}

    def test_a_tampered_signature_is_refused(self):
        payload, stamp, signature = auth.sign({"user": "ada"}, SECRET).split(".")
        assert auth.read(f"{payload}.{stamp}.{signature[:-1]}x", SECRET) == {}

    def test_an_old_token_is_refused(self):
        stale = auth.sign({"user": "ada"}, SECRET, when=time.time() - 3600)
        assert auth.read(stale, SECRET, max_age=60) == {}
        assert auth.read(stale, SECRET, max_age=7200) == {"user": "ada"}

    def test_the_token_carries_the_time_it_was_signed(self):
        _payload, stamp, _signature = auth.sign({"user": "ada"}, SECRET).split(".")
        signed_at = base64.urlsafe_b64decode(stamp + "=" * (-len(stamp) % 4))
        assert abs(int(signed_at) - time.time()) < 5

    def test_another_secret_cannot_read_it(self):
        token = auth.sign({"user": "ada"}, SECRET)
        assert auth.read(token, "a-different-secret-xxxxx") == {}

    def test_rubbish_is_refused_without_raising(self):
        assert auth.read("not-a-token", SECRET) == {}
        assert auth.read("", SECRET) == {}


class TestCookie:
    def test_the_named_cookie_is_found(self):
        request = get({"Cookie": "theme=dark; session=abc; tz=UTC"})
        assert auth.cookie(request, "session") == "abc"

    def test_a_missing_cookie_is_an_empty_string(self):
        assert auth.cookie(get({"Cookie": "theme=dark"}), "session") == ""
        assert auth.cookie(get(), "session") == ""


class TestSession:
    def test_the_secret_cannot_be_short(self):
        try:
            auth.session("short")
        except ValueError as error:
            assert "16" in str(error)
        else:
            assert False, "a short secret should be refused"

    def test_a_fresh_request_has_an_empty_session(self):
        middleware, save = auth.session(SECRET)
        request = get()
        assert middleware(request) is None
        assert request.session == {}

        headers = {}
        save(request, headers)
        assert headers == {}

    def test_changing_the_dict_sets_a_cookie(self):
        middleware, save = auth.session(SECRET)
        request = get()
        middleware(request)
        request.session["user"] = "ada"

        headers = {}
        save(request, headers)
        assert headers["Set-Cookie"].startswith("session=")
        assert "HttpOnly" in headers["Set-Cookie"]
        assert "SameSite=Lax" in headers["Set-Cookie"]
        assert "Max-Age=2592000" in headers["Set-Cookie"]
        assert "Secure" not in headers["Set-Cookie"]

    def test_secure_can_be_asked_for(self):
        middleware, save = auth.session(SECRET, secure=True)
        request = get()
        middleware(request)
        request.session["user"] = "ada"

        headers = {}
        save(request, headers)
        assert headers["Set-Cookie"].endswith("; Secure")


class TestSessionConfig:
    def send(self, config, **kwargs):
        middleware, save = auth.session(SECRET, config=config, **kwargs)
        request = get()
        middleware(request)
        request.session["user"] = "ada"
        headers = {}
        save(request, headers)
        return headers["Set-Cookie"]

    def test_the_cookie_follows_the_app_settings(self):
        from gromon import App

        app = App()
        app.config["SESSION_COOKIE_NAME"] = "gromon"
        app.config["SESSION_COOKIE_PATH"] = "/app"
        app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["PERMANENT_SESSION_LIFETIME"] = 60

        header = self.send(app.config)
        assert header.startswith("gromon=")
        assert "Path=/app" in header
        assert "SameSite=Strict" in header
        assert "Max-Age=60" in header
        assert header.endswith("; Secure")

    def test_httponly_can_be_turned_off(self):
        from gromon import App

        app = App()
        app.config["SESSION_COOKIE_HTTPONLY"] = False
        assert "HttpOnly" not in self.send(app.config)

    def test_an_explicit_argument_beats_the_config(self):
        from gromon import App

        app = App()
        app.config["SESSION_COOKIE_NAME"] = "gromon"
        app.config["SESSION_COOKIE_SECURE"] = True

        header = self.send(app.config, name="sid", secure=False)
        assert header.startswith("sid=")
        assert "Secure" not in header

    def test_no_config_gives_the_defaults(self):
        from gromon import App

        app = App()
        header = self.send(app.config)
        assert header.startswith("session=")
        assert "Path=/" in header
        assert "SameSite=Lax" in header
        assert "Max-Age=2592000" in header
        assert "HttpOnly" in header
        assert "Secure" not in header

    def test_the_cookie_comes_back_on_the_next_request(self):
        middleware, save = auth.session(SECRET)
        login = get()
        middleware(login)
        login.session["user"] = "ada"

        headers = {}
        save(login, headers)

        later = get({"Cookie": headers["Set-Cookie"].split(";")[0]})
        middleware(later)
        assert later.session == {"user": "ada"}

    def test_a_forged_cookie_gives_an_empty_session(self):
        middleware, save = auth.session(SECRET)
        forged = auth.sign({"user": "root"}, "not-the-secret-at-all")
        request = get({"Cookie": f"session={forged}"})
        middleware(request)
        assert request.session == {}

    def test_the_cookie_name_can_change(self):
        middleware, save = auth.session(SECRET, name="gromon")
        request = get()
        middleware(request)
        request.session["user"] = "ada"

        headers = {}
        save(request, headers)
        assert headers["Set-Cookie"].startswith("gromon=")


def test_the_expired_handler_clears_the_cookie():
    status, kind, body, headers = make_response(auth.expired("session")())
    assert status == 200
    assert headers["Set-Cookie"] == "session=; Path=/; Max-Age=0"


def test_the_expired_handler_forgets_the_session():
    from gromon.app import app
    from gromon.http import Request

    seen = {}

    @app.route("/logout")
    def logout(request):
        auth.expired()()
        seen["after"] = dict(request.session)
        return "", 204

    request = Request("GET", "/logout", {}, b"")
    request.session["user"] = "ada"
    app.handle(request)
    assert seen["after"] == {}
