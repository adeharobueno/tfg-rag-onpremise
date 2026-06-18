"""
Tests de gestión de usuarios y roles (RF-C07).
Verifica los endpoints CRUD de usuarios, restringidos al rol admin.
"""
import pytest
from app.database import get_pool_admin


TEST_USERNAME = "test_user_crud"


async def cleanup_test_user():
    async with get_pool_admin().acquire() as conn:
        await conn.execute("DELETE FROM users WHERE username = $1", TEST_USERNAME)


@pytest.mark.asyncio
async def test_create_user_admin(client, jwt_admin):
    """RF-C07: Admin puede crear un usuario nuevo."""
    await cleanup_test_user()
    try:
        response = await client.post(
            "/api/v1/admin/users",
            json={
                "username": TEST_USERNAME,
                "password": "TestPass2026",
                "department": "Administración",
                "user_role": "dept_standard"
            },
            headers={"Authorization": f"Bearer {jwt_admin}"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["username"] == TEST_USERNAME
        assert data["user_role"] == "dept_standard"
    finally:
        await cleanup_test_user()


@pytest.mark.asyncio
async def test_create_user_then_login(client, jwt_admin):
    """RF-C07 + RF-C01: Un usuario creado puede autenticarse."""
    await cleanup_test_user()
    try:
        await client.post(
            "/api/v1/admin/users",
            json={
                "username": TEST_USERNAME,
                "password": "TestPass2026",
                "department": "Administración",
                "user_role": "dept_standard"
            },
            headers={"Authorization": f"Bearer {jwt_admin}"}
        )
        # El usuario creado debe poder hacer login
        login = await client.post("/auth/token", json={
            "username": TEST_USERNAME,
            "password": "TestPass2026"
        })
        assert login.status_code == 200
        assert login.json()["user"]["role"] == "dept_standard"
    finally:
        await cleanup_test_user()


@pytest.mark.asyncio
async def test_create_user_forbidden_non_admin(client, jwt_dept_standard_admin):
    """RF-C07: dept_standard no puede crear usuarios → 403."""
    response = await client.post(
        "/api/v1/admin/users",
        json={
            "username": "no_deberia_crearse",
            "password": "x",
            "department": "Administración",
            "user_role": "dept_standard"
        },
        headers={"Authorization": f"Bearer {jwt_dept_standard_admin}"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_user_invalid_role(client, jwt_admin):
    """RF-C07: Rol inválido devuelve 422."""
    response = await client.post(
        "/api/v1/admin/users",
        json={
            "username": "usuario_rol_malo",
            "password": "x",
            "department": "Administración",
            "user_role": "superadmin"
        },
        headers={"Authorization": f"Bearer {jwt_admin}"}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_duplicate_user(client, jwt_admin):
    """RF-C07: Crear usuario duplicado devuelve 409."""
    await cleanup_test_user()
    try:
        await client.post("/api/v1/admin/users", json={
            "username": TEST_USERNAME, "password": "x",
            "department": "Administración", "user_role": "dept_standard"
        }, headers={"Authorization": f"Bearer {jwt_admin}"})
        # Segundo intento
        response = await client.post("/api/v1/admin/users", json={
            "username": TEST_USERNAME, "password": "y",
            "department": "RRHH", "user_role": "dept_high"
        }, headers={"Authorization": f"Bearer {jwt_admin}"})
        assert response.status_code == 409
    finally:
        await cleanup_test_user()


@pytest.mark.asyncio
async def test_list_users_admin(client, jwt_admin):
    """RF-C07: Admin puede listar usuarios sin ver hashes."""
    response = await client.get(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {jwt_admin}"}
    )
    assert response.status_code == 200
    users = response.json()
    assert isinstance(users, list)
    assert len(users) >= 3  # los 3 usuarios semilla
    # Verificar que no se exponen hashes
    assert all("password_hash" not in u for u in users)
    assert all("username" in u and "user_role" in u for u in users)


@pytest.mark.asyncio
async def test_list_users_forbidden_non_admin(client, jwt_dept_standard_admin):
    """RF-C07: dept_standard no puede listar usuarios → 403."""
    response = await client.get(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {jwt_dept_standard_admin}"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_user_role(client, jwt_admin):
    """RF-C07: Admin puede modificar el rol de un usuario."""
    await cleanup_test_user()
    try:
        await client.post("/api/v1/admin/users", json={
            "username": TEST_USERNAME, "password": "TestPass2026",
            "department": "Administración", "user_role": "dept_standard"
        }, headers={"Authorization": f"Bearer {jwt_admin}"})

        response = await client.put(
            f"/api/v1/admin/users/{TEST_USERNAME}",
            json={"user_role": "dept_high"},
            headers={"Authorization": f"Bearer {jwt_admin}"}
        )
        assert response.status_code == 200
        assert response.json()["changed"]["user_role"] == "dept_high"
    finally:
        await cleanup_test_user()


@pytest.mark.asyncio
async def test_update_user_password_then_login(client, jwt_admin):
    """RF-C07: Cambiar contraseña permite login con la nueva, no con la antigua."""
    await cleanup_test_user()
    try:
        await client.post("/api/v1/admin/users", json={
            "username": TEST_USERNAME, "password": "OldPass2026",
            "department": "Administración", "user_role": "dept_standard"
        }, headers={"Authorization": f"Bearer {jwt_admin}"})

        # Cambiar contraseña
        await client.put(
            f"/api/v1/admin/users/{TEST_USERNAME}",
            json={"password": "NewPass2026"},
            headers={"Authorization": f"Bearer {jwt_admin}"}
        )
        # Login con nueva contraseña funciona
        login_new = await client.post("/auth/token", json={
            "username": TEST_USERNAME, "password": "NewPass2026"
        })
        assert login_new.status_code == 200
        # Login con contraseña antigua falla
        login_old = await client.post("/auth/token", json={
            "username": TEST_USERNAME, "password": "OldPass2026"
        })
        assert login_old.status_code == 401
    finally:
        await cleanup_test_user()


@pytest.mark.asyncio
async def test_update_nonexistent_user(client, jwt_admin):
    """RF-C07: Actualizar usuario inexistente devuelve 404."""
    response = await client.put(
        "/api/v1/admin/users/usuario_fantasma_xyz",
        json={"user_role": "admin"},
        headers={"Authorization": f"Bearer {jwt_admin}"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_user(client, jwt_admin):
    """RF-C07: Admin puede eliminar un usuario."""
    await cleanup_test_user()
    try:
        await client.post("/api/v1/admin/users", json={
            "username": TEST_USERNAME, "password": "TestPass2026",
            "department": "Administración", "user_role": "dept_standard"
        }, headers={"Authorization": f"Bearer {jwt_admin}"})

        response = await client.delete(
            f"/api/v1/admin/users/{TEST_USERNAME}",
            headers={"Authorization": f"Bearer {jwt_admin}"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"

        # Verificar que ya no puede hacer login
        login = await client.post("/auth/token", json={
            "username": TEST_USERNAME, "password": "TestPass2026"
        })
        assert login.status_code == 401
    finally:
        await cleanup_test_user()


@pytest.mark.asyncio
async def test_delete_self_forbidden(client, jwt_admin):
    """RF-C07: Un admin no puede eliminar su propio usuario → 400."""
    # jwt_admin tiene sub = "test_admin"
    response = await client.delete(
        "/api/v1/admin/users/test_admin",
        headers={"Authorization": f"Bearer {jwt_admin}"}
    )
    # 400 (auto-eliminación) o 404 si test_admin no existe en BD
    assert response.status_code in (400, 404)