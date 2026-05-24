from fastapi import FastAPI, Depends, HTTPException, Header, BackgroundTasks
from fastapi.responses import StreamingResponse
from app.database import get_db_connection, search_vectors_with_rls
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

    # Variable mutable para poder extraer el texto desde el generador síncrono
    full_response_accumulator = [""]

    # 4. Generador SSE (Streaming Síncrono)
    def event_generator():
        yield f"event: metadata\ndata: {json.dumps(sources)}\n\n"
        
        ollama_chat_url = "http://ollama_engine:11434/api/chat"
        chat_payload = {
            "model": "llama3.1:8b",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": FEW_SHOT_USER},
                {"role": "assistant", "content": FEW_SHOT_ASSISTANT},
                {"role": "user", "content": f"<contexto>\n{context_text}\n</contexto>\n\nPregunta: {request.question}"}
            ],
            "stream": True,
            "options": {"temperature": 0.0, "top_p": 0.1, "num_ctx": 4096}
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

    # 5. Tarea en Segundo Plano (Audit Trail)
    # Esta función asíncrona es gestionada por el loop principal de FastAPI *después* del stream
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

    # Delegamos la tarea de base de datos a FastAPI
    background_tasks.add_task(save_log_task)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
