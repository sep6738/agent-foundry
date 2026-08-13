"""API-key authenticator tests."""

from __future__ import annotations

from agent_backend.app.auth import APIKeyAuthenticator


def test_authenticator_accepts_header_key_and_maps_user() -> None:
    authenticator = APIKeyAuthenticator(("secret-1",), {"secret-1": "alice"})
    result = authenticator.authenticate(header_key="secret-1", authorization=None)
    assert result.error is None
    assert result.user_id == "alice"


def test_authenticator_accepts_bearer_token() -> None:
    authenticator = APIKeyAuthenticator(("secret-2",))
    result = authenticator.authenticate(
        header_key=None,
        authorization="Bearer secret-2",
        header_user="bob",
    )
    assert result.error is None
    assert result.user_id == "bob"


def test_authenticator_rejects_unknown_key() -> None:
    authenticator = APIKeyAuthenticator(("secret-1",))
    result = authenticator.authenticate(header_key="wrong", authorization=None)
    assert result.error == "unauthorized"
