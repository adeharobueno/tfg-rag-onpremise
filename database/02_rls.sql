-- =============================================================================
-- TRABAJO DE FIN DE GRADO - ETSIIT UGR
-- Fichero 02_rls.sql: Automatización de Privilegios Mínimos y Cortafuegos RLS
-- =============================================================================

-- 1. CREACIÓN DEL ROL DE SERVICIO CON BARRERAS DE CONTROL (Mínimo Privilegio)
-- Se comprueba si existe previamente para garantizar la reproducibilidad del script
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_user WHERE usename = 'api_gateway') THEN
        CREATE USER api_gateway WITH PASSWORD 'App_Pass_Gateway_Secure_2026?';
    END IF;
END $$;

-- Revocar privilegios globales por defecto en el esquema público por seguridad
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO api_gateway;

-- Otorgar permisos estrictos de manipulación de datos (DML) al rol de la API
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE users TO api_gateway;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE document_sections TO api_gateway;

-- Permitir el uso de secuencias autoincrementales
GRANT USAGE, SELECT ON SEQUENCE users_user_id_seq TO api_gateway;
GRANT USAGE, SELECT ON SEQUENCE document_sections_section_id_seq TO api_gateway;


-- 2. ACTIVACIÓN DE ROW-LEVEL SECURITY (RLS)
ALTER TABLE document_sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_sections FORCE ROW LEVEL SECURITY; -- Obliga RLS incluso para dueños de tablas no superusuarios


-- 3. DISEÑO DE LA POLÍTICA MULTIFACTORIAL EXIGIDA EN EL CAPÍTULO 4
CREATE POLICY rls_policy_document_sections ON document_sections
AS RESTRICTIVE
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
