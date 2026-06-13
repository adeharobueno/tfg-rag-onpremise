#!/usr/bin/env python3
"""
Golden Set — Tuning de Parámetros RAG
Ejecuta las 20 preguntas originales (bloques A-E) variando un parámetro por ronda.
Conserva las trazas anteriores (comparativa de modelos) en la BD.

Uso:
  python3 golden_set_params.py              # Ejecuta las 4 rondas
  python3 golden_set_params.py --only R4    # Solo una ronda
"""

import requests
import json
import sys
import time
import subprocess
from datetime import datetime

API_BASE = "http://localhost:8000"
JWT_SECRET = "ETSIIT_UGR_SECRET_KEY_2026"
TIMEOUT = 600
DB_CMD = ["docker", "exec", "postgres_db", "psql", "-U", "postgres", "-d", "tfg_rag_db", "-t", "-A", "-c"]
MODEL = "llama3.1:8b"

PARAM_ROUNDS = [
    {"tag": "R4-topk3",    "param": "top_k",                "value": "3",   "baseline": "6",   "desc": "top_k reducido: menos chunks, menos ruido"},
    {"tag": "R5-topk10",   "param": "top_k",                "value": "10",  "baseline": "6",   "desc": "top_k aumentado: más chunks, más cobertura"},
    {"tag": "R6-thresh03", "param": "similarity_threshold",  "value": "0.3", "baseline": "0.0", "desc": "Umbral de similitud: filtra chunks irrelevantes"},
    {"tag": "R7-temp03",   "param": "temperature",           "value": "0.3", "baseline": "0.0", "desc": "Temperatura 0.3: respuestas más variadas"},
]

def generate_tokens():
    try:
        import jwt
    except ImportError:
        print("ERROR: pip3 install PyJWT")
        sys.exit(1)
    return {
        "adm_std":   jwt.encode({"department": "Administración", "role": "dept_standard"}, JWT_SECRET, algorithm="HS256"),
        "adm_high":  jwt.encode({"department": "Administración", "role": "dept_high"},     JWT_SECRET, algorithm="HS256"),
        "rrhh_std":  jwt.encode({"department": "RRHH",           "role": "dept_standard"}, JWT_SECRET, algorithm="HS256"),
        "rrhh_high": jwt.encode({"department": "RRHH",           "role": "dept_high"},     JWT_SECRET, algorithm="HS256"),
        "admin":     jwt.encode({"department": "Administración", "role": "admin"},          JWT_SECRET, algorithm="HS256"),
    }

# Solo las 20 preguntas originales (bloques A-E) con respuesta factual
GOLDEN_SET = [
    {"id": "GS-01", "bloque": "A-ADM-std", "q": "¿Cuál es la cuantía máxima autorizada para alojamiento en viajes?",
     "token_key": "adm_std", "expected": "110 EUR por noche"},
    {"id": "GS-02", "bloque": "A-ADM-std", "q": "¿Cuál es la dieta máxima diaria para viajes internacionales?",
     "token_key": "adm_std", "expected": "75 EUR"},
    {"id": "GS-03", "bloque": "A-ADM-std", "q": "¿Cuántos días de antelación mínima se requieren para solicitar vacaciones?",
     "token_key": "adm_std", "expected": "15 días de antelación"},
    {"id": "GS-04", "bloque": "A-ADM-std", "q": "¿Cuál es el periodo mínimo de días consecutivos en vacaciones fraccionadas?",
     "token_key": "adm_std", "expected": "5 días laborables consecutivos"},
    {"id": "GS-05", "bloque": "B-ADM-high", "q": "¿Cuál es el valor de los activos corrientes en el cierre Q1 2026?",
     "token_key": "adm_high", "expected": "450.000 EUR"},
    {"id": "GS-06", "bloque": "B-ADM-high", "q": "¿Cuánto se ha invertido en proyectos de IA locales?",
     "token_key": "adm_high", "expected": "85.000 EUR"},
    {"id": "GS-07", "bloque": "B-ADM-high", "q": "¿Cuál es el fondo de reserva para contingencias de ciberseguridad?",
     "token_key": "adm_high", "expected": "50.000 EUR"},
    {"id": "GS-08", "bloque": "B-ADM-high", "q": "¿Cuál es el umbral crítico de tiempo de búsqueda vectorial definido en el plan estratégico?",
     "token_key": "adm_high", "expected": "50 milisegundos por query"},
    {"id": "GS-09", "bloque": "C-RRHH-std", "q": "¿Cuáles son los valores principales de la organización según el manual de bienvenida?",
     "token_key": "rrhh_std", "expected": "Soberanía del dato, excelencia académica e innovación en IA"},
    {"id": "GS-10", "bloque": "C-RRHH-std", "q": "¿A través de qué canal puede un empleado nuevo canalizar sus dudas iniciales?",
     "token_key": "rrhh_std", "expected": "Oficina virtual de RRHH o correo institucional interno"},
    {"id": "GS-11", "bloque": "C-RRHH-std", "q": "¿Con qué frecuencia deben entregarse los partes de confirmación durante una baja?",
     "token_key": "rrhh_std", "expected": "Cada 7 días"},
    {"id": "GS-12", "bloque": "C-RRHH-std", "q": "¿En qué plazo debe notificarse una baja laboral?",
     "token_key": "rrhh_std", "expected": "Máximo 24 horas desde la emisión del parte médico"},
    {"id": "GS-13", "bloque": "D-RRHH-high", "q": "¿Cuál es la banda salarial de un Investigador Principal?",
     "token_key": "rrhh_high", "expected": "55.000 EUR - 75.000 EUR"},
    {"id": "GS-14", "bloque": "D-RRHH-high", "q": "¿Cuál es la banda salarial de un Ingeniero de Software Senior?",
     "token_key": "rrhh_high", "expected": "42.000 EUR - 54.000 EUR"},
    {"id": "GS-15", "bloque": "D-RRHH-high", "q": "¿Cuándo se realizan las revisiones salariales?",
     "token_key": "rrhh_high", "expected": "Cada mes de diciembre"},
    {"id": "GS-16", "bloque": "D-RRHH-high", "q": "¿A partir de qué día asume la Seguridad Social el pago directo en una baja?",
     "token_key": "rrhh_high", "expected": "A partir del día 21"},
    {"id": "GS-17", "bloque": "E-admin", "q": "¿Cuál es la dieta máxima diaria nacional para viajes?",
     "token_key": "admin", "expected": "45 EUR"},
    {"id": "GS-18", "bloque": "E-admin", "q": "¿Cuál es la banda salarial de un Ingeniero de Datos Junior?",
     "token_key": "admin", "expected": "28.000 EUR - 38.000 EUR"},
    {"id": "GS-19", "bloque": "E-admin", "q": "¿Qué parámetros HNSW se usan en el índice vectorial según el plan estratégico?",
     "token_key": "admin", "expected": "m=16 y ef_construction=64"},
    {"id": "GS-20", "bloque": "E-admin", "q": "¿Qué porcentaje de la base reguladora abona la empresa entre el día 4 y 20 de una baja?",
     "token_key": "admin", "expected": "60% de la base reguladora"},
]

def db_exec(sql):
    result = subprocess.run(DB_CMD + [sql], capture_output=True, text=True)
    return result.stdout.strip()

def set_param(key, value):
    db_exec(f"UPDATE rag_config SET value='{value}', updated_at=NOW() WHERE key='{key}';")
    time.sleep(2)
    return db_exec(f"SELECT value FROM rag_config WHERE key='{key}';") == value

def ask_question(token, question):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        r = requests.post(f"{API_BASE}/api/v1/chat/stream", json={"question": question},
                          headers=headers, stream=True, timeout=TIMEOUT)
        if r.status_code != 200:
            try: return None, r.json().get("error", f"HTTP {r.status_code}")
            except: return None, f"HTTP {r.status_code}"

        metadata, full_response = None, ""
        for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
            if not chunk: continue
            for event_block in chunk.strip().split("\n\n"):
                lines = event_block.strip().split("\n")
                evt = data = None
                for line in lines:
                    if line.startswith("event:"): evt = line[6:].strip()
                    elif line.startswith("data:"): data = line[5:].strip()
                if not data: continue
                if evt == "metadata":
                    try: metadata = json.loads(data)
                    except: pass
                elif evt == "message":
                    if data == "[DONE]": continue
                    try: full_response += json.loads(data).get("token", "")
                    except: pass
        return metadata, full_response.strip() if full_response.strip() else "(respuesta vacía)"
    except requests.exceptions.Timeout: return None, f"TIMEOUT ({TIMEOUT}s)"
    except Exception as e: return None, f"ERROR: {str(e)[:150]}"

def wait_for_evaluations(target, max_wait=600):
    print(f"\n  Esperando evaluaciones del audit_worker", end="", flush=True)
    start = time.time()
    count = "0"
    while time.time() - start < max_wait:
        count = db_exec("SELECT COUNT(*) FROM trulens_evaluations;")
        try:
            if int(count) >= target:
                print(f" ✓ ({count}/{target})")
                return True
        except: pass
        print(".", end="", flush=True)
        time.sleep(20)
    print(f" ⚠ timeout ({count}/{target})")
    return False

def run_param_round(round_info, tokens, all_results, eval_offset):
    tag = round_info["tag"]
    param = round_info["param"]
    value = round_info["value"]
    baseline = round_info["baseline"]
    desc = round_info["desc"]

    ronda_start = datetime.now()
    print(f"\n{'▓'*70}")
    print(f"  RONDA: {tag}")
    print(f"  Parámetro: {param} = {baseline} → {value}")
    print(f"  Modelo: {MODEL} (fijo)")
    print(f"  Hipótesis: {desc}")
    print(f"  Inicio: {ronda_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'▓'*70}\n")

    # Asegurar modelo correcto
    if not set_param("model", MODEL):
        print(f"  ERROR: No se pudo configurar modelo {MODEL}")
        return

    # Cambiar el parámetro bajo test
    if not set_param(param, value):
        print(f"  ERROR: No se pudo configurar {param}={value}")
        return

    # Mostrar config activa
    config = db_exec("SELECT key || '=' || value FROM rag_config ORDER BY key;")
    print(f"  Config activa:")
    for line in config.split("\n"):
        marker = " ◄" if param in line else ""
        print(f"    {line}{marker}")
    print()

    # Registrar timestamp de inicio para poder filtrar después
    ts_start = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    results = []
    ok = denied = empty = errs = 0
    current_bloque = None

    for i, item in enumerate(GOLDEN_SET):
        if item["bloque"] != current_bloque:
            current_bloque = item["bloque"]
            print(f"\n{'─'*60}")
            print(f"  {current_bloque}")
            print(f"{'─'*60}\n")

        q_start = datetime.now()
        print(f"  [{item['id']}] {item['q'][:60]}...")
        sys.stdout.flush()

        metadata, response = ask_question(tokens[item["token_key"]], item["q"])
        elapsed = (datetime.now() - q_start).total_seconds()

        if response.startswith("ERROR") or response.startswith("TIMEOUT"):
            status, errs = "error", errs + 1
            print(f"      ✗ {response} ({elapsed:.0f}s)")
        elif response == "Operación denegada":
            status, denied = "rls_denied", denied + 1
            print(f"      ⊘ RLS denegado ({elapsed:.0f}s)")
        elif response == "(respuesta vacía)":
            status, empty = "empty", empty + 1
            print(f"      ○ Vacía ({elapsed:.0f}s)")
        else:
            status, ok = "ok", ok + 1
            print(f"      ✓ {response[:100].replace(chr(10),' ')}... ({elapsed:.0f}s)")

        if metadata and isinstance(metadata, list):
            print(f"      Chunks: {len(metadata)}")

        results.append({
            "id": item["id"], "bloque": item["bloque"],
            "question": item["q"], "expected": item["expected"],
            "response": response, "metadata": metadata,
            "elapsed_seconds": round(elapsed, 1), "status": status,
            "model": MODEL, "ronda": tag,
            "param_changed": param, "param_value": value,
            "chunks_count": len(metadata) if metadata and isinstance(metadata, list) else 0
        })
        if i < len(GOLDEN_SET) - 1: time.sleep(2)

    ts_end = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ronda_min = (datetime.now() - ronda_start).total_seconds() / 60

    print(f"\n{'─'*60}")
    print(f"  {tag} completada en {ronda_min:.1f} min")
    print(f"  OK: {ok} | Denegadas: {denied} | Vacías: {empty} | Errores: {errs}")
    print(f"  Ventana temporal: {ts_start} → {ts_end}")
    print(f"{'─'*60}")

    # Restaurar parámetro al baseline
    print(f"\n  Restaurando {param} = {baseline}...")
    set_param(param, baseline)
    print(f"  ✓ Restaurado")

    # Esperar evaluaciones
    wait_for_evaluations(eval_offset + len(GOLDEN_SET))

    # Consultar métricas de esta ronda por ventana temporal
    metrics = db_exec(f"""
        SELECT
            ROUND(AVG(te.context_relevance)::numeric, 3) AS cr,
            ROUND(AVG(te.groundedness)::numeric, 3) AS gr,
            ROUND(AVG(te.answer_relevance)::numeric, 3) AS ar,
            SUM(CASE WHEN te.requires_review THEN 1 ELSE 0 END) AS rev
        FROM audit_logs al
        JOIN trulens_evaluations te ON al.log_id = te.log_id
        WHERE al.timestamp >= '{ts_start}'::timestamp
          AND al.timestamp <= '{ts_end}'::timestamp + interval '1 minute';
    """)
    if metrics and "|" in metrics:
        parts = metrics.split("|")
        print(f"\n  Métricas {tag}: CR={parts[0].strip()} GR={parts[1].strip()} AR={parts[2].strip()} Review={parts[3].strip()}")

    all_results.extend(results)
    return results

def main():
    only_round = None
    if "--only" in sys.argv:
        idx = sys.argv.index("--only") + 1
        if idx < len(sys.argv): only_round = sys.argv[idx]

    rounds_to_run = [r for r in PARAM_ROUNDS if only_round in r["tag"]] if only_round else PARAM_ROUNDS
    if only_round and not rounds_to_run:
        print(f"ERROR: Ronda '{only_round}' no encontrada.")
        sys.exit(1)

    global_start = datetime.now()
    existing_evals = int(db_exec("SELECT COUNT(*) FROM trulens_evaluations;") or "0")

    print(f"{'═'*70}")
    print(f"  GOLDEN SET — TUNING DE PARÁMETROS RAG")
    print(f"  Modelo fijo: {MODEL}")
    print(f"  Preguntas por ronda: {len(GOLDEN_SET)}")
    print(f"  Rondas: {', '.join(r['tag'] for r in rounds_to_run)}")
    print(f"  Evaluaciones previas en BD: {existing_evals}")
    print(f"  Inicio: {global_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═'*70}\n")

    print("Generando tokens JWT...")
    tokens = generate_tokens()
    for name in tokens: print(f"  ✓ {name}")
    print()

    all_results = []
    for i, round_info in enumerate(rounds_to_run):
        eval_target = existing_evals + (i + 1) * len(GOLDEN_SET)
        run_param_round(round_info, tokens, all_results, eval_target)
        if i < len(rounds_to_run) - 1:
            print(f"\n  ⏳ Pausa de 15s antes de la siguiente ronda...")
            time.sleep(15)

    # Guardar resultados
    output_file = f"golden_set_params_{global_start.strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    global_min = (datetime.now() - global_start).total_seconds() / 60

    print(f"\n{'═'*70}")
    print(f"  TUNING COMPLETADO")
    print(f"  Duración: {global_min:.1f} minutos")
    print(f"  Archivo: {output_file}")
    print(f"{'═'*70}\n")

    # Comparativa final: baseline R1 vs las 4 rondas de tuning
    print("  Comparativa Baseline vs Tuning:\n")
    comp = db_exec("""
        WITH ranked AS (
            SELECT
                al.log_id,
                al.timestamp,
                te.context_relevance,
                te.groundedness,
                te.answer_relevance,
                te.requires_review
            FROM audit_logs al
            JOIN trulens_evaluations te ON al.log_id = te.log_id
            WHERE al.model_used = 'llama3.1:8b'
            ORDER BY al.timestamp
        )
        SELECT
            CASE
                WHEN rn <= 28 THEN 'R1-Base (top_k=6)'
                ELSE 'R4-R7 (tuning)'
            END AS grupo,
            COUNT(*) AS trazas,
            ROUND(AVG(context_relevance)::numeric, 3) AS cr,
            ROUND(AVG(groundedness)::numeric, 3) AS gr,
            ROUND(AVG(answer_relevance)::numeric, 3) AS ar,
            SUM(CASE WHEN requires_review THEN 1 ELSE 0 END) AS rev
        FROM (SELECT *, ROW_NUMBER() OVER (ORDER BY log_id) AS rn FROM ranked) sub
        GROUP BY CASE WHEN rn <= 28 THEN 'R1-Base (top_k=6)' ELSE 'R4-R7 (tuning)' END
        ORDER BY grupo;
    """)
    if comp:
        print(f"  {'Grupo':<25} {'Trazas':>7} {'CR':>8} {'GR':>8} {'AR':>8} {'Rev':>5}")
        print(f"  {'─'*60}")
        for line in comp.split("\n"):
            parts = line.split("|")
            if len(parts) >= 6:
                print(f"  {parts[0].strip():<25} {parts[1].strip():>7} {parts[2].strip():>8} {parts[3].strip():>8} {parts[4].strip():>8} {parts[5].strip():>5}")

    print(f"\n  Para comparativa detallada por ronda de tuning:")
    print(f"  Consulta las métricas por ventana temporal en audit_dump.sh")

if __name__ == "__main__":
    main()
