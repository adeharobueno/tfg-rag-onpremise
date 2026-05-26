import streamlit as st
import requests
import json
import psycopg2

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

st.sidebar.title("🔒 Control de Acceso RLS")
jwt_token = st.sidebar.text_input(
    "Token JWT (Bearer):",
    type="password",
    help="Pega aquí el token corporativo generado"
)
st.sidebar.markdown("---")
st.sidebar.subheader("📄 Trazabilidad de Fuentes")
sources_container = st.sidebar.empty()

tab1, tab2 = st.tabs(["💬 Asistente RAG", "📊 Panel de Gobernanza"])

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

            except requests.exceptions.ConnectionError:
                st.error("Error crítico: No se pudo conectar con el API Gateway.")

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
                st.error("🔴 Documentos EXPIRADOS — Bloqueados por política RLS")
                for doc in expirados:
                    st.markdown(
                        f"**{doc[0]}** | Dpto: `{doc[1]}` | "
                        f"Nivel: `{doc[2]}` | "
                        f"Expiró: `{doc[3].strftime('%d/%m/%Y %H:%M')}`"
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
