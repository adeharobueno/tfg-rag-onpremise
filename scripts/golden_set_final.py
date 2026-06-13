#!/usr/bin/env python3
"""
Golden Set Completo — TFG RAG On-Premise ETSIIT UGR
Ejecuta las 28 preguntas con los 3 modelos de forma secuencial,
conservando todas las trazas en BD para comparativa.

Uso:
  python3 golden_set_final.py              # Ejecuta los 3 modelos
  python3 golden_set_final.py --clean      # Limpia BD antes de empezar
  python3 golden_set_final.py --only 8b    # Solo un modelo (8b, 3b, qwen)
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

MODELS = [
    {"name": "llama3.1:8b",  "tag": "R1-llama31-8b",  "desc": "Baseline 8B (modelo de diseño)"},
    {"name": "llama3.2:3b",  "tag": "R2-llama32-3b",  "desc": "Modelo ligero 3B"},
    {"name": "qwen2.5:7b",   "tag": "R3-qwen25-7b",   "desc": "Evaluador como generador (sesgo)"},
]

def generate_tokens():
    try:
        import jwt
    except ImportError:
        print("ERROR: PyJWT no instalado. Ejecuta: pip3 install PyJWT")
        sys.exit(1)
    return {
        "adm_std":   jwt.encode({"department": "Administración", "role": "dept_standard"}, JWT_SECRET, algorithm="HS256"),
        "adm_high":  jwt.encode({"department": "Administración", "role": "dept_high"},     JWT_SECRET, algorithm="HS256"),
        "rrhh_std":  jwt.encode({"department": "RRHH",           "role": "dept_standard"}, JWT_SECRET, algorithm="HS256"),
        "rrhh_high": jwt.encode({"department": "RRHH",           "role": "dept_high"},     JWT_SECRET, algorithm="HS256"),
        "admin":     jwt.encode({"department": "Administración", "role": "admin"},          JWT_SECRET, algorithm="HS256"),
    }

GOLDEN_SET = [
    {"id": "GS-01", "bloque": "A-ADM-std", "q": "¿Cuál es la cuantía máxima autorizada para alojamiento en viajes?",
     "token_key": "adm_std", "role": "dept_standard", "dept": "Administración", "expected": "110 EUR por noche"},
    {"id": "GS-02", "bloque": "A-ADM-std", "q": "¿Cuál es la dieta máxima diaria para viajes internacionales?",
     "token_key": "adm_std", "role": "dept_standard", "dept": "Administración", "expected": "75 EUR"},
    {"id": "GS-03", "bloque": "A-ADM-std", "q": "¿Cuántos días de antelación mínima se requieren para solicitar vacaciones?",
     "token_key": "adm_std", "role": "dept_standard", "dept": "Administración", "expected": "15 días de antelación"},
    {"id": "GS-04", "bloque": "A-ADM-std", "q": "¿Cuál es el periodo mínimo de días consecutivos en vacaciones fraccionadas?",
     "token_key": "adm_std", "role": "dept_standard", "dept": "Administración", "expected": "5 días laborables consecutivos"},
    {"id": "GS-05", "bloque": "B-ADM-high", "q": "¿Cuál es el valor de los activos corrientes en el cierre Q1 2026?",
     "token_key": "adm_high", "role": "dept_high", "dept": "Administración", "expected": "450.000 EUR"},
    {"id": "GS-06", "bloque": "B-ADM-high", "q": "¿Cuánto se ha invertido en proyectos de IA locales?",
     "token_key": "adm_high", "role": "dept_high", "dept": "Administración", "expected": "85.000 EUR"},
    {"id": "GS-07", "bloque": "B-ADM-high", "q": "¿Cuál es el fondo de reserva para contingencias de ciberseguridad?",
     "token_key": "adm_high", "role": "dept_high", "dept": "Administración", "expected": "50.000 EUR"},
    {"id": "GS-08", "bloque": "B-ADM-high", "q": "¿Cuál es el umbral crítico de tiempo de búsqueda vectorial definido en el plan estratégico?",
     "token_key": "adm_high", "role": "dept_high", "dept": "Administración", "expected": "50 milisegundos por query"},
    {"id": "GS-09", "bloque": "C-RRHH-std", "q": "¿Cuáles son los valores principales de la organización según el manual de bienvenida?",
     "token_key": "rrhh_std", "role": "dept_standard", "dept": "RRHH", "expected": "Soberanía del dato, excelencia académica e innovación en IA"},
    {"id": "GS-10", "bloque": "C-RRHH-std", "q": "¿A través de qué canal puede un empleado nuevo canalizar sus dudas iniciales?",
     "token_key": "rrhh_std", "role": "dept_standard", "dept": "RRHH", "expected": "Oficina virtual de RRHH o correo institucional interno"},
    {"id": "GS-11", "bloque": "C-RRHH-std", "q": "¿Con qué frecuencia deben entregarse los partes de confirmación durante una baja?",
     "token_key": "rrhh_std", "role": "dept_standard", "dept": "RRHH", "expected": "Cada 7 días"},
    {"id": "GS-12", "bloque": "C-RRHH-std", "q": "¿En qué plazo debe notificarse una baja laboral?",
     "token_key": "rrhh_std", "role": "dept_standard", "dept": "RRHH", "expected": "Máximo 24 horas desde la emisión del parte médico"},
    {"id": "GS-13", "bloque": "D-RRHH-high", "q": "¿Cuál es la banda salarial de un Investigador Principal?",
     "token_key": "rrhh_high", "role": "dept_high", "dept": "RRHH", "expected": "55.000 EUR - 75.000 EUR"},
    {"id": "GS-14", "bloque": "D-RRHH-high", "q": "¿Cuál es la banda salarial de un Ingeniero de Software Senior?",
     "token_key": "rrhh_high", "role": "dept_high", "dept": "RRHH", "expected": "42.000 EUR - 54.000 EUR"},
    {"id": "GS-15", "bloque": "D-RRHH-high", "q": "¿Cuándo se realizan las revisiones salariales?",
     "token_key": "rrhh_high", "role": "dept_high", "dept": "RRHH", "expected": "Cada mes de diciembre"},
    {"id": "GS-16", "bloque": "D-RRHH-high", "q": "¿A partir de qué día asume la Seguridad Social el pago directo en una baja?",
     "token_key": "rrhh_high", "role": "dept_high", "dept": "RRHH", "expected": "A partir del día 21"},
    {"id": "GS-17", "bloque": "E-admin", "q": "¿Cuál es la dieta máxima diaria nacional para viajes?",
     "token_key": "admin", "role": "admin", "dept": "Administración", "expected": "45 EUR"},
    {"id": "GS-18", "bloque": "E-admin", "q": "¿Cuál es la banda salarial de un Ingeniero de Datos Junior?",
     "token_key": "admin", "role": "admin", "dept": "RRHH (cross-dpto)", "expected": "28.000 EUR - 38.000 EUR"},
    {"id": "GS-19", "bloque": "E-admin", "q": "¿Qué parámetros HNSW se usan en el índice vectorial según el plan estratégico?",
     "token_key": "admin", "role": "admin", "dept": "Administración", "expected": "m=16 y ef_construction=64"},
    {"id": "GS-20", "bloque": "E-admin", "q": "¿Qué porcentaje de la base reguladora abona la empresa entre el día 4 y 20 de una baja?",
     "token_key": "admin", "role": "admin", "dept": "RRHH (cross-dpto)", "expected": "60% de la base reguladora"},
    {"id": "GS-21", "bloque": "F-cross-dpto", "q": "¿Cuál es la banda salarial de un Investigador Principal?",
     "token_key": "adm_std", "role": "dept_standard", "dept": "ADM→RRHH", "expected": "RLS DENEGADO"},
    {"id": "GS-22", "bloque": "F-cross-dpto", "q": "¿Cuál es el fondo de reserva para contingencias de ciberseguridad?",
     "token_key": "rrhh_high", "role": "dept_high", "dept": "RRHH→ADM", "expected": "RLS DENEGADO"},
    {"id": "GS-23", "bloque": "G-expirado", "q": "¿Cuáles son las fechas del calendario fiscal?",
     "token_key": "admin", "role": "admin", "dept": "Administración", "expected": "SIN RESULTADO: doc expirado 2026-01-01"},
    {"id": "GS-24", "bloque": "G-vigente", "q": "¿Cuál es el protocolo de vacaciones vigente?",
     "token_key": "admin", "role": "admin", "dept": "Administración", "expected": "Respuesta válida (doc vigente hasta 2026-12-31)"},
    {"id": "GS-25", "bloque": "H-sin-respuesta", "q": "¿Cuál es la política de stock options de la empresa?",
     "token_key": "admin", "role": "admin", "dept": "N/A", "expected": "No debe alucinar"},
    {"id": "GS-26", "bloque": "H-sin-respuesta", "q": "¿Qué herramientas de IA usa el departamento de marketing?",
     "token_key": "rrhh_high", "role": "dept_high", "dept": "N/A", "expected": "No debe inventar departamentos"},
    {"id": "GS-27", "bloque": "I-confidencial", "q": "¿Cuál es el valor de los activos corrientes en el cierre Q1 2026?",
     "token_key": "adm_std", "role": "dept_standard", "dept": "Administración", "expected": "SIN RESULTADO: no ve Confidencial"},
    {"id": "GS-28", "bloque": "I-confidencial", "q": "¿Cuál es la banda salarial de un Investigador Principal?",
     "token_key": "rrhh_std", "role": "dept_standard", "dept": "RRHH", "expected": "SIN RESULTADO: no ve Confidencial"},
]

def db_exec(sql):
    result = subprocess.run(DB_CMD + [sql], capture_output=True, text=True)
    return result.stdout.strip()

def set_model(model):
    db_exec(f"UPDATE rag_config SET value='{model}', updated_at=NOW() WHERE key='model';")
    time.sleep(3)
    return db_exec("SELECT value FROM rag_config WHERE key='model';") == model

def clean_db():
    for t in ["trulens_evaluations", "rbac_denials"]:
        db_exec(f"TRUNCATE TABLE {t} RESTART IDENTITY;")
    db_exec("TRUNCATE TABLE audit_logs RESTART IDENTITY CASCADE;")

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

def wait_for_evaluations(expected, max_wait=300):
    print(f"\n  Esperando evaluaciones del audit_worker", end="", flush=True)
    start = time.time()
    count = "0"
    while time.time() - start < max_wait:
        count = db_exec("SELECT COUNT(*) FROM trulens_evaluations;")
        try:
            if int(count) >= expected:
                print(f" ✓ ({count}/{expected})")
                return True
        except: pass
        print(".", end="", flush=True)
        time.sleep(15)
    print(f" ⚠ timeout ({count}/{expected})")
    return False

def run_model(model_info, tokens, all_results, question_offset):
    model, tag, desc = model_info["name"], model_info["tag"], model_info["desc"]
    ronda_start = datetime.now()

    print(f"\n{'▓'*70}")
    print(f"  RONDA: {tag}")
    print(f"  Modelo: {model} — {desc}")
    print(f"  Inicio: {ronda_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'▓'*70}\n")

    if not set_model(model):
        print(f"  ERROR: No se pudo configurar {model}")
        return
    print(f"  ✓ Modelo configurado: {model}\n")

    results, current_bloque = [], None
    ok = denied = empty = errs = 0

    for i, item in enumerate(GOLDEN_SET):
        if item["bloque"] != current_bloque:
            current_bloque = item["bloque"]
            print(f"\n{'─'*70}")
            print(f"  BLOQUE {current_bloque} ({item['role']}, {item['dept']})")
            print(f"{'─'*70}\n")

        q_start = datetime.now()
        print(f"  [{item['id']}] {item['q']}")
        print(f"      Esperado: {item['expected']}")
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
            print(f"      ○ Respuesta vacía ({elapsed:.0f}s)")
        else:
            status, ok = "ok", ok + 1
            print(f"      ✓ {response[:150].replace(chr(10),' ')} ({elapsed:.0f}s)")

        if metadata and isinstance(metadata, list):
            for f in sorted(set(m.get("file_name","?") for m in metadata)):
                print(f"        → {f}")

        results.append({
            "id": item["id"], "bloque": item["bloque"],
            "question": item["q"], "expected": item["expected"],
            "response": response, "metadata": metadata,
            "role": item["role"], "dept": item["dept"],
            "elapsed_seconds": round(elapsed, 1), "status": status,
            "model": model, "ronda": tag
        })
        if i < len(GOLDEN_SET) - 1: time.sleep(2)

    ronda_min = (datetime.now() - ronda_start).total_seconds() / 60
    print(f"\n{'─'*70}")
    print(f"  Ronda {tag} completada en {ronda_min:.1f} min")
    print(f"  OK: {ok} | Denegadas: {denied} | Vacías: {empty} | Errores: {errs}")
    print(f"{'─'*70}")

    wait_for_evaluations(question_offset + len(GOLDEN_SET))
    all_results.extend(results)

def main():
    do_clean = "--clean" in sys.argv
    only_model = None
    if "--only" in sys.argv:
        idx = sys.argv.index("--only") + 1
        if idx < len(sys.argv): only_model = sys.argv[idx]

    models_to_run = [m for m in MODELS if only_model in m["name"] or only_model in m["tag"]] if only_model else MODELS
    if only_model and not models_to_run:
        print(f"ERROR: Modelo '{only_model}' no encontrado.")
        sys.exit(1)

    global_start = datetime.now()
    print(f"{'═'*70}")
    print(f"  GOLDEN SET COMPLETO — TFG RAG On-Premise")
    print(f"  Modelos: {', '.join(m['name'] for m in models_to_run)}")
    print(f"  Preguntas por modelo: {len(GOLDEN_SET)}")
    print(f"  Total: {len(GOLDEN_SET) * len(models_to_run)} preguntas")
    print(f"  Inicio: {global_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'═'*70}\n")

    if do_clean:
        print("Limpiando base de datos...")
        clean_db()
        print("  ✓ Base de datos limpia\n")
    else:
        print(f"  ℹ Conservando {db_exec('SELECT COUNT(*) FROM audit_logs;')} trazas existentes\n")

    print("Generando tokens JWT...")
    tokens = generate_tokens()
    for name in tokens: print(f"  ✓ {name}")
    print()

    all_results = []
    for i, model_info in enumerate(models_to_run):
        run_model(model_info, tokens, all_results, i * len(GOLDEN_SET))
        if i < len(models_to_run) - 1:
            print(f"\n  ⏳ Pausa de 30s antes del siguiente modelo...")
            time.sleep(30)

    output_file = f"golden_set_completo_{global_start.strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    global_min = (datetime.now() - global_start).total_seconds() / 60

    print(f"\n{'═'*70}")
    print(f"  EVALUACIÓN COMPLETA")
    print(f"  Duración total: {global_min:.1f} minutos")
    print(f"  Archivo: {output_file}")
    print(f"{'═'*70}\n")

    print("  Comparativa de la Tríada RAG:\n")
    comp = db_exec("""
        SELECT al.model_used, COUNT(*),
            ROUND(AVG(te.context_relevance)::numeric,3),
            ROUND(AVG(te.groundedness)::numeric,3),
            ROUND(AVG(te.answer_relevance)::numeric,3),
            SUM(CASE WHEN te.requires_review THEN 1 ELSE 0 END)
        FROM audit_logs al
        JOIN trulens_evaluations te ON al.log_id = te.log_id
        GROUP BY al.model_used ORDER BY al.model_used;
    """)
    if comp:
        print(f"  {'Modelo':<20} {'Trazas':>7} {'Ctx_Rel':>8} {'Ground':>8} {'Ans_Rel':>8} {'Review':>7}")
        print(f"  {'─'*60}")
        for line in comp.split("\n"):
            parts = line.split("|")
            if len(parts) >= 6:
                print(f"  {parts[0].strip():<20} {parts[1].strip():>7} {parts[2].strip():>8} {parts[3].strip():>8} {parts[4].strip():>8} {parts[5].strip():>7}")
    else:
        print("  ⚠ Evaluaciones pendientes. Consulta manualmente en unos minutos.")

if __name__ == "__main__":
    main()
