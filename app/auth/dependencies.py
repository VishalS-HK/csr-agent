"""FastAPI dependency that turns a bearer token into the customer it belongs to.

Endpoints take the customer from here, never from the request body or the
model (doc §8: derive identity from the authenticated request).
"""

import logging
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg_pool import PoolTimeout

from app.auth.tokens import InvalidToken, KeysUnavailable, TokenVerifier

logger = logging.getLogger(__name__)

# auto_error=False so a missing header gets our 401, not FastAPI's 403.
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Customer:
    id: UUID
    name: str
    email: str


def _unauthorized() -> HTTPException:
    # Same message for every token problem: don't tell callers which check failed.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing access token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _service_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Authentication is temporarily unavailable",
    )


async def get_current_customer(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Customer:
    if credentials is None:
        raise _unauthorized()

    verifier: TokenVerifier = request.app.state.token_verifier
    try:
        subject = await verifier.verify(credentials.credentials)
    except InvalidToken:
        raise _unauthorized() from None
    except KeysUnavailable:
        logger.exception("Could not fetch Supabase signing keys")
        raise _service_unavailable() from None

    try:
        async with request.app.state.pool.connection() as conn:
            cur = await conn.execute(
                "select id, name, email from app.customers where external_auth_subject = %s",
                (subject,),
            )
            row = await cur.fetchone()
    except (psycopg.Error, PoolTimeout):
        logger.exception("Could not look up the authenticated customer")
        raise _service_unavailable() from None

    if row is None:
        # A real Supabase user, but not linked to any customer record.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No customer account is linked to this login",
        )
    return Customer(id=row[0], name=row[1], email=row[2])


CurrentCustomer = Annotated[Customer, Depends(get_current_customer)]
