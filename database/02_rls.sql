-- =============================================================================
-- TRABAJO DE FIN DE GRADO - ETSIIT UGR
-- Fichero 02_rls.sql: Automatización de Privilegios Mínimos y Cortafuegos RLS
-- =============================================================================

-- 1. CREACIÓN DEL ROL DE SERVICIO Y PERMISOS BASE
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_user WHERE usename = 'api_gateway') THEN
        CREATE USER api_gateway WITH PASSWORD 'App_Pass_Gateway_Secure_2026?';
    END IF;
END $$;

-- Limpieza de permisos por defecto y asignación estricta
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO api_gateway;

-- Permisos DML estrictos para la pasarela
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE users TO api_gateway;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE document_sections TO api_gateway;

-- Permisos sobre todas las secuencias (necesario para los BIGSERIAL)
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO api_gateway;


-- 2. ACTIVACIÓN DE ROW-LEVEL SECURITY (RLS)
ALTER TABLE document_sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_sections FORCE ROW LEVEL SECURITY;


-- 3. POLÍTICAS DE CONTROL DE ACCESO DESACOPLADAS (Lectura vs Escritura)

-- 3.1. POLÍTICA DE INGESTA (ETL n8n): Permite la inserción libre de fragmentos en segundo plano
CREATE POLICY rls_policy_insert ON document_sections
    FOR INSERT
    TO api_gateway
    WITH CHECK (true);

-- 3.2. POLÍTICA DE CONSULTA MULTIFACTORIAL (API FastAPI): Exige validación JWT transaccional
CREATE POLICY rls_policy_select ON document_sections
    FOR SELECT
    TO api_gateway
    USING (
        -- Regla Alfa: El rol 'admin' (Director de IA) puentea cualquier restricción sectorial
        current_setting('app.current_user_role', true) = 'admin'
        OR
        (
            -- Regla Beta: Coherencia estricta de Departamento (Aislamiento Sectorial)
            department = current_setting('app.current_user_dept', true)
            AND
            -- Regla Gamma: Evaluación Jerárquica del Nivel de Confidencialidad
            CASE
                WHEN confidentiality_level = 'Público' THEN true
                WHEN confidentiality_level = 'Interno' THEN current_setting('app.current_user_role', true) IN ('dept_high', 'dept_standard')
                WHEN confidentiality_level = 'Confidencial' THEN current_setting('app.current_user_role', true) = 'dept_high'
                ELSE false
            END
        )
    );
