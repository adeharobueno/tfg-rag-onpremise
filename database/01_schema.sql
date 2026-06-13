-- =============================================================================
-- TRABAJO DE FIN DE GRADO - ETSIIT UGR
-- Sistema RAG On-Premise con Gobernanza y Soberanía del Dato
-- Script Maestro de Inicialización del Esquema Relacional-Vectorial
-- =============================================================================

-- 1. EXTENSIONES DE SEGURIDAD Y SOPORTE VECTORIAL
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto; -- Habilita hashing seguro (Blowfish/Bcrypt) dentro de Postgres

-- 2. LIMPIEZA DE ENTORNOS PREVIOS (Garantía de idempotencia en despliegues)
DROP TABLE IF EXISTS document_sections CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- 3. TABLA DE USUARIOS Y ROLES SEMILLA (Autenticación Local RBAC - Capítulo 4)
CREATE TABLE users (
    user_id BIGSERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    department VARCHAR(50) NOT NULL, -- Valores restringidos: 'Recursos Humanos' o 'Administración'
    user_role VARCHAR(20) NOT NULL,   -- Valores jerárquicos: 'admin', 'dept_high', 'dept_standard'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- INYECCIÓN DE USUARIOS SEMILLA CON CONTRASEÑAS ENCRIPTADAS MEDIANTE BCRYPT (Para pruebas del Hito 5)
-- Las contraseñas en texto claro corresponden a 'AdminPassword2026', 'HighPassword2026' y 'StandardPassword2026'
INSERT INTO users (username, password_hash, department, user_role) VALUES
('director_ia', crypt('AdminPassword2026', gen_salt('bf', 12)), 'Administración', 'admin'),
('jefe_rrhh', crypt('HighPassword2026', gen_salt('bf', 12)), 'Recursos Humanos', 'dept_high'),
('tecnico_admin', crypt('StandardPassword2026', gen_salt('bf', 12)), 'Administración', 'dept_standard');

-- 4. TABLA DE FRAGMENTOS DE DOCUMENTOS (Estructura RAG - Capítulos 2 y 4)

CREATE TABLE document_sections (
    section_id BIGSERIAL PRIMARY KEY,
    document_hash CHAR(64),
    filename VARCHAR(255) GENERATED ALWAYS AS (metadata->>'file_name') STORED,
    department VARCHAR(50),
    confidentiality_level VARCHAR(20),
    chunk_index INT,
    text TEXT NOT NULL,
    embedding vector(768),
    metadata JSONB,
    valid_until TIMESTAMP WITH TIME ZONE DEFAULT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
-- Índices GIN y Vectoriales esenciales para el rendimiento del RAG
CREATE INDEX IF NOT EXISTS idx_document_sections_metadata ON document_sections USING GIN (metadata);
CREATE INDEX IF NOT EXISTS idx_document_sections_embedding ON document_sections USING hnsw (embedding vector_cosine_ops);

-- 5. TABLA DE TRAZAS DE AUDITORÍA (Plano de Auditoría - Capítulo 4)
DROP TABLE IF EXISTS audit_logs CASCADE;

CREATE TABLE audit_logs (
    log_id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    user_department VARCHAR(100) NOT NULL,
    user_role VARCHAR(100) NOT NULL,
    question TEXT NOT NULL,
    response TEXT NOT NULL,
    context_used TEXT NOT NULL,
    chunks_id INTEGER[] NOT NULL,
    model_used VARCHAR(50) DEFAULT NULL,          -- Modelo LLM usado en la inferencia
    requires_review BOOLEAN DEFAULT FALSE
);

-- 6. TABLA DE CONFIGURACIÓN DINÁMICA DEL SISTEMA RAG (Tab 4 - Configuración)
DROP TABLE IF EXISTS rag_config CASCADE;

CREATE TABLE rag_config (
    key VARCHAR(50) PRIMARY KEY,
    value TEXT NOT NULL,
    updated_by VARCHAR(50) DEFAULT 'system',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Valores semilla coherentes con los parámetros de inferencia del proyecto
INSERT INTO rag_config (key, value) VALUES
    ('model',                'llama3.1:8b'),
    ('temperature',          '0.0'),
    ('top_k',                '6'),
    ('similarity_threshold', '0.0'),
    ('chunk_size',           '650'),
    ('chunk_overlap',        '130'),
    ('num_ctx',              '4096'),
    ('num_predict',          '512');

-- 7. TABLA DE EVALUACIONES TRULENS (Comparativa de Evaluadores - Tab 3)
DROP TABLE IF EXISTS trulens_evaluations CASCADE;

CREATE TABLE trulens_evaluations (
    eval_id SERIAL PRIMARY KEY,
    log_id INTEGER NOT NULL REFERENCES audit_logs(log_id),
    context_relevance FLOAT,
    groundedness FLOAT,
    answer_relevance FLOAT,
    requires_review BOOLEAN DEFAULT FALSE,
    evaluated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_trulens_log_id ON trulens_evaluations(log_id);

-- 8. TABLA DE DENEGACIONES DE ACCESO RBAC (RF-D05 - Auditoría de Seguridad)
DROP TABLE IF EXISTS rbac_denials CASCADE;

CREATE TABLE rbac_denials (
    denial_id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    username VARCHAR(100) DEFAULT 'anonymous',
    department VARCHAR(100) DEFAULT NULL,
    user_role VARCHAR(50) DEFAULT NULL,
    endpoint VARCHAR(255) NOT NULL,
    denial_reason VARCHAR(50) NOT NULL,  -- 'token_invalid', 'token_expired', 'rls_empty', 'role_forbidden'
    detail TEXT DEFAULT NULL,
    ip_address VARCHAR(45) DEFAULT NULL
);

CREATE INDEX idx_rbac_denials_timestamp ON rbac_denials(timestamp DESC);
CREATE INDEX idx_rbac_denials_reason ON rbac_denials(denial_reason);

-- 9. CONFIGURACIÓN COMPLEMENTARIA DE SEGURIDAD RELACIONAL
-- Otorgar privilegios mínimos de estructura para evitar el uso del superusuario en el backend de FastAPI
-- El rol 'api_gateway' se creará de forma automatizada en 02_rls.sql
