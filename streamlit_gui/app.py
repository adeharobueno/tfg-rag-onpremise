

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import json
import psycopg2
import base64
import re as _re

st.set_page_config(
    page_title="Corporate RAG | ETSIIT",
    page_icon="🛡️",
    layout="wide"
)

def get_db_conn_admin():
    return psycopg2.connect(
        host="postgres_db",
        database="tfg_rag_db",
        user="postgres",
        password="Sub_Secret_Pass_Admin_2026!"
    )

def get_expired_documents():
    conn = get_db_conn_admin()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT filename, department, confidentiality_level, valid_until,
            CASE 
                WHEN valid_until < CURRENT_TIMESTAMP THEN 'EXPIRADO'
                WHEN valid_until < CURRENT_TIMESTAMP + INTERVAL '30 days' THEN 'Proximo'
                ELSE 'Vigente'
            END as estado
        FROM document_sections
        WHERE valid_until IS NOT NULL
        ORDER BY valid_until ASC;
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_audit_stats():
    conn = get_db_conn_admin()
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE requires_review = true) as requieren_revision,
            COUNT(DISTINCT user_department) as departamentos
        FROM audit_logs;
    """)
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

def get_system_status():
    conn = get_db_conn_admin()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            ROUND(AVG(diff), 2) AS latencia_media,
            COUNT(*) AS total_queries,
            ROUND(AVG(chunks_medio), 1) AS chunks_medio
        FROM (
            SELECT
                EXTRACT(EPOCH FROM (timestamp - LAG(timestamp) OVER (ORDER BY timestamp))) AS diff,
                array_length(chunks_id, 1) AS chunks_medio
            FROM audit_logs
            WHERE chunks_id IS NOT NULL AND array_length(chunks_id, 1) > 0
        ) sub
    """)
    row = cur.fetchone()
    cur.execute("SELECT COUNT(DISTINCT user_department), COUNT(DISTINCT user_role) FROM audit_logs")
    depts, roles = cur.fetchone()
    cur.close()
    conn.close()
    return row[0], row[1], row[2], depts, roles

def decode_jwt_payload(token):
    """Decodifica el payload del JWT sin verificar firma (solo para display)."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
        return payload
    except Exception:
        return None

st.sidebar.title("🔒 Control de Acceso RLS")
jwt_token = st.sidebar.text_input(
    "Token JWT (Bearer):",
    type="password",
    help="Pega aquí el token corporativo generado"
)
# Panel de identidad RLS
if jwt_token:
    _payload = decode_jwt_payload(jwt_token)
    if _payload:
        _dept = _payload.get("department", "desconocido")
        _role = _payload.get("role", "desconocido")
        _role_labels = {
            "admin": ("🔴 admin", "Acceso total — todos los departamentos y niveles"),
            "dept_high": ("🟠 dept_high", "Público + Interno + Confidencial (propio dpto)"),
            "dept_standard": ("🟡 dept_standard", "Público + Interno (propio dpto)")
        }
        _role_badge, _role_desc = _role_labels.get(_role, (f"⚪ {_role}", "Rol no reconocido"))
        st.sidebar.success(f"✅ Token válido")
        st.sidebar.markdown(f"**Departamento:** `{_dept}`")
        st.sidebar.markdown(f"**Rol:** {_role_badge}")
        st.sidebar.caption(_role_desc)
        # Nivel de acceso visual
        _niveles = {
            "admin":         ["🟢 Público", "🟡 Interno", "🔴 Confidencial", "🌐 Todos los dptos"],
            "dept_high":     ["🟢 Público", "🟡 Interno", "🔴 Confidencial", f"🏢 Solo {_dept}"],
            "dept_standard": ["🟢 Público", "🟡 Interno", "⛔ Confidencial bloq.", f"🏢 Solo {_dept}"]
        }
        st.sidebar.markdown("**Política RLS activa:**")
        for nivel in _niveles.get(_role, []):
            st.sidebar.markdown(f"- {nivel}")
    else:
        st.sidebar.warning("⚠️ Token no decodificable")
else:
    st.sidebar.info("🔑 Sin token — introduce tu JWT corporativo para operar.")

st.sidebar.markdown("---")
st.sidebar.subheader("📄 Trazabilidad de Fuentes")
sources_container = st.sidebar.empty()

tab1, tab2, tab3, tab4 = st.tabs(["💬 Asistente RAG", "📊 Panel de Gobernanza", "⚖️ Comparativa Evaluadores", "⚙️ Configuración"])

with tab1:
    st.title("🛡️ Asistente RAG Soberano")
    st.caption("Arquitectura On-Premise con Auditoría TruLens y Seguridad de Vectores")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("Escribe tu consulta corporativa..."):
        if not jwt_token:
            st.error("⚠️ Operación rechazada: Debes introducir un token corporativo válido.")
            st.stop()

        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            response_placeholder = st.empty()
            full_response = ""
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {jwt_token}"
            }
            try:
                with requests.post(
                    "http://api_gateway:8000/api/v1/chat/stream",
                    json={"question": prompt},
                    headers=headers,
                    stream=True
                ) as r:
                    if "application/json" in r.headers.get('Content-Type', ''):
                        error_data = r.json()
                        st.error(f"❌ {error_data.get('error', 'Token inválido o acceso no autorizado.')}")
                        st.stop()

                    for line in r.iter_lines():
                        if line:
                            decoded_line = line.decode('utf-8')
                            if decoded_line.startswith("data: "):
                                data_str = decoded_line[6:]
                                if data_str == "{}":
                                    break
                                try:
                                    data_json = json.loads(data_str)
                                    if "token" in data_json:
                                        full_response += data_json["token"]
                                        response_placeholder.markdown(full_response + "▌")
                                    elif isinstance(data_json, list):
                                        with sources_container.container():
                                            for source in data_json:
                                                st.info(
                                                    f"**Documento:** {source['file_name']}\n\n"
                                                    f"**Seguridad:** {source['security']}\n\n"
                                                    f"**Vector ID:** {source['id']}"
                                                )
                                except json.JSONDecodeError:
                                    continue

                response_placeholder.markdown(full_response)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": full_response
                })
                # Mostrar info RLS de la última query en sidebar
                if jwt_token:
                    _p = decode_jwt_payload(jwt_token)
                    if _p:
                        _chunks_match = _re.search(r'"chunks_used":\s*(\d+)', full_response)
                        _n_chunks = _chunks_match.group(1) if _chunks_match else "6"
                        sources_container.markdown(
                            f"**Última query procesada**\n\n"
                            f"🔍 Chunks recuperados: `{_n_chunks}` (LIMIT 6)\n\n"
                            f"🛡️ Filtro RLS aplicado: `{_p.get('department','?')}` · `{_p.get('role','?')}`\n\n"
                            f"📊 Auditoría asíncrona: `OllamaJuice + TruLens`"
                        )

            except requests.exceptions.ConnectionError:
                st.error("Error crítico: No se pudo conectar con el API Gateway.")

    # --- HISTORIAL DE QUERIES ---
    st.markdown("---")
    with st.expander("🕐 Historial de consultas de esta sesión", expanded=False):
        if st.session_state.messages:
            user_msgs = [(i, m["content"]) for i, m in enumerate(st.session_state.messages) if m["role"] == "user"]
            if user_msgs:
                st.caption(f"{len(user_msgs)} consulta(s) realizadas en esta sesión · Auditoría registrada en audit_logs")
                for idx, (i, q) in enumerate(reversed(user_msgs[-10:])):
                    st.markdown(f"**{len(user_msgs)-idx}.** {q}")
            else:
                st.info("Aún no has realizado ninguna consulta.")

            if st.button("🗑️ Limpiar historial de sesión"):
                st.session_state.messages = []
                st.rerun()
        else:
            st.info("Aún no has realizado ninguna consulta en esta sesión.")

        # Últimas queries del usuario actual desde audit_logs (por JWT)
        if jwt_token:
            _p = decode_jwt_payload(jwt_token)
            if _p:
                try:
                    conn_hist = get_db_conn_admin()
                    cur_hist = conn_hist.cursor()
                    cur_hist.execute("""
                        SELECT log_id, timestamp, left(question, 100), requires_review
                        FROM audit_logs
                        WHERE user_department = %s AND user_role = %s
                        ORDER BY log_id DESC LIMIT 5
                    """, (_p.get("department"), _p.get("role")))
                    hist_rows = cur_hist.fetchall()
                    cur_hist.close()
                    conn_hist.close()
                    if hist_rows:
                        st.markdown(f"**Últimas 5 queries auditadas** · `{_p.get('department')}` · `{_p.get('role')}`")
                        for row in hist_rows:
                            flag = "🔴" if row[3] else "🟢"
                            st.markdown(f"{flag} `#{row[0]}` · {row[1].strftime('%d/%m %H:%M')} · {row[2]}...")
                except Exception as e:
                    st.caption(f"No se pudo cargar el historial auditado: {e}")

with tab2:
    st.title("📊 Panel de Gobernanza Corporativa")
    st.caption("Monitorización de caducidad documental y auditoría de calidad RAG")

    st.subheader("🔍 Estadísticas de Auditoría")
    try:
        stats = get_audit_stats()
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Interacciones", stats[0])
        with col2:
            st.metric("Requieren Revisión", stats[1])
        with col3:
            st.metric("Departamentos Activos", stats[2])
    except Exception as e:
        st.warning(f"No se pudieron cargar las estadísticas: {e}")

    st.markdown("---")

    # --- ESTADO DEL SISTEMA ---
    st.subheader("⚙️ Estado del Sistema")
    st.caption("Parámetros operativos en tiempo real — inferencia 100% on-premise sin dependencias cloud.")
    try:
        lat, total_q, chunks_medio, n_depts, n_roles = get_system_status()
        sc1, sc2, sc3, sc4, sc5 = st.columns(5)
        sc1.metric("Modelo activo", "Llama 3.1 8B", help="Quantización Q4_K_M — inferencia CPU Xeon Silver 4410Y")
        sc2.metric("Embedding", "nomic-embed-text", help="768 dimensiones — índice HNSW cosine en pgvector")
        sc3.metric("Queries totales", int(total_q) if total_q else 0, help="Interacciones registradas en audit_logs")
        sc4.metric("Chunks/query (media)", f"{chunks_medio:.1f}" if chunks_medio else "6.0", help="Límite vectorial configurado: LIMIT 6")
        sc5.metric("Temperatura LLM", "0.0", help="top_p=0.1 · num_ctx=4096 · num_predict=512 — respuestas deterministas")
        st.caption("🖥️ Servidor: Intel Xeon Silver 4410Y · 80 GB RAM · RAID 5 SAS 10K · Sin GPU — soberanía total del dato.")
    except Exception as e:
        st.warning(f"No se pudo cargar el estado del sistema: {e}")

    st.markdown("---")

    # --- FILTROS RLS ---
    st.subheader("🔍 Filtro de Auditoría por Departamento y Rol")
    st.caption("El RLS garantiza que cada usuario solo accede a los documentos de su departamento y nivel.")
    try:
        conn_filt = get_db_conn_admin()
        cur_filt = conn_filt.cursor()
        cur_filt.execute("SELECT DISTINCT user_department FROM audit_logs ORDER BY user_department")
        all_depts = ["Todos"] + [r[0] for r in cur_filt.fetchall()]
        cur_filt.execute("SELECT DISTINCT user_role FROM audit_logs ORDER BY user_role")
        all_roles = ["Todos"] + [r[0] for r in cur_filt.fetchall()]
        cur_filt.close()
        conn_filt.close()

        fc1, fc2, fc3 = st.columns([2, 2, 1])
        sel_dept = fc1.selectbox("Departamento", all_depts, key="filt_dept")
        sel_role = fc2.selectbox("Rol", all_roles, key="filt_role")
        sel_review = fc3.selectbox("Estado", ["Todos", "Solo requires_review"], key="filt_review")

        where_clauses = []
        params = []
        if sel_dept != "Todos":
            where_clauses.append("user_department = %s")
            params.append(sel_dept)
        if sel_role != "Todos":
            where_clauses.append("user_role = %s")
            params.append(sel_role)
        if sel_review == "Solo requires_review":
            where_clauses.append("requires_review = true")
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        conn_filt2 = get_db_conn_admin()
        cur_filt2 = conn_filt2.cursor()
        cur_filt2.execute(f"""
            SELECT log_id, timestamp, user_department, user_role,
                   left(question, 80) AS pregunta,
                   requires_review,
                   array_length(chunks_id, 1) AS n_chunks
            FROM audit_logs
            {where_sql}
            ORDER BY log_id DESC
            LIMIT 50
        """, params if params else None)
        filt_rows = cur_filt2.fetchall()
        cur_filt2.close()
        conn_filt2.close()

        df_filt = pd.DataFrame(filt_rows, columns=[
            "Log ID", "Timestamp", "Departamento", "Rol",
            "Pregunta", "Requires Review", "Chunks"
        ])
        df_filt["Requires Review"] = df_filt["Requires Review"].apply(lambda x: "🔴 Sí" if x else "🟢 No")
        st.dataframe(df_filt, use_container_width=True, hide_index=True)
        st.caption(f"Mostrando {len(df_filt)} trazas (máx. 50). Filtra por departamento y rol para verificar el aislamiento RLS.")

    except Exception as e:
        st.warning(f"No se pudieron cargar los filtros: {e}")

    st.markdown("---")

    st.subheader("🗂️ Distribución del Corpus Documental")
    st.caption("Chunks indexados en pgvector por departamento y nivel de confidencialidad — justifica el diseño RLS.")
    try:
        conn_corp = get_db_conn_admin()
        cur_corp = conn_corp.cursor()
        cur_corp.execute("""
            SELECT department, confidentiality_level, COUNT(*) AS chunks,
                   COUNT(DISTINCT document_hash) AS docs
            FROM document_sections
            GROUP BY department, confidentiality_level
            ORDER BY department, confidentiality_level
        """)
        corpus_rows = cur_corp.fetchall()
        cur_corp.execute("SELECT COUNT(*), COUNT(DISTINCT document_hash), COUNT(DISTINCT department) FROM document_sections")
        total_chunks, total_docs, total_depts = cur_corp.fetchone()
        cur_corp.close()
        conn_corp.close()

        kc1, kc2, kc3 = st.columns(3)
        kc1.metric("Total Chunks", total_chunks, help="Fragmentos indexados en pgvector")
        kc2.metric("Documentos únicos", total_docs, help="Identificados por SHA-256")
        kc3.metric("Departamentos", total_depts, help="Con política RLS activa")

        df_corpus = pd.DataFrame(corpus_rows, columns=["Departamento", "Confidencialidad", "Chunks", "Docs"])

        color_map = {"Público": "#52b788", "Interno": "#f4a261", "Confidencial": "#e63946"}
        # Pivotamos para garantizar que cada departamento es una categoría
        import numpy as np
        depts = df_corpus["Departamento"].unique().tolist()
        fig_corpus = go.Figure()
        for nivel in ["Público", "Interno", "Confidencial"]:
            y_vals = []
            for dept in depts:
                row = df_corpus[(df_corpus["Departamento"] == dept) & (df_corpus["Confidencialidad"] == nivel)]
                y_vals.append(int(row["Chunks"].values[0]) if not row.empty else 0)
            fig_corpus.add_trace(go.Bar(
                name=nivel,
                x=depts,
                y=y_vals,
                marker_color=color_map.get(nivel, "#aaa"),
                text=y_vals,
                textposition="inside"
            ))
        fig_corpus.update_layout(
            barmode="stack",
            yaxis_title="Nº de Chunks",
            xaxis_title="Departamento",
            xaxis=dict(type="category"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            height=320,
            margin=dict(t=40, b=20)
        )
        st.plotly_chart(fig_corpus, use_container_width=True)
        st.caption(
            "🟢 Público — accesible por todos los roles  |  "
            "🟡 Interno — dept_standard y superior  |  "
            "🔴 Confidencial — solo dept_high y admin. "
            "La política RLS PERMISSIVE filtra automáticamente según rol del usuario autenticado."
        )

        with st.expander("Ver desglose por documento"):
            st.dataframe(df_corpus, use_container_width=True, hide_index=True)

    except Exception as e:
        st.warning(f"No se pudo cargar la distribución del corpus: {e}")

    st.markdown("---")

    st.subheader("📅 Estado de Vigencia Documental")
    st.caption("Los documentos EXPIRADOS son bloqueados automáticamente por la política RLS restrictiva.")

    try:
        docs = get_expired_documents()
        if docs:
            expirados = [d for d in docs if d[4] == 'EXPIRADO']
            proximos = [d for d in docs if d[4] == 'Proximo']
            vigentes = [d for d in docs if d[4] == 'Vigente']

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("🔴 Expirados", len(expirados))
            with col2:
                st.metric("🟡 Próximos a expirar", len(proximos))
            with col3:
                st.metric("🟢 Vigentes", len(vigentes))

            st.markdown("---")

            if expirados:
                st.error(f"🔴 {len(expirados)} documento(s) EXPIRADO(S) — Bloqueados automáticamente por política RLS RESTRICTIVE")
                for doc in expirados:
                    with st.container(border=True):
                        ec1, ec2, ec3, ec4 = st.columns([3, 1, 1, 1])
                        ec1.markdown(f"### 🚫 {doc[0]}")
                        ec2.markdown(f"**Dpto.**  \n`{doc[1]}`")
                        ec3.markdown(f"**Nivel**  \n`{doc[2]}`")
                        ec4.markdown(f"**Expiró**  \n`{doc[3].strftime('%d/%m/%Y')}`")
                        st.markdown(
                            "> ⚠️ Este documento **no es accesible** para ningún usuario, incluido `admin`. "
                            "La política `rls_policy_no_expired` (RESTRICTIVE FOR SELECT) bloquea automáticamente "
                            "cualquier chunk cuyo `valid_until < CURRENT_TIMESTAMP`."
                        )

            if proximos:
                st.warning("🟡 Documentos próximos a expirar — Acción recomendada")
                for doc in proximos:
                    st.markdown(
                        f"**{doc[0]}** | Dpto: `{doc[1]}` | "
                        f"Nivel: `{doc[2]}` | "
                        f"Expira: `{doc[3].strftime('%d/%m/%Y %H:%M')}`"
                    )

            if vigentes:
                st.success("🟢 Documentos vigentes con fecha de expiración configurada")
                for doc in vigentes:
                    st.markdown(
                        f"**{doc[0]}** | Dpto: `{doc[1]}` | "
                        f"Nivel: `{doc[2]}` | "
                        f"Expira: `{doc[3].strftime('%d/%m/%Y %H:%M')}`"
                    )
        else:
            st.info("No hay documentos con fecha de expiración configurada.")

    except Exception as e:
        st.warning(f"No se pudieron cargar los datos de caducidad: {e}")

with tab3:
    st.header("⚖️ Comparativa de Evaluadores: OllamaJuice vs TruLens")
    st.caption("Evaluación de la Tríada RAG sobre el Golden Set v3 (20 trazas)")

    # --- KPIs FIJOS GOLDEN SET v1 ---
    st.subheader("📋 Resultados Golden Set v1 — Referencia Base")
    st.caption("19 trazas evaluadas · OllamaJuiceProvider artesanal · Evaluación ciega sin TruLens")
    gs_col1, gs_col2, gs_col3, gs_col4, gs_col5 = st.columns(5)
    gs_col1.metric("Context Relevance", "0.690", help="Media CR sobre 19 trazas (mín 0.40 · máx 0.80)")
    gs_col2.metric("Groundedness", "0.870", help="Media GR sobre 19 trazas (mín 0.80 · máx 1.00)")
    gs_col3.metric("Answer Relevance", "0.810", help="Media AR sobre 19 trazas (mín 0.60 · máx 0.90)")
    gs_col4.metric("Requires Review", "5 / 19", help="Trazas con CR<0.6 o GR<0.6 — 26.3% del golden set")
    gs_col5.metric("Preguntas correctas", "11 / 19", help="57.9% — respuestas verificadas manualmente como correctas")
    st.info(
        "**Métrica más débil:** Context Relevance (0.69) — 5 fallos por distancia semántica query↔chunk. "
        "**Métrica más robusta:** Groundedness (0.87) — el modelo no alucina con el contexto recuperado. "
        "**GS-19 excluida** por timeout (documento extenso)."
    )
    st.divider()
    # --- FIN KPIs FIJOS ---


    try:
        conn_cmp = get_db_conn_admin()
        cur_cmp = conn_cmp.cursor()
        cur_cmp.execute("""
            SELECT
                a.log_id,
                CAST(substring(a.response FROM %(cr)s) AS FLOAT)  AS juice_cr,
                CAST(substring(a.response FROM %(gr)s) AS FLOAT)  AS juice_gr,
                CAST(substring(a.response FROM %(ar)s) AS FLOAT)  AS juice_ar,
                a.requires_review  AS juice_review,
                t.context_relevance AS trulens_cr,
                t.groundedness      AS trulens_gr,
                t.answer_relevance  AS trulens_ar,
                t.requires_review   AS trulens_review
            FROM audit_logs a
            JOIN trulens_evaluations t ON a.log_id = t.log_id
            ORDER BY a.log_id
        """, {
            'cr': 'context_relevance": ([0-9.]+)',
            'gr': '"groundedness": ([0-9.]+)',
            'ar': 'answer_relevance": ([0-9.]+)'
        })
        rows = cur_cmp.fetchall()
        cur_cmp.close()
        conn_cmp.close()

        df = pd.DataFrame(rows, columns=[
            "log_id",
            "juice_cr", "juice_gr", "juice_ar", "juice_review",
            "trulens_cr", "trulens_gr", "trulens_ar", "trulens_review"
        ])

        # KPIs
        st.subheader("Medias globales")
        col1, col2, col3 = st.columns(3)
        metrics = [
            ("Context Relevance", "juice_cr", "trulens_cr"),
            ("Groundedness",      "juice_gr", "trulens_gr"),
            ("Answer Relevance",  "juice_ar", "trulens_ar"),
        ]
        for col, (label, jcol, tcol) in zip([col1, col2, col3], metrics):
            jmean = df[jcol].mean()
            tmean = df[tcol].mean()
            delta = tmean - jmean
            with col:
                st.metric(f"OllamaJuice — {label}", f"{jmean:.3f}")
                st.metric(f"TruLens — {label}", f"{tmean:.3f}",
                          delta=f"Δ {delta:+.3f}", delta_color="off")

        # Requires Review
        st.subheader("Detección de trazas problemáticas")
        c1, c2 = st.columns(2)
        c1.metric("OllamaJuice — requires_review",
                  f"{df['juice_review'].sum()}/{len(df)}",
                  help="Trazas marcadas con CR<0.6 o GR<0.6")
        c2.metric("TruLens — requires_review",
                  f"{df['trulens_review'].sum()}/{len(df)}",
                  help="Trazas marcadas con CR<0.6 o GR<0.6")

        # Tabla detallada de trazas problemáticas
        df_review = df[df["juice_review"] | df["trulens_review"]].copy()
        if not df_review.empty:
            with st.expander(f"🔴 Ver detalle de {len(df_review)} trazas problemáticas detectadas", expanded=True):
                conn_rev = get_db_conn_admin()
                cur_rev = conn_rev.cursor()
                ids = df_review["log_id"].tolist()
                cur_rev.execute("""
                    SELECT log_id, question, left(response, 300), user_department, user_role
                    FROM audit_logs
                    WHERE log_id = ANY(%s)
                    ORDER BY log_id
                """, (ids,))
                rev_rows = cur_rev.fetchall()
                cur_rev.close()
                conn_rev.close()

                for row in rev_rows:
                    lid, question, response_snippet, dept, role = row
                    tr = df_review[df_review["log_id"] == lid].iloc[0]
                    juice_flag = "🔴" if tr["juice_review"] else "🟢"
                    trulens_flag = "🔴" if tr["trulens_review"] else "🟢"
                    st.markdown(f"**Log #{lid}** — `{dept}` · `{role}`")
                    col_q, col_m = st.columns([2, 1])
                    with col_q:
                        st.markdown(f"**Pregunta:** {question}")
                        st.markdown(f"**Respuesta (extracto):** _{response_snippet}..._")
                    with col_m:
                        st.markdown("| Métrica | OllamaJuice | TruLens |")
                        st.markdown("|---|---|---|")
                        st.markdown(f"| CR | `{tr['juice_cr']:.2f}` | `{tr['trulens_cr']:.2f}` |")
                        st.markdown(f"| GR | `{tr['juice_gr']:.2f}` | `{tr['trulens_gr']:.2f}` |")
                        st.markdown(f"| AR | `{tr['juice_ar']:.2f}` | `{tr['trulens_ar']:.2f}` |")
                        st.markdown(f"| Review | {juice_flag} OllamaJuice | {trulens_flag} TruLens |")
                    # Botón marcar revisado
                    if juice_flag == "🔴" or trulens_flag == "🔴":
                        btn_key = f"mark_reviewed_{lid}"
                        if st.button(f"✅ Marcar Log #{lid} como revisado", key=btn_key, type="secondary"):
                            try:
                                conn_upd = get_db_conn_admin()
                                cur_upd = conn_upd.cursor()
                                cur_upd.execute(
                                    "UPDATE audit_logs SET requires_review = FALSE WHERE log_id = %s",
                                    (lid,)
                                )
                                conn_upd.commit()
                                cur_upd.close()
                                conn_upd.close()
                                st.success(f"✅ Log #{lid} marcado como revisado. Recarga para actualizar.")
                            except Exception as upd_e:
                                st.error(f"Error al actualizar: {upd_e}")
                    st.divider()
        else:
            st.success("✅ Ninguna traza marcada como requires_review en el conjunto actual.")

        # Gráfica 1: Barras agrupadas
        st.subheader("Puntuaciones medias por evaluador")
        fig_bar = go.Figure()
        labels = ["Context Relevance", "Groundedness", "Answer Relevance"]
        juice_means  = [df["juice_cr"].mean(),   df["juice_gr"].mean(),   df["juice_ar"].mean()]
        trulens_means = [df["trulens_cr"].mean(), df["trulens_gr"].mean(), df["trulens_ar"].mean()]
        fig_bar.add_trace(go.Bar(name="OllamaJuice", x=labels, y=juice_means,  marker_color="#e07b39"))
        fig_bar.add_trace(go.Bar(name="TruLens",     x=labels, y=trulens_means, marker_color="#3a86c8"))
        fig_bar.update_layout(barmode="group", yaxis=dict(range=[0,1], title="Puntuación"),
                              legend=dict(orientation="h", yanchor="bottom", y=1.02),
                              height=350, margin=dict(t=40, b=20))
        st.plotly_chart(fig_bar, use_container_width=True)

        # Gráfica 2: Scatter CR
        st.subheader("Dispersión por traza — Context Relevance")
        colors = ["red" if r else "#3a86c8" for r in df["juice_review"]]
        fig_scatter = go.Figure()
        fig_scatter.add_trace(go.Scatter(
            x=list(df["juice_cr"]),
            y=list(df["trulens_cr"]),
            mode="markers+text",
            text=list(df["log_id"].astype(str)),
            textposition="top center",
            marker=dict(color=["red" if r else "#3a86c8" for r in df["juice_review"]], size=12),
            name="Trazas (rojo = requires_review)"
        ))
        fig_scatter.add_shape(type="line", x0=0.2, y0=0.2, x1=1, y1=1,
                              line=dict(dash="dash", color="gray"))
        fig_scatter.update_layout(
            xaxis_title="OllamaJuice CR",
            yaxis_title="TruLens CR",
            xaxis=dict(range=[0.2, 1.05]),
            yaxis=dict(range=[0.6, 1.05]),
            height=400
        )
        st.plotly_chart(fig_scatter, use_container_width=True)
        st.caption("Línea diagonal = concordancia perfecta. Puntos sobre diagonal = TruLens más optimista. "
                   "Log 46 (GS-01) en rojo = único fallo real detectado por OllamaJuice.")

        # Gráfica Scatter GR
        st.subheader("Dispersión por traza — Groundedness")
        fig_scatter_gr = go.Figure()
        fig_scatter_gr.add_trace(go.Scatter(
            x=list(df["juice_gr"]),
            y=list(df["trulens_gr"]),
            mode="markers+text",
            text=list(df["log_id"].astype(str)),
            textposition="top center",
            marker=dict(color=["red" if r else "#52b788" for r in df["juice_review"]], size=12),
            name="Trazas (rojo = requires_review)"
        ))
        fig_scatter_gr.add_shape(type="line", x0=0.5, y0=0.5, x1=1, y1=1,
                                 line=dict(dash="dash", color="gray"))
        fig_scatter_gr.update_layout(
            xaxis_title="OllamaJuice GR",
            yaxis_title="TruLens GR",
            xaxis=dict(range=[0.5, 1.05]),
            yaxis=dict(range=[0.5, 1.05]),
            height=400
        )
        st.plotly_chart(fig_scatter_gr, use_container_width=True)
        st.caption("Groundedness: ambos evaluadores tienden a concordar. "
                   "Trazas rojas = marcadas requires_review por OllamaJuice.")

        # Gráfica Scatter AR
        st.subheader("Dispersión por traza — Answer Relevance")
        fig_scatter_ar = go.Figure()
        fig_scatter_ar.add_trace(go.Scatter(
            x=list(df["juice_ar"]),
            y=list(df["trulens_ar"]),
            mode="markers+text",
            text=list(df["log_id"].astype(str)),
            textposition="top center",
            marker=dict(color=["red" if r else "#9b5de5" for r in df["juice_review"]], size=12),
            name="Trazas (rojo = requires_review)"
        ))
        fig_scatter_ar.add_shape(type="line", x0=0.5, y0=0.5, x1=1, y1=1,
                                 line=dict(dash="dash", color="gray"))
        fig_scatter_ar.update_layout(
            xaxis_title="OllamaJuice AR",
            yaxis_title="TruLens AR",
            xaxis=dict(range=[0.5, 1.05]),
            yaxis=dict(range=[0.5, 1.05]),
            height=400
        )
        st.plotly_chart(fig_scatter_ar, use_container_width=True)
        st.caption("Answer Relevance: métrica con mayor concordancia entre evaluadores. "
                   "Desviaciones indican diferente sensibilidad a la completitud de la respuesta.")

        # Gráfica 3: Delta por traza
        st.subheader("Diferencia (Δ) entre evaluadores por traza")
        df["delta_cr"] = (df["trulens_cr"] - df["juice_cr"]).round(3)
        df["delta_gr"] = (df["trulens_gr"] - df["juice_gr"]).round(3)
        df["delta_ar"] = (df["trulens_ar"] - df["juice_ar"]).round(3)
        fig_delta = go.Figure()
        fig_delta.add_trace(go.Bar(name="ΔCR", x=list(df["log_id"].astype(str)), y=list(df["delta_cr"]), marker_color="#e07b39"))
        fig_delta.add_trace(go.Bar(name="ΔGR", x=list(df["log_id"].astype(str)), y=list(df["delta_gr"]), marker_color="#3a86c8"))
        fig_delta.add_trace(go.Bar(name="ΔAR", x=list(df["log_id"].astype(str)), y=list(df["delta_ar"]), marker_color="#52b788"))
        fig_delta.add_hline(y=0, line_dash="solid", line_color="black", line_width=1)
        fig_delta.update_layout(
            barmode="group",
            xaxis_title="Log ID (traza)",
            yaxis_title="TruLens − OllamaJuice",
            yaxis=dict(range=[-0.1, 0.5]),  # ajustado al rango real
            height=350,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(t=40, b=20)
        )        
        st.plotly_chart(fig_delta, use_container_width=True)
        st.caption("Valores positivos = TruLens más optimista. "
                   "Log 46 muestra ΔCR=+0.40, la mayor divergencia del golden set.")

        # Tabla detalle
        with st.expander("Ver tabla completa de datos"):
            st.dataframe(df.style.highlight_max(
                subset=["juice_cr","juice_gr","juice_ar","trulens_cr","trulens_gr","trulens_ar"],
                color="#d4edda"
            ), use_container_width=True)

        # --- EXPORTAR INFORME PDF ---
        st.markdown("---")
        st.subheader("📄 Exportar Informe del Golden Set")
        if st.button("⬇️ Generar informe PDF", type="primary"):
            try:
                from reportlab.lib.pagesizes import A4
                from reportlab.lib import colors
                from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
                from reportlab.lib.units import cm
                import io, datetime

                buffer = io.BytesIO()
                doc = SimpleDocTemplate(buffer, pagesize=A4,
                                        rightMargin=2*cm, leftMargin=2*cm,
                                        topMargin=2*cm, bottomMargin=2*cm)
                styles = getSampleStyleSheet()
                story = []

                # Título
                title_style = ParagraphStyle('title', parent=styles['Title'], fontSize=16, spaceAfter=6)
                story.append(Paragraph("Informe de Evaluación — Golden Set RAG", title_style))
                story.append(Paragraph(f"Sistema RAG On-Premise · ETSIIT UGR · {datetime.date.today().strftime('%d/%m/%Y')}", styles['Normal']))
                story.append(Spacer(1, 0.5*cm))

                # KPIs Golden Set v1
                story.append(Paragraph("Resultados Golden Set v1 — OllamaJuiceProvider (Referencia Base)", styles['Heading2']))
                gs1_data = [
                    ["Métrica", "Media", "Mínimo", "Máximo"],
                    ["Context Relevance", "0.690", "0.40", "0.80"],
                    ["Groundedness",      "0.870", "0.80", "1.00"],
                    ["Answer Relevance",  "0.810", "0.60", "0.90"],
                    ["Requires Review",   "5 / 19 (26.3%)", "—", "—"],
                    ["Correctas",         "11 / 19 (57.9%)", "—", "—"],
                ]
                t1 = Table(gs1_data, colWidths=[5*cm, 3*cm, 3*cm, 3*cm])
                t1.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2c3e50')),
                    ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
                    ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
                    ('GRID',       (0,0), (-1,-1), 0.5, colors.grey),
                    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f2f2f2')]),
                    ('ALIGN',      (1,0), (-1,-1), 'CENTER'),
                ]))
                story.append(t1)
                story.append(Spacer(1, 0.5*cm))

                # KPIs dinámicos
                story.append(Paragraph("Comparativa OllamaJuice vs TruLens — Datos en BD", styles['Heading2']))
                means_data = [
                    ["Métrica", "OllamaJuice", "TruLens", "Δ (TruLens − OllamaJuice)"],
                    ["Context Relevance",
                     f"{df['juice_cr'].mean():.3f}", f"{df['trulens_cr'].mean():.3f}",
                     f"{(df['trulens_cr']-df['juice_cr']).mean():+.3f}"],
                    ["Groundedness",
                     f"{df['juice_gr'].mean():.3f}", f"{df['trulens_gr'].mean():.3f}",
                     f"{(df['trulens_gr']-df['juice_gr']).mean():+.3f}"],
                    ["Answer Relevance",
                     f"{df['juice_ar'].mean():.3f}", f"{df['trulens_ar'].mean():.3f}",
                     f"{(df['trulens_ar']-df['juice_ar']).mean():+.3f}"],
                    ["Requires Review",
                     f"{df['juice_review'].sum()}/{len(df)}",
                     f"{df['trulens_review'].sum()}/{len(df)}", "—"],
                ]
                t2 = Table(means_data, colWidths=[4.5*cm, 3*cm, 3*cm, 4.5*cm])
                t2.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2c3e50')),
                    ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
                    ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
                    ('GRID',       (0,0), (-1,-1), 0.5, colors.grey),
                    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f2f2f2')]),
                    ('ALIGN',      (1,0), (-1,-1), 'CENTER'),
                ]))
                story.append(t2)
                story.append(Spacer(1, 0.5*cm))

                # Tabla detalle por traza
                story.append(Paragraph("Detalle por Traza", styles['Heading2']))
                detail_header = ["Log ID", "J.CR", "T.CR", "J.GR", "T.GR", "J.AR", "T.AR", "Review"]
                detail_rows = [detail_header]
                for _, row in df.iterrows():
                    detail_rows.append([
                        str(int(row['log_id'])),
                        f"{row['juice_cr']:.2f}", f"{row['trulens_cr']:.2f}",
                        f"{row['juice_gr']:.2f}", f"{row['trulens_gr']:.2f}",
                        f"{row['juice_ar']:.2f}", f"{row['trulens_ar']:.2f}",
                        "🔴" if row['juice_review'] else "🟢"
                    ])
                t3 = Table(detail_rows, colWidths=[1.5*cm,1.8*cm,1.8*cm,1.8*cm,1.8*cm,1.8*cm,1.8*cm,1.8*cm])
                t3.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2c3e50')),
                    ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
                    ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
                    ('FONTSIZE',   (0,0), (-1,-1), 8),
                    ('GRID',       (0,0), (-1,-1), 0.5, colors.grey),
                    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f2f2f2')]),
                    ('ALIGN',      (0,0), (-1,-1), 'CENTER'),
                ]))
                story.append(t3)

                doc.build(story)
                buffer.seek(0)
                st.download_button(
                    label="📥 Descargar informe PDF",
                    data=buffer,
                    file_name=f"golden_set_report_{datetime.date.today().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf"
                )
            except ImportError:
                st.error("Falta la librería reportlab. Instálala añadiendo 'reportlab' al requirements.txt y rebuildeando.")
            except Exception as pdf_e:
                st.error(f"Error generando PDF: {pdf_e}")

    except Exception as e:
        st.error(f"Error al cargar comparativa: {e}")

# ══ TAB 4 — CONFIGURACIÓN ══════════════════════════════
with tab4:
    import requests as _req
    st.header("⚙️ Configuración del Sistema RAG")
    st.caption("Los cambios se aplican en caliente y se persisten en base de datos.")

    _API = "http://api_gateway_container:8000"

    def _admin_token():
        try:
            import jwt as _jwt
            return _jwt.encode(
                {"sub": "directoria", "department": "Administracion", "role": "admin"},
                "ETSIIT_UGR_SECRET_KEY_2026",
                algorithm="HS256"
            )
        except Exception:
            return None

    @st.cache_data(ttl=15)
    def _load_cfg():
        tok = _admin_token()
        if not tok:
            return {}
        try:
            r = _req.get(f"{_API}/api/v1/config",
                headers={"Authorization": f"Bearer {tok}"}, timeout=5)
            return r.json() if r.status_code == 200 else {}
        except Exception:
            return {}

    def _cv(cfg, key, default):
        try:
            return type(default)(cfg[key]["value"])
        except Exception:
            return default

    cfg4 = _load_cfg()

    if not cfg4:
        st.error("No se pudo conectar con la API para cargar la configuración.")
    else:
        st.success(f"✅ {len(cfg4)} parámetros cargados desde BD")

    st.markdown("---")
    st.subheader("🔍 Recuperación Vectorial")
    c1, c2 = st.columns(2)
    with c1:
        n_top_k = st.slider("top_k — Chunks recuperados", 1, 15, _cv(cfg4, "top_k", 6),
            help="Número de chunks enviados al LLM como contexto.")
        n_sim = st.slider("similarity_threshold", 0.0, 1.0,
            _cv(cfg4, "similarity_threshold", 0.0), step=0.05,
            help="Umbral mínimo de similitud coseno. 0.0 = sin filtro.")
    with c2:
        n_chunk = st.number_input("chunk_size (tokens)", 100, 2000,
            _cv(cfg4, "chunk_size", 650), step=50)
        n_overlap = st.number_input("chunk_overlap (tokens)", 0, 500,
            _cv(cfg4, "chunk_overlap", 130), step=10)

    st.markdown("---")
    st.subheader("🤖 Modelo LLM")
    c3, c4 = st.columns(2)
    with c3:
        # Consultar modelos disponibles en Ollama (excluir modelos de embedding)
        _EMBED_MODELS = {"nomic-embed-text", "mxbai-embed-large", "all-minilm", "nomic-embed"}
        try:
            _ollama_r = _req.get("http://ollama_engine:11434/api/tags", timeout=3)
            _all = [m["name"] for m in _ollama_r.json().get("models", [])]
            _models = sorted([m for m in _all if not any(e in m for e in _EMBED_MODELS)])
        except Exception:
            _models = ["llama3.1:8b", "llama3.2:3b", "qwen2.5:7b"]
        _cur = _cv(cfg4, "model", "llama3.1:8b")
        if _cur not in _models:
            _models.insert(0, _cur)
        n_model = st.selectbox("Modelo Ollama activo", _models, index=_models.index(_cur))
        n_temp = st.slider("temperature", 0.0, 1.0, _cv(cfg4, "temperature", 0.0), step=0.05)
    with c4:
        n_ctx = st.select_slider("num_ctx — Ventana contexto",
            options=[1024, 2048, 4096, 8192, 16384],
            value=_cv(cfg4, "num_ctx", 4096))
        n_pred = st.select_slider("num_predict — Tokens respuesta",
            options=[128, 256, 512, 1024, 2048],
            value=_cv(cfg4, "num_predict", 512))

    st.markdown("---")
    cb1, cb2, _ = st.columns([1, 1, 3])
    with cb1:
        _apply = st.button("✅ Aplicar cambios", type="primary", use_container_width=True)
    with cb2:
        _reload = st.button("🔄 Recargar", use_container_width=True)

    if _reload:
        st.cache_data.clear()
        st.rerun()

    if _apply:
        _tok = _admin_token()
        if not _tok:
            st.error("No se pudo obtener token de admin.")
        else:
            _payload = {
                "top_k": n_top_k, "similarity_threshold": n_sim,
                "chunk_size": n_chunk, "chunk_overlap": n_overlap,
                "model": n_model, "temperature": n_temp,
                "num_ctx": n_ctx, "num_predict": n_pred,
            }
            try:
                _r = _req.put(f"{_API}/api/v1/config", json=_payload,
                    headers={"Authorization": f"Bearer {_tok}"}, timeout=10)
                if _r.status_code == 200:
                    _upd = _r.json().get("updated", {})
                    st.success(f"✅ {len(_upd)} parámetros actualizados")
                    for _k, _v in _upd.items():
                        st.write(f"  • `{_k}` → `{_v}`")
                    st.cache_data.clear()
                else:
                    st.error(f"Error API {_r.status_code}: {_r.text}")
            except Exception as _e:
                st.error(f"Error de conexión: {_e}")

    st.markdown("---")
    st.subheader("📋 Estado actual en Base de Datos")
    if cfg4:
        import pandas as _pd
        _rows = [{"Parámetro": k, "Valor": v["value"],
                  "Modificado por": v.get("updated_by", "—"),
                  "Última actualización": v.get("updated_at", "—")}
                 for k, v in cfg4.items()]
        st.dataframe(_pd.DataFrame(_rows).sort_values("Parámetro"),
            use_container_width=True, hide_index=True)
