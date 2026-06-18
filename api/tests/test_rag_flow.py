"""
Tests del flujo RAG completo end-to-end.
Verifica el camino feliz: consulta exitosa, streaming SSE, deduplicación,
registro en audit_logs y propagación del trigger sync_metadata.
RF-A06, RF-C03, RF-C06, RF-C08, RF-D01.
"""
import pytest
import json
import numpy as np
from app.database import get_pool_admin


# ── HELPERS ────────────────────────────────────────────

async def insert_test_doc(hash_value, department="Administración", level="Público"):
    """Inserta un documento de prueba accesible y devuelve su hash."""
    import requests
    res = requests.post(
        "http://ollama_engine:11434/api/embeddings",
        json={"model": "nomic-embed-text", "prompt": "procedimiento de vacaciones del personal"}
    )
    emb = np.array(res.json()["embedding"], dtype=np.float32)

    async with get_pool_admin().acquire() as conn:
        await conn.execute("DELETE FROM document_sections WHERE document_hash = $1", hash_value)
        meta = json.dumps({
            "file_name": "test_vacaciones.txt",
            "department": department,
            "confidentiality_level": level,
            "document_hash": hash_value
        })
        await conn.execute("""
            INSERT INTO document_sections (text, metadata, embedding, department,
                confidentiality_level, document_hash)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, "El procedimiento de vacaciones requiere solicitud con 15 días de antelación.",
            meta, emb, department, level, hash_value)


async def cleanup_test_doc(hash_value):
    async with get_pool_admin().acquire() as conn:
        await conn.execute("DELETE FROM document_sections WHERE document_hash = $1", hash_value)


# ── TESTS ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rag_flow_success(client, jwt_admin):
    """RF-C03 + RF-C06: Consulta RAG exitosa devuelve stream SSE con eventos tipados."""
    test_hash = "testflow0000000000000000000000000000000000000000000000000000flow"
    await insert_test_doc(test_hash)
    try:
        response = await client.post(
            "/api/v1/chat/stream",
            json={"question": "¿Cuál es el procedimiento de vacaciones?"},
            headers={"Authorization": f"Bearer {jwt_admin}"}
        )
        assert response.status_code == 200
        body = response.text
        # Verificar que contiene eventos SSE tipados
        assert "event: metadata" in body, "Falta el evento metadata en el stream"
        assert "event: done" in body or "data:" in body, "Falta contenido SSE"
    finally:
        await cleanup_test_doc(test_hash)


@pytest.mark.asyncio
async def test_deduplication_exists_true(client):
    """RF-A06 + RF-C08: Documento existente devuelve exists=true."""
    test_hash = "testdedup0000000000000000000000000000000000000000000000000dedup1"
    await insert_test_doc(test_hash)
    try:
        response = await client.get(f"/api/v1/document/exists/{test_hash}")
        assert response.status_code == 200
        data = response.json()
        assert data["exists"] is True
        assert data["hash"] == test_hash
    finally:
        await cleanup_test_doc(test_hash)


@pytest.mark.asyncio
async def test_deduplication_exists_false(client):
    """RF-A06: Hash inexistente devuelve exists=false."""
    fake_hash = "nonexistent00000000000000000000000000000000000000000000000000000"
    response = await client.get(f"/api/v1/document/exists/{fake_hash}")
    assert response.status_code == 200
    assert response.json()["exists"] is False


@pytest.mark.asyncio
async def test_audit_log_created(client, jwt_admin):
    """RF-D01: Tras consulta exitosa, se registra traza en audit_logs con model_used."""
    test_hash = "testaudit0000000000000000000000000000000000000000000000000audit1"
    await insert_test_doc(test_hash)
    
    # Contar trazas antes
    async with get_pool_admin().acquire() as conn:
        count_before = await conn.fetchval("SELECT COUNT(*) FROM audit_logs")
        
    try:
        await client.post(
            "/api/v1/chat/stream",
            json={"question": "¿Cuál es el procedimiento de vacaciones?"},
            headers={"Authorization": f"Bearer {jwt_admin}"}
        )
        # Dar tiempo al BackgroundTask
        import asyncio
        await asyncio.sleep(2)

        async with get_pool_admin().acquire() as conn:
            count_after = await conn.fetchval("SELECT COUNT(*) FROM audit_logs")
            last = await conn.fetchrow(
                "SELECT model_used, chunks_id, user_role FROM audit_logs ORDER BY log_id DESC LIMIT 1"
            )

        assert count_after > count_before, "No se registró la traza en audit_logs"
        assert last["model_used"] is not None, "model_used no se registró"
        assert last["chunks_id"] is not None, "chunks_id no se registró"
    finally:
        await cleanup_test_doc(test_hash)


@pytest.mark.asyncio
async def test_trigger_sync_metadata():
    """El trigger trg_sync_metadata propaga JSONB a columnas relacionales."""
    test_hash = "testtrigger00000000000000000000000000000000000000000000000trig1"
    
    async with get_pool_admin().acquire() as conn:
        try:
            await conn.execute("DELETE FROM document_sections WHERE document_hash = $1", test_hash)
            import requests
            res = requests.post(
                "http://ollama_engine:11434/api/embeddings",
                json={"model": "nomic-embed-text", "prompt": "test trigger"}
            )
            emb = np.array(res.json()["embedding"], dtype=np.float32)

            # Insertar SOLO con metadata JSONB, sin las columnas relacionales
            meta = json.dumps({
                "file_name": "trigger_test.txt",
                "department": "Recursos Humanos",
                "confidentiality_level": "Interno",
                "document_hash": test_hash
            })
            await conn.execute("""
                INSERT INTO document_sections (text, metadata, embedding)
                VALUES ($1, $2, $3)
            """, "Texto de prueba del trigger", meta, emb)

            # Verificar que el trigger propagó los valores a las columnas
            row = await conn.fetchrow(
                "SELECT department, confidentiality_level, document_hash FROM document_sections WHERE document_hash = $1",
                test_hash
            )
            assert row["department"] == "Recursos Humanos", "Trigger no propagó department"
            assert row["confidentiality_level"] == "Interno", "Trigger no propagó confidentiality_level"
            assert row["document_hash"].strip() == test_hash, "Trigger no propagó document_hash"
        finally:
            await conn.execute("DELETE FROM document_sections WHERE document_hash = $1", test_hash)


@pytest.mark.asyncio
async def test_config_dynamic_update(client, jwt_admin):
    """RF-C07: PUT /config modifica un valor y GET /config lo refleja."""
    # Leer valor actual
    res_get = await client.get(
        "/api/v1/config",
        headers={"Authorization": f"Bearer {jwt_admin}"}
    )
    original = res_get.json().get("top_k", {}).get("value", "6")

    try:
        # Modificar
        res_put = await client.put(
            "/api/v1/config",
            json={"top_k": 8},
            headers={"Authorization": f"Bearer {jwt_admin}"}
        )
        assert res_put.status_code == 200

        # Verificar el cambio
        res_get2 = await client.get(
            "/api/v1/config",
            headers={"Authorization": f"Bearer {jwt_admin}"}
        )
        assert res_get2.json()["top_k"]["value"] == "8"
    finally:
        # Restaurar valor original
        await client.put(
            "/api/v1/config",
            json={"top_k": int(original)},
            headers={"Authorization": f"Bearer {jwt_admin}"}
        )