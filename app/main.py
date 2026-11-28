import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request, Response
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from app.auth import TokenVerifier
from app.config import Settings, get_settings
from app.db import create_pool

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    pool: AsyncConnectionPool | None = None,
    token_verifier: TokenVerifier | None = None,
) -> FastAPI:
    """App factory. Run with: uvicorn app.main:create_app --factory"""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.pool = pool or create_pool(settings or get_settings())
        app.state.token_verifier = token_verifier or TokenVerifier.from_settings(
            settings or get_settings()
        )
        await app.state.pool.open(wait=False)  # don't block startup on the DB
        try:
            yield
        finally:
            await app.state.pool.close()

    app = FastAPI(title="CSR Agent", lifespan=lifespan)

    @app.get("/health")
    async def health(request: Request, response: Response) -> dict[str, str]:
        try:
            async with request.app.state.pool.connection() as conn:
                await conn.execute("SELECT 1")
        except (psycopg.Error, PoolTimeout):
            logger.exception("Health check: database unavailable")
            response.status_code = 503
            return {"status": "degraded", "database": "unavailable"}
        return {"status": "ok", "database": "ok"}

    return app
