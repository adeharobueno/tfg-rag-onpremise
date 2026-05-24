import streamlit as st
import requests
import json

# Configuración visual de la página
st.set_page_config(page_title="Corporate RAG | ETSSIIT", page_icon="🛡️", layout="wide")

# ==========================================
# Panel Lateral: Seguridad y Fuentes
# ==========================================
st.sidebar.title("🔒 Control de Acceso RLS")
jwt_token = st.sidebar.text_input("Token JWT (Bearer):", type="password", help="Pega aquí el token generado corporativo")

st.sidebar.markdown("---")
st.sidebar.subheader("📄 Trazabilidad de Fuentes")
sources_container = st.sidebar.empty()

# ==========================================
# Panel Principal: Chat RAG
# ==========================================
st.title("🛡️ Asistente RAG Soberano")
st.caption("Arquitectura On-Premise con Auditoría TruLens y Seguridad de Vectores")

# Inicialización de la memoria de chat en la sesión
if "messages" not in st.session_state:
    st.session_state.messages = []

# Renderizar historial previo
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Entrada del usuario
if prompt := st.chat_input("Escribe tu consulta (ej. ¿Cuál es el presupuesto confidencial?)"):
    
    # Validar credenciales antes de enviar nada
    if not jwt_token:
        st.error("⚠️ Operación rechazada: Debes introducir un token corporativo válido en el panel lateral.")
        st.stop()

    # Mostrar el mensaje del usuario
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Contenedor para la respuesta en streaming
    with st.chat_message("assistant"):
        response_placeholder = st.empty()
        full_response = ""
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {jwt_token}"
        }
        
        try:
            # Petición HTTP POST consumiendo el Server-Sent Events (SSE) del API Gateway
            with requests.post("http://api_gateway:8000/api/v1/chat/stream", 
                               json={"question": prompt}, 
                               headers=headers, 
                               stream=True) as r:
                
                # Gestión de denegaciones limpias (FastAPI devuelve JSON en lugar de Stream si falla el RLS)
                if "application/json" in r.headers.get('Content-Type', ''):
                    error_data = r.json()
                    st.error(f"❌ {error_data.get('error', 'Token inválido o acceso no autorizado.')}")
                    st.stop()

                # Decodificación del Stream en tiempo real
                for line in r.iter_lines():
                    if line:
                        decoded_line = line.decode('utf-8')
                        
                        # Capturamos solo las líneas de datos de SSE
                        if decoded_line.startswith("data: "):
                            data_str = decoded_line[6:]
                            
                            # Cierre del canal
                            if data_str == "{}":
                                break
                                
                            try:
                                data_json = json.loads(data_str)
                                
                                # 1. Lluvia de tokens (Llama 3.1 8B)
                                if "token" in data_json:
                                    full_response += data_json["token"]
                                    response_placeholder.markdown(full_response + "▌")
                                
                                # 2. Metadatos de fuentes (PostgreSQL)
                                elif isinstance(data_json, list):
                                    with sources_container.container():
                                        for source in data_json:
                                            st.info(f"**Documento:** {source['file_name']}\n\n**Seguridad:** {source['security']}\n\n**Vector ID:** {source['id']}")
                                            
                            except json.JSONDecodeError:
                                continue
                                
            # Imprimir el resultado final sin el cursor parpadeante
            response_placeholder.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            
        except requests.exceptions.ConnectionError:
            st.error("Error crítico: No se pudo conectar con el microservicio API Gateway.")
