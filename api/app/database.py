import asyncpg
import os

DB_DSN = os.getenv("DATABASE_URL", "postgresql://api_gateway:App_Pass_Gateway_Secure_2026?@postgres_db:5432/tfg_rag_db")

async def get_db_connection():
    return await asyncpg.connect(DB_DSN)

async def search_vectors_with_rls(conn, embedding: list[float], dept: str, clearance: str, role: str, limit: int = 3):
    # Abrimos una transacción estricta
    async with conn.transaction():
        # Inyección de variables GUC transaccionales para el cortafuegos RLS
        await conn.execute("SET LOCAL app.current_user_dept = $1;", dept)
        await conn.execute("SET LOCAL app.current_user_role = $2;", role)
        await conn.execute("SET LOCAL request.jwt.claim.department = $1;", dept)
        await conn.execute("SET LOCAL request.jwt.claim.clearance = $3;", clearance)
        
        # Consulta de similitud del coseno utilizando el operador <=> de pgvector
        query = """
            SELECT section_id, text, filename, confidentiality_level, (embedding <=> $1) AS distance
            FROM document_sections
            ORDER BY embedding <=> $1
            LIMIT $2;
        """
        return await conn.fetch(query, embedding, limit)
