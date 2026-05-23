from fastapi import FastAPI, Depends, HTTPException, Header
from app.database import get_db_connection, search_vectors_with_rls
from pydantic import BaseModel
import requests, jwt

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

@app.post("/api/v1/retrieve")
async def retrieve_context(request: QueryRequest, token_data: dict = Depends(verify_jwt_token)):
    ollama_url = "http://ollama_engine:11434/api/embeddings"
    response = requests.post(ollama_url, json={"model": "nomic-embed-text", "prompt": request.question})
    if response.status_code != 200: 
        raise HTTPException(status_code=500, detail="Error en Ollama")
    
    query_embedding = response.json()["embedding"]
    conn = await get_db_connection()
    try:
        # Extraemos solo lo que existe en el token
        dept = token_data.get("department", "UNKNOWN")
        role = token_data.get("role", "UNKNOWN")
        
        results = await search_vectors_with_rls(conn, query_embedding, dept, role)
        return {"chunks": [{"id": r["section_id"], "text": r["text"], "security": r["confidentiality_level"]} for r in results]}
    finally: 
        await conn.close()
