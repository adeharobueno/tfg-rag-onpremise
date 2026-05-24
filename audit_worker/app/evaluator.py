import json
import asyncio
import asyncpg
import requests
import time
import urllib.parse

# ==========================================
# Configuración de Base de Datos
# ==========================================
DB_USER = "api_gateway"
DB_PASS = "App_Pass_Gateway_Secure_2026?"
DB_HOST = "postgres_db"
DB_PORT = "5432"
DB_NAME = "tfg_rag_db"

# ==========================================
# Motor de Evaluación (Juez LLM Local)
# ==========================================
class OllamaJuiceProvider:
    def __init__(self, model_name="llama3.1:8b", endpoint="http://ollama_engine:11434/api/chat"):
        self.model_name = model_name
        self.endpoint = endpoint

    def _call_ollama_judge(self, system_prompt, user_prompt):
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "options": {"temperature": 0.0}
        }
        try:
            res = requests.post(self.endpoint, json=payload)
            output = res.json()["message"]["content"]
            for word in output.split():
                try:
                    score = float(word)
                    if 0.0 <= score <= 1.0:
                        return score
                except ValueError:
                    continue
            return 0.5 
        except Exception as e:
            print(f"Error de conexión con Ollama Judge: {e}")
            return 0.0

    def context_relevance(self, question, context):
        sys_prompt = "Eres un auditor de sistemas RAG. Evalúa si el contexto contiene información útil para responder a la pregunta. Responde ÚNICAMENTE con un número flotante entre 0.0 y 1.0."
        usr_prompt = f"Pregunta: {question}\nContexto: {context}"
        return self._call_ollama_judge(sys_prompt, usr_prompt)

    def groundedness(self, context, response):
        sys_prompt = "Eres un auditor de seguridad semántica. Evalúa si la respuesta se basa ÚNICAMENTE en el contexto. Responde ÚNICAMENTE con un número flotante entre 0.0 (alucinación) y 1.0 (fidelidad)."
        usr_prompt = f"Contexto: {context}\nRespuesta: {response}"
        return self._call_ollama_judge(sys_prompt, usr_prompt)

    def answer_relevance(self, question, response):
        sys_prompt = "Eres un experto QA. Evalúa si la respuesta atiende de forma directa a la pregunta. Responde ÚNICAMENTE con un número flotante entre 0.0 y 1.0."
        usr_prompt = f"Pregunta: {question}\nRespuesta: {response}"
        return self._call_ollama_judge(sys_prompt, usr_prompt)

# ==========================================
# Orquestador Asíncrono
# ==========================================
async def evaluate_pending_logs():
    judge = OllamaJuiceProvider()
    
    safe_pass = urllib.parse.quote_plus(DB_PASS)
    safe_db_url = f"postgresql://{DB_USER}:{safe_pass}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    
    try:
        conn = await asyncpg.connect(safe_db_url)
        
        records = await conn.fetch(
            "SELECT log_id, question, response, context_used FROM audit_logs WHERE response NOT LIKE '%[Métricas Auditoría:%' LIMIT 10;"
        )
        
        if not records:
            print("Evaluador en reposo: No hay trazas pendientes.")
            await conn.close()
            return

        print(f"Iniciando evaluación de {len(records)} trazas de auditoría...")

        for r in records:
            log_id = r['log_id']
            q = r['question']
            a = r['response']
            c = r['context_used']

            score_context = judge.context_relevance(q, c)
            score_grounded = judge.groundedness(c, a)
            score_answer = judge.answer_relevance(q, a)

            requires_review = True if (score_grounded < 0.6 or score_context < 0.6) else False

            metrics_json = json.dumps({
                "context_relevance": score_context,
                "groundedness": score_grounded,
                "answer_relevance": score_answer
            })

            await conn.execute(
                """
                UPDATE audit_logs 
                SET requires_review = $1, 
                    response = response || '\n[Métricas Auditoría: ' || $2 || ']'
                WHERE log_id = $3;
                """,
                requires_review, metrics_json, log_id
            )
            print(f"[✓] Log {log_id} auditado. Revisión manual requerida: {requires_review}")

        await conn.close()
        
    except Exception as e:
        print(f"[!] Error de Gobernanza: {e}")

# ==========================================
# Bucle de Ejecución Continua
# ==========================================
if __name__ == "__main__":
    print("Iniciando servicio de Gobernanza y Auditoría (Audit Worker)...")
    while True:
        asyncio.run(evaluate_pending_logs())
        time.sleep(30)
