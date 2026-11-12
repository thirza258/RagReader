"""Helpers for tests that call token-protected endpoints.

It holds no TestCase, so the runner finds nothing to run in it. Every legacy,
deep-analysis and workspace endpoint (except sign-up, sign-in and
analysis-config) needs `Authorization: Bearer <token>`, and the analysis
WebSocket needs an auth frame first.
"""
from workspace.auth import issue_token

LOCMEM_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
# The production hasher (PBKDF2, ~1M iterations) would make every password
# test slow; behaviour does not depend on which hasher is configured.
FAST_PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


def bearer(user):
    """Extra request kwargs carrying a fresh token for `user`."""
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token(user)}"}


def sign_in(client, user):
    """Make every request `client` sends carry a fresh token for `user`; returns the token."""
    token = issue_token(user)
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return token


def auth_frame(token):
    """The first frame the analysis WebSocket expects."""
    return {"type": "auth", "token": token}


async def open_analysis_socket(communicator, token):
    """Connect and authenticate a WebsocketCommunicator; returns `connected`."""
    connected, _ = await communicator.connect()
    if connected:
        await communicator.send_json_to(auth_frame(token))
    return connected


class SignedInClientMixin:
    """`self.sign_in(user)` signs the test client in and returns the user."""

    def sign_in(self, user, client=None):
        sign_in(client or self.client, user)
        return user
