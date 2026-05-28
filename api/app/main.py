from fastapi import FastAPI, Depends, HTTPException, Header, BackgroundTasks
from fastapi.responses import StreamingResponse
from app.database import get_db_connection, get_db_connection_admin, search_vectors_with_rls
from pydantic import BaseModel
import requests, jwt, json

app = FastAPI(title="TFG RAG Secure API Gateway", version="1.0.0")
JWT_SECRET = "ETSIIT_UGR_SECRET_KEY_2026"

class QueryRequest(BaseModel):
    question: str

def verify_jwt_token(authorization: str = Header(...)):
    try:
        token = authorization.split(" ")[1]
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except:
        raise HTTPException(status_code=401, detail="Token corporativo inválido")

SYSTEM_PROMPT = """Eres un microservicio interno de extracción de datos. Tu única tarea es extraer el tema utilizando ESTRICTAMENTE este formato: 'Según el archivo [fuente], trata sobre [tema].' No emitas advertencias, disclaimers ni texto conversacional."""

FEW_SHOT_USER = """<contexto>
<documento fuente="recortes_q3.pdf" seguridad="Alta">
Lista confidencial de recortes salariales y despidos masivos para el Q3.
</documento>
</contexto>
Pregunta: ¿Sobre qué temas trata el documento recuperado?"""

FEW_SHOT_ASSISTANT = "Según el archivo recortes_q3.pdf, trata sobre recortes salariales y despidos masivos."

@app.post("/api/v1/chat/stream")

async def _get_active_model(conn) -> str:
    try:
        conn_cfg = await get_db_connection_admin()
        row = await conn_cfg.fetchrow("SELECT value FROM rag_config WHERE key='model'")
        await conn_cfg.close()
        return row["value"] if row else "llama3.1:8b"
    except Exception:
        return "llama3.1:8b"

async def rag_chat_stream(request: QueryRequest, background_tasks: BackgroundTasks, token_data: dict = Depends(verify_jwt_token)):
    # 1. Vectorización
    ollama_embed_url = "http://ollama_engine:11434/api/embeddings"
    res_embed = requests.post(ollama_embed_url, json={"model": "nomic-embed-text", "prompt": request.question})
    query_embedding = res_embed.json()["embedding"]
    
    # 2. Recuperación Segura (RLS)
    dept = token_data.get("department", "UNKNOWN")
    role = token_data.get("role", "UNKNOWN")
    
    conn = await get_db_connection()
    try:
        results = await search_vectors_with_rls(conn, query_embedding, dept, role)
    finally: 
        await conn.close()

    if not results:
        return {"error": "Operación denegada"}

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

    # Si no hay chunks relevantes (umbral similitud o RLS filtró todo), respuesta inmediata
    if not results:
        async def empty_generator():
            msg = "No dispongo de información relevante en el repositorio corporativo para responder a esta consulta con el nivel de acceso actual."
            yield f"event: metadata\ndata: {json.dumps([])}\n\n"
            yield f"data: {json.dumps({'token': msg})}\n\n"
            yield "data: {}\n\n"
        return StreamingResponse(empty_generator(), media_type="text/event-stream")

    full_response_accumulator = [""]

    # 4. Generador SSE
    def event_generator():
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
        
        with requests.post(ollama_chat_url, json=chat_payload, stream=True) as response:
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    if "message" in chunk and "content" in chunk["message"]:
                        token = chunk["message"]["content"]
                        full_response_accumulator[0] += token
                        yield f"event: message\ndata: {json.dumps({'token': token})}\n\n"
        
        yield "event: done\ndata: {}\n\n"

    # 5. Audit Trail en Background
    async def save_log_task():
        try:
            write_conn = await get_db_connection()
            insert_query = """
                INSERT INTO audit_logs (user_department, user_role, question, response, context_used, chunks_id)
                VALUES ($1, $2, $3, $4, $5, $6);
            """
            await write_conn.execute(
                insert_query, 
                dept, role, request.question, full_response_accumulator[0], context_text, chunks_id
            )
            await write_conn.close()
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
    conn = await get_db_connection_admin()
    try:
        result = await conn.fetchval(
            "SELECT COUNT(*) FROM document_sections WHERE document_hash = $1",
            document_hash
        )
        return {"exists": result > 0, "hash": document_hash}
    finally:
        await conn.close()

@app.delete("/api/v1/document/{filename}")
async def delete_document_chunks(filename: str, token_data: dict = Depends(verify_jwt_token)):
    """
    Elimina todos los chunks de un documento por nombre de fichero.
    Utilizado por el pipeline de n8n antes de reingestar una versión actualizada.
    Solo accesible para el rol admin.
    """
    if token_data.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Operación restringida al rol admin")
    
    conn = await get_db_connection()
    try:
        await conn.execute(
            "DELETE FROM document_sections WHERE filename = $1",
            filename
        )
        return {"deleted": True, "filename": filename}
    finally:
        await conn.close()


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
    conn = await get_db_connection_admin()
    try:
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
    finally:
        await conn.close()

@app.put("/api/v1/config")
async def update_config(updates: ConfigUpdate, payload: dict = Depends(verify_jwt_token)):
    from fastapi import HTTPException as _HTTPException
    if payload.get("role") != "admin":
        raise _HTTPException(status_code=403, detail="Solo administradores pueden modificar la configuracion")
    conn = await get_db_connection_admin()
    try:
        changed = {}
        data = updates.dict(exclude_none=True)
        for key, val in data.items():
            await conn.execute(
                "UPDATE rag_config SET value=$1, updated_by=$2, updated_at=CURRENT_TIMESTAMP WHERE key=$3",
                str(val), payload.get("sub", "admin"), key
            )
            changed[key] = str(val)
        return {"status": "ok", "updated": changed}
    finally:
        await conn.close()
