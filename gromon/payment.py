"""Taking money: a REST client for the Stripe API, without the SDK.

    from gromon import payment

    stripe = payment.Client("sk_live_...")

    @route("/buy")
    def buy():
        checkout = stripe.checkout("price_123", url="https://shop.example/thanks")
        return "", 303, "text/html", {"Location": checkout["url"]}

    @route("/webhook", methods=["POST"])
    def webhook(request):
        if payment.verify(request.body, request.headers["Stripe-Signature"], secret):
            fulfill(request.json())

The webhook is the only trustworthy source of truth: the browser can be
faked, the signature cannot be.
"""

import hmac
import json
import time
from hashlib import sha256
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

API = "https://api.stripe.com"
VERSION = "2024-06-20"


class PaymentError(Exception):
    """A call the provider refused. `status` and `body` come from the provider."""

    def __init__(self, message, status=0, body=b"", code=None):
        super().__init__(message)
        self.status, self.body, self.code = status, body, code


class Client:
    """Talks to one Stripe account. `transport` is only there for tests."""

    def __init__(self, secret, version=VERSION, api=API, transport=None):
        self.secret = secret
        self.version = version
        self.api = api.rstrip("/")
        self.transport = transport or send

    def post(self, path, **fields):
        """POST form-encoded fields to /v1/... and return the parsed JSON."""
        return self.call("POST", path, urlencode(fields).encode())

    def get(self, path, **params):
        """GET /v1/... with query parameters and return the parsed JSON."""
        query = f"?{urlencode(params)}" if params else ""
        return self.call("GET", f"{path}{query}", None)

    def checkout(self, price, url, quantity=1, mode="payment", **extra):
        """Start a Checkout session. Send the browser to the returned 'url'."""
        fields = {"line_items[0][price]": price, "line_items[0][quantity]": quantity}
        fields.update(mode=mode, success_url=url, cancel_url=extra.pop("cancel_url", url), **extra)
        return self.post("/v1/checkout/sessions", **fields)

    def session(self, identifier):
        """One checkout session again, to see whether it was paid."""
        return self.get(f"/v1/checkout/sessions/{identifier}")

    def call(self, method, path, body):
        headers = {
            "Authorization": f"Bearer {self.secret}",
            "Stripe-Version": self.version,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        status, raw = self.transport(self.api + path, body, headers)
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            raise PaymentError("The provider sent something that is not JSON", status, raw)

        if not 200 <= status < 300:
            raise PaymentError(
                data.get("error", {}).get("message", "Payment refused"),
                status,
                raw,
                data.get("error", {}).get("type"),
            )
        return data


def send(url, body, headers):
    """The default transport: one urlopen call, returning (status, body)."""
    request = UrlRequest(url, data=body, headers=headers, method="POST" if body else "GET")
    try:
        with urlopen(request) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()
    except URLError as error:
        raise PaymentError(f"Could not reach the provider: {error.reason}")


def sign(payload, secret, timestamp=None):
    """The Stripe-Signature header for this exact payload and timestamp."""
    stamp = int(timestamp if timestamp is not None else time.time())
    digest = hmac.new(secret.encode(), f"{stamp}.{payload}".encode(), sha256).hexdigest()
    return f"t={stamp},v1={digest}"


def verify(payload, header, secret, tolerance=300):
    """True when this payload really came from the provider just now.

    More than one v1 is allowed, which is how the provider rotates a secret.
    """
    if not payload or not header:
        return False

    stamp, signatures = None, []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            stamp = value
        elif key == "v1" and value:
            signatures.append(value)

    try:
        if not stamp or abs(time.time() - int(stamp)) > tolerance:
            return False
    except (TypeError, ValueError):
        return False

    expected = hmac.new(secret.encode(), f"{stamp}.{payload}".encode(), sha256).hexdigest()
    return any(hmac.compare_digest(expected, signature) for signature in signatures)
