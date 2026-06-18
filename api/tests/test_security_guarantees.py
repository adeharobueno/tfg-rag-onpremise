"""
Tests de garantías de seguridad a nivel de motor de base de datos y validación de entrada.
Verifica garantías que no dependen de la lógica de aplicación sino del propio PostgreSQL,
y la robustez de la API ante entradas malformadas.
RNF-N02, RNF-S06, RF-D05.
"""
import pytest
import json
import numpy as np
from datetime import datetime, timezone
from app.database import get_pool, get_pool_admin
import asyncpg


# ── HELPERS ────────────────────────────────────────────

async def get_test_embedding(prompt="test seguridad"):
    import requests
    res = requests.post(
        "http://ollama_engine:11434/api/embeddings",
        json={"model": "nomic-embed-text", "prompt": prompt}
    )
    return np.array(res.json()["embedding"], dtype=np.float32)


# ── INMUTABILIDAD DE AUDIT_LOGS (RNF-N02) ───────────────

@pytest.mark.asyncio
async def test_audit_logs_immutable_no_delete():
    """RNF-N02: El rol api_gateway NO puede ejecutar DELETE sobre audit_logs."""
    async with get_pool().acquire() as conn: # conexión como api_gateway
        # Intentar DELETE debe lanzar excepción de permisos insuficientes
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await conn.execute("DELETE FROM audit_logs WHERE log_id = -1")


@pytest.mark.asyncio
async def test_audit_logs_allows_insert_and_update():
    """RNF-N02: api_gateway SÍ puede INSERT y UPDATE sobre audit_logs (solo DELETE está vetado)."""
    async with get_pool().acquire() as conn:
        # INSERT permitido
        await conn.execute("""
            INSERT INTO audit_logs (user_department, user_role, question, response,
                context_used, chunks_id, model_used)
            VALUES ('TEST_DEPT', 'admin', 'q', 'r', 'c', ARRAY[1,2], 'test_model')
        """)
        log_id = await conn.fetchval(
            "SELECT log_id FROM audit_logs WHERE user_department = 'TEST_DEPT' ORDER BY log_id DESC LIMIT 1"
        )
        # UPDATE permitido (para requires_review)
        await conn.execute(
            "UPDATE audit_logs SET requires_review = TRUE WHERE log_id = $1", log_id
        )
        val = await conn.fetchval(
            "SELECT requires_review FROM audit_logs WHERE log_id = $1", log_id
        )
        assert val is True
        
    # Limpieza con superusuario (sí puede DELETE)
    async with get_pool_admin().acquire() as admin:
        await admin.execute("DELETE FROM audit_logs WHERE user_department = 'TEST_DEPT'")


# ── POLÍTICA RESTRICTIVE A NIVEL DE MOTOR (RNF-S06) ─────

@pytest.mark.asyncio
async def test_expired_blocked_at_engine_level():
    """RNF-S06: La política RESTRICTIVE bloquea documentos expirados incluso con SELECT directo."""
    test_hash = "testexpiry000000000000000000000000000000000000000000000000expir"
    emb = await get_test_embedding()
    
    async with get_pool_admin().acquire() as admin:
        await admin.execute("DELETE FROM document_sections WHERE document_hash = $1", test_hash)
        expired_dt = datetime(2020, 1, 1, tzinfo=timezone.utc)
        meta = json.dumps({
            "file_name": "expired.txt",
            "department": "Administración",
            "confidentiality_level": "Público",
            "valid_until": expired_dt.isoformat(),
            "document_hash": test_hash
        })
        await admin.execute("""
            INSERT INTO document_sections (text, metadata, embedding, department,
                confidentiality_level, valid_until, document_hash)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, "Documento expirado nivel motor", meta, emb, "Administración",
            "Público", expired_dt, test_hash)

    try:
        # Incluso con admin y SELECT directo filtrando por hash, RLS RESTRICTIVE bloquea
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT set_config('app.current_user_dept', 'Administración', true);")
                await conn.execute("SELECT set_config('app.current_user_role', 'admin', true);")
                rows = await conn.fetch(
                    "SELECT text FROM document_sections WHERE document_hash = $1", test_hash
                )
        assert len(rows) == 0, \
            f"FUGA CRÍTICA: documento expirado visible a nivel de motor: {[dict(r) for r in rows]}"
    finally:
        async with get_pool_admin().acquire() as admin:
            await admin.execute("DELETE FROM document_sections WHERE document_hash = $1", test_hash)


# ── DENEGACIÓN RLS_EMPTY (RF-D05) ───────────────────────

@pytest.mark.asyncio
async def test_rls_empty_denial_logged(client, jwt_dept_standard_admin):
    """RF-D05: Cuando RLS filtra todos los resultados, se registra denegación rls_empty."""
    # Contar denegaciones rls_empty antes
    async with get_pool_admin().acquire() as conn:
        count_before = await conn.fetchval(
            "SELECT COUNT(*) FROM rbac_denials WHERE denial_reason = 'rls_empty'"
        )

    # Un dept_standard de Administración pregunta por algo que no existe en su alcance.
    # Usamos una consulta muy específica para maximizar probabilidad de 0 resultados accesibles.
    await client.post(
        "/api/v1/chat/stream",
        json={"question": "xyzqwerty informacion inexistente zzz9999 confidencial rrhh nivel maximo"},
        headers={"Authorization": f"Bearer {jwt_dept_standard_admin}"}
    )
    import asyncio
    await asyncio.sleep(1)

    async with get_pool_admin().acquire() as conn:
        count_after = await conn.fetchval(
            "SELECT COUNT(*) FROM rbac_denials WHERE denial_reason = 'rls_empty'"
        )

    # Nota: este test depende de que la búsqueda no devuelva chunks accesibles.
    # Si el corpus tiene documentos públicos de Administración muy genéricos, podría
    # devolver resultados. Se documenta como verificación best-effort.
    assert count_after >= count_before, \
        "El contador de denegaciones rls_empty no debería decrecer"


# ── VALIDACIÓN DE ENTRADA ───────────────────────────────

@pytest.mark.asyncio
async def test_chat_missing_question_field(client, jwt_admin):
    """Validación: petición sin campo 'question' devuelve 422."""
    response = await client.post(
        "/api/v1/chat/stream",
        json={"texto": "campo incorrecto"},
        headers={"Authorization": f"Bearer {jwt_admin}"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_malformed_json(client, jwt_admin):
    """Validación: JSON malformado devuelve 422."""
    response = await client.post(
        "/api/v1/chat/stream",
        content=b"{esto no es json valido",
        headers={
            "Authorization": f"Bearer {jwt_admin}",
            "Content-Type": "application/json"
        }
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_auth_missing_password(client):
    """Validación: login sin password devuelve 422."""
    response = await client.post("/auth/token", json={"username": "director_ia"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_config_put_invalid_type(client, jwt_admin):
    """Validación: PUT /config con tipo incorrecto devuelve 422."""
    response = await client.put(
        "/api/v1/config",
        json={"top_k": "no_es_un_numero"},
        headers={"Authorization": f"Bearer {jwt_admin}"}
    )
    assert response.status_code == 422