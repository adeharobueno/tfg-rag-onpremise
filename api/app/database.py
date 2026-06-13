import asyncpg
import os
from pgvector.asyncpg import register_vector

DB_DSN = os.getenv("DATABASE_URL")

async def get_db_connection():
    conn = await asyncpg.connect(DB_DSN)
    await register_vector(conn)
    return conn

async def search_vectors_with_rls(conn, embedding: list[float], dept: str, role: str, limit: int = None):
    async with conn.transaction():
        await conn.execute("SELECT set_config('app.current_user_dept', $1, true);", dept)
        await conn.execute("SELECT set_config('app.current_user_role', $1, true);", role)

        query = """
            SELECT section_id, text, metadata, confidentiality_level,
                   (embedding <=> $1) AS distance
            FROM document_sections
            ORDER BY embedding <=> $1 LIMIT $2;
        """
        if limit is None:
            try:
                conn_cfg = await get_db_connection_admin()
                row = await conn_cfg.fetchrow("SELECT value FROM rag_config WHERE key='top_k'")
                await conn_cfg.close()
                limit = int(row["value"]) if row else 6
            except Exception:
                limit = 6
        return await conn.fetch(query, embedding, limit)

DB_DSN_ADMIN = os.getenv("DATABASE_URL_ADMIN")

async def get_db_connection_admin():
    conn = await asyncpg.connect(DB_DSN_ADMIN)
    await register_vector(conn)
    return conn
