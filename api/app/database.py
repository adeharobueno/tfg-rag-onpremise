import asyncpg
import os
from pgvector.asyncpg import register_vector

DB_DSN = os.getenv("DATABASE_URL", "postgresql://api_gateway:App_Pass_Gateway_Secure_2026%3F@postgres_db:5432/tfg_rag_db")

async def get_db_connection():
    conn = await asyncpg.connect(DB_DSN)
    await register_vector(conn)
    return conn

async def search_vectors_with_rls(conn, embedding: list[float], dept: str, role: str, limit: int = 3):
    async with conn.transaction():
        # Configuración segura de variables de entorno de transacción (GUC)
        await conn.execute("SELECT set_config('app.current_user_dept', $1, true);", dept)
        await conn.execute("SELECT set_config('app.current_user_role', $1, true);", role)
        
        # Recuperamos explícitamente el campo 'metadata' (JSONB) y 'confidentiality_level'
        query = """
            SELECT section_id, text, metadata, confidentiality_level, (embedding <=> $1) AS distance
            FROM document_sections
            ORDER BY embedding <=> $1 LIMIT $2;
        """
        return await conn.fetch(query, embedding, limit)
