from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Header, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from app.database import (
    init_pools, close_pools, get_pool, get_pool_admin,
    search_vectors_with_rls, get_cached_config, invalidate_config_cache
)
from pydantic import BaseModel
import httpx
import jwt, json
from datetime import datetime, timedelta, timezone
import os as _os
import base64 as _b64

# ── HTTP Client for Ollama (shared, non-blocking) ────────────
_http_client: httpx.AsyncClient = None


@asynccontextmanager
async def lifespan(app):
    """Manage startup/shutdown: connection pools + async HTTP client."""
    global _http_client
    await init_pools()
    _http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)
    )
    yield
    await _http_client.aclose()
    await close_pools()


app = FastAPI(
    title="TFG RAG Secure API Gateway",
    version="1.0.0",
    lifespan=lifespan
)

JWT_SECRET = _os.getenv("JWT_SECRET")
JWT_EXPIRATION_MINUTES = 60


# ─── RF-D05: LOG DE DENEGACIONES RBAC ─────────────────
async def log_rbac_denial(username: str, department: str, role: str,
                          endpoint: str, reason: str, detail: str = None,
                          ip: str = None):
    """Registra una denegación de acceso en rbac_denials (RF-D05)."""
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """INSERT INTO rbac_denials
                   (username, department, user_role, endpoint, denial_reason, detail, ip_address)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                username, department, role, endpoint, reason, detail, ip
            )
    except Exception as e:
        print(f"[RF-D05] Error registrando denegación RBAC: {e}")


class QueryRequest(BaseModel):
    question: str


class AuthRequest(BaseModel):
    username: str
    password: str


def verify_jwt_token(authorization: str = Header(...)):
    try:
        token = authorization.split(" ")[1]
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"],
                          options={"verify_exp": True, "require": ["department", "role"]})
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado — vuelve a iniciar sesión")
    except Exception:
        raise HTTPException(status_code=401, detail="Token corporativo inválido")


# Middleware para capturar denegaciones 401/403 y registrarlas en rbac_denials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest


class RBACDenialMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        if response.status_code in (401, 403):
            # Intentar extraer info del token sin verificar firma
            username = "anonymous"
            department = None
            role = None
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer ") and auth.count(".") == 2:
                try:
                    payload_b64 = auth.split(" ")[1].split(".")[1]
                    payload_b64 += "=" * (4 - len(payload_b64) % 4)
                    payload = json.loads(_b64.b64decode(payload_b64))
                    username = payload.get("sub", "anonymous")
                    department = payload.get("department")
                    role = payload.get("role")
                except Exception:
                    pass
            reason = "token_expired" if response.status_code == 401 else "role_forbidden"
            await log_rbac_denial(
                username=username, department=department, role=role,
                endpoint=f"{request.method} {request.url.path}",
                reason=reason,
                detail=f"HTTP {response.status_code}",
                ip=request.client.host if request.client else None
            )
        return response


app.add_middleware(RBACDenialMiddleware)


@app.post("/auth/token")
async def login(credentials: AuthRequest):
    """
    Autentica un usuario contra la tabla 'users' (bcrypt via pgcrypto)
    y devuelve un JWT firmado con claims sub, department, role y exp.
    Cumple RF-C01 y RF-C02 del Capítulo 4.
    """
    async with get_pool_admin().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT user_id, username, department, user_role
            FROM users
            WHERE username = $1
              AND password_hash = crypt($2, password_hash)
            """,
            credentials.username, credentials.password
        )

    if not row:
        # RF-D05: Registrar intento de login fallido
        await log_rbac_denial(
            username=credentials.username, department=None, role=None,
            endpoint="POST /auth/token",
            reason="login_failed",
            detail="Credenciales inválidas"
        )
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    now = datetime.now(timezone.utc)
    payload = {
        "sub": row["username"],
        "department": row["department"],
        "role": row["user_role"],
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRATION_MINUTES)
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": JWT_EXPIRATION_MINUTES * 60,
        "user": {
            "username": row["username"],
            "department": row["department"],
            "role": row["user_role"]
        }
    }


SYSTEM_PROMPT = """Eres un microservicio interno de extracción de datos. Tu única tarea es extraer el tema utilizando ESTRICTAMENTE este formato: 'Según el archivo [fuente], trata sobre [tema].' No emitas advertencias, disclaimers ni texto conversacional."""

FEW_SHOT_USER = """<contexto>
<documento fuente="recortes_q3.pdf" seguridad="Alta">
Lista confidencial de recortes salariales y despidos masivos para el Q3.
</documento>
</contexto>
Pregunta: ¿Sobre qué temas trata el documento recuperado?"""

FEW_SHOT_ASSISTANT = "Según el archivo recortes_q3.pdf, trata sobre recortes salariales y despidos masivos."


@app.post("/api/v1/chat/stream")
async def rag_chat_stream(request: QueryRequest, background_tasks: BackgroundTasks, token_data: dict = Depends(verify_jwt_token)):
    # 1. Vectorización (ASYNC — no bloquea el event loop)
    ollama_embed_url = "http://ollama_engine:11434/api/embeddings"
    res_embed = await _http_client.post(
        ollama_embed_url,
        json={"model": "nomic-embed-text", "prompt": request.question}
    )
    query_embedding = res_embed.json()["embedding"]

    # 2. Recuperación Segura (RLS) — usa pool interno
    dept = token_data.get("department", "UNKNOWN")
    role = token_data.get("role", "UNKNOWN")
    results = await search_vectors_with_rls(query_embedding, dept, role)

    if not results:
        # RF-D05: Registrar denegación silenciosa por RLS
        background_tasks.add_task(
            log_rbac_denial,
            username=token_data.get("sub", "unknown"),
            department=dept, role=role,
            endpoint="POST /api/v1/chat/stream",
            reason="rls_empty",
            detail=f"Query: {request.question[:200]}"
        )
        return {"error": "Operación denegada"}

    # 2b. Obtener modelo activo (CACHED — sin conexión extra)
    _active_model_name = await get_cached_config("model", "llama3.1:8b")

    # 3. Metadatos de Trazabilidad
    sources = [
        {
            "id": r['section_id'],
            "file_name": json.loads(r['metadata']).get("file_name") if isinstance(r['metadata'], str) else r['metadata'].get("file_name"),
            "security": r['confidentiality_level']
        } for r in results
    ]
    chunks_id = [r['section_id'] for r in results]
    context_text = "\n".join([f'<documento fuente="{sources[i]["file_name"]}" seguridad="{sources[i]["security"]}">\n{r["text"]}\n</documento>' for i, r in enumerate(results)])

    full_response_accumulator = [""]

    # 4. Generador SSE (ASYNC — no bloquea el event loop)
    async def event_generator():
        yield f"event: metadata\ndata: {json.dumps(sources)}\n\n"

        ollama_chat_url = "http://ollama_engine:11434/api/chat"
        chat_payload = {
            "model": _active_model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": FEW_SHOT_USER},
                {"role": "assistant", "content": FEW_SHOT_ASSISTANT},
                {"role": "user", "content": f"<contexto>\n{context_text}\n</contexto>\n\nPregunta: {request.question}"}
            ],
            "stream": True,
            "options": {"temperature": 0.0, "top_p": 0.1, "num_ctx": 4096, "num_predict": 512}
        }

        async with _http_client.stream("POST", ollama_chat_url, json=chat_payload) as response:
            async for line in response.aiter_lines():
                if line:
                    chunk = json.loads(line)
                    if "message" in chunk and "content" in chunk["message"]:
                        token = chunk["message"]["content"]
                        full_response_accumulator[0] += token
                        yield f"event: message\ndata: {json.dumps({'token': token})}\n\n"

        yield "event: done\ndata: {}\n\n"

    # 5. Audit Trail en Background (usa pool)
    async def save_log_task():
        try:
            async with get_pool().acquire() as conn:
                insert_query = """
                    INSERT INTO audit_logs (user_department, user_role, question, response, context_used, chunks_id, model_used)
                    VALUES ($1, $2, $3, $4, $5, $6, $7);
                """
                await conn.execute(
                    insert_query,
                    dept, role, request.question, full_response_accumulator[0], context_text, chunks_id, _active_model_name
                )
        except Exception as e:
            print(f"Error de auditoría: {e}")

    background_tasks.add_task(save_log_task)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/v1/document/exists/{document_hash}")
async def check_document_hash(document_hash: str):
    """
    Comprueba si un documento con el hash SHA-256 dado ya existe en la BD.
    Utilizado por el pipeline de ingesta de n8n para deduplicación.
    Usa conexión de superusuario para bypass de RLS en consulta administrativa interna.
    """
    async with get_pool_admin().acquire() as conn:
        result = await conn.fetchval(
            "SELECT COUNT(*) FROM document_sections WHERE document_hash = $1",
            document_hash
        )
    return {"exists": result > 0, "hash": document_hash}


@app.delete("/api/v1/document/{filename}")
async def delete_document_chunks(filename: str, token_data: dict = Depends(verify_jwt_token)):
    """
    Elimina todos los chunks de un documento por nombre de fichero.
    Utilizado por el pipeline de n8n antes de reingestar una versión actualizada.
    Solo accesible para el rol admin.
    """
    if token_data.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Operación restringida al rol admin")

    async with get_pool().acquire() as conn:
        await conn.execute(
            "DELETE FROM document_sections WHERE filename = $1",
            filename
        )
    return {"deleted": True, "filename": filename}


# ─── RAG CONFIG ───────────────────────────────
from pydantic import BaseModel as _BaseModel
from typing import Optional as _Optional


class ConfigUpdate(_BaseModel):
    top_k: _Optional[int] = None
    similarity_threshold: _Optional[float] = None
    chunk_size: _Optional[int] = None
    chunk_overlap: _Optional[int] = None
    model: _Optional[str] = None
    temperature: _Optional[float] = None
    num_ctx: _Optional[int] = None
    num_predict: _Optional[int] = None


@app.get("/api/v1/config")
async def get_config(payload: dict = Depends(verify_jwt_token)):
    async with get_pool_admin().acquire() as conn:
        rows = await conn.fetch(
            "SELECT key, value, updated_by, updated_at FROM rag_config ORDER BY key"
        )
    return {
        r["key"]: {
            "value": r["value"],
            "updated_by": r["updated_by"],
            "updated_at": str(r["updated_at"])
        } for r in rows
    }


@app.put("/api/v1/config")
async def update_config(updates: ConfigUpdate, payload: dict = Depends(verify_jwt_token)):
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores pueden modificar la configuracion")
    async with get_pool_admin().acquire() as conn:
        changed = {}
        data = updates.model_dump(exclude_none=True)
        for key, val in data.items():
            await conn.execute(
                "UPDATE rag_config SET value=$1, updated_by=$2, updated_at=CURRENT_TIMESTAMP WHERE key=$3",
                str(val), payload.get("sub", "admin"), key
            )
            changed[key] = str(val)
    # Invalidar caché tras actualización
    await invalidate_config_cache()
    return {"status": "ok", "updated": changed}


# ─── RF-C07: GESTIÓN DE USUARIOS Y ROLES ──────────────
from typing import Optional as _Opt

VALID_ROLES = {"admin", "dept_high", "dept_standard"}


class UserCreate(_BaseModel):
    username: str
    password: str
    department: str
    user_role: str


class UserUpdate(_BaseModel):
    password: _Opt[str] = None
    department: _Opt[str] = None
    user_role: _Opt[str] = None


def _require_admin(payload: dict):
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Operación restringida al rol admin")


@app.post("/api/v1/admin/users", status_code=201)
async def create_user(user: UserCreate, payload: dict = Depends(verify_jwt_token)):
    """Crea un nuevo usuario con contraseña hasheada en bcrypt coste 12. Solo admin."""
    _require_admin(payload)
    if user.user_role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"Rol inválido. Válidos: {', '.join(VALID_ROLES)}")
    async with get_pool_admin().acquire() as conn:
        existing = await conn.fetchval("SELECT user_id FROM users WHERE username = $1", user.username)
        if existing:
            raise HTTPException(status_code=409, detail="El usuario ya existe")
        await conn.execute(
            """INSERT INTO users (username, password_hash, department, user_role)
               VALUES ($1, crypt($2, gen_salt('bf', 12)), $3, $4)""",
            user.username, user.password, user.department, user.user_role
        )
    return {"status": "created", "username": user.username,
            "department": user.department, "user_role": user.user_role}


@app.get("/api/v1/admin/users")
async def list_users(payload: dict = Depends(verify_jwt_token)):
    """Lista los usuarios existentes sin exponer los hashes de contraseña. Solo admin."""
    _require_admin(payload)
    async with get_pool_admin().acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, username, department, user_role, created_at FROM users ORDER BY user_id"
        )
    return [
        {"user_id": r["user_id"], "username": r["username"],
         "department": r["department"], "user_role": r["user_role"],
         "created_at": str(r["created_at"])}
        for r in rows
    ]


@app.put("/api/v1/admin/users/{username}")
async def update_user(username: str, updates: UserUpdate, payload: dict = Depends(verify_jwt_token)):
    """Actualiza departamento, rol o contraseña de un usuario. Solo admin."""
    _require_admin(payload)
    if updates.user_role is not None and updates.user_role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail=f"Rol inválido. Válidos: {', '.join(VALID_ROLES)}")
    async with get_pool_admin().acquire() as conn:
        existing = await conn.fetchval("SELECT user_id FROM users WHERE username = $1", username)
        if not existing:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        changed = {}
        if updates.password is not None:
            await conn.execute(
                "UPDATE users SET password_hash = crypt($1, gen_salt('bf', 12)) WHERE username = $2",
                updates.password, username
            )
            changed["password"] = "actualizada"
        if updates.department is not None:
            await conn.execute(
                "UPDATE users SET department = $1 WHERE username = $2",
                updates.department, username
            )
            changed["department"] = updates.department
        if updates.user_role is not None:
            await conn.execute(
                "UPDATE users SET user_role = $1 WHERE username = $2",
                updates.user_role, username
            )
            changed["user_role"] = updates.user_role
    return {"status": "updated", "username": username, "changed": changed}


@app.delete("/api/v1/admin/users/{username}")
async def delete_user(username: str, payload: dict = Depends(verify_jwt_token)):
    """Elimina un usuario. Solo admin. No permite auto-eliminación."""
    _require_admin(payload)
    if payload.get("sub") == username:
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propio usuario")
    async with get_pool_admin().acquire() as conn:
        existing = await conn.fetchval("SELECT user_id FROM users WHERE username = $1", username)
        if not existing:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        await conn.execute("DELETE FROM users WHERE username = $1", username)
    return {"status": "deleted", "username": username}
