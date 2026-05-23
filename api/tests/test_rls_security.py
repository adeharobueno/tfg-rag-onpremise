import pytest
import jwt
from httpx import AsyncClient
from app.main import app, JWT_SECRET
from app.database import get_db_connection

def generate_mock_jwt(dept: str, role: str):
    return jwt.encode({"department": dept, "role": role}, JWT_SECRET, algorithm="HS256")

@pytest.mark.asyncio
async def test_rls_blocks_unauthorized_vectors():
    test_query = "Protocolos de despido y salarios directivos"
    
    # FASE 1: Obtener un vector real de Ollama para garantizar la máxima puntuación
    async with AsyncClient() as ac:
        ollama_res = await ac.post("http://ollama_engine:11434/api/embeddings", 
                                   json={"model": "nomic-embed-text", "prompt": test_query})
        real_embedding = ollama_res.json()["embedding"]

    # FASE 2: Inyección de semilla controlada (Setup)
    conn = await get_db_connection()
    await conn.execute("DELETE FROM document_sections WHERE department IN ('TEST_RRHH', 'TEST_IT')")
    
    await conn.execute("""
        INSERT INTO document_sections (text, metadata, embedding, department, confidentiality_level)
        VALUES 
        ($1, '{"file_name": "secreto.pdf"}', $2::vector, 'TEST_RRHH', 'Confidencial'),
        ($3, '{"file_name": "impresora.pdf"}', $4::vector, 'TEST_IT', 'Público')
    """, 
    "Documento altamente confidencial sobre los protocolos de despido", real_embedding, 
    "Manual técnico básico para reparar la impresora", real_embedding)
    await conn.close()

    # FASE 3: Ejecución de las peticiones HTTP
    payload = {"question": test_query}
    headers_rrhh = {"Authorization": f"Bearer {generate_mock_jwt('TEST_RRHH', 'manager')}"}
    headers_it = {"Authorization": f"Bearer {generate_mock_jwt('TEST_IT', 'employee')}"}
    headers_admin = {"Authorization": f"Bearer {generate_mock_jwt('CUALQUIERA', 'admin')}"}

    async with AsyncClient(app=app, base_url="http://test") as ac:
        res_rrhh = await ac.post("/api/v1/retrieve", json=payload, headers=headers_rrhh)
        res_it = await ac.post("/api/v1/retrieve", json=payload, headers=headers_it)
        res_admin = await ac.post("/api/v1/retrieve", json=payload, headers=headers_admin)

    # Transformamos las respuestas en cadenas de texto plano para evaluar el contenido real
    textos_rrhh = str([c.get("text") for c in res_rrhh.json().get("chunks", [])])
    textos_it = str([c.get("text") for c in res_it.json().get("chunks", [])])
    textos_admin = str([c.get("text") for c in res_admin.json().get("chunks", [])])

    print(f"\n--- DEPURACIÓN DE CONTEXTO ---")
    print(f"RRHH recuperó: {textos_rrhh}")
    print(f"IT recuperó: {textos_it}")

    # FASE 4: Validaciones de Lógica de Negocio y RLS
    assert "despido" in textos_rrhh, "Fallo: RRHH no puede ver su propio documento"
    assert "despido" not in textos_it, "Fuga Crítica: IT está viendo el documento confidencial de RRHH"
    assert "despido" in textos_admin and "impresora" in textos_admin, "Fallo: Admin no ve todos los datos"
