import json
from urllib.parse import parse_qs

import pytest

from gromon import payment


class FakeTransport:
    """Stands in for urlopen so the tests never touch the network."""

    def __init__(self, status=200, payload=None, raw=None):
        self.calls = []
        self.status = status
        self.raw = raw
        self.payload = payload if payload is not None else {"id": "cs_1", "url": "https://pay.test/x"}

    def __call__(self, url, body, headers):
        self.calls.append({"url": url, "body": body, "headers": headers})
        raw = self.raw if self.raw is not None else json.dumps(self.payload)
        return self.status, raw.encode() if isinstance(raw, str) else raw

    @property
    def fields(self):
        parsed = parse_qs(self.calls[-1]["body"].decode())
        return {key: value[0] for key, value in parsed.items()}


def client(**kwargs):
    transport = FakeTransport(**kwargs)
    return payment.Client("sk_test_123", transport=transport), transport


class TestClient:
    def test_the_secret_is_sent_as_a_bearer_token(self):
        stripe, transport = client()
        stripe.get("/v1/customers")
        assert transport.calls[0]["headers"]["Authorization"] == "Bearer sk_test_123"

    def test_the_api_version_is_sent(self):
        stripe, transport = client()
        stripe.get("/v1/customers")
        assert transport.calls[0]["headers"]["Stripe-Version"] == payment.VERSION

    def test_the_version_can_be_pinned(self):
        transport = FakeTransport()
        payment.Client("sk", version="2020-01-01", transport=transport).get("/v1/customers")
        assert transport.calls[0]["headers"]["Stripe-Version"] == "2020-01-01"

    def test_the_base_url_can_be_replaced(self):
        transport = FakeTransport()
        payment.Client("sk", api="https://api.test/", transport=transport).get("/v1/customers")
        assert transport.calls[0]["url"] == "https://api.test/v1/customers"

    def test_fields_are_form_encoded(self):
        stripe, transport = client()
        stripe.post("/v1/subscriptions", customer="cus_1", **{"items[0][price]": "price_1"})
        assert transport.calls[0]["body"] == b"customer=cus_1&items%5B0%5D%5Bprice%5D=price_1"
        assert transport.calls[0]["headers"]["Content-Type"].startswith(
            "application/x-www-form-urlencoded"
        )

    def test_get_params_go_into_the_query_string(self):
        stripe, transport = client()
        stripe.get("/v1/charges", limit=3)
        assert transport.calls[0]["url"].endswith("/v1/charges?limit=3")
        assert transport.calls[0]["body"] is None

    def test_the_json_comes_back(self):
        stripe, transport = client()
        assert stripe.get("/v1/customers")["id"] == "cs_1"

    def test_a_refusal_raises(self):
        stripe, _ = client(
            status=402,
            payload={"error": {"message": "Card declined", "type": "card_error"}},
        )
        try:
            stripe.post("/v1/charges", amount=100)
        except payment.PaymentError as error:
            assert error.status == 402
            assert error.code == "card_error"
            assert str(error) == "Card declined"
        else:
            assert False, "a 402 should raise"

    def test_a_refusal_without_json_says_so(self):
        stripe, _ = client(status=500, raw="<html>gateway</html>")
        try:
            stripe.get("/v1/charges")
        except payment.PaymentError as error:
            assert "not JSON" in str(error)
            assert error.status == 500
        else:
            assert False, "a 500 should raise"

    def test_checkout_sends_the_line_item(self):
        stripe, transport = client()
        stripe.checkout("price_123", url="https://shop.test/thanks", quantity=2)
        assert transport.fields == {
            "line_items[0][price]": "price_123",
            "line_items[0][quantity]": "2",
            "mode": "payment",
            "success_url": "https://shop.test/thanks",
            "cancel_url": "https://shop.test/thanks",
        }

    def test_checkout_can_cancel_somewhere_else(self):
        stripe, transport = client()
        stripe.checkout("price_123", url="https://shop.test/thanks", cancel_url="https://shop.test")
        assert transport.fields["cancel_url"] == "https://shop.test"

    def test_checkout_returns_the_url_to_redirect_to(self):
        stripe, transport = client()
        assert stripe.checkout("price_123", url="https://shop.test")["url"] == "https://pay.test/x"
        assert transport.calls[0]["url"].endswith("/v1/checkout/sessions")

    def test_a_session_is_fetched_by_id(self):
        stripe, transport = client()
        stripe.session("cs_123")
        assert transport.calls[0]["url"].endswith("/v1/checkout/sessions/cs_123")


class TestSignature:
    PAYLOAD = b'{"id": "evt_1", "type": "checkout.session.completed"}'
    SECRET = "whsec_test"

    def test_a_signature_we_made_verifies(self):
        header = payment.sign(self.PAYLOAD, self.SECRET)
        assert payment.verify(self.PAYLOAD, header, self.SECRET)

    def test_the_shape_is_the_documented_one(self):
        header = payment.sign(self.PAYLOAD, self.SECRET, timestamp=1492774577)
        stamp, signature = header.split(",")
        assert stamp == "t=1492774577"
        assert signature.startswith("v1=") and len(signature) == 67

    def test_another_payload_does_not_verify(self):
        header = payment.sign(self.PAYLOAD, self.SECRET)
        assert not payment.verify(b'{"id": "evt_2"}', header, self.SECRET)

    def test_another_secret_does_not_verify(self):
        header = payment.sign(self.PAYLOAD, self.SECRET)
        assert not payment.verify(self.PAYLOAD, header, "whsec_other")

    def test_an_old_signature_is_refused(self):
        header = payment.sign(self.PAYLOAD, self.SECRET, timestamp=1492774577)
        assert not payment.verify(self.PAYLOAD, header, self.SECRET)

    def test_the_tolerance_can_be_widened(self):
        header = payment.sign(self.PAYLOAD, self.SECRET, timestamp=1492774577)
        assert payment.verify(self.PAYLOAD, header, self.SECRET, tolerance=10**9)

    def test_rotation_keeps_the_old_secret_working(self):
        old = payment.sign(self.PAYLOAD, self.SECRET, timestamp=1492774577)
        new = payment.sign(self.PAYLOAD, "whsec_next", timestamp=1492774577)
        both = f"{old},{new.split(',')[1]}"
        assert payment.verify(self.PAYLOAD, both, self.SECRET, 10**9)
        assert payment.verify(self.PAYLOAD, both, "whsec_next", 10**9)

    def test_a_missing_header_is_refused(self):
        assert not payment.verify(self.PAYLOAD, "", self.SECRET)
        assert not payment.verify(self.PAYLOAD, None, self.SECRET)
        assert not payment.verify(b"", payment.sign(self.PAYLOAD, self.SECRET), self.SECRET)

    def test_a_header_without_a_timestamp_is_refused(self):
        assert not payment.verify(self.PAYLOAD, "v1=deadbeef", self.SECRET)

    def test_a_rubbish_timestamp_is_refused(self):
        assert not payment.verify(self.PAYLOAD, "t=yesterday,v1=deadbeef", self.SECRET)


class TestErrors:
    def test_a_network_failure_is_a_payment_error(self):
        def broken(url, body, headers):
            raise payment.PaymentError("Could not reach the provider")

        with pytest.raises(payment.PaymentError):
            payment.Client("sk", transport=broken).get("/v1/charges")

    def test_the_error_keeps_what_the_provider_sent(self):
        error = payment.PaymentError("nope", 402, b'{"error": {}}', "card_error")
        assert (error.status, error.body, error.code) == (402, b'{"error": {}}', "card_error")
