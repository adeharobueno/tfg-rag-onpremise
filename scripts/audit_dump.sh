#!/bin/bash
# =============================================================================
# AUDIT DUMP — Recopila toda la info necesaria para auditoría del TFG
# Uso: bash audit_dump.sh
# Genera: ~/tfg_project/scripts/audit_dump_output.txt
# =============================================================================

OUT=~/tfg_project/scripts/audit_dump_output.txt
echo "" > $OUT

sep() { echo "" >> $OUT; echo "================================================================================" >> $OUT; echo "### $1" >> $OUT; echo "================================================================================" >> $OUT; }

# --- FICHEROS DE CÓDIGO ---
sep "app.py — Streamlit GUI"
cat ~/tfg_project/streamlit_gui/app.py >> $OUT

sep "main.py — API Gateway"
cat ~/tfg_project/api/app/main.py >> $OUT

sep "evaluator.py — Audit Worker"
cat ~/tfg_project/audit_worker/app/evaluator.py >> $OUT

sep "docker-compose.yml"
cat ~/tfg_project/docker-compose.yml >> $OUT

# --- REQUIREMENTS ---
sep "requirements — API"
cat ~/tfg_project/api/requirements.txt >> $OUT 2>/dev/null || echo "No encontrado" >> $OUT

sep "requirements — Audit Worker"
cat ~/tfg_project/audit_worker/requirements.txt >> $OUT 2>/dev/null || echo "No encontrado" >> $OUT

sep "requirements — Streamlit"
cat ~/tfg_project/streamlit_gui/requirements.txt >> $OUT 2>/dev/null || echo "No encontrado" >> $OUT

# --- BASE DE DATOS ---
sep "BD — Tablas existentes"
docker exec postgres_db psql -U postgres -d tfg_rag_db -c "\dt" >> $OUT

sep "BD — Esquema completo columnas"
docker exec postgres_db psql -U postgres -d tfg_rag_db \
  -c "SELECT table_name, column_name, data_type, column_default, is_nullable FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name, ordinal_position;" >> $OUT

sep "BD — rag_config actual"
docker exec postgres_db psql -U postgres -d tfg_rag_db \
  -c "SELECT * FROM rag_config ORDER BY key;" >> $OUT

sep "BD — audit_logs muestra (últimas 5)"
docker exec postgres_db psql -U postgres -d tfg_rag_db \
  -c "SELECT log_id, timestamp, user_department, user_role, model_used, LEFT(question,60) as question, requires_review FROM audit_logs ORDER BY log_id DESC LIMIT 5;" >> $OUT

sep "BD — Distribución por modelo"
docker exec postgres_db psql -U postgres -d tfg_rag_db \
  -c "SELECT model_used, COUNT(*) as trazas FROM audit_logs GROUP BY model_used ORDER BY model_used;" >> $OUT

sep "BD — Métricas por modelo (join trulens)"
docker exec postgres_db psql -U postgres -d tfg_rag_db \
  -c "SELECT a.model_used, COUNT(*) as trazas, ROUND(AVG(te.context_relevance)::numeric,3) as CR_medio, ROUND(AVG(te.groundedness)::numeric,3) as GR_medio, ROUND(AVG(te.answer_relevance)::numeric,3) as AR_medio, ROUND(AVG(CASE WHEN te.requires_review THEN 1.0 ELSE 0.0 END)::numeric,3) as review_rate FROM audit_logs a LEFT JOIN trulens_evaluations te ON a.log_id=te.log_id GROUP BY a.model_used ORDER BY a.model_used;" >> $OUT

sep "BD — trulens_evaluations muestra (últimas 5)"
docker exec postgres_db psql -U postgres -d tfg_rag_db \
  -c "SELECT * FROM trulens_evaluations ORDER BY eval_id DESC LIMIT 5;" >> $OUT

sep "BD — Conteo evaluaciones pendientes (logs sin eval)"
docker exec postgres_db psql -U postgres -d tfg_rag_db \
  -c "SELECT COUNT(*) as logs_sin_evaluacion FROM audit_logs a LEFT JOIN trulens_evaluations te ON a.log_id=te.log_id WHERE te.eval_id IS NULL;" >> $OUT

# --- ESTADO CONTENEDORES ---
sep "Docker — Contenedores activos"
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}" >> $OUT

sep "Docker — Logs api_gateway (últimas 20 líneas)"
docker logs api_gateway_container --tail 20 >> $OUT 2>&1

sep "Docker — Logs audit_worker (últimas 20 líneas)"
docker logs audit_worker --tail 20 >> $OUT 2>&1

sep "Docker — Modelos Ollama disponibles"
docker exec ollama_engine ollama list >> $OUT 2>&1

# --- ESTRUCTURA DE FICHEROS ---
sep "Estructura del proyecto"
find ~/tfg_project -not -path "*/\.*" -not -path "*__pycache__*" -not -path "*/node_modules/*" | sort >> $OUT

# ---  Denegaciones RLS
sep "BD — rbac_denials (últimas 10)"
docker exec postgres_db psql -U postgres -d tfg_rag_db \
  -c "SELECT denial_id, username, user_role, endpoint, denial_reason, LEFT(detail,60) FROM rbac_denials ORDER BY timestamp DESC LIMIT 10;" >> $OUT

# --- Documentos expirados
sep "BD — Documentos expirados"
docker exec postgres_db psql -U postgres -d tfg_rag_db \
  -c "SELECT DISTINCT metadata->>'file_name' as archivo, valid_until, CASE WHEN valid_until < NOW() THEN 'EXPIRADO' ELSE 'VIGENTE' END as estado FROM document_sections WHERE valid_until IS NOT NULL;" >> $OUT

echo ""
echo "============================================================"
echo "DUMP COMPLETADO → $OUT"
echo "Tamaño: $(wc -l < $OUT) líneas / $(du -sh $OUT | cut -f1)"
echo "============================================================"
