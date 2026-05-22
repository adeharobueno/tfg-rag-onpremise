from fastapi import FastAPI, Depends, HTTPException, Header
from app.database import get_db_connection, search_vectors_with_rls
import requests
import jwt

app = FastAPI(title="TFG RAG Secure API Gateway", version="1.0.0")
JWT_SECRET = "ETSIIT_UGR_SECRET_KEY_2026"

# Esquema de validación para la entrada
from pydantic import BaseModel
class QueryRequest(BaseModel):
    question: str

def verify_jwt_token(authorization: str = Header(...)):
    try:
        token = authorization.split(" ")[1]
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except Exception:
        raise HTTPException(status_code=401, detail="Token corporativo inválido o ausente")

@app.post("/api/v1/retrieve")
async def retrieve_context(request: QueryRequest, token_data: dict = Depends(verify_jwt_token)):
    # 1. Llamada local al motor de Ollama para vectorizar la pregunta del usuario
    ollama_url = "http://ollama_engine:11434/api/embeddings"
    response = requests.post(ollama_url, json={"model": "nomic-embed-text", "prompt": request.question})
    
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail="Error al conectar con el motor de embeddings local")
    
    query_embedding = response.json()["embedding"]
    
    # 2. Conectar a la base de datos y recuperar aplicando las reglas RLS
    conn = await get_db_connection()
    try:
        results = await search_vectors_with_rls(
            conn=conn,
            embedding=query_embedding,
            dept=token_data.get("department"),
            clearance=token_data.get("clearance"),
            role=token_data.get("role")
        )
        
        # Formatamos la salida estructurada
        context_chunks = []
        for r in results:
            context_chunks.append({
                "id": r["section_id"],
                "text": r["text"],
                "source": r["filename"],
                "security": r["confidentiality_level"],
                "score": round(1 - r["distance"], 4) # Transformamos distancia a similitud
            })
            
        return {"chunks": context_chunks}
    finally:
        await conn.close()
