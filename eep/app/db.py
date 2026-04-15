"""asyncpg connection pool management for EEP.

The pool is created once during application lifespan and closed on shutdown.
All DB credentials come from the DATABASE_URL environment variable.
"""

import os

import asyncpg

DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://infraguard:infraguard@localhost:5432/infraguard",
)

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    """Create the asyncpg connection pool. Called on application startup."""
    global _pool
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)


async def close_pool() -> None:
    """Close the asyncpg connection pool. Called on application shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """Return the active pool, raising RuntimeError if not initialised."""
    if _pool is None:
        raise RuntimeError("DB pool is not initialised — was init_pool() called?")
    return _pool
