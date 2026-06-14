# 🛡️ Sistema RAG On-Premise con Arquitectura de 5 Planos

![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)
![Python 3.10](https://img.shields.io/badge/Python-3.10-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.103.1-009688.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)
![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-black.svg)
![n8n](https://img.shields.io/badge/n8n-Workflow_Automation-FF6B6B.svg)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)

## 📖 Descripción General
Este proyecto implementa una solución **Retrieval-Augmented Generation (RAG) 100% On-Premise**, diseñada para entornos corporativos de alta privacidad (Zero-Trust). El sistema orquesta modelos LLM locales (Llama 3.1) garantizando que ningún dato confidencial abandone la infraestructura de la empresa. Cumple con normativas de trazabilidad inspiradas en el marco NIST AI 600-1 y utiliza un modelo estricto de Control de Acceso Basado en Roles (RBAC) a nivel de base de datos.

## 🏗️ Arquitectura de 5 Planos
El sistema está dividido en cinco planos funcionales completamente desacoplados para facilitar su escalabilidad y auditoría:

1. **Plano de Identidad**: Autenticación JWT y asignación de roles. Interfaz de usuario intuitiva desarrollada en **Streamlit**.
2. **Plano de Ingesta**: Pipeline ETL asíncrono gestionado con **n8n**. Deduplica documentos, fragmenta (*chunking*) y vectoriza la información.
3. **Plano de Datos**: Núcleo de almacenamiento en **PostgreSQL** con la extensión **pgvector**. Implementa seguridad **Row-Level Security (RLS)** inquebrantable delegando los permisos directamente al motor de la base de datos.
4. **Plano de Inferencia**: Ejecución del LLM **Llama 3.1** (8B) y el modelo de embeddings `nomic-embed-text` de forma totalmente local y aislada gracias a **Ollama**.
5. **Plano de Auditoría**: Trabajador en segundo plano que implementa una Arquitectura de Evaluación Diferida (Doble Evaluador) calculando la tríada RAG (Context Relevance, Groundedness, Answer Relevance) usando **TruLens** sin afectar a la latencia del usuario.

## ✨ Características Principales
* **Seguridad Zero-Trust (RLS):** El filtrado de documentos por departamento y confidencialidad se aplica de forma transaccional usando inyecciones de variables de contexto globales (GUC).
* **Flujo Real-Time SSE:** Generación de respuestas por streaming asíncrono (Server-Sent Events) para una experiencia de usuario fluida e instantánea.
* **Evaluación Asíncrona Automática:** Auditoría continua de la calidad de las respuestas en lote, utilizando a Ollama como juez evaluador.
* **Despliegue Contenerizado:** Arquitectura de microservicios con 6 contenedores interconectados bajo la red privada `rag_network`, desplegables de forma automatizada.

## 🚀 Instalación y Despliegue

### Requisitos Previos
* **SO:** Ubuntu 24.04 LTS (o equivalente basado en Linux).
* **Hardware:** Procesador con soporte de instrucciones AVX2 (Intel Xeon/Core o AMD Ryzen), mínimo 32 GB de RAM. No requiere tarjeta gráfica dedicada (GPU).
* **Software:** Docker Engine y Docker Compose instalados.

### Guía Rápida de Despliegue

1. **Clonar el repositorio:**
   ```bash
   git clone https://github.com/tu-usuario/rag-on-premise.git
   cd rag-on-premise
   ```

2. **Configurar el entorno:**
   ```bash
   cp .env.example .env
   # Edita el archivo .env con tus claves seguras (JWT_SECRET_KEY, contraseñas, etc.)
   ```

3. **Descargar los modelos locales de Ollama:**
   ```bash
   docker-compose up -d ollama
   # Esperar unos segundos a que Ollama levante su API
   docker exec -it ollama ollama pull llama3.1:8b
   docker exec -it ollama ollama pull nomic-embed-text
   ```

4. **Levantar el resto de la infraestructura:**
   ```bash
   docker-compose up -d --build
   ```

5. **Acceder a los paneles de control:**
   * **Interfaz de Chat y Dashboard (Streamlit):** `http://localhost:8501`
   * **API Gateway (Swagger UI):** `http://localhost:8000/docs`
   * **Orquestador de Ingesta (n8n):** `http://localhost:5678`

## 📄 Licencia

Este proyecto se distribuye bajo la licencia **GNU Lesser General Public License v3.0 (LGPL-3.0)**. 

Esto permite utilizar este software libremente e integrarlo en proyectos propietarios o de código cerrado corporativos, con la única condición de que si se realizan modificaciones *directamente al código fuente original de este repositorio*, dichas mejoras deben ser compartidas de vuelta a la comunidad bajo los mismos términos.

Consulta el archivo [LICENSE](LICENSE) completo para más detalles legales.
