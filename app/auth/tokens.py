"""Verify Supabase Auth access tokens.

The project signs tokens with an asymmetric key (ES256). The public half is
published at ``{SUPABASE_URL}/auth/v1/.well-known/jwks.json``; we fetch it,
cache it, and check every token against it. No secret is needed to verify.
"""

import asyncio
from typing import Protocol
from uuid import UUID

import jwt

from app.config import Settings

# Only the asymmetric algorithm the project uses. Never list HS256 here: a
# token must not be able to pick a weaker algorithm than the key requires.
ALGORITHMS = ["ES256"]
AUDIENCE = "authenticated"
JWKS_CACHE_SECONDS = 10 * 60


class InvalidToken(Exception):
    """The token is missing, malformed, expired, or not signed by our project."""


class KeysUnavailable(Exception):
    """The signing keys could not be fetched from Supabase."""


class SigningKeySource(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK: ...


class TokenVerifier:
    def __init__(self, issuer: str, keys: SigningKeySource) -> None:
        self.issuer = issuer
        self._keys = keys

    @classmethod
    def from_settings(cls, settings: Settings) -> "TokenVerifier":
        auth_url = f"{settings.supabase_url}/auth/v1"
        # PyJWKClient fetches lazily (on the first token), so building it
        # makes no network call.
        keys = jwt.PyJWKClient(
            f"{auth_url}/.well-known/jwks.json",
            cache_keys=True,
            lifespan=JWKS_CACHE_SECONDS,
        )
        return cls(issuer=auth_url, keys=keys)

    async def verify(self, token: str) -> UUID:
        """Return the Supabase user id (``sub``) of a valid token."""
        try:
            # PyJWKClient uses blocking urllib; keep it off the event loop.
            key = await asyncio.to_thread(self._keys.get_signing_key_from_jwt, token)
        except jwt.PyJWKClientConnectionError as exc:
            raise KeysUnavailable(str(exc)) from exc
        except (jwt.PyJWKClientError, jwt.PyJWTError) as exc:
            # Unknown key id, or a token too malformed to read its header.
            raise InvalidToken(str(exc)) from exc

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=ALGORITHMS,
                audience=AUDIENCE,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
            return UUID(claims["sub"])
        except (jwt.PyJWTError, ValueError, TypeError) as exc:
            raise InvalidToken(str(exc)) from exc
