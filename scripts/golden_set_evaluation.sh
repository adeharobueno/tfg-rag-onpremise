#!/bin/bash

# =============================================================================
# GOLDEN SET DE EVALUACIÓN RAG — TFG ETSIIT UGR
# Evaluación de 20 preguntas de referencia distribuidas por rol y departamento
# =============================================================================

API_URL="http://localhost:8000/api/v1/chat/stream"
JWT_SECRET="ETSIIT_UGR_SECRET_KEY_2026"
RESULTS_FILE=~/tfg_project/scripts/golden_set_results.json
LOG_FILE=~/tfg_project/scripts/golden_set_log.txt

# Limpiar ficheros anteriores
echo "[]" > $RESULTS_FILE
echo "" > $LOG_FILE

echo "============================================================"
echo "GOLDEN SET DE EVALUACIÓN RAG — $(date)"
echo "============================================================"

# Generar tokens JWT por rol
TOKEN_ADM_STD=$(python3 -c "import jwt; print(jwt.encode({'department': 'Administración', 'role': 'dept_standard'}, '$JWT_SECRET', algorithm='HS256'))")
TOKEN_ADM_HIGH=$(python3 -c "import jwt; print(jwt.encode({'department': 'Administración', 'role': 'dept_high'}, '$JWT_SECRET', algorithm='HS256'))")
TOKEN_RRHH_STD=$(python3 -c "import jwt; print(jwt.encode({'department': 'RRHH', 'role': 'dept_standard'}, '$JWT_SECRET', algorithm='HS256'))")
TOKEN_RRHH_HIGH=$(python3 -c "import jwt; print(jwt.encode({'department': 'RRHH', 'role': 'dept_high'}, '$JWT_SECRET', algorithm='HS256'))")
TOKEN_ADMIN=$(python3 -c "import jwt; print(jwt.encode({'department': 'Administración', 'role': 'admin'}, '$JWT_SECRET', algorithm='HS256'))")

# Función para ejecutar una pregunta y capturar respuesta
execute_question() {
    local ID=$1
    local QUESTION=$2
    local TOKEN=$3
    local EXPECTED=$4
    local ROLE=$5
    local DEPT=$6

    echo ""
    echo "------------------------------------------------------------"
    echo "[$ID] $QUESTION"
    echo "Rol: $ROLE | Dpto: $DEPT"
    echo "------------------------------------------------------------"

    # Capturar respuesta del stream SSE
    RESPONSE=$(curl -s -N -X POST "$API_URL" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $TOKEN" \
        -d "{\"question\": \"$QUESTION\"}" \
        --max-time 120 | grep "data:" | grep "token" | \
        python3 -c "
import sys, json
tokens = []
for line in sys.stdin:
    line = line.strip()
    if line.startswith('data:'):
        try:
            data = json.loads(line[6:])
            if 'token' in data:
                tokens.append(data['token'])
        except:
            pass
print(''.join(tokens))
")

    # Mostrar resultado
    echo "Respuesta: $RESPONSE"
    echo "Esperado:  $EXPECTED"

    # Guardar en log
    echo "[$ID] Q: $QUESTION" >> $LOG_FILE
    echo "[$ID] R: $RESPONSE" >> $LOG_FILE
    echo "[$ID] E: $EXPECTED" >> $LOG_FILE
    echo "" >> $LOG_FILE

    # Pequeña pausa para no saturar Ollama
    sleep 3
}

# =============================================================================
# BLOQUE A — Administración / dept_standard (Público + Interno)
# =============================================================================
echo ""
echo "BLOQUE A — Administración / dept_standard"
echo "============================================================"

execute_question "GS-01" \
    "¿Cuál es la cuantía máxima autorizada para alojamiento en viajes?" \
    "$TOKEN_ADM_STD" \
    "110 EUR por noche" \
    "dept_standard" "Administración"

execute_question "GS-02" \
    "¿Cuál es la dieta máxima diaria para viajes internacionales?" \
    "$TOKEN_ADM_STD" \
    "75 EUR" \
    "dept_standard" "Administración"

execute_question "GS-03" \
    "¿Cuántos días de antelación mínima se requieren para solicitar vacaciones?" \
    "$TOKEN_ADM_STD" \
    "15 días de antelación" \
    "dept_standard" "Administración"

execute_question "GS-04" \
    "¿Cuál es el periodo mínimo de días consecutivos en vacaciones fraccionadas?" \
    "$TOKEN_ADM_STD" \
    "5 días laborables consecutivos" \
    "dept_standard" "Administración"

# =============================================================================
# BLOQUE B — Administración / dept_high (Confidencial)
# =============================================================================
echo ""
echo "BLOQUE B — Administración / dept_high"
echo "============================================================"

execute_question "GS-05" \
    "¿Cuál es el valor de los activos corrientes en el cierre Q1 2026?" \
    "$TOKEN_ADM_HIGH" \
    "450.000 EUR" \
    "dept_high" "Administración"

execute_question "GS-06" \
    "¿Cuánto se ha invertido en proyectos de IA locales?" \
    "$TOKEN_ADM_HIGH" \
    "85.000 EUR" \
    "dept_high" "Administración"

execute_question "GS-07" \
    "¿Cuál es el fondo de reserva para contingencias de ciberseguridad?" \
    "$TOKEN_ADM_HIGH" \
    "50.000 EUR" \
    "dept_high" "Administración"

execute_question "GS-08" \
    "¿Cuál es el umbral crítico de tiempo de búsqueda vectorial definido en el plan estratégico?" \
    "$TOKEN_ADM_HIGH" \
    "50 milisegundos por query" \
    "dept_high" "Administración"

# =============================================================================
# BLOQUE C — RRHH / dept_standard (Público + Interno)
# =============================================================================
echo ""
echo "BLOQUE C — RRHH / dept_standard"
echo "============================================================"

execute_question "GS-09" \
    "¿Cuáles son los valores principales de la organización según el manual de bienvenida?" \
    "$TOKEN_RRHH_STD" \
    "Soberanía del dato, excelencia académica e innovación en IA" \
    "dept_standard" "RRHH"

execute_question "GS-10" \
    "¿A través de qué canal puede un empleado nuevo canalizar sus dudas iniciales?" \
    "$TOKEN_RRHH_STD" \
    "Oficina virtual de RRHH o correo institucional interno" \
    "dept_standard" "RRHH"

execute_question "GS-11" \
    "¿Con qué frecuencia deben entregarse los partes de confirmación durante una baja?" \
    "$TOKEN_RRHH_HIGH" \
    "Cada 7 días" \
    "dept_standard" "RRHH"

execute_question "GS-12" \
    "¿En qué plazo debe notificarse una baja laboral?" \
    "$TOKEN_RRHH_HIGH" \
    "Máximo 24 horas desde la emisión del parte médico" \
    "dept_standard" "RRHH"

# =============================================================================
# BLOQUE D — RRHH / dept_high (Confidencial)
# =============================================================================
echo ""
echo "BLOQUE D — RRHH / dept_high"
echo "============================================================"

execute_question "GS-13" \
    "¿Cuál es la banda salarial de un Investigador Principal?" \
    "$TOKEN_RRHH_HIGH" \
    "55.000 EUR - 75.000 EUR" \
    "dept_high" "RRHH"

execute_question "GS-14" \
    "¿Cuál es la banda salarial de un Ingeniero de Software Senior?" \
    "$TOKEN_RRHH_HIGH" \
    "42.000 EUR - 54.000 EUR" \
    "dept_high" "RRHH"

execute_question "GS-15" \
    "¿Cuándo se realizan las revisiones salariales?" \
    "$TOKEN_RRHH_HIGH" \
    "Cada mes de diciembre" \
    "dept_high" "RRHH"

execute_question "GS-16" \
    "¿A partir de qué día asume la Seguridad Social el pago directo en una baja?" \
    "$TOKEN_RRHH_HIGH" \
    "A partir del día 21" \
    "dept_high" "RRHH"

# =============================================================================
# BLOQUE E — admin (Transversal)
# =============================================================================
echo ""
echo "BLOQUE E — admin (transversal)"
echo "============================================================"

execute_question "GS-17" \
    "¿Cuál es la dieta máxima diaria nacional para viajes?" \
    "$TOKEN_ADMIN" \
    "45 EUR" \
    "admin" "Administración"

execute_question "GS-18" \
    "¿Cuál es la banda salarial de un Ingeniero de Datos Junior?" \
    "$TOKEN_ADMIN" \
    "28.000 EUR - 38.000 EUR" \
    "admin" "RRHH"

execute_question "GS-19" \
    "¿Qué parámetros HNSW se usan en el índice vectorial según el plan estratégico?" \
    "$TOKEN_ADMIN" \
    "m=16 y ef_construction=64" \
    "admin" "Administración"

execute_question "GS-20" \
    "¿Qué porcentaje de la base reguladora abona la empresa entre el día 4 y 20 de una baja?" \
    "$TOKEN_ADMIN" \
    "60% de la base reguladora" \
    "admin" "RRHH"

# =============================================================================
# RESUMEN FINAL
# =============================================================================
echo ""
echo "============================================================"
echo "EVALUACIÓN COMPLETADA — $(date)"
echo "Log guardado en: $LOG_FILE"
echo "============================================================"
echo ""
echo "Consultando métricas del audit_worker en PostgreSQL..."
sleep 10

docker exec postgres_db psql -U postgres -d tfg_rag_db -c "
SELECT 
    log_id,
    user_role,
    user_department,
    LEFT(question, 50) as pregunta,
    requires_review
FROM audit_logs
ORDER BY log_id DESC
LIMIT 20;"

