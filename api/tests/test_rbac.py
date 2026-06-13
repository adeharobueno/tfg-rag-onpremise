"""
Tests de control de acceso RBAC y aislamiento departamental.
RNF-S05: Verificación de que ningún rol accede a chunks no autorizados.
"""
import pytest


@pytest.mark.asyncio
async def test_admin_delete_allowed(client, jwt_admin):
    """RF-C09: Admin puede ejecutar DELETE."""
    response = await client.delete(
        "/api/v1/document/fichero_inexistente.txt",
        headers={"Authorization": f"Bearer {jwt_admin}"}
    )
    # 200 aunque no exista el fichero (DELETE idempotente)
    assert response.status_code == 200
    assert response.json()["deleted"] is True


@pytest.mark.asyncio
async def test_dept_standard_delete_forbidden(client, jwt_dept_standard_admin):
    """RF-C09 + RF-D05: dept_standard no puede ejecutar DELETE → 403."""
    response = await client.delete(
        "/api/v1/document/cualquier.txt",
        headers={"Authorization": f"Bearer {jwt_dept_standard_admin}"}
    )
    assert response.status_code == 403
    assert "admin" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_dept_high_delete_forbidden(client, jwt_dept_high_rrhh):
    """RF-C09: dept_high tampoco puede ejecutar DELETE → 403."""
    response = await client.delete(
        "/api/v1/document/cualquier.txt",
        headers={"Authorization": f"Bearer {jwt_dept_high_rrhh}"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_config_get_all_roles(client, jwt_admin, jwt_dept_standard_admin):
    """RF-C07: GET /config accesible para todos los roles con JWT válido."""
    res_admin = await client.get(
        "/api/v1/config",
        headers={"Authorization": f"Bearer {jwt_admin}"}
    )
    assert res_admin.status_code == 200
    assert "model" in res_admin.json()

    res_std = await client.get(
        "/api/v1/config",
        headers={"Authorization": f"Bearer {jwt_dept_standard_admin}"}
    )
    assert res_std.status_code == 200


@pytest.mark.asyncio
async def test_config_put_admin_only(client, jwt_admin, jwt_dept_standard_admin):
    """RF-C07: PUT /config solo admin. dept_standard → 403."""
    # Admin puede modificar
    res_admin = await client.put(
        "/api/v1/config",
        json={"temperature": 0.0},
        headers={"Authorization": f"Bearer {jwt_admin}"}
    )
    assert res_admin.status_code == 200

    # dept_standard no puede
    res_std = await client.put(
        "/api/v1/config",
        json={"temperature": 0.5},
        headers={"Authorization": f"Bearer {jwt_dept_standard_admin}"}
    )
    assert res_std.status_code == 403


@pytest.mark.asyncio
async def test_document_exists_public(client):
    """RF-C08: Endpoint exists es público (sin JWT), para uso interno de n8n."""
    response = await client.get("/api/v1/document/exists/0000000000000000000000000000000000000000000000000000000000000000")
    assert response.status_code == 200
    data = response.json()
    assert "exists" in data
    assert data["exists"] is False
