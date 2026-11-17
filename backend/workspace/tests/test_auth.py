"""Token authentication, the sign-up token, and per-user ownership (PRD §39)."""
from django.test import override_settings

from common.testing import FAST_PASSWORD_HASHERS
from workspace.auth import hash_token, issue_token, MAX_TOKENS_PER_USER
from workspace.models import ApiToken, ChatSession, Workspace
from workspace.tests.helpers import WorkspaceTestCase, bearer, build_pdf, make_user


class TokenAuthenticationTests(WorkspaceTestCase):
    def test_missing_token_is_401_with_the_error_envelope(self):
        response = self.client.get("/api/v1/workspaces/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["WWW-Authenticate"], "Bearer")
        error = response.json()["error"]
        self.assertEqual(error["code"], "authentication_required")
        self.assertEqual(set(error), {"code", "message", "retryable", "stage", "details"})

    def test_invalid_tokens_are_401(self):
        for header in ("Bearer rr_not-a-real-token", "Bearer", "Bearer a b", "Bearer abc", "Bearer rr_é"):
            with self.subTest(header=header):
                response = self.client.get("/api/v1/workspaces/", HTTP_AUTHORIZATION=header)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["error"]["code"], "authentication_required")

    def test_only_a_hash_of_the_token_is_stored(self):
        token = issue_token(self.user)
        self.assertTrue(token.startswith("rr_"))
        self.assertFalse(ApiToken.objects.filter(key_hash=token).exists())
        self.assertTrue(ApiToken.objects.filter(key_hash=hash_token(token), user=self.user).exists())

    def test_token_use_is_recorded(self):
        token = issue_token(self.user)
        self.client.get("/api/v1/workspaces/", HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertIsNotNone(ApiToken.objects.get(key_hash=hash_token(token)).last_used_at)

    def test_old_tokens_are_pruned_beyond_the_cap(self):
        first = issue_token(self.user)
        for _ in range(MAX_TOKENS_PER_USER + 2):
            issue_token(self.user)
        self.assertLessEqual(ApiToken.objects.filter(user=self.user).count(), MAX_TOKENS_PER_USER)
        response = self.client.get("/api/v1/workspaces/", HTTP_AUTHORIZATION=f"Bearer {first}")
        self.assertEqual(response.status_code, 401)


@override_settings(PASSWORD_HASHERS=FAST_PASSWORD_HASHERS)
class SignUpTokenTests(WorkspaceTestCase):
    def sign_up(self, username, email, password="correct horse battery"):
        return self.client.post("/api/v1/sign-up/", {"EMAIL": email, "USERNAME": username, "PASSWORD": password},
                                content_type="application/json")

    def sign_in(self, username, password="correct horse battery"):
        return self.client.post("/api/v1/sign-in/", {"USERNAME": username, "PASSWORD": password},
                                content_type="application/json")

    def test_sign_up_adds_a_working_token_and_keeps_its_shape(self):
        response = self.sign_up("newcomer", "newcomer@example.com")
        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        self.assertEqual(data["username"], "newcomer")
        self.assertEqual(data["email"], "newcomer@example.com")
        self.assertEqual(data["response"], "User created successfully!")
        self.assertTrue(data["token"].startswith("rr_"))
        listing = self.client.get("/api/v1/workspaces/", HTTP_AUTHORIZATION=f"Bearer {data['token']}")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([workspace["is_default"] for workspace in listing.json()["results"]], [True])

    def test_every_sign_in_issues_a_new_token_and_old_ones_keep_working(self):
        first = self.sign_up("repeat", "repeat@example.com").json()["data"]["token"]
        again = self.sign_in("repeat")
        self.assertEqual(again.status_code, 200)
        second = again.json()["token"]
        self.assertNotEqual(first, second)
        for token in (first, second):
            self.assertEqual(self.client.get("/api/v1/workspaces/", HTTP_AUTHORIZATION=f"Bearer {token}").status_code, 200)

    def test_signing_up_again_never_mints_a_token(self):
        self.sign_up("repeat", "repeat@example.com")
        again = self.sign_up("repeat", "repeat@example.com", password="another long passphrase")
        self.assertEqual(again.status_code, 409)
        self.assertIsNone(again.json()["data"])
        self.assertEqual(ApiToken.objects.filter(user__username="repeat").count(), 1)


class OwnershipTests(WorkspaceTestCase):
    """Another user's objects are indistinguishable from missing ones: 404."""

    def setUp(self):
        super().setUp()
        self.document = self.add_text("Alpha paragraph about embeddings.", title="Mine")
        self.workspace_id = self.document["workspace_id"]
        self.conversation = self.post("/api/v1/conversations/", {"document_ids": [self.document["id"]]}).json()
        self.mallory = make_user("mallory")
        self.intruder = bearer(self.mallory)

    def test_foreign_objects_are_404_for_every_verb(self):
        doc, conv, ws = self.document["id"], self.conversation["id"], self.workspace_id
        requests = [
            ("get", f"/api/v1/workspaces/{ws}/"), ("patch", f"/api/v1/workspaces/{ws}/"), ("delete", f"/api/v1/workspaces/{ws}/"),
            ("get", f"/api/v1/documents/{doc}/"), ("patch", f"/api/v1/documents/{doc}/"), ("delete", f"/api/v1/documents/{doc}/"),
            ("get", f"/api/v1/documents/{doc}/ingestion/"), ("post", f"/api/v1/documents/{doc}/ingestion/"),
            ("get", f"/api/v1/documents/{doc}/file/"), ("get", f"/api/v1/documents/{doc}/text/"),
            ("get", f"/api/v1/conversations/{conv}/"), ("patch", f"/api/v1/conversations/{conv}/"),
            ("delete", f"/api/v1/conversations/{conv}/"), ("get", f"/api/v1/conversations/{conv}/messages/"),
            ("post", f"/api/v1/conversations/{conv}/messages/"),
            ("get", f"/api/v1/documents/?workspace_id={ws}"), ("get", f"/api/v1/conversations/?workspace_id={ws}"),
        ]
        for method, path in requests:
            with self.subTest(method=method, path=path):
                if method in ("post", "patch"):
                    response = getattr(self.client, method)(path, {"title": "x", "name": "x", "content": "q"},
                                                            content_type="application/json", **self.intruder)
                else:
                    response = getattr(self.client, method)(path, **self.intruder)
                self.assertEqual(response.status_code, 404, response.content)
                self.assertEqual(response.json()["error"]["code"], "not_found")
        # Nothing was changed or deleted along the way.
        self.assertEqual(self.get(f"/api/v1/documents/{doc}/").json()["title"], "Mine")
        self.assertTrue(ChatSession.objects.filter(pk=conv).exists())
        self.assertTrue(Workspace.objects.filter(pk=ws).exists())

    def test_foreign_document_ids_cannot_be_attached(self):
        own_workspace = self.client.get("/api/v1/workspaces/", **self.intruder).json()["results"][0]["id"]
        response = self.client.post(
            "/api/v1/conversations/", {"workspace_id": own_workspace, "document_ids": [self.document["id"]]},
            content_type="application/json", **self.intruder,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "invalid_request")
        self.assertIn("document_ids", response.json()["error"]["details"])

    def test_uploads_cannot_target_a_foreign_workspace(self):
        response = self.upload("paper.pdf", build_pdf(["Alpha"]), auth=self.intruder, workspace_id=self.workspace_id)
        self.assertEqual(response.status_code, 404)

    def test_lists_only_show_the_callers_objects(self):
        documents = self.client.get("/api/v1/documents/", **self.intruder).json()["results"]
        conversations = self.client.get("/api/v1/conversations/", **self.intruder).json()["results"]
        self.assertEqual((documents, conversations), ([], []))
