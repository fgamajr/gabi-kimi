# Data Governance: Sync Pipeline do GABI

**Escopo**: Tabelas de ingestão (`ingest_jobs`, `discovered_links`, `source_registry`, `documents`) e processo de sincronização Snapshot + Diff + Reconcile.  
**Versão**: 1.0  
**Data**: 2026-02-13

---

## 1. Visão Geral

Este documento estabelece verificações de governança de dados para o pipeline de sincronização do GABI, garantindo:

- **Integridade referencial**: Relações consistentes entre sources, jobs e documentos
- **Audit trail**: Rastreabilidade completa de operações (criação, modificação, remoção)
- **Reconciliação confiável**: Soft delete para itens removidos na fonte, preservando histórico
- **Performance**: Índices adequados para operações de diff e reconcile

---

## 2. Checklist de Schema

### 2.1 Primary Keys (PK)

Todas as tabelas principais devem ter chaves primárias estáveis:

| Tabela | PK Esperada | Tipo | Verificação |
|--------|-------------|------|-------------|
| `ingest_jobs` | `id` | UUID/GUID | [ ] PK definida com `DEFAULT gen_random_uuid()` |
| `discovered_links` | `id` | BIGINT (serial) | [ ] PK auto-incremento ou UUID |
| `source_registry` | `id` | UUID ou VARCHAR(100) | [ ] PK usando `source_id` do YAML |
| `documents` | `id` | UUID/GUID | [ ] PK definida; **NÃO usar ID externo como PK** |

> **Recomendação**: Usar UUIDs para `ingest_jobs` e `documents` permite merge de dados entre ambientes sem conflitos.

### 2.2 Foreign Keys (FK)

Relacionamentos obrigatórios para integridade referencial:

| FK | Tabela Origem | Tabela Destino | Ação ON DELETE | Verificação |
|----|---------------|----------------|----------------|-------------|
| `fk_jobs_source` | `ingest_jobs.source_id` | `source_registry.id` | RESTRICT | [ ] FK criada |
| `fk_jobs_link` | `ingest_jobs.link_id` | `discovered_links.id` | SET NULL | [ ] FK criada (permite job sem link) |
| `fk_jobs_parent` | `ingest_jobs.parent_job_id` | `ingest_jobs.id` | SET NULL | [ ] Self-referencing FK para hierarquia |
| `fk_links_source` | `discovered_links.source_id` | `source_registry.id` | CASCADE | [ ] Remoção de source remove links |
| `fk_documents_source` | `documents.source_id` | `source_registry.id` | RESTRICT | [ ] Source obrigatória para documento |

> **Nota**: `ON DELETE RESTRICT` em `documents` evita remoção acidental de sources com documentos; usar soft delete sempre.

### 2.3 Índices Estratégicos

Índices para operações eficientes de diff, reconcile e consultas:

#### Índices de Source

| Índice | Colunas | Propósito | Verificação |
|--------|---------|-----------|-------------|
| `idx_jobs_source_status` | `(source_id, status)` | Listar jobs pendentes por source | [ ] Criado |
| `idx_links_source` | `(source_id)` | Listar links descobertos por source | [ ] Criado |
| `idx_documents_source` | `(source_id)` | Contar documentos por source | [ ] Criado |

#### Índices de Hash (Chave de Unicidade)

| Índice | Colunas | Tipo | Propósito | Verificação |
|--------|---------|------|-----------|-------------|
| `idx_documents_hash_source` | `(content_hash, source_id)` | UNIQUE | **Prevenir duplicatas** na mesma source | [ ] Criado |
| `idx_documents_external_key` | `(source_id, external_id)` | UNIQUE | **Natural key**: identificador estável da fonte | [ ] Criado |

> **Importante**: `content_hash` sozinho NÃO deve ser único globalmente (documentos idênticos podem vir de sources diferentes). A unicidade é `(content_hash, source_id)`.

#### Índices de Remoção (Soft Delete)

| Índice | Colunas | Propósito | Verificação |
|--------|---------|-----------|-------------|
| `idx_documents_removed` | `(removed_from_source_at)` WHERE `removed_from_source_at IS NOT NULL` | Listar documentos removidos (partial index) | [ ] Criado |
| `idx_documents_active` | `(source_id, status)` WHERE `removed_from_source_at IS NULL` | Listar documentos ativos por source | [ ] Criado (partial) |

#### Índices de Auditoria

| Índice | Colunas | Propósito | Verificação |
|--------|---------|-----------|-------------|
| `idx_jobs_created` | `(created_at)` | Ordenar jobs por data | [ ] Criado |
| `idx_documents_modified` | `(updated_at)` | Detectar modificações recentes | [ ] Criado |

### 2.4 Colunas de Auditoria

Todas as tabelas devem ter trilha de auditoria completa:

#### Tabela `ingest_jobs`

| Coluna | Tipo | Default | Verificação |
|--------|------|---------|-------------|
| `created_at` | TIMESTAMPTZ | `NOW()` | [ ] Com default |
| `updated_at` | TIMESTAMPTZ | `NOW()` | [ ] Trigger para auto-update |
| `started_at` | TIMESTAMPTZ | NULL | [ ] Nullable |
| `completed_at` | TIMESTAMPTZ | NULL | [ ] Nullable |

#### Tabela `discovered_links`

| Coluna | Tipo | Default | Verificação |
|--------|------|---------|-------------|
| `created_at` | TIMESTAMPTZ | `NOW()` | [ ] Com default |
| `updated_at` | TIMESTAMPTZ | `NOW()` | [ ] Trigger para auto-update |
| `last_checked_at` | TIMESTAMPTZ | NULL | [ ] Para change detection |

#### Tabela `source_registry`

| Coluna | Tipo | Default | Verificação |
|--------|------|---------|-------------|
| `created_at` | TIMESTAMPTZ | `NOW()` | [ ] Com default |
| `updated_at` | TIMESTAMPTZ | `NOW()` | [ ] Trigger para auto-update |
| `last_refresh_at` | TIMESTAMPTZ | NULL | [ ] Última sincronização |

#### Tabela `documents`

| Coluna | Tipo | Default | Verificação |
|--------|------|---------|-------------|
| `created_at` | TIMESTAMPTZ | `NOW()` | [ ] Com default |
| `updated_at` | TIMESTAMPTZ | `NOW()` | [ ] Trigger para auto-update |
| `discovered_at` | TIMESTAMPTZ | `NOW()` | [ ] Primeira descoberta |
| `fetched_at` | TIMESTAMPTZ | NULL | [ ] Quando conteúdo foi baixado |
| `hashed_at` | TIMESTAMPTZ | NULL | [ ] Quando hash foi calculado |
| `indexed_at` | TIMESTAMPTZ | NULL | [ ] Quando indexado no ES |

#### Colunas de Soft Delete (Exclusivo para `documents`)

| Coluna | Tipo | Default | Verificação |
|--------|------|---------|-------------|
| `removed_from_source_at` | TIMESTAMPTZ | NULL | [ ] NULL = ativo; valor = removido |
| `removed_reason` | VARCHAR(50) | NULL | [ ] 'source_deleted', 'manual', 'expired' |

> **Regra**: NUNCA usar `DELETE FROM documents`. Sempre usar `UPDATE ... SET removed_from_source_at = NOW()`.

---

## 3. Checklist de Dados e Retenção

### 3.1 Política de Soft Delete

| Aspecto | Regra | Verificação |
|---------|-------|-------------|
| Marcação | Documento é "removido" quando `removed_from_source_at IS NOT NULL` | [ ] Implementado |
| Consultas ativas | Todas as queries devem filtrar `WHERE removed_from_source_at IS NULL` | [ ] Views ou helpers criados |
| Auditoria | Motivo da remoção registrado em `removed_reason` | [ ] Campo obrigatório no processo |

### 3.2 Política de Retenção

| Cenário | Ação | Período | Implementação | Verificação |
|---------|------|---------|---------------|-------------|
| Documentos removidos | **Arquivamento** (exportar para S3/Glacier) | Após 90 dias | Job periódico exporta e marca `archived_at` | [ ] Job criado |
| Documentos removidos | **Hard delete** (apenas após arquivamento) | Após 30 dias do arquivamento | Job confirma arquivamento antes de deletar | [ ] Política definida |
| Jobs completados | **Purge** (remover jobs antigos) | Após 30 dias | Job limpa `ingest_jobs` com `completed_at < NOW() - 30d` | [ ] Job de purge criado |
| Links descobertos | **Atualização** | A cada sync | Atualizar `last_checked_at`; remover se não re-aparecerem em 180 dias | [ ] Política definida |

> **Recomendação**: Implementar job `DataRetentionJob` que roda semanalmente e executa as políticas acima, registrando métricas.

### 3.3 Estatísticas de Sync

Manter métricas de reconciliação para observabilidade:

| Métrica | Tipo | Fonte | Verificação |
|---------|------|-------|-------------|
| `sync_run_id` | UUID | Identificador da execução de sync | [ ] Tabela `sync_runs` criada |
| `documents_added` | INT | Contagem de INSERTs | [ ] Registrado |
| `documents_updated` | INT | Contagem de UPDATEs (hash mudou) | [ ] Registrado |
| `documents_removed` | INT | Contagem de soft deletes | [ ] Registrado |
| `documents_unchanged` | INT | Contagem de skips (idempotente) | [ ] Registrado |
| `sync_duration_ms` | BIGINT | Tempo total de reconcile | [ ] Registrado |

**Tabela sugerida**: `sync_runs`

```sql
CREATE TABLE sync_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id VARCHAR(100) NOT NULL REFERENCES source_registry(id),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL, -- 'running', 'completed', 'failed'
    documents_added INT DEFAULT 0,
    documents_updated INT DEFAULT 0,
    documents_removed INT DEFAULT 0,
    documents_unchanged INT DEFAULT 0,
    error_message TEXT,
    snapshot_hash VARCHAR(64), -- Hash do snapshot para idempotência
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 4. Checklist de Rastreabilidade

### 4.1 Source Attribution

Todo documento deve ter source clara:

| Requisito | Implementação | Verificação |
|-----------|---------------|-------------|
| `source_id` obrigatório | `NOT NULL` em `documents.source_id` | [ ] Constraint criada |
| Source válida | FK para `source_registry` | [ ] FK criada |
| Referência estável | Usar `external_id` (natural key) + `source_id` | [ ] Índice único criado |

### 4.2 Ciclo de Vida do Documento

Estados devem ser rastreáveis:

```
discovered → fetched → hashed → parsed → chunked → indexed
   ↑           ↑        ↑        ↑        ↑         ↑
discovered_at fetched_at hashed_at parsed_at ... indexed_at
```

| Timestamp | Propósito | Verificação |
|-----------|-----------|-------------|
| `discovered_at` | Quando apareceu pela primeira vez em um snapshot | [ ] Preenchido no INSERT |
| `fetched_at` | Quando o conteúdo foi baixado da fonte | [ ] Preenchido após fetch |
| `hashed_at` | Quando o hash foi calculado | [ ] Preenchido após hash |
| `indexed_at` | Quando indexado no Elasticsearch | [ ] Preenchido após index |
| `removed_from_source_at` | Quando deixou de existir na fonte | [ ] Preenchido no reconcile de remoção |

### 4.3 Rastreabilidade de Remoções

| Requisito | Implementação | Verificação |
|-----------|---------------|-------------|
| Motivo documentado | `removed_reason` preenchido com enum | [ ] Valores permitidos: 'source_deleted', 'manual', 'expired' |
| Sync run vinculado | `last_sync_run_id` em documents (opcional) | [ ] Saber qual sync removeu |
| Query de removidos | View `v_removed_documents` | [ ] Criada para auditoria |
| Undelete possível | Update `removed_from_source_at = NULL` | [ ] Procedimento documentado |

**View sugerida**:

```sql
CREATE VIEW v_removed_documents AS
SELECT 
    d.id,
    d.source_id,
    d.external_id,
    d.title,
    d.removed_from_source_at,
    d.removed_reason,
    d.discovered_at,
    (d.removed_from_source_at - d.discovered_at) as lifetime
FROM documents d
WHERE d.removed_from_source_at IS NOT NULL
ORDER BY d.removed_from_source_at DESC;
```

---

## 5. Recomendações Prioritárias

### 🔴 Prioridade 1 (Implementar Imediatamente)

| # | Recomendação | Justificativa |
|---|--------------|---------------|
| 1 | **Criar índice único `(source_id, external_id)`** em `documents` | Garante natural key estável; evita duplicatas na mesma fonte |
| 2 | **Criar índice único `(content_hash, source_id)`** | Garante deduplicação por conteúdo na mesma source |
| 3 | **Implementar `removed_from_source_at` + `removed_reason`** | Core do soft delete; audit trail de remoções |
| 4 | **Criar tabela `sync_runs`** | Observabilidade; métricas de reconcile; debugging |

### 🟡 Prioridade 2 (Próxima Sprint)

| # | Recomendação | Justificativa |
|---|--------------|---------------|
| 5 | **Criar partial index `idx_documents_active`** | Performance de queries que ignoram removidos |
| 6 | **Implementar triggers `updated_at`** | Audit trail automático de modificações |
| 7 | **Criar job `DataRetentionJob`** | Automação de arquivamento e purge |
| 8 | **Criar view `v_removed_documents`** | Facilitar auditoria de remoções |

### 🟢 Prioridade 3 (Manutenção Contínua)

| # | Recomendação | Justificativa |
|---|--------------|---------------|
| 9 | **Monitorar tamanho do índice `idx_documents_hash_source`** | Índice de hash pode crescer muito; considerar partições |
| 10 | **Documentar procedimento de undelete** | Caso remoção seja revertida na fonte |
| 11 | **Implementar `snapshot_hash` em `sync_runs`** | Idempotência: skip sync se snapshot idêntico |
| 12 | **Auditoria trimestral** de documentos removidos | Verificar se política de retenção está sendo seguida |

---

## 6. Validação do Zero Kelvin

Ao subir o sistema do zero, verificar:

```bash
# 1. Schema
./scripts/db-verify.sh --check-governance

# 2. Índices
psql -c "\di idx_documents_*"

# 3. Constraints
psql -c "\d documents"

# 4. Dados de teste
INSERT INTO source_registry (id, name, provider) VALUES ('test_tcu', 'Test', 'TCU');
INSERT INTO documents (source_id, external_id, content_hash, title) 
VALUES ('test_tcu', 'DOC-001', 'abc123...', 'Test');
-- Deve falhar: duplicata de (source_id, external_id)

# 5. Soft delete
UPDATE documents SET removed_from_source_at = NOW(), removed_reason = 'manual' 
WHERE external_id = 'DOC-001';
SELECT * FROM v_removed_documents;
```

---

## 7. Referências

- Arquitetura: `PIPELINE_COMPLETO_ROADMAP.md`
- Plano de Sincronização: `syncronizacao.md`
- Schema Atual: `src/Gabi.Postgres/Migrations/`
- Skill de Governança: `.agents/skills/data-governance-audit/SKILL.md`

---

**Próxima Revisão**: Após implementação da migration `AddSoftDeleteAndNaturalKey`
