"""Accounts: password sign-up and claim, sign-in, sign-out, expiry, throttling (PRD §39).

Hermetic: locmem cache (the throttle counts there), MD5 hashing for speed.
"""
import os
from datetime import timedelta
from unittest import mock

os.environ.setdefault("RAG_DISABLE_ENGINE_INIT", "1")

from django.contrib.auth.hashers import check_password
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from common.testing import FAST_PASSWORD_HASHERS, LOCMEM_CACHE
from router.models import Document, GuestUser
from workspace.auth import hash_token, issue_token
from workspace.models import ApiToken

PASSWORD = "correct horse battery staple"


@override_settings(CACHES=LOCMEM_CACHE, PASSWORD_HASHERS=FAST_PASSWORD_HASHERS)
class AccountTestCase(TestCase):
    def setUp(self):
        cache.clear()  # Throttle history outlives each test in locmem.

    def sign_up(self, username="newcomer", email="newcomer@example.com", password=PASSWORD, **extra):
        body = {"USERNAME": username, "EMAIL": email}
        if password is not None:
            body["PASSWORD"] = password
        return self.client.post("/api/v1/sign-up/", body, content_type="application/json", **extra)

    def sign_in(self, password=PASSWORD, **identifier):
        body = {"PASSWORD": password, **(identifier or {"USERNAME": "newcomer"})}
        return self.client.post("/api/v1/sign-in/", body, content_type="application/json")

    def workspaces(self, token):
        return self.client.get("/api/v1/workspaces/", HTTP_AUTHORIZATION=f"Bearer {token}")


class SignUpTests(AccountTestCase):
    def test_new_account_stores_only_a_hash_and_gets_a_working_token(self):
        response = self.sign_up()
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(set(body), {"status", "message", "timestamp", "data"})
        self.assertEqual(body["data"]["response"], "User created successfully!")
        user = GuestUser.objects.get(username="newcomer")
        self.assertNotIn(PASSWORD, user.password)
        self.assertTrue(user.password.startswith("md5$"))
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(self.workspaces(body["data"]["token"]).status_code, 200)

    def test_password_validators_reject_weak_passwords_with_their_messages(self):
        for password, fragment in (("short", "too short"), ("password123", "too common"), ("12345678901", "entirely numeric")):
            with self.subTest(password=password):
                response = self.sign_up(password=password)
                self.assertEqual(response.status_code, 400)
                error = response.json()["error"]
                self.assertEqual(error["code"], "invalid_request")
                self.assertTrue(any(fragment in message for message in error["details"]["PASSWORD"]), error)
                self.assertIsNone(response.json()["data"])
        self.assertFalse(GuestUser.objects.filter(username="newcomer").exists())

    def test_similarity_to_the_username_is_checked(self):
        response = self.sign_up(username="marguerite", email="m@example.com", password="marguerite1")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(any("similar" in m for m in response.json()["error"]["details"]["PASSWORD"]))

    def test_blank_or_missing_fields_are_400_not_500(self):
        self.assertEqual(self.sign_up(password="").status_code, 400)
        response = self.client.post("/api/v1/sign-up/", {"EMAIL": "x@example.com"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("USERNAME", response.json()["error"]["details"])

    def test_an_account_with_a_password_is_409_and_never_gets_a_token(self):
        self.sign_up()
        for username, email in (("newcomer", "newcomer@example.com"), ("newcomer", "other@example.com"),
                                ("someone", "newcomer@example.com")):
            with self.subTest(username=username, email=email):
                response = self.sign_up(username=username, email=email, password="another long passphrase")
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["error"]["code"], "account_exists")
                self.assertIsNone(response.json()["data"])
        self.assertEqual(ApiToken.objects.count(), 1)
        self.assertTrue(GuestUser.objects.get(username="newcomer").check_password(PASSWORD))

    def test_a_password_is_required(self):
        # A passwordless account could later be claimed by anyone who learns
        # its username and email, so none can be created any more.
        response = self.sign_up(password=None)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")
        self.assertIn("PASSWORD", response.json()["error"]["details"])
        self.assertFalse(GuestUser.objects.filter(username="newcomer").exists())
        self.assertFalse(ApiToken.objects.exists())

    def test_new_usernames_cannot_contain_an_at_sign(self):
        response = self.sign_up(username="someone@example.com", email="real@example.com")
        self.assertEqual(response.status_code, 400)
        self.assertIn("USERNAME", response.json()["error"]["details"])
        self.assertFalse(GuestUser.objects.filter(email="real@example.com").exists())


class LegacyClaimTests(AccountTestCase):
    def setUp(self):
        super().setUp()
        self.legacy = GuestUser.objects.create(username="legacy", email="legacy@example.com")
        self.document = Document.objects.create(user=self.legacy, name="old.txt", source_type="text")
        # A token minted by the old identifier-only sign-up: whoever asked for it.
        self.old_token = issue_token(self.legacy)

    def test_exact_username_and_email_set_the_password_once(self):
        response = self.sign_up(username="legacy", email="legacy@example.com")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertTrue(data["claimed"])
        self.assertEqual(self.workspaces(data["token"]).status_code, 200)
        self.legacy.refresh_from_db()
        self.assertTrue(self.legacy.check_password(PASSWORD))
        # Same account, same documents.
        self.assertEqual(GuestUser.objects.filter(username="legacy").count(), 1)
        self.assertTrue(Document.objects.filter(pk=self.document.pk, user=self.legacy).exists())
        # Tokens handed out before the password existed are revoked.
        self.assertEqual(self.workspaces(self.old_token).status_code, 401)
        # The claim is one-time: the next attempt is an ordinary conflict.
        second = self.sign_up(username="legacy", email="legacy@example.com", password="attacker passphrase 42")
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["error"]["code"], "account_exists")
        self.assertTrue(GuestUser.objects.get(pk=self.legacy.pk).check_password(PASSWORD))
        self.assertEqual(self.sign_in(USERNAME="legacy").status_code, 200)

    def test_the_email_must_match_exactly(self):
        for email in ("other@example.com", "LEGACY@example.com"):
            with self.subTest(email=email):
                response = self.sign_up(username="legacy", email=email)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["error"]["code"], "account_exists")
        self.legacy.refresh_from_db()
        self.assertFalse(self.legacy.has_password)
        self.assertEqual(ApiToken.objects.filter(user=self.legacy).count(), 1)

    def test_a_weak_password_does_not_claim(self):
        response = self.sign_up(username="legacy", email="legacy@example.com", password="123")
        self.assertEqual(response.status_code, 400)
        self.legacy.refresh_from_db()
        self.assertFalse(self.legacy.has_password)

    def test_a_lost_race_does_not_overwrite_the_winner(self):
        # Another request sets the password between this one's read and write.
        def concurrent_claim(password, user):
            GuestUser.objects.filter(pk=user.pk).update(password="md5$winner$hash")
            return []

        with mock.patch("authentication.views.password_errors", side_effect=concurrent_claim):
            response = self.sign_up(username="legacy", email="legacy@example.com")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(GuestUser.objects.get(pk=self.legacy.pk).password, "md5$winner$hash")
        self.assertEqual(ApiToken.objects.filter(user=self.legacy).count(), 1)

    def test_plaintext_passwords_are_never_logged(self):
        with self.assertLogs("authentication.views", "INFO") as logs:
            self.sign_up(username="legacy", email="legacy@example.com")
        self.assertTrue(logs.output)
        self.assertFalse(any(PASSWORD in line for line in logs.output))


class SignInTests(AccountTestCase):
    def setUp(self):
        super().setUp()
        self.sign_up()

    def test_username_or_email_with_the_password_issues_a_token(self):
        for identifier in ({"USERNAME": "newcomer"}, {"EMAIL": "newcomer@example.com"}, {"USERNAME": "newcomer@example.com"}):
            with self.subTest(identifier=identifier):
                response = self.sign_in(**identifier)
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertEqual((body["username"], body["email"]), ("newcomer", "newcomer@example.com"))
                self.assertTrue(body["token"].startswith("rr_"))
                self.assertIsNotNone(body["expires_at"])
                self.assertEqual(self.workspaces(body["token"]).status_code, 200)

    def test_unknown_account_and_wrong_password_are_indistinguishable(self):
        with mock.patch("authentication.views.check_password", wraps=check_password) as dummy:
            unknown = self.sign_in(USERNAME="nobody")
        dummy.assert_called_once()  # A hash is checked even with no account.
        wrong = self.sign_in(password="not the password")
        self.assertEqual((unknown.status_code, wrong.status_code), (401, 401))
        self.assertEqual(unknown.content, wrong.content)
        self.assertEqual(unknown.json()["error"]["code"], "invalid_credentials")
        self.assertEqual(ApiToken.objects.count(), 1)  # Only the sign-up token.

    def test_a_passwordless_account_looks_like_a_wrong_password(self):
        # Revealing "no password yet" would list the accounts still open to a claim.
        GuestUser.objects.create(username="legacy", email="legacy@example.com")
        with mock.patch("authentication.views.check_password", wraps=check_password) as dummy:
            passwordless = self.sign_in(USERNAME="legacy")
        dummy.assert_called_once()
        unknown = self.sign_in(USERNAME="nobody")
        self.assertEqual(passwordless.status_code, 401)
        self.assertEqual(passwordless.content, unknown.content)
        self.assertFalse(ApiToken.objects.filter(user__username="legacy").exists())

    def test_an_identifier_with_an_at_sign_is_only_looked_up_as_an_email(self):
        # A legacy username equal to someone else's email must not shadow them.
        shadow = GuestUser.objects.create(username="newcomer@example.com", email="shadow@example.com")
        shadow.set_password("shadow passphrase 77")
        shadow.save()
        response = self.sign_in(USERNAME="newcomer@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["username"], "newcomer")
        wrong_account = self.sign_in(password="shadow passphrase 77", USERNAME="newcomer@example.com")
        self.assertEqual(wrong_account.status_code, 401)
        # The shadow account signs in with its own email.
        own = self.sign_in(password="shadow passphrase 77", EMAIL="shadow@example.com")
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.json()["username"], "newcomer@example.com")

    def test_missing_fields_are_400(self):
        response = self.client.post("/api/v1/sign-in/", {"PASSWORD": PASSWORD}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")
        response = self.client.post("/api/v1/sign-in/", {"USERNAME": "newcomer"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_a_stale_bearer_header_does_not_block_signing_in(self):
        response = self.client.post("/api/v1/sign-in/", {"USERNAME": "newcomer", "PASSWORD": PASSWORD},
                                    content_type="application/json", HTTP_AUTHORIZATION="Bearer rr_revoked")
        self.assertEqual(response.status_code, 200)


class SignOutAndExpiryTests(AccountTestCase):
    def setUp(self):
        super().setUp()
        self.token = self.sign_up().json()["data"]["token"]

    def test_sign_out_revokes_only_the_presenting_token(self):
        other = self.sign_in().json()["token"]
        response = self.client.post("/api/v1/sign-out/", HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.workspaces(self.token).status_code, 401)
        self.assertEqual(self.workspaces(other).status_code, 200)
        again = self.client.post("/api/v1/sign-out/", HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertEqual(again.status_code, 401)

    def test_sign_out_requires_a_token(self):
        response = self.client.post("/api/v1/sign-out/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "authentication_required")

    def test_tokens_expire_after_the_configured_days(self):
        record = ApiToken.objects.get(key_hash=hash_token(self.token))
        self.assertAlmostEqual(record.expires_at, timezone.now() + timedelta(days=30), delta=timedelta(minutes=1))
        with override_settings(RAG_TOKEN_TTL_DAYS=2):
            short = issue_token(record.user)
        self.assertAlmostEqual(ApiToken.objects.get(key_hash=hash_token(short)).expires_at,
                               timezone.now() + timedelta(days=2), delta=timedelta(minutes=1))

    def test_an_expired_token_is_401_everywhere_and_removed(self):
        ApiToken.objects.filter(key_hash=hash_token(self.token)).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.workspaces(self.token).status_code, 401)
        legacy = self.client.get("/api/v1/document/newcomer/", HTTP_AUTHORIZATION=f"Bearer {self.token}")
        self.assertEqual(legacy.status_code, 401)
        self.assertEqual(legacy.json()["error"]["code"], "authentication_required")
        self.assertFalse(ApiToken.objects.filter(key_hash=hash_token(self.token)).exists())


class ThrottleTests(AccountTestCase):
    @override_settings(RAG_AUTH_THROTTLE_RATE="3/min")
    def test_sign_in_and_sign_up_share_a_per_client_limit(self):
        for _ in range(3):
            self.assertEqual(self.sign_in(USERNAME="nobody").status_code, 401)
        limited = self.sign_in(USERNAME="nobody")
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()["error"]["code"], "rate_limited")
        self.assertTrue(limited.json()["error"]["retryable"])
        self.assertIn("Retry-After", limited)
        sign_up = self.sign_up(username="late", email="late@example.com")
        self.assertEqual(sign_up.status_code, 429)
        self.assertEqual(sign_up.json()["status"], 429)
        self.assertEqual(sign_up.json()["error"]["code"], "rate_limited")
        self.assertFalse(GuestUser.objects.filter(username="late").exists())
        # Another client still gets through.
        other = self.client.post("/api/v1/sign-in/", {"USERNAME": "nobody", "PASSWORD": "x"},
                                 content_type="application/json", REMOTE_ADDR="10.0.0.9")
        self.assertEqual(other.status_code, 401)

    @override_settings(RAG_AUTH_THROTTLE_RATE="", RAG_AUTH_IDENTIFIER_THROTTLE_RATE="3/hour")
    def test_one_account_is_limited_across_client_addresses(self):
        for index in range(3):
            response = self.client.post("/api/v1/sign-in/", {"USERNAME": "newcomer", "PASSWORD": "guess"},
                                        content_type="application/json", REMOTE_ADDR=f"10.0.0.{index + 1}")
            self.assertEqual(response.status_code, 401)
        limited = self.client.post("/api/v1/sign-in/", {"USERNAME": " NEWCOMER ", "PASSWORD": PASSWORD},
                                   content_type="application/json", REMOTE_ADDR="10.0.0.99")
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()["error"]["code"], "rate_limited")
        # Other accounts are unaffected.
        other = self.client.post("/api/v1/sign-in/", {"USERNAME": "someone", "PASSWORD": "guess"},
                                 content_type="application/json", REMOTE_ADDR="10.0.0.99")
        self.assertEqual(other.status_code, 401)

    @override_settings(RAG_AUTH_THROTTLE_RATE="3/min")
    def test_a_forged_forwarded_for_does_not_reset_the_client_limit(self):
        # NUM_PROXIES defaults to 1: only the address the proxy appended counts.
        for index in range(3):
            self.client.post("/api/v1/sign-in/", {"USERNAME": f"probe{index}", "PASSWORD": "x"},
                             content_type="application/json", HTTP_X_FORWARDED_FOR=f"1.2.3.{index}, 203.0.113.5")
        limited = self.client.post("/api/v1/sign-in/", {"USERNAME": "probe9", "PASSWORD": "x"},
                                   content_type="application/json", HTTP_X_FORWARDED_FOR="9.9.9.9, 203.0.113.5")
        self.assertEqual(limited.status_code, 429)

    @override_settings(RAG_AUTH_THROTTLE_RATE="", RAG_AUTH_IDENTIFIER_THROTTLE_RATE="")
    def test_an_empty_rate_disables_the_throttle(self):
        for _ in range(12):
            self.assertEqual(self.sign_in(USERNAME="nobody").status_code, 401)
