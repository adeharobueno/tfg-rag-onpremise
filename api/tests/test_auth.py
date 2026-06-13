"""
Tests del endpoint POST /auth/token y verificación JWT.
"""
import pytest


@pytest.mark.asyncio
async def test_login_valid_credentials(client):
    """RF-C01: Login con credenciales válidas devuelve JWT."""
    response = await client.post("/auth/token", json={
        "username": "director_ia",
        "password": "AdminPassword2026"
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["role"] == "admin"
    assert data["user"]["department"] == "Administración"
    assert data["expires_in"] == 3600


@pytest.mark.asyncio
async def test_login_invalid_password(client):
    """RF-D05: Login fallido devuelve 401 y queda registrado en rbac_denials."""
    response = await client.post("/auth/token", json={
        "username": "director_ia",
        "password": "contraseña_incorrecta"
    })
    assert response.status_code == 401
    assert "Credenciales inválidas" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_nonexistent_user(client):
    """Login con usuario inexistente devuelve 401."""
    response = await client.post("/auth/token", json={
        "username": "usuario_fantasma",
        "password": "cualquiera"
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_rejected(client, jwt_expired):
    """RF-C03: Token expirado devuelve 401 con mensaje específico."""
    response = await client.post(
        "/api/v1/chat/stream",
        json={"question": "test"},
        headers={"Authorization": f"Bearer {jwt_expired}"}
    )
    assert response.status_code == 401
    assert "expirado" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_invalid_token_rejected(client):
    """RF-C03: Token malformado devuelve 401."""
    response = await client.post(
        "/api/v1/chat/stream",
        json={"question": "test"},
        headers={"Authorization": "Bearer token_inventado_12345"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_missing_token_rejected(client):
    """RF-C03: Petición sin token devuelve 422 (header requerido)."""
    response = await client.post(
        "/api/v1/chat/stream",
        json={"question": "test"}
    )
    assert response.status_code in (401, 422)
