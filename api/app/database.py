import asyncpg
import os
import time
from pgvector.asyncpg import register_vector

DB_DSN = os.getenv("DATABASE_URL")
DB_DSN_ADMIN = os.getenv("DATABASE_URL_ADMIN")

# ── Connection Pools (initialized at FastAPI startup) ─────────
_pool = None
_pool_admin = None


async def init_pools():
    """Initialize connection pools. Called at FastAPI startup via lifespan."""
    global _pool, _pool_admin
    _pool = await asyncpg.create_pool(
        DB_DSN, min_size=2, max_size=8, init=register_vector
    )
    _pool_admin = await asyncpg.create_pool(
        DB_DSN_ADMIN, min_size=1, max_size=4, init=register_vector
    )


async def close_pools():
    """Close connection pools. Called at FastAPI shutdown via lifespan."""
    if _pool:
        await _pool.close()
    if _pool_admin:
        await _pool_admin.close()


def get_pool():
    return _pool


def get_pool_admin():
    return _pool_admin


# ── Config Cache with TTL ────────────────────────────────────
_config_cache = {}
_CONFIG_TTL = 30  # seconds


async def get_cached_config(key: str, default: str = None) -> str:
    """Read a config value from rag_config with 30s TTL cache."""
    now = time.time()
    if key in _config_cache:
        value, ts = _config_cache[key]
        if now - ts < _CONFIG_TTL:
            return value

    async with _pool_admin.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM rag_config WHERE key=$1", key
        )
    value = row["value"] if row else default
    _config_cache[key] = (value, now)
    return value


async def invalidate_config_cache():
    """Clear the config cache (called after config updates)."""
    global _config_cache
    _config_cache = {}


# ── RLS Vector Search (uses pool internally) ─────────────────
async def search_vectors_with_rls(
    embedding: list[float], dept: str, role: str, limit: int = None
):
    if limit is None:
        top_k = await get_cached_config("top_k", "6")
        limit = int(top_k)

    async with _pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_user_dept', $1, true);", dept
            )
            await conn.execute(
                "SELECT set_config('app.current_user_role', $1, true);", role
            )

            query = """
                SELECT section_id, text, metadata, confidentiality_level,
                       (embedding <=> $1) AS distance
                FROM document_sections
                ORDER BY embedding <=> $1 LIMIT $2;
            """
            return await conn.fetch(query, embedding, limit)
