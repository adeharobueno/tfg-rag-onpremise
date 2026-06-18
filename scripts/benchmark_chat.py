"""
Benchmark de latencia del chat RAG.
Ejecutar ANTES y DESPUÉS de aplicar las optimizaciones para comparar.

Uso:
    python benchmark_chat.py http://localhost:8000 usuario contraseña
"""
import sys, time, json, requests

API_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
USERNAME = sys.argv[2] if len(sys.argv) > 2 else "director_ia"
PASSWORD = sys.argv[3] if len(sys.argv) > 3 else "admin2026"

PREGUNTA = "¿Cuáles son las políticas de vacaciones de la empresa?"

print("=" * 60)
print(f"BENCHMARK DE LATENCIA RAG — {time.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Endpoint: {API_URL}")
print("=" * 60)

# ── 1. Medir latencia de autenticación ────────────────────
print("\n[1/4] Autenticación...")
t0 = time.perf_counter()
r = requests.post(f"{API_URL}/auth/token",
                   json={"username": USERNAME, "password": PASSWORD}, timeout=15)
t_auth = time.perf_counter() - t0

if r.status_code != 200:
    print(f"  ERROR: {r.status_code} — {r.text}")
    sys.exit(1)

token = r.json()["access_token"]
user = r.json()["user"]
print(f"  OK — {user['username']} ({user['department']}/{user['role']})")
print(f"  Latencia auth: {t_auth*1000:.0f} ms")

headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# ── 2. Medir TTFT (Time to First Token) ──────────────────
print(f"\n[2/4] Chat streaming — \"{PREGUNTA[:50]}...\"")
t0 = time.perf_counter()
t_first_token = None
full_response = ""
n_tokens = 0
n_sources = 0

with requests.post(f"{API_URL}/api/v1/chat/stream",
                    json={"question": PREGUNTA},
                    headers=headers, stream=True, timeout=300) as r:
    if "application/json" in r.headers.get("Content-Type", ""):
        print(f"  ERROR: {r.json()}")
        sys.exit(1)

    current_event = ""
    for line in r.iter_lines():
        if line:
            decoded = line.decode("utf-8")
            if decoded.startswith("event: "):
                current_event = decoded[7:].strip()
                continue
            if decoded.startswith("data: "):
                data_str = decoded[6:]
                if data_str == "{}":
                    break
                try:
                    data = json.loads(data_str)
                    if current_event == "metadata" and isinstance(data, list):
                        n_sources = len(data)
                    elif current_event == "message" and "token" in data:
                        if t_first_token is None:
                            t_first_token = time.perf_counter() - t0
                        full_response += data["token"]
                        n_tokens += 1
                except json.JSONDecodeError:
                    continue

t_total = time.perf_counter() - t0

# ── 3. Calcular métricas ─────────────────────────────────
tokens_per_sec = n_tokens / (t_total - (t_first_token or 0)) if t_first_token and n_tokens > 1 else 0

print(f"  Fuentes RLS recuperadas: {n_sources}")
print(f"  Tokens generados: {n_tokens}")
print(f"  Respuesta: {full_response[:120]}...")

# ── 4. Medir endpoint de config (no-LLM) ─────────────────
print(f"\n[3/4] Lectura de config (endpoint ligero)...")
t0 = time.perf_counter()
r = requests.get(f"{API_URL}/api/v1/config", headers=headers, timeout=10)
t_config = time.perf_counter() - t0
print(f"  Latencia config: {t_config*1000:.0f} ms")

# ── 5. Medir segunda query (modelo ya warm) ───────────────
print(f"\n[4/4] Segunda query (modelo warm)...")
t0_warm = time.perf_counter()
t_first_warm = None
n_tokens_warm = 0

with requests.post(f"{API_URL}/api/v1/chat/stream",
                    json={"question": "¿Qué documentos hay disponibles?"},
                    headers=headers, stream=True, timeout=300) as r:
    current_event = ""
    for line in r.iter_lines():
        if line:
            decoded = line.decode("utf-8")
            if decoded.startswith("event: "):
                current_event = decoded[7:].strip()
                continue
            if decoded.startswith("data: "):
                data_str = decoded[6:]
                if data_str == "{}":
                    break
                try:
                    data = json.loads(data_str)
                    if current_event == "message" and "token" in data:
                        if t_first_warm is None:
                            t_first_warm = time.perf_counter() - t0_warm
                        n_tokens_warm += 1
                except json.JSONDecodeError:
                    continue

t_total_warm = time.perf_counter() - t0_warm
tps_warm = n_tokens_warm / (t_total_warm - (t_first_warm or 0)) if t_first_warm and n_tokens_warm > 1 else 0

# ── RESUMEN ───────────────────────────────────────────────
print("\n" + "=" * 60)
print("RESULTADOS")
print("=" * 60)
print(f"  Auth latencia:             {t_auth*1000:>8.0f} ms")
print(f"  Config latencia:           {t_config*1000:>8.0f} ms")
print(f"  TTFT (1ª query):           {(t_first_token or 0)*1000:>8.0f} ms")
print(f"  Total (1ª query):          {t_total*1000:>8.0f} ms  ({n_tokens} tokens)")
print(f"  Velocidad (1ª query):      {tokens_per_sec:>8.1f} tok/s")
print(f"  TTFT (2ª query, warm):     {(t_first_warm or 0)*1000:>8.0f} ms")
print(f"  Total (2ª query, warm):    {t_total_warm*1000:>8.0f} ms  ({n_tokens_warm} tokens)")
print(f"  Velocidad (2ª, warm):      {tps_warm:>8.1f} tok/s")
print("=" * 60)
print("Guarda estos resultados para comparar antes/después.")
