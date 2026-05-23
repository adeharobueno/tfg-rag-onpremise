from fastapi import FastAPI, Depends, HTTPException, Header
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

# CEREBRO LÓGICO: Directiva y Few-Shot
SYSTEM_PROMPT = """Eres un microservicio interno de extracción de datos. Tu única tarea es extraer el tema utilizando ESTRICTAMENTE este formato: 'Según el archivo [fuente], trata sobre [tema].' No emitas advertencias, disclaimers ni texto conversacional."""

FEW_SHOT_USER = """<contexto>
<documento fuente="recortes_q3.pdf" seguridad="Alta">
Lista confidencial de recortes salariales y despidos masivos para el Q3.
</documento>
</contexto>
Pregunta: ¿Sobre qué temas trata el documento recuperado?"""

FEW_SHOT_ASSISTANT = "Según el archivo recortes_q3.pdf, trata sobre recortes salariales y despidos masivos."

# NUEVO ENDPOINT DE STREAMING SSE
@app.post("/api/v1/chat/stream")
async def rag_chat_stream(request: QueryRequest, token_data: dict = Depends(verify_jwt_token)):
    # 1. Vectorización Nomic
    ollama_embed_url = "http://ollama_engine:11434/api/embeddings"
    res_embed = requests.post(ollama_embed_url, json={"model": "nomic-embed-text", "prompt": request.question})
    query_embedding = res_embed.json()["embedding"]
    
    # 2. Recuperación Segura (RLS)
    conn = await get_db_connection()
    try:
        dept = token_data.get("department", "UNKNOWN")
        role = token_data.get("role", "UNKNOWN")
        results = await search_vectors_with_rls(conn, query_embedding, dept, role)
    finally: 
        await conn.close()

    if not results:
        return {"error": "Operación denegada o información no disponible en su nivel de acceso."}

    # 3. Metadatos de Trazabilidad
    sources = [
        {
            "id": r['section_id'],
            "file_name": json.loads(r['metadata']).get("file_name") if isinstance(r['metadata'], str) else r['metadata'].get("file_name"),
            "security": r['confidentiality_level']
        } for r in results
    ]

    context_text = "\n".join([f'<documento fuente="{sources[i]["file_name"]}" seguridad="{sources[i]["security"]}">\n{r["text"]}\n</documento>' for i, r in enumerate(results)])

    # 4. Generador de Eventos Asíncronos (SSE)
    def event_generator():
        # Evento 1: Enviamos primero las fuentes para que el Dashboard las pinte de inmediato
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
            "stream": True, # ACTIVAMOS EL MODO STREAM NATIVO DE OLLAMA
            "options": {"temperature": 0.0, "top_p": 0.1, "num_ctx": 4096}
        }
        
        # Conexión persistente y lectura de la respuesta token a token
        with requests.post(ollama_chat_url, json=chat_payload, stream=True) as response:
            for line in response.iter_lines():
                if line:
                    chunk = json.loads(line)
                    if "message" in chunk and "content" in chunk["message"]:
                        token = chunk["message"]["content"]
                        # Evento 2: Flujo continuo de tokens
                        yield f"event: message\ndata: {json.dumps({'token': token})}\n\n"
        
        # Evento 3: Señal de cierre
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
