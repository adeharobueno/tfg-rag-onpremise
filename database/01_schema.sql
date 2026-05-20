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
('director_ia', crypt('AdminPassword2026', gen_salt('bf', 10)), 'Administración', 'admin'),
('jefe_rrhh', crypt('HighPassword2026', gen_salt('bf', 10)), 'Recursos Humanos', 'dept_high'),
('tecnico_admin', crypt('StandardPassword2026', gen_salt('bf', 10)), 'Administración', 'dept_standard');

-- 4. TABLA DE FRAGMENTOS DE DOCUMENTOS (Estructura RAG - Capítulos 2 y 4)
CREATE TABLE document_sections (
    section_id BIGSERIAL PRIMARY KEY,
    document_hash CHAR(64) NOT NULL,          -- Identificador SHA-256 para control de deduplicación
    filename VARCHAR(255) NOT NULL,            -- Nombre del archivo de origen (PDF, DOCX, TXT)
    department VARCHAR(50) NOT NULL,          -- Departamento propietario del dato ('Recursos Humanos'/'Administración')
    confidentiality_level VARCHAR(20) NOT NULL, -- Niveles inmutables: 'Público', 'Interno', 'Confidencial'
    chunk_index INT NOT NULL,                  -- Índice secuencial del fragmento dentro del documento
    content TEXT NOT NULL,                     -- Texto claro extraído de un tamaño de ~650 tokens
    -- COLUMNA VECTORIAL CORREGIDA A EXACTAMENTE 768 DIMENSIONES
    embedding vector(768),                     
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. CONFIGURACIÓN COMPLEMENTARIA DE SEGURIDAD RELACIONAL
-- Otorgar privilegios mínimos de estructura para evitar el uso del superusuario en el backend de FastAPI
-- El rol 'api_gateway' se creará de forma automatizada mediante docker-entrypoint en la siguiente jornada
