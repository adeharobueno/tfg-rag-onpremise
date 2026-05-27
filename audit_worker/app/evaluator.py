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
# EVALUADOR 1: OllamaJuiceProvider (Artesanal)
# Evaluador personalizado que usa Ollama como juez ciego
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
            print(f"[OllamaJuice] Error de conexión con Ollama Judge: {e}")
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
# EVALUADOR 2: TruLens con Provider Personalizado
# Integración nativa con el framework TruLens usando
# Ollama como backend de evaluación local
# ==========================================
from trulens.core import Provider
from pydantic import Field

class TruLensOllamaProvider(Provider):
    """
    Proveedor personalizado de TruLens que delega la evaluación
    en el motor de inferencia local Ollama, manteniendo la
    soberanía del dato al no transmitir trazas a servicios externos.
    """
    model_name: str = Field(default="llama3.1:8b")
    ollama_endpoint: str = Field(default="http://ollama_engine:11434/api/chat")

    def _call_ollama(self, system_prompt, user_prompt):
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
            res = requests.post(self.ollama_endpoint, json=payload)
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
            print(f"[TruLens] Error de conexión con Ollama: {e}")
            return 0.0

    def context_relevance_score(self, question, context):
        sys_prompt = (
            "You are a RAG system auditor. Your task is to evaluate whether "
            "the retrieved context contains useful information to answer the "
            "given question. Rate the relevance on a scale from 0.0 (completely "
            "irrelevant) to 1.0 (highly relevant). Respond ONLY with a single "
            "floating-point number between 0.0 and 1.0."
        )
        usr_prompt = f"Question: {question}\n\nRetrieved Context:\n{context}"
        return self._call_ollama(sys_prompt, usr_prompt)

    def groundedness_score(self, context, response):
        sys_prompt = (
            "You are a semantic security auditor specialized in detecting "
            "hallucinations in AI-generated responses. Evaluate whether the "
            "response is ENTIRELY grounded in the provided context. A score "
            "of 1.0 means every claim in the response can be traced back to "
            "the context. A score of 0.0 means the response is completely "
            "fabricated. Respond ONLY with a single floating-point number "
            "between 0.0 and 1.0."
        )
        usr_prompt = f"Context:\n{context}\n\nResponse:\n{response}"
        return self._call_ollama(sys_prompt, usr_prompt)

    def answer_relevance_score(self, question, response):
        sys_prompt = (
            "You are a QA expert evaluating response quality. Assess whether "
            "the response directly and adequately addresses the user's question. "
            "A score of 1.0 means the response perfectly answers the question. "
            "A score of 0.0 means the response is completely off-topic. "
            "Respond ONLY with a single floating-point number between 0.0 and 1.0."
        )
        usr_prompt = f"Question: {question}\n\nResponse:\n{response}"
        return self._call_ollama(sys_prompt, usr_prompt)

# ==========================================
# Orquestador Asíncrono Dual
# Ejecuta ambos evaluadores secuencialmente
# ==========================================
async def evaluate_pending_logs():
    juice_judge = OllamaJuiceProvider()
    trulens_judge = TruLensOllamaProvider()

    safe_pass = urllib.parse.quote_plus(DB_PASS)
    safe_db_url = f"postgresql://{DB_USER}:{safe_pass}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

    try:
        conn = await asyncpg.connect(safe_db_url)

        records = await conn.fetch(
            """SELECT log_id, question, response, context_used 
               FROM audit_logs 
               WHERE response NOT LIKE '%[Métricas Auditoría:%' 
               LIMIT 10;"""
        )

        if not records:
            print("Evaluador en reposo: No hay trazas pendientes.")
            await conn.close()
            return

        print(f"Iniciando evaluación dual de {len(records)} trazas de auditoría...")

        for r in records:
            log_id = r['log_id']
            q = r['question']
            a = r['response']
            c = r['context_used']

            # =============================================
            # EVALUADOR 1: OllamaJuiceProvider (artesanal)
            # =============================================
            print(f"\n[Evaluador 1/2] OllamaJuiceProvider → Log {log_id}")
            juice_cr = juice_judge.context_relevance(q, c)
            juice_gr = juice_judge.groundedness(c, a)
            juice_ar = juice_judge.answer_relevance(q, a)
            juice_review = True if (juice_gr < 0.6 or juice_cr < 0.6) else False

            juice_metrics = json.dumps({
                "context_relevance": juice_cr,
                "groundedness": juice_gr,
                "answer_relevance": juice_ar
            })

            await conn.execute(
                """
                UPDATE audit_logs
                SET requires_review = $1,
                    response = response || E'\n[Métricas Auditoría: ' || $2 || ']'
                WHERE log_id = $3;
                """,
                juice_review, juice_metrics, log_id
            )
            print(f"  [✓] OllamaJuice: CR={juice_cr}, GR={juice_gr}, AR={juice_ar} | Review={juice_review}")

            # =============================================
            # EVALUADOR 2: TruLens Provider (framework)
            # =============================================
            print(f"[Evaluador 2/2] TruLens Provider → Log {log_id}")
            trulens_cr = trulens_judge.context_relevance_score(q, c)
            trulens_gr = trulens_judge.groundedness_score(c, a)
            trulens_ar = trulens_judge.answer_relevance_score(q, a)
            trulens_review = True if (trulens_gr < 0.6 or trulens_cr < 0.6) else False

            await conn.execute(
                """
                INSERT INTO trulens_evaluations 
                    (log_id, context_relevance, groundedness, answer_relevance, requires_review)
                VALUES ($1, $2, $3, $4, $5);
                """,
                log_id, trulens_cr, trulens_gr, trulens_ar, trulens_review
            )
            print(f"  [✓] TruLens:     CR={trulens_cr}, GR={trulens_gr}, AR={trulens_ar} | Review={trulens_review}")

            # =============================================
            # Comparativa instantánea
            # =============================================
            delta_cr = abs(juice_cr - trulens_cr)
            delta_gr = abs(juice_gr - trulens_gr)
            delta_ar = abs(juice_ar - trulens_ar)
            print(f"  [Δ] Diferencia:  ΔCR={delta_cr:.2f}, ΔGR={delta_gr:.2f}, ΔAR={delta_ar:.2f}")

        await conn.close()
        print(f"\nEvaluación dual completada para {len(records)} trazas.")

    except Exception as e:
        print(f"[!] Error de Gobernanza: {e}")

# ==========================================
# Bucle de Ejecución Continua
# ==========================================
if __name__ == "__main__":
    print("=" * 60)
    print("SERVICIO DE GOBERNANZA Y AUDITORÍA DUAL")
    print("Evaluador 1: OllamaJuiceProvider (artesanal, prompts ES)")
    print("Evaluador 2: TruLens Provider (framework, prompts EN)")
    print("=" * 60)
    while True:
        asyncio.run(evaluate_pending_logs())
        time.sleep(30)
