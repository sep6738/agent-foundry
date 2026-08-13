"""Optional API-key authentication with per-key user mapping."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AuthResult:
    user_id: str | None = None
    error: str | None = None


class APIKeyAuthenticator:
    def __init__(self, api_keys: tuple[str, ...] = (), key_users: dict[str, str] | None = None):
        self.api_keys = set(api_keys)
        self.key_users = dict(key_users or {})

    def authenticate(
        self,
        *,
        header_key: str | None,
        authorization: str | None,
        header_user: str | None = None,
    ) -> AuthResult:
        if not self.api_keys:
            return AuthResult(user_id=header_user or "default")
        key = header_key
        if not key and authorization and authorization.startswith("Bearer "):
            key = authorization[7:]
        if not key or key not in self.api_keys:
            return AuthResult(error="unauthorized")
        user_id = self.key_users.get(key) or header_user or "default"
        return AuthResult(user_id=user_id)

    def is_configured(self) -> bool:
        return bool(self.api_keys)
