"""Customer authentication, with a locally generated key: no Supabase needed."""

import json
import time
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.auth import CurrentCustomer, TokenVerifier
from app.main import create_app

ISSUER = "https://test-project.supabase.co/auth/v1"
KID = "test-key"
LINKED_SUB = UUID("aaaaaaaa-0000-0000-0000-000000000001")
CUSTOMER_ID = UUID("10000000-0000-0000-0000-000000000001")

PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())


class StaticKeys:
    """Stands in for PyJWKClient: always serves our test public key."""

    def __init__(self, error: Exception | None = None) -> None:
        jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(PRIVATE_KEY.public_key()))
        self._key = jwt.PyJWK({**jwk, "kid": KID, "alg": "ES256"})
        self._error = error

    def get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK:
        if self._error:
            raise self._error
        if jwt.get_unverified_header(token).get("kid") != KID:
            raise jwt.PyJWKClientError("Unable to find a signing key that matches")
        return self._key


class FakeCursor:
    def __init__(self, row) -> None:
        self._row = row

    async def fetchone(self):
        return self._row


class FakeConnection:
    def __init__(self, fail: bool) -> None:
        self._fail = fail

    async def execute(self, query: str, params=None):
        if self._fail:
            raise psycopg.OperationalError("database down")
        assert "external_auth_subject" in query
        (subject,) = params
        row = (CUSTOMER_ID, "Asha Verma", "asha@example.com") if subject == LINKED_SUB else None
        return FakeCursor(row)


class FakePool:
    def __init__(self, fail: bool = False) -> None:
        self._fail = fail

    async def open(self, wait: bool = True) -> None:
        pass

    async def close(self) -> None:
        pass

    @asynccontextmanager
    async def connection(self):
        yield FakeConnection(self._fail)


def make_token(
    sub: str = str(LINKED_SUB),
    *,
    key=PRIVATE_KEY,
    algorithm: str = "ES256",
    kid: str = KID,
    expires_in: int = 3600,
    **overrides,
) -> str:
    now = int(time.time())
    claims = {
        "sub": sub,
        "aud": "authenticated",
        "iss": ISSUER,
        "iat": now,
        "exp": now + expires_in,
        "role": "authenticated",
        **overrides,
    }
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": kid})


def make_client(keys=None, pool=None) -> TestClient:
    app = create_app(
        pool=pool or FakePool(),
        token_verifier=TokenVerifier(issuer=ISSUER, keys=keys or StaticKeys()),
    )

    # Throwaway route: real endpoints arrive with the ticket API.
    @app.get("/whoami")
    async def whoami(customer: CurrentCustomer) -> dict[str, str]:
        return {"id": str(customer.id), "email": customer.email}

    return TestClient(app)


def get_whoami(token: str | None, **client_kwargs):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with make_client(**client_kwargs) as client:
        return client.get("/whoami", headers=headers)


def test_valid_token_resolves_linked_customer():
    resp = get_whoami(make_token())
    assert resp.status_code == 200
    assert resp.json() == {"id": str(CUSTOMER_ID), "email": "asha@example.com"}


def test_missing_token_is_401():
    resp = get_whoami(None)
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("not-a-jwt", id="garbage"),
        pytest.param(make_token(expires_in=-60), id="expired"),
        pytest.param(make_token(aud="anon"), id="wrong-audience"),
        pytest.param(make_token(iss="https://other.supabase.co/auth/v1"), id="wrong-issuer"),
        pytest.param(make_token(key=OTHER_PRIVATE_KEY), id="bad-signature"),
        pytest.param(make_token(kid="unknown"), id="unknown-key-id"),
        pytest.param(make_token(sub="not-a-uuid"), id="sub-not-uuid"),
        # Algorithm confusion: an HS256 token "signed" with a guessable secret.
        pytest.param(make_token(key="x" * 32, algorithm="HS256"), id="hs256-rejected"),
    ],
)
def test_invalid_tokens_are_401(token):
    resp = get_whoami(token)
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Invalid or missing access token"}


def test_token_without_exp_is_401():
    now = int(time.time())
    token = jwt.encode(
        {"sub": str(LINKED_SUB), "aud": "authenticated", "iss": ISSUER, "iat": now},
        PRIVATE_KEY, algorithm="ES256", headers={"kid": KID},
    )
    assert get_whoami(token).status_code == 401


def test_valid_token_for_unlinked_user_is_403():
    resp = get_whoami(make_token(sub=str(uuid4())))
    assert resp.status_code == 403


def test_unreachable_jwks_is_503():
    keys = StaticKeys(error=jwt.PyJWKClientConnectionError("connection refused"))
    assert get_whoami(make_token(), keys=keys).status_code == 503


def test_database_down_is_503():
    assert get_whoami(make_token(), pool=FakePool(fail=True)).status_code == 503
