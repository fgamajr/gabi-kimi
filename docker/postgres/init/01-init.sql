-- GABI - PostgreSQL Initialization
-- Este script é executado na primeira vez que o container inicia

-- Criar extensões úteis
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- Para busca textual

-- Configurar timezone
SET timezone = 'America/Sao_Paulo';

-- Comentários
COMMENT ON DATABASE gabi IS 'GABI - Sistema de Ingestão e Busca de Dados Jurídicos TCU';
