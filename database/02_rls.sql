-- =============================================================================
-- TRABAJO DE FIN DE GRADO - ETSIIT UGR
-- Fichero 02_rls.sql: Automatización de Privilegios Mínimos y Cortafuegos RLS
-- =============================================================================

-- 1. CREACIÓN DEL ROL DE SERVICIO CON BARRERAS DE CONTROL (Mínimo Privilegio)
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
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE audit_logs TO api_gateway;

-- Permitir el uso de secuencias autoincrementales
GRANT USAGE, SELECT ON SEQUENCE users_user_id_seq TO api_gateway;
GRANT USAGE, SELECT ON SEQUENCE document_sections_section_id_seq TO api_gateway;
GRANT USAGE, SELECT ON SEQUENCE audit_logs_log_id_seq TO api_gateway;

-- =============================================================================
-- 2. TRIGGER: Sincroniza metadatos JSONB a columnas relacionales
-- =============================================================================
CREATE OR REPLACE FUNCTION sync_metadata_columns()
RETURNS TRIGGER AS $$
BEGIN
    NEW.department := NEW.metadata->>'department';
    NEW.confidentiality_level := NEW.metadata->>'confidentiality_level';
    IF NEW.metadata->>'valid_until' IS NOT NULL THEN
        NEW.valid_until := (NEW.metadata->>'valid_until')::TIMESTAMP WITH TIME ZONE;
    END IF;
    IF NEW.metadata->>'document_hash' IS NOT NULL THEN
        NEW.document_hash := NEW.metadata->>'document_hash';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
-- DROP IF EXISTS garantiza idempotencia en redespliegues
DROP TRIGGER IF EXISTS trg_sync_metadata ON document_sections;

CREATE TRIGGER trg_sync_metadata
BEFORE INSERT OR UPDATE ON document_sections
FOR EACH ROW EXECUTE FUNCTION sync_metadata_columns();

-- =============================================================================
-- 3. ACTIVACIÓN DE ROW-LEVEL SECURITY (RLS)
-- =============================================================================
ALTER TABLE document_sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_sections FORCE ROW LEVEL SECURITY;

-- =============================================================================
-- 4. POLÍTICAS DE SEGURIDAD RLS
-- =============================================================================

-- Política de inserción: api_gateway puede insertar sin restricciones
DROP POLICY IF EXISTS rls_policy_insert ON document_sections;
CREATE POLICY rls_policy_insert ON document_sections
FOR INSERT
TO api_gateway
WITH CHECK (true);

-- Política de borrado: api_gateway puede borrar sin restricciones
DROP POLICY IF EXISTS rls_policy_delete ON document_sections;
CREATE POLICY rls_policy_delete ON document_sections
FOR DELETE
TO api_gateway
USING (true);

-- Política PERMISSIVE: Autorización jerárquica por rol y departamento
DROP POLICY IF EXISTS rls_policy_select ON document_sections;
CREATE POLICY rls_policy_select ON document_sections
FOR SELECT
TO api_gateway
USING (
    current_setting('app.current_user_role', true) = 'admin'
    OR 
    (
        department = current_setting('app.current_user_dept', true)
        AND 
        CASE 
            WHEN confidentiality_level = 'Público' THEN true
            WHEN confidentiality_level = 'Interno' THEN 
                current_setting('app.current_user_role', true) 
                IN ('dept_high', 'dept_standard')
            WHEN confidentiality_level = 'Confidencial' THEN 
                current_setting('app.current_user_role', true) = 'dept_high'
            ELSE false
        END
    )
);

-- Política RESTRICTIVA: Garantiza que nunca se sirven documentos expirados
-- independientemente de las políticas permisivas de rol y departamento
DROP POLICY IF EXISTS rls_policy_no_expired ON document_sections;
CREATE POLICY rls_policy_no_expired ON document_sections
AS RESTRICTIVE
FOR SELECT
TO api_gateway
USING (
    valid_until IS NULL 
    OR valid_until > CURRENT_TIMESTAMP
);
