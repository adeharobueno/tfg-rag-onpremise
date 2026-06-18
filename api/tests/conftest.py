"""
Fixtures compartidas para los tests del API Gateway.
Se ejecutan dentro del contenedor api_gateway_container.

CORRECCIÓN: Se inicializan los pools de conexión mediante el lifespan
de FastAPI antes de ejecutar los tests. Sin esta inicialización,
get_pool() y get_pool_admin() devuelven None.
"""
import pytest
import jwt
import os
from httpx import AsyncClient, ASGITransport
from app.main import app

JWT_SECRET = os.getenv("JWT_SECRET")


# ── INICIALIZACIÓN DE POOLS ────────────────────────────


@pytest.fixture(autouse=True)
async def _init_pools():
    """
    Fixture autouse que levanta el lifespan de la app (inicializa los
    pools de conexión asyncpg) antes de CADA test y los cierra después.

    Esto garantiza que get_pool() y get_pool_admin() devuelvan pools
    válidos tanto para los tests que usan el fixture `client` como
    para los que acceden directamente a la BD (test_rls_security,
    test_security_guarantees).
    """
    async with app.router.lifespan_context(app):
        yield


# ── CLIENTE HTTP ────────────────────────────────────────


@pytest.fixture
async def client(_init_pools):
    """Cliente HTTP asíncrono para tests contra FastAPI."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── TOKENS JWT ──────────────────────────────────────────


@pytest.fixture
def jwt_admin():
    """Token JWT válido para el rol admin."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": "test_admin",
        "department": "Administración",
        "role": "admin",
        "iat": now,
        "exp": now + timedelta(minutes=30)
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture
def jwt_dept_high_rrhh():
    """Token JWT válido para dept_high en Recursos Humanos."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": "test_jefe_rrhh",
        "department": "Recursos Humanos",
        "role": "dept_high",
        "iat": now,
        "exp": now + timedelta(minutes=30)
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture
def jwt_dept_standard_admin():
    """Token JWT válido para dept_standard en Administración."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": "test_tecnico",
        "department": "Administración",
        "role": "dept_standard",
        "iat": now,
        "exp": now + timedelta(minutes=30)
    }, JWT_SECRET, algorithm="HS256")


@pytest.fixture
def jwt_expired():
    """Token JWT expirado (para test de denegación)."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": "test_expired",
        "department": "Administración",
        "role": "admin",
        "iat": now - timedelta(hours=2),
        "exp": now - timedelta(hours=1)
    }, JWT_SECRET, algorithm="HS256")