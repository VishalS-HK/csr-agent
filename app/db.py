from psycopg_pool import AsyncConnectionPool

from app.config import Settings


def create_pool(settings: Settings) -> AsyncConnectionPool:
    """Build the connection pool without connecting.

    Open it with ``await pool.open(wait=False)`` so the app starts even when
    the database is unreachable; requests then fail with ``PoolTimeout``
    instead of the app crashing at startup.
    """
    return AsyncConnectionPool(
        conninfo=settings.database_url.get_secret_value(),
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        timeout=settings.db_pool_timeout_seconds,
        open=False,
        name="app",
    )
