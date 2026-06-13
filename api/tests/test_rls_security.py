"""
Tests de aislamiento RLS en PostgreSQL.
Verifica que las políticas RLS filtran correctamente por departamento,
nivel de confidencialidad y expiración documental.
Usa queries SQL directas con GUC para activar RLS, evitando dependencia
del ranking vectorial que compite con el corpus real.
RNF-S01, RNF-S06, RNF-S05.
"""
import pytest
import json
import numpy as np
from datetime import datetime, timezone
from app.database import get_db_connection, get_db_connection_admin
import requests


# ── HELPERS ────────────────────────────────────────────

async def get_test_embedding():
    """Obtiene un embedding real de Ollama para los datos de prueba."""
    res = requests.post(
        "http://ollama_engine:11434/api/embeddings",
        json={"model": "nomic-embed-text", "prompt": "documento de prueba para tests RLS"}
    )
    return res.json()["embedding"]


async def setup_test_data(embedding):
    """Inserta datos de prueba con departamentos y niveles de test."""
    conn = await get_db_connection_admin()
    await conn.execute(
        "DELETE FROM document_sections WHERE department IN ('TEST_RRHH', 'TEST_ADM')"
    )
    emb_np = np.array(embedding, dtype=np.float32)
    expired_dt = datetime(2020, 1, 1, tzinfo=timezone.utc)

    test_docs = [
        ("Protocolo confidencial de despidos TEST", "TEST_RRHH", "Confidencial", None),
        ("Manual público de bienvenida TEST", "TEST_RRHH", "Público", None),
        ("Documento interno RRHH TEST", "TEST_RRHH", "Interno", None),
        ("Presupuesto interno TEST administración", "TEST_ADM", "Interno", None),
        ("Guía pública TEST administración", "TEST_ADM", "Público", None),
        ("Documento expirado TEST", "TEST_ADM", "Público", expired_dt),
    ]
    for text, dept, level, exp in test_docs:
        meta = json.dumps({
            "file_name": f"test_{dept}_{level}.txt",
            "department": dept,
            "confidentiality_level": level,
            "valid_until": exp.isoformat() if exp else None,
            "document_hash": "test_" + dept + "_" + level
        })
        await conn.execute("""
            INSERT INTO document_sections (text, metadata, embedding, department,
                confidentiality_level, valid_until, document_hash)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, text, meta, emb_np, dept, level,
            exp if exp else None, "test_" + dept + "_" + level)
    await conn.close()


async def cleanup_test_data():
    """Elimina datos de prueba."""
    conn = await get_db_connection_admin()
    await conn.execute(
        "DELETE FROM document_sections WHERE department IN ('TEST_RRHH', 'TEST_ADM')"
    )
    await conn.close()


async def query_rls_as_role(dept, role):
    """
    Ejecuta una query SELECT directa sobre document_sections con RLS activado,
    filtrando solo los datos de test. Evita la búsqueda vectorial para no competir
    con el corpus real en el ranking de distancia.
    """
    conn = await get_db_connection()
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.current_user_dept', $1, true);", dept)
            await conn.execute("SELECT set_config('app.current_user_role', $1, true);", role)
            rows = await conn.fetch("""
                SELECT text, department, confidentiality_level, valid_until
                FROM document_sections
                WHERE department IN ('TEST_RRHH', 'TEST_ADM')
                ORDER BY department, confidentiality_level
            """)
        return [dict(r) for r in rows]
    finally:
        await conn.close()


# ── TESTS ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rls_dept_isolation():
    """RNF-S01: Un usuario de TEST_RRHH no ve documentos de TEST_ADM y viceversa."""
    embedding = await get_test_embedding()
    await setup_test_data(embedding)
    try:
        rows_rrhh = await query_rls_as_role("TEST_RRHH", "dept_high")
        rows_adm = await query_rls_as_role("TEST_ADM", "dept_standard")

        # RRHH dept_high ve documentos de su departamento
        depts_rrhh = set(r["department"] for r in rows_rrhh)
        assert "TEST_RRHH" in depts_rrhh, \
            f"dept_high de TEST_RRHH no ve sus documentos: {rows_rrhh}"
        assert "TEST_ADM" not in depts_rrhh, \
            f"FUGA: dept_high de TEST_RRHH ve documentos de TEST_ADM: {rows_rrhh}"

        # ADM dept_standard ve documentos de su departamento
        depts_adm = set(r["department"] for r in rows_adm)
        assert "TEST_ADM" in depts_adm, \
            f"dept_standard de TEST_ADM no ve sus documentos: {rows_adm}"
        assert "TEST_RRHH" not in depts_adm, \
            f"FUGA: dept_standard de TEST_ADM ve documentos de TEST_RRHH: {rows_adm}"
    finally:
        await cleanup_test_data()


@pytest.mark.asyncio
async def test_rls_confidentiality_levels():
    """RNF-S01: dept_standard no ve documentos Confidenciales de su propio departamento."""
    embedding = await get_test_embedding()
    await setup_test_data(embedding)
    try:
        rows_std = await query_rls_as_role("TEST_RRHH", "dept_standard")
        rows_high = await query_rls_as_role("TEST_RRHH", "dept_high")

        levels_std = set(r["confidentiality_level"] for r in rows_std)
        levels_high = set(r["confidentiality_level"] for r in rows_high)

        # dept_standard ve Público e Interno, NO Confidencial
        assert "Público" in levels_std, \
            f"dept_standard no ve Público: {levels_std}"
        assert "Interno" in levels_std, \
            f"dept_standard no ve Interno: {levels_std}"
        assert "Confidencial" not in levels_std, \
            f"FUGA: dept_standard ve Confidencial: {rows_std}"

        # dept_high ve Público, Interno Y Confidencial
        assert "Confidencial" in levels_high, \
            f"dept_high no ve Confidencial: {levels_high}"
        assert "Público" in levels_high, \
            f"dept_high no ve Público: {levels_high}"
    finally:
        await cleanup_test_data()


@pytest.mark.asyncio
async def test_rls_expired_documents_blocked():
    """RNF-S06: Documentos expirados bloqueados para TODOS los roles, incluido admin."""
    embedding = await get_test_embedding()
    await setup_test_data(embedding)
    try:
        rows_admin = await query_rls_as_role("TEST_ADM", "admin")
        rows_std = await query_rls_as_role("TEST_ADM", "dept_standard")

        # Ningún rol ve el documento expirado
        texts_admin = [r["text"] for r in rows_admin]
        texts_std = [r["text"] for r in rows_std]

        assert not any("expirado" in t.lower() for t in texts_admin), \
            f"FUGA CRÍTICA: Admin ve documento expirado: {texts_admin}"
        assert not any("expirado" in t.lower() for t in texts_std), \
            f"FUGA: dept_standard ve documento expirado: {texts_std}"

        # Pero admin sí ve los documentos vigentes de TEST_ADM
        assert len(rows_admin) > 0, \
            f"Admin no ve ningún documento vigente de TEST_ADM"
    finally:
        await cleanup_test_data()


@pytest.mark.asyncio
async def test_rls_admin_sees_all_departments():
    """RNF-S01: Admin ve documentos vigentes de todos los departamentos."""
    embedding = await get_test_embedding()
    await setup_test_data(embedding)
    try:
        rows_admin = await query_rls_as_role("CUALQUIERA", "admin")

        depts = set(r["department"] for r in rows_admin)
        assert "TEST_RRHH" in depts, \
            f"Admin no ve TEST_RRHH: {depts}"
        assert "TEST_ADM" in depts, \
            f"Admin no ve TEST_ADM: {depts}"

        # Admin ve todos los niveles vigentes
        levels = set(r["confidentiality_level"] for r in rows_admin)
        assert "Público" in levels and "Interno" in levels and "Confidencial" in levels, \
            f"Admin no ve todos los niveles: {levels}"

        # Pero NO ve el expirado
        texts = [r["text"] for r in rows_admin]
        assert not any("expirado" in t.lower() for t in texts), \
            f"FUGA: Admin ve documento expirado: {texts}"
    finally:
        await cleanup_test_data()
