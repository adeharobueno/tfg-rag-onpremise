# 🛡️ Sistema RAG On-Premise con Arquitectura de 5 Planos

![License: LGPL v3](https://img.shields.io/badge/License-LGPL_v3-blue.svg)
![Python 3.10](https://img.shields.io/badge/Python-3.10-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.103.1-009688.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)
![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-black.svg)
![n8n](https://img.shields.io/badge/n8n-Workflow_Automation-FF6B6B.svg)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)

## 📖 Descripción General
Este proyecto implementa una solución **Retrieval-Augmented Generation (RAG) 100% On-Premise**, diseñada para entornos corporativos de alta privacidad (Zero-Trust). El sistema orquesta modelos LLM locales (Llama 3.1) garantizando que ningún dato confidencial abandone la infraestructura de la empresa. Su principio rector es la **seguridad por diseño**: el control de acceso se delega en las políticas de **seguridad a nivel de fila (Row-Level Security, RLS)** del propio motor de base de datos, en lugar de confiarse a la lógica de aplicación. La trazabilidad y la auditoría continua de la calidad se inspiran en el marco **NIST AI RMF** (AI Risk Management Framework) y en las directrices de OWASP.

## 🏗️ Arquitectura de 5 Planos
El sistema se organiza en cinco planos funcionales desacoplados, desplegados sobre seis contenedores Docker interconectados, lo que facilita su escalabilidad y auditoría:

1. **Plano de Identidad**: Autenticación JWT y asignación de roles. Interfaz de usuario desarrollada en **Streamlit**.
2. **Plano de Ingesta**: Pipeline ETL asíncrono gestionado con **n8n**. Deduplica documentos, fragmenta (*chunking*) y vectoriza la información.
3. **Plano de Datos**: Núcleo de almacenamiento en **PostgreSQL** con la extensión **pgvector**. Aplica **Row-Level Security (RLS)** delegando el control de acceso directamente en el motor de la base de datos.
4. **Plano de Inferencia**: Ejecución del LLM **Llama 3.1** (8B) y el modelo de embeddings `nomic-embed-text` de forma totalmente local y aislada gracias a **Ollama**.
5. **Plano de Auditoría**: Trabajador en segundo plano que implementa una Arquitectura de Evaluación Diferida (Doble Evaluador), calculando la tríada RAG (Context Relevance, Groundedness, Answer Relevance) con **TruLens** sin afectar a la latencia percibida por el usuario.

> ℹ️ Los **cinco planos** son una división funcional (lógica); a nivel de despliegue se materializan en **seis servicios** definidos en `docker-compose.yml`.

## ✨ Características Principales
* **Seguridad Zero-Trust (RLS):** El filtrado de documentos por departamento y nivel de confidencialidad se aplica de forma transaccional en el motor de datos, mediante la inyección de variables de contexto de sesión (GUC). Al residir las políticas en la base de datos, cualquier vía de acceso queda sujeta a ellas de forma automática.
* **Respuesta por streaming (SSE):** La generación se entrega mediante *Server-Sent Events*, mostrando la respuesta de forma progresiva a medida que el modelo la produce, en lugar de esperar a que esté completa.
* **Evaluación asíncrona automática:** Auditoría continua y desacoplada de la calidad de las respuestas en lote, utilizando a Ollama como modelo evaluador (*LLM-as-a-Judge*).
* **Despliegue contenerizado:** Arquitectura de microservicios con seis contenedores interconectados bajo la red privada `rag_network`, desplegables de forma automatizada.

## 🚀 Instalación y Despliegue

### Requisitos Previos
* **SO:** Ubuntu 24.04 LTS (o equivalente basado en Linux).
* **Hardware:** Procesador x86-64 con soporte de **AVX2** como mínimo (Intel Xeon/Core o AMD Ryzen). Se recomienda un procesador con **AVX-512 / VNNI / AMX** (p. ej. Intel Xeon Sapphire Rapids) para un rendimiento de inferencia óptimo. Mínimo 32 GB de RAM (recomendado 64 GB o más para alojar el modelo de forma holgada). **No requiere tarjeta gráfica dedicada (GPU).**
* **Software:** Docker Engine y Docker Compose instalados.

### Guía Rápida de Despliegue

1. **Clonar el repositorio:**
   ```bash
   git clone https://github.com/adeharobueno/tfg-rag-onpremise.git
   cd tfg-rag-onpremise
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

> ⚙️ **Nota sobre rendimiento:** la inferencia se ejecuta íntegramente sobre CPU (sin GPU). Esto prioriza la soberanía del dato y el despliegue sobre hardware de propósito general frente a la latencia: los tiempos de respuesta son sensiblemente superiores a los de una solución acelerada por GPU o cloud, una contrapartida asumida por diseño y documentada en la memoria del proyecto.

## 📄 Licencia

Este proyecto se distribuye bajo la licencia **GNU Lesser General Public License v3.0 (LGPL-3.0)**.

Esto permite utilizar este software libremente e integrarlo en proyectos propietarios o de código cerrado corporativos, con la única condición de que, si se realizan modificaciones *directamente al código fuente original de este repositorio*, dichas mejoras deben compartirse de vuelta a la comunidad bajo los mismos términos.

Consulta el archivo [LICENSE](LICENSE) completo para más detalles legales.
