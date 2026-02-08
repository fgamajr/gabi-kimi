"""
003_audit_functions

Migração de funções e triggers de auditoria.
Expande as capacidades de audit_log com hash chain, funções auxiliares
para inserção, verificação de integridade e views de consulta.

Revision ID: 003_audit_functions
Revises: 001_initial_schema
Create Date: 2026-02-06 17:00:00.000000+00:00

INVARIANTES:
- Audit log imutável (REVOKE UPDATE/DELETE)
- Hash chain para integridade (SHA-256)
- Funções de verificação de integridade
- Views otimizadas para consulta

DEPENDÊNCIAS:
- 001_initial_schema (tabela audit_log e função base)
- pgcrypto (extensão para funções digest)

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '003_audit_functions'
down_revision: Union[str, None] = '002_indexes_constraints'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Execute a migração de funções de auditoria."""
    
    # =======================================================================
    # 1. GARANTIR EXTENSÕES NECESSÁRIAS
    # =======================================================================
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    
    # =======================================================================
    # 2. FUNÇÃO: calculate_audit_hash() - VERSÃO MELHORADA
    # =======================================================================
    # Recria a função com lógica aprimorada de hash chain
    op.execute("""
        CREATE OR REPLACE FUNCTION calculate_audit_hash()
        RETURNS TRIGGER AS $$
        DECLARE
            prev_hash TEXT;
            data_to_hash TEXT;
            last_record RECORD;
        BEGIN
            -- Buscar o registro mais recente para obter o hash anterior
            SELECT event_hash INTO prev_hash
            FROM audit_log
            ORDER BY timestamp DESC, id DESC
            LIMIT 1;
            
            -- Se não houver registro anterior, usar '0' (genesis)
            NEW.previous_hash := COALESCE(prev_hash, '0');
            
            -- Construir string de dados para hash com todos os campos relevantes
            -- Ordem é importante para consistência
            data_to_hash := 
                COALESCE(NEW.event_type::text, '') || '|' ||
                COALESCE(NEW.severity::text, '') || '|' ||
                COALESCE(NEW.user_id::text, '') || '|' ||
                COALESCE(NEW.resource_type::text, '') || '|' ||
                COALESCE(NEW.resource_id::text, '') || '|' ||
                COALESCE(NEW.timestamp::text, NOW()::text) || '|' ||
                NEW.previous_hash || '|' ||
                COALESCE(NEW.request_id::text, '') || '|' ||
                COALESCE(NEW.correlation_id::text, '');
            
            -- Calcular SHA-256 do evento
            NEW.event_hash := encode(digest(data_to_hash, 'sha256'), 'hex');
            
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    
    # Adicionar comentário na função
    op.execute("""
        COMMENT ON FUNCTION calculate_audit_hash() IS 
        'Calcula hash SHA-256 do evento de auditoria com base nos dados do evento e no hash anterior. Implementa hash chain para garantir integridade.'
    """)
    
    # =======================================================================
    # 3. TRIGGER: calculate_audit_hash_trigger
    # =======================================================================
    # Recria o trigger para usar a função atualizada
    op.execute("""
        DROP TRIGGER IF EXISTS calculate_audit_hash_trigger ON audit_log
    """)
    
    op.execute("""
        CREATE TRIGGER calculate_audit_hash_trigger
        BEFORE INSERT ON audit_log
        FOR EACH ROW
        EXECUTE FUNCTION calculate_audit_hash()
    """)
    
    op.execute("""
        COMMENT ON TRIGGER calculate_audit_hash_trigger ON audit_log IS 
        'Trigger que calcula automaticamente o hash chain antes de inserir no audit_log'
    """)
    
    # =======================================================================
    # 4. FUNÇÃO: insert_audit_event() - API Simplificada
    # =======================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION insert_audit_event(
            p_event_type audit_event_type,
            p_severity audit_severity DEFAULT 'info',
            p_user_id TEXT DEFAULT NULL,
            p_user_email TEXT DEFAULT NULL,
            p_session_id TEXT DEFAULT NULL,
            p_ip_address INET DEFAULT NULL,
            p_user_agent TEXT DEFAULT NULL,
            p_resource_type TEXT DEFAULT NULL,
            p_resource_id TEXT DEFAULT NULL,
            p_action_details JSONB DEFAULT NULL,
            p_before_state JSONB DEFAULT NULL,
            p_after_state JSONB DEFAULT NULL,
            p_request_id TEXT DEFAULT NULL,
            p_correlation_id TEXT DEFAULT NULL
        )
        RETURNS UUID AS $$
        DECLARE
            new_id UUID;
        BEGIN
            INSERT INTO audit_log (
                event_type,
                severity,
                user_id,
                user_email,
                session_id,
                ip_address,
                user_agent,
                resource_type,
                resource_id,
                action_details,
                before_state,
                after_state,
                request_id,
                correlation_id
            ) VALUES (
                p_event_type,
                p_severity,
                p_user_id,
                p_user_email,
                p_session_id,
                p_ip_address,
                p_user_agent,
                p_resource_type,
                p_resource_id,
                p_action_details,
                p_before_state,
                p_after_state,
                p_request_id,
                p_correlation_id
            )
            RETURNING id INTO new_id;
            
            RETURN new_id;
        END;
        $$ LANGUAGE plpgsql
    """)
    
    op.execute("""
        COMMENT ON FUNCTION insert_audit_event IS 
        'Função auxiliar para inserir eventos de auditoria de forma simplificada. Retorna o UUID do evento criado.'
    """)
    
    # =======================================================================
    # 5. FUNÇÃO: verify_audit_chain() - Verificação de Integridade
    # =======================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION verify_audit_chain(
            p_start_time TIMESTAMP WITH TIME ZONE DEFAULT NULL,
            p_end_time TIMESTAMP WITH TIME ZONE DEFAULT NULL
        )
        RETURNS TABLE (
            total_records BIGINT,
            valid_hashes BIGINT,
            invalid_hashes BIGINT,
            broken_chain_count BIGINT,
            first_invalid_id UUID,
            first_invalid_timestamp TIMESTAMP WITH TIME ZONE,
            integrity_status TEXT
        ) AS $$
        DECLARE
            v_total BIGINT;
            v_valid BIGINT;
            v_invalid BIGINT;
            v_broken BIGINT;
            v_first_invalid_id UUID;
            v_first_invalid_ts TIMESTAMP WITH TIME ZONE;
        BEGIN
            -- Contar total de registros no período
            SELECT COUNT(*) INTO v_total
            FROM audit_log
            WHERE (p_start_time IS NULL OR timestamp >= p_start_time)
              AND (p_end_time IS NULL OR timestamp <= p_end_time);
            
            -- Verificar hashes válidos (recalcular e comparar)
            WITH recalculated AS (
                SELECT 
                    a.id,
                    a.timestamp,
                    a.previous_hash,
                    a.event_hash,
                    encode(digest(
                        COALESCE(a.event_type::text, '') || '|' ||
                        COALESCE(a.severity::text, '') || '|' ||
                        COALESCE(a.user_id::text, '') || '|' ||
                        COALESCE(a.resource_type::text, '') || '|' ||
                        COALESCE(a.resource_id::text, '') || '|' ||
                        COALESCE(a.timestamp::text, '') || '|' ||
                        a.previous_hash || '|' ||
                        COALESCE(a.request_id::text, '') || '|' ||
                        COALESCE(a.correlation_id::text, ''),
                        'sha256'
                    ), 'hex') AS calculated_hash
                FROM audit_log a
                WHERE (p_start_time IS NULL OR a.timestamp >= p_start_time)
                  AND (p_end_time IS NULL OR a.timestamp <= p_end_time)
            )
            SELECT 
                COUNT(*) FILTER (WHERE event_hash = calculated_hash),
                COUNT(*) FILTER (WHERE event_hash != calculated_hash),
                MIN(id) FILTER (WHERE event_hash != calculated_hash),
                MIN(timestamp) FILTER (WHERE event_hash != calculated_hash)
            INTO v_valid, v_invalid, v_first_invalid_id, v_first_invalid_ts
            FROM recalculated;
            
            -- Verificar integridade da cadeia (previous_hash deve corresponder ao event_hash anterior)
            WITH ordered_records AS (
                SELECT 
                    id,
                    timestamp,
                    previous_hash,
                    event_hash,
                    LAG(event_hash) OVER (ORDER BY timestamp, id) AS expected_previous_hash
                FROM audit_log
                WHERE (p_start_time IS NULL OR timestamp >= p_start_time)
                  AND (p_end_time IS NULL OR timestamp <= p_end_time)
            )
            SELECT COUNT(*) INTO v_broken
            FROM ordered_records
            WHERE expected_previous_hash IS NOT NULL 
              AND previous_hash != expected_previous_hash;
            
            -- Retornar resultados
            RETURN QUERY SELECT 
                v_total,
                v_valid,
                v_invalid,
                v_broken,
                v_first_invalid_id,
                v_first_invalid_ts,
                CASE 
                    WHEN v_invalid > 0 OR v_broken > 0 THEN 'CORROMPIDO'
                    WHEN v_total = 0 THEN 'VAZIO'
                    ELSE 'VALIDO'
                END;
        END;
        $$ LANGUAGE plpgsql
    """)
    
    op.execute("""
        COMMENT ON FUNCTION verify_audit_chain IS 
        'Verifica a integridade da hash chain do audit_log. Retorna estatísticas de validação e identifica o primeiro registro corrompido, se houver.'
    """)
    
    # =======================================================================
    # 6. FUNÇÃO: get_audit_chain_summary() - Resumo da Cadeia
    # =======================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION get_audit_chain_summary()
        RETURNS TABLE (
            total_events BIGINT,
            first_event_time TIMESTAMP WITH TIME ZONE,
            last_event_time TIMESTAMP WITH TIME ZONE,
            genesis_hash TEXT,
            latest_hash TEXT,
            events_by_severity JSONB,
            events_by_type JSONB
        ) AS $$
        BEGIN
            RETURN QUERY
            SELECT 
                COUNT(*)::BIGINT AS total_events,
                MIN(timestamp) AS first_event_time,
                MAX(timestamp) AS last_event_time,
                MIN(event_hash) FILTER (WHERE previous_hash = '0') AS genesis_hash,
                (SELECT event_hash FROM audit_log ORDER BY timestamp DESC, id DESC LIMIT 1) AS latest_hash,
                (SELECT jsonb_object_agg(severity::text, cnt) FROM (
                    SELECT severity, COUNT(*) as cnt FROM audit_log GROUP BY severity
                ) sub) AS events_by_severity,
                (SELECT jsonb_object_agg(event_type::text, cnt) FROM (
                    SELECT event_type, COUNT(*) as cnt FROM audit_log GROUP BY event_type
                ) sub) AS events_by_type
            FROM audit_log;
        END;
        $$ LANGUAGE plpgsql
    """)
    
    op.execute("""
        COMMENT ON FUNCTION get_audit_chain_summary IS 
        'Retorna um resumo estatístico da cadeia de auditoria incluindo contagem, timestamps e distribuição por severidade e tipo.'
    """)
    
    # =======================================================================
    # 7. FUNÇÃO: get_audit_events_by_resource() - Busca por Recurso
    # =======================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION get_audit_events_by_resource(
            p_resource_type TEXT,
            p_resource_id TEXT,
            p_limit INTEGER DEFAULT 100,
            p_offset INTEGER DEFAULT 0
        )
        RETURNS TABLE (
            event_id UUID,
            event_timestamp TIMESTAMP WITH TIME ZONE,
            event_type audit_event_type,
            severity audit_severity,
            user_id TEXT,
            action_details JSONB,
            event_hash TEXT,
            chain_valid BOOLEAN
        ) AS $$
        BEGIN
            RETURN QUERY
            SELECT 
                a.id AS event_id,
                a.timestamp AS event_timestamp,
                a.event_type,
                a.severity,
                a.user_id,
                a.action_details,
                a.event_hash,
                -- Verificar se o hash corresponde ao esperado
                (a.event_hash = encode(digest(
                    COALESCE(a.event_type::text, '') || '|' ||
                    COALESCE(a.severity::text, '') || '|' ||
                    COALESCE(a.user_id::text, '') || '|' ||
                    COALESCE(a.resource_type::text, '') || '|' ||
                    COALESCE(a.resource_id::text, '') || '|' ||
                    COALESCE(a.timestamp::text, '') || '|' ||
                    a.previous_hash || '|' ||
                    COALESCE(a.request_id::text, '') || '|' ||
                    COALESCE(a.correlation_id::text, ''),
                    'sha256'
                ), 'hex')) AS chain_valid
            FROM audit_log a
            WHERE a.resource_type = p_resource_type
              AND a.resource_id = p_resource_id
            ORDER BY a.timestamp DESC, a.id DESC
            LIMIT p_limit
            OFFSET p_offset;
        END;
        $$ LANGUAGE plpgsql
    """)
    
    op.execute("""
        COMMENT ON FUNCTION get_audit_events_by_resource IS 
        'Busca eventos de auditoria relacionados a um recurso específico, retornando também a validade do hash chain para cada evento.'
    """)
    
    # =======================================================================
    # 8. FUNÇÃO: archive_old_audit_logs() - Arquivamento (Soft Delete)
    # =======================================================================
    op.execute("""
        CREATE OR REPLACE FUNCTION archive_old_audit_logs(
            p_retention_days INTEGER DEFAULT 2555,  -- ~7 anos
            p_batch_size INTEGER DEFAULT 10000
        )
        RETURNS TABLE (
            archived_count INTEGER,
            oldest_archived TIMESTAMP WITH TIME ZONE,
            newest_archived TIMESTAMP WITH TIME ZONE
        ) AS $$
        DECLARE
            v_cutoff_date TIMESTAMP WITH TIME ZONE;
            v_count INTEGER;
            v_oldest TIMESTAMP WITH TIME ZONE;
            v_newest TIMESTAMP WITH TIME ZONE;
        BEGIN
            -- Calcular data de corte
            v_cutoff_date := NOW() - (p_retention_days || ' days')::INTERVAL;
            
            -- Criar tabela de arquivamento se não existir
            CREATE TABLE IF NOT EXISTS audit_log_archive (
                LIKE audit_log INCLUDING ALL,
                archived_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                archive_reason TEXT DEFAULT 'retention_policy'
            );
            
            -- Obter range de registros a serem arquivados
            SELECT MIN(timestamp), MAX(timestamp)
            INTO v_oldest, v_newest
            FROM audit_log
            WHERE timestamp < v_cutoff_date;
            
            -- Mover registros para arquivamento (em batch)
            WITH archived AS (
                DELETE FROM audit_log
                WHERE id IN (
                    SELECT id FROM audit_log
                    WHERE timestamp < v_cutoff_date
                    LIMIT p_batch_size
                )
                RETURNING *
            )
            INSERT INTO audit_log_archive (
                id, timestamp, event_type, severity, user_id, user_email,
                session_id, ip_address, user_agent, resource_type, resource_id,
                action_details, before_state, after_state, previous_hash,
                event_hash, request_id, correlation_id
            )
            SELECT 
                id, timestamp, event_type, severity, user_id, user_email,
                session_id, ip_address, user_agent, resource_type, resource_id,
                action_details, before_state, after_state, previous_hash,
                event_hash, request_id, correlation_id
            FROM archived;
            
            GET DIAGNOSTICS v_count = ROW_COUNT;
            
            RETURN QUERY SELECT v_count, v_oldest, v_newest;
        END;
        $$ LANGUAGE plpgsql
    """)
    
    op.execute("""
        COMMENT ON FUNCTION archive_old_audit_logs IS 
        'Move registros antigos do audit_log para audit_log_archive baseado na política de retenção. Padrão: 2555 dias (~7 anos).'
    """)
    
    # =======================================================================
    # 9. VIEW: audit_log_recent - Últimos Eventos
    # =======================================================================
    op.execute("""
        CREATE OR REPLACE VIEW audit_log_recent AS
        SELECT 
            id,
            timestamp,
            event_type,
            severity,
            user_id,
            user_email,
            resource_type,
            resource_id,
            action_details,
            event_hash,
            previous_hash,
            request_id,
            correlation_id,
            -- Verificação visual do chain
            CASE 
                WHEN previous_hash = '0' THEN 'GENESIS'
                ELSE 'LINKED'
            END AS chain_status
        FROM audit_log
        WHERE timestamp >= NOW() - INTERVAL '24 hours'
        ORDER BY timestamp DESC
    """)
    
    op.execute("""
        COMMENT ON VIEW audit_log_recent IS 
        'View dos eventos de auditoria das últimas 24 horas com status da cadeia'
    """)
    
    # =======================================================================
    # 10. VIEW: audit_log_statistics - Estatísticas
    # =======================================================================
    op.execute("""
        CREATE OR REPLACE VIEW audit_log_statistics AS
        SELECT 
            DATE_TRUNC('hour', timestamp) AS hour,
            event_type,
            severity,
            COUNT(*) AS event_count,
            COUNT(DISTINCT user_id) AS unique_users,
            COUNT(DISTINCT resource_id) AS unique_resources
        FROM audit_log
        WHERE timestamp >= NOW() - INTERVAL '30 days'
        GROUP BY DATE_TRUNC('hour', timestamp), event_type, severity
        ORDER BY hour DESC, event_count DESC
    """)
    
    op.execute("""
        COMMENT ON VIEW audit_log_statistics IS 
        'View de estatísticas agregadas de auditoria por hora (últimos 30 dias)'
    """)
    
    # =======================================================================
    # 11. VIEW: audit_security_events - Eventos de Segurança
    # =======================================================================
    op.execute("""
        CREATE OR REPLACE VIEW audit_security_events AS
        SELECT 
            id,
            timestamp,
            event_type,
            severity,
            user_id,
            user_email,
            ip_address,
            resource_type,
            resource_id,
            action_details,
            request_id
        FROM audit_log
        WHERE severity IN ('error', 'critical')
           OR event_type IN (
               'user_login',
               'user_logout',
               'permission_changed',
               'config_changed',
               'dlq_message_created'
           )
        ORDER BY timestamp DESC
    """)
    
    op.execute("""
        COMMENT ON VIEW audit_security_events IS 
        'View de eventos de segurança relevantes para monitoramento (logins, alterações de permissão, erros críticos)'
    """)
    
    # =======================================================================
    # 12. POLÍTICA DE SEGURANÇA: REVOKE UPDATE/DELETE
    # =======================================================================
    # Garantir que audit_log seja imutável
    op.execute('REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC')
    
    # Criar política RLS (Row Level Security) se necessário
    op.execute("""
        DO $$
        BEGIN
            -- Habilitar RLS na tabela audit_log
            ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
            
            -- Criar política para permitir apenas INSERT
            DROP POLICY IF EXISTS audit_log_insert_only ON audit_log;
            CREATE POLICY audit_log_insert_only ON audit_log
                FOR INSERT WITH CHECK (true);
        EXCEPTION
            WHEN insufficient_privilege THEN
                -- Ignorar se não tiver privilégios suficientes
                NULL;
        END;
        $$;
    """)
    
    # =======================================================================
    # 13. ÍNDICES ADICIONAIS PARA AUDITORIA
    # =======================================================================
    # Índice para busca por severidade e timestamp
    op.create_index(
        'idx_audit_severity_timestamp',
        'audit_log',
        ['severity', sa.text('timestamp DESC')],
        postgresql_where=sa.text("severity IN ('error', 'critical')")
    )
    
    # Índice para busca por correlation_id
    op.create_index(
        'idx_audit_correlation',
        'audit_log',
        ['correlation_id'],
        postgresql_where=sa.text('correlation_id IS NOT NULL')
    )
    
    # Índice para hash chain (verificação rápida)
    op.create_index(
        'idx_audit_hash_chain',
        'audit_log',
        ['previous_hash', 'event_hash']
    )
    
    # =======================================================================
    # 14. COMENTÁRIOS FINAIS
    # =======================================================================
    op.execute("""
        COMMENT ON TABLE audit_log IS 
        'Log de auditoria imutável com hash chain SHA-256 para garantia de integridade. Use funções insert_audit_event() para inserir. NUNCA execute UPDATE ou DELETE.'
    """)


def downgrade() -> None:
    """Reverta a migração removendo funções e views de auditoria."""
    
    # =======================================================================
    # REMOVER ÍNDICES ADICIONAIS
    # =======================================================================
    op.drop_index('idx_audit_hash_chain', table_name='audit_log')
    op.drop_index('idx_audit_correlation', table_name='audit_log')
    op.drop_index('idx_audit_severity_timestamp', table_name='audit_log')
    
    # =======================================================================
    # REMOVER POLÍTICA RLS
    # =======================================================================
    op.execute("""
        DO $$
        BEGIN
            DROP POLICY IF EXISTS audit_log_insert_only ON audit_log;
            ALTER TABLE audit_log DISABLE ROW LEVEL SECURITY;
        EXCEPTION
            WHEN insufficient_privilege THEN
                NULL;
        END;
        $$;
    """)
    
    # Restaurar permissões (com cautela)
    op.execute('GRANT UPDATE, DELETE ON audit_log TO PUBLIC')
    
    # =======================================================================
    # REMOVER VIEWS
    # =======================================================================
    op.execute('DROP VIEW IF EXISTS audit_security_events')
    op.execute('DROP VIEW IF EXISTS audit_log_statistics')
    op.execute('DROP VIEW IF EXISTS audit_log_recent')
    
    # =======================================================================
    # REMOVER FUNÇÕES
    # =======================================================================
    op.execute('DROP FUNCTION IF EXISTS archive_old_audit_logs(INTEGER, INTEGER)')
    op.execute('DROP FUNCTION IF EXISTS get_audit_events_by_resource(TEXT, TEXT, INTEGER, INTEGER)')
    op.execute('DROP FUNCTION IF EXISTS get_audit_chain_summary()')
    op.execute('DROP FUNCTION IF EXISTS verify_audit_chain(TIMESTAMP WITH TIME ZONE, TIMESTAMP WITH TIME ZONE)')
    op.execute('DROP FUNCTION IF EXISTS insert_audit_event(audit_event_type, audit_severity, TEXT, TEXT, TEXT, INET, TEXT, TEXT, TEXT, JSONB, JSONB, JSONB, TEXT, TEXT)')
    
    # =======================================================================
    # RESTAURAR FUNÇÃO E TRIGGER ORIGINAIS (simplificados)
    # =======================================================================
    op.execute('DROP TRIGGER IF EXISTS calculate_audit_hash_trigger ON audit_log')
    
    op.execute("""
        CREATE OR REPLACE FUNCTION calculate_audit_hash()
        RETURNS TRIGGER AS $$
        DECLARE
            prev_hash TEXT;
            data_to_hash TEXT;
        BEGIN
            SELECT event_hash INTO prev_hash
            FROM audit_log
            ORDER BY timestamp DESC
            LIMIT 1;
            
            NEW.previous_hash := COALESCE(prev_hash, '0');
            
            data_to_hash := NEW.event_type || '|' || 
                            COALESCE(NEW.user_id, '') || '|' || 
                            COALESCE(NEW.resource_id, '') || '|' ||
                            NEW.timestamp::text || '|' ||
                            NEW.previous_hash;
            
            NEW.event_hash := encode(digest(data_to_hash, 'sha256'), 'hex');
            
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    
    op.execute("""
        CREATE TRIGGER calculate_audit_hash_trigger
        BEFORE INSERT ON audit_log
        FOR EACH ROW
        EXECUTE FUNCTION calculate_audit_hash()
    """)
