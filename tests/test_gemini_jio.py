"""Tests for gemini_jio (Jio AI Gemini Pro activation-link generator)."""
import base64
import json
import os
import unittest
from unittest import mock

import gemini_jio
from gemini_jio import (gemini_menu, generate_activation_link,
                        gemini_result_text, how_it_works_text, _sa_jwt,
                        _config, _request_example)

_ENV_VARS = [
    "GEMINI_JIO_SA_FILE", "GEMINI_JIO_SA_JSON", "GEMINI_JIO_PARTNER",
    "GEMINI_JIO_PRODUCT", "GEMINI_JIO_PROMOTION", "GEMINI_JIO_REGION",
    "GEMINI_JIO_PARTNER_USER_TOKEN", "GEMINI_JIO_SUBSCRIPTION_ID",
    "GEMINI_JIO_ENV", "GEMINI_JIO_SCOPE", "GEMINI_JIO_BASE",
]


def _clean_env():
    """A dict clearing all GEMINI_JIO_* vars for patch.dict."""
    return {k: "" for k in _ENV_VARS}


def _make_sa():
    """A real (throwaway) RSA service account so the JWT can be verified."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode("ascii")
    return {"client_email": "svc@test.iam.gserviceaccount.com",
            "private_key": pem, "project_id": "test-proj"}, key


def _mock_token_client(token="tok123", expire="2026-11-06T12:00:00Z",
                       status=(200, "https://accounts.google.com/v3/signin")):
    """A client whose POST returns an access token then a userSession, and
    whose GET reports a live 200 -> forces the LIVE path."""
    client = mock.Mock()
    access = mock.Mock()
    access.raise_for_status.return_value = None
    access.json.return_value = {"access_token": "access-xyz", "expires_in": 3600}
    session = mock.Mock()
    session.raise_for_status.return_value = None
    session.status_code = 200
    session.json.return_value = {"userSession": {"token": token,
                                                 "expireTime": expire}}
    client.post.side_effect = [access, session]
    get = mock.Mock()
    get.status_code = status[0]
    get.url = status[1]
    client.get.return_value = get
    return client


class StudyTextTests(unittest.TestCase):
    def test_explains_the_mechanism(self):
        text = how_it_works_text()
        for needle in ("serviceactivation.google.com/subscription/new",
                       "reseller", "RS256", "userSessions:generate",
                       "Pub/Sub", "18 months", "not forgeable"):
            self.assertIn(needle, text, "missing: " + needle)

    def test_link_shape_constant(self):
        self.assertIn("subscription/new", how_it_works_text())


class MenuTests(unittest.TestCase):
    def test_menu_buttons(self):
        menu = gemini_menu()
        data = [btn["callback_data"]
                for row in menu["reply_markup"]["inline_keyboard"]
                for btn in row]
        self.assertIn("gj:gen", data)
        self.assertIn("gj:how", data)
        self.assertIn("ui:home", data)
        self.assertIn("Gemini", menu["text"])


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        with mock.patch.dict(os.environ, _clean_env(), clear=False):
            cfg = _config()
        self.assertEqual(cfg["region"], "IN")
        self.assertFalse(cfg["sandbox"])
        self.assertIn("paymentsresellersubscription.googleapis.com", cfg["api_base"])

    def test_sandbox(self):
        with mock.patch.dict(os.environ, {"GEMINI_JIO_ENV": "sandbox"}, clear=False):
            cfg = _config()
        self.assertTrue(cfg["sandbox"])
        self.assertIn("sandbox", cfg["act_base"])


class TemplateTests(unittest.TestCase):
    def test_template_when_unconfigured(self):
        with mock.patch.dict(os.environ, _clean_env(), clear=False):
            result = generate_activation_link(verify=False)
        self.assertEqual(result["mode"], "template")
        self.assertIn("/subscription/new/", result["url"])
        self.assertIn("GEMINI_JIO_PARTNER", result["missing"])
        self.assertIn("GEMINI_JIO_PRODUCT", result["missing"])
        self.assertIn("GEMINI_JIO_SA_FILE",
                      "".join(result["missing"]))
        self.assertEqual(len(result["steps"]), 6)
        req = result["request_example"]
        self.assertIn("subscription", req)
        self.assertEqual(req["subscription"]["serviceLocation"]["regionCode"],
                         "IN")
        self.assertEqual(len(req["subscription"]["lineItems"]), 1)

    def test_request_example_product_and_promotion(self):
        with mock.patch.dict(os.environ, _clean_env(), clear=False):
            result = generate_activation_link(
                partner="p", product="partners/p/products/GOOGLE_AI_PRO",
                promotion="partners/p/promotions/FREE_18MO",
                partner_user_token="jio-999", verify=False)
        self.assertEqual(result["mode"], "template")  # no SA key -> template
        line = result["request_example"]["subscription"]["lineItems"][0]
        self.assertEqual(line["product"], "partners/p/products/GOOGLE_AI_PRO")
        self.assertEqual(line["lineItemPromotionSpecs"][0]["promotion"],
                         "partners/p/promotions/FREE_18MO")
        self.assertEqual(result["request_example"]["subscription"]
                         ["partnerUserToken"], "jio-999")
        self.assertEqual(result["request_example"]["parent"], "partners/p")


class JwtTests(unittest.TestCase):
    def test_sa_jwt_structure_and_signature(self):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        sa, key = _make_sa()
        token = _sa_jwt(sa, gemini_jio._DEFAULT_SCOPE, 1_700_000_000)
        header_b64, payload_b64, sig_b64 = token.split(".")
        # no padding added (urlsafe, '=' stripped)
        pad = lambda s: s + "=" * (-len(s) % 4)
        header = json.loads(base64.urlsafe_b64decode(pad(header_b64)))
        payload = json.loads(base64.urlsafe_b64decode(pad(payload_b64)))
        self.assertEqual(header["alg"], "RS256")
        self.assertEqual(payload["iss"], sa["client_email"])
        self.assertEqual(payload["aud"], gemini_jio._TOKEN_URL)
        self.assertEqual(payload["exp"] - payload["iat"], 3600)
        # verify the signature with the public key
        signing_input = (header_b64 + "." + payload_b64).encode("ascii")
        sig = base64.urlsafe_b64decode(pad(sig_b64))
        pub = serialization.load_pem_public_key(key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo))
        pub.verify(sig, signing_input, padding.PKCS1v15(), hashes.SHA256())

    def test_sa_jwt_claims_change_with_inputs(self):
        sa, _ = _make_sa()
        t1 = _sa_jwt(sa, "scope-a", 1_000_000)
        t2 = _sa_jwt(sa, "scope-b", 1_000_001)
        self.assertNotEqual(t1, t2)


class LiveTests(unittest.TestCase):
    def _gen(self, client, **kw):
        sa, _ = _make_sa()
        kw.setdefault("sa", sa)
        kw.setdefault("partner", "p")
        kw.setdefault("product", "partners/p/products/GOOGLE_AI_PRO")
        kw.setdefault("partner_user_token", "jio-999")
        kw.setdefault("verify", True)
        return generate_activation_link(client=client, **kw)

    def test_live_path_mints_url(self):
        result = self._gen(_mock_token_client(token="LIVETOK"),
                           subscription_id="sub-1")
        self.assertEqual(result["mode"], "live")
        self.assertTrue(result["url"].endswith("/subscription/new/LIVETOK"))
        self.assertEqual(result["token"], "LIVETOK")
        self.assertEqual(result["expires_at"], "2026-11-06T12:00:00Z")
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["url_check"], (200,
                         "https://accounts.google.com/v3/signin"))
        self.assertIn("LIVE", gemini_result_text(result))

    def test_verify_false_skips_get(self):
        client = _mock_token_client()
        result = self._gen(client, verify=False)
        self.assertEqual(result["mode"], "live")
        self.assertIsNone(result["url_check"])
        client.get.assert_not_called()

    def test_token_endpoint_failure_is_error(self):
        client = mock.Mock()
        client.post.side_effect = gemini_jio.requests.RequestException("down")
        result = self._gen(client)
        self.assertEqual(result["mode"], "error")
        self.assertIn("down", result["note"])
        self.assertIn("right now", gemini_result_text(result))

    def test_user_sessions_error_is_error(self):
        sa, _ = _make_sa()
        client = mock.Mock()
        access = mock.Mock()
        access.raise_for_status.return_value = None
        access.json.return_value = {"access_token": "a"}
        bad = mock.Mock()
        bad.status_code = 401
        bad.text = "Unauthorized"
        client.post.side_effect = [access, bad]
        result = generate_activation_link(
            client=client, sa=sa, partner="p",
            product="partners/p/products/X", partner_user_token="u",
            verify=False)
        self.assertEqual(result["mode"], "error")
        self.assertIn("401", result["note"])

    def test_no_token_in_response_is_error(self):
        sa, _ = _make_sa()
        client = mock.Mock()
        access = mock.Mock()
        access.raise_for_status.return_value = None
        access.json.return_value = {"access_token": "a"}
        session = mock.Mock()
        session.status_code = 200
        session.json.return_value = {"userSession": {}}  # empty
        client.post.side_effect = [access, session]
        result = generate_activation_link(
            client=client, sa=sa, partner="p",
            product="partners/p/products/X", partner_user_token="u",
            verify=False)
        self.assertEqual(result["mode"], "error")
        self.assertIn("no token", result["note"])


class ResultTextTests(unittest.TestCase):
    def test_template_text_has_request_and_missing(self):
        with mock.patch.dict(os.environ, _clean_env(), clear=False):
            result = generate_activation_link(verify=False)
        text = gemini_result_text(result)
        self.assertIn("TEMPLATE", text)
        self.assertIn("userSessions:generate", text)
        self.assertIn("GEMINI_JIO_PARTNER", text)
        self.assertIn("/subscription/new/<TOKEN>", text)

    def test_error_text_mentions_note(self):
        with mock.patch.dict(os.environ, _clean_env(), clear=False):
            result = generate_activation_link(verify=False)
            result["mode"] = "error"
            result["note"] = "boom"
        text = gemini_result_text(result)
        self.assertIn("boom", text)


if __name__ == "__main__":
    unittest.main()
