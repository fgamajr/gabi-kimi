> Status: **histórico / deprecated (backend-only desde 2026-02-19)**  
> Este documento é referência de arquitetura antiga de dashboard/frontend.

# Dashboard Integration Architecture

## Executive Summary

Análise arquitetural para integração do dashboard React do projeto `user-first-view` com a API GABI, incluindo:
1. Adaptação para refletir apenas a fase "Discovering" implementada
2. Nova granularidade por link (Source → Link → Documents)
3. Implementação completa de segurança (JWT, Rate Limiting, Hardening)

---

## 1. Matriz de Gaps: Frontend Expectations vs Backend Reality

### 1.1 Pipeline Stages Gap

| Stage (Frontend) | Status Real | Ação Requerida |
|------------------|-------------|----------------|
| `harvest` | ✅ Implementado (Discovering) | Renomear para "discovery" |
| `sync` | ⚠️ Parcial (PostgreSQL storage) | Marcar como "completed" para links descobertos |
| `ingest` | ❌ Não implementado | Status "planned" |
| `processing` | ❌ Não implementado | Status "planned" |
| `embedding` | ❌ Não implementado | Status "planned" |
| `index` | ❌ Não implementado | Status "planned" |

**Decisão Arquitetural:** Criar um `PipelineStageService` que retorna estágios com base no estado real do sistema, não simulado.

### 1.2 Data Granularity Gap

| Nível | Frontend Espera | Backend Tem | Gap |
|-------|-----------------|-------------|-----|
| Source | ✅ Lista de sources | ✅ SourceRegistry | Nenhum |
| Link | ✅ Lista paginada de links | ✅ DiscoveredLinks | Falta paginação na API |
| Documents | ✅ Count por link | ❌ Não temos | Precisa nova entidade/tabela |

**Decisão Arquitetural:** Adicionar `DocumentEntity` para granularidade futura, mas por ora usar metadata JSONB.

### 1.3 API Contract Gaps

| Endpoint | Esperado | Existe | Status |
|----------|----------|--------|--------|
| `GET /stats` | ✅ StatsResponse | ✅ Implementado | Funcional |
| `GET /jobs` | ✅ JobsResponse | ✅ Implementado | Funcional |
| `GET /pipeline` | ✅ PipelineStage[] | ✅ Implementado | Precisa adaptar estágios |
| `GET /sources/{id}` | SourceDetails | ✅ Implementado | Precisa expandir |
| `GET /sources/{id}/links` | Paginated<Link> | ❌ NÃO EXISTE | **CRÍTICO** |
| `GET /sources/{id}/links/{linkId}` | LinkDetails | ❌ NÃO EXISTE | **CRÍTICO** |

---

## 2. Proposta Arquitetural

### 2.1 Novo Modelo de Dados

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SOURCE REGISTRY                                      │
│  ┌─────────────┐                                                            │
│  │ tcu_acordaos│                                                            │
│  │ - enabled   │                                                            │
│  │ - provider  │                                                            │
│  └──────┬──────┘                                                            │
│         │                                                                    │
│         ▼                                                                    │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                    DISCOVERED LINKS                                 │     │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐    │     │
│  │  │ Link #1         │  │ Link #2         │  │ Link #N         │    │     │
│  │  │ - url           │  │ - url           │  │ - url           │    │     │
│  │  │ - status        │  │ - status        │  │ - status        │    │     │
│  │  │ - discoveredAt  │  │ - discoveredAt  │  │ - discoveredAt  │    │     │
│  │  │ - metadata      │  │ - metadata      │  │ - metadata      │    │     │
│  │  │   {documentCount│  │   {documentCount│  │   {documentCount│    │     │
│  │  │    contentHash} │  │    contentHash} │  │    contentHash} │    │     │
│  │  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘    │     │
│  └───────────┼───────────────────┼───────────────────┼─────────────┘     │
│              │                   │                   │                      │
│              ▼                   ▼                   ▼                      │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                    INGEST QUEUE (Future)                            │     │
│  │  - link_id → document_extraction_job                               │     │
│  │  - status: pending → processing → completed                        │     │
│  └────────────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Adaptação do Pipeline para Realidade

```typescript
// Novo contrato adaptado
interface PipelineStage {
  name: 'discovery' | 'ingest' | 'processing' | 'embedding' | 'indexing';
  label: string;
  description: string;
  count: number;
  total: number;
  status: 'active' | 'completed' | 'planned' | 'error';
  availability: 'available' | 'coming_soon';
  lastActivity?: string;
}

// Mapeamento real
const pipelineMapping = {
  discovery:  {
    status: 'active',           // Temos dados reais
    availability: 'available',
    count: (source) => source.DiscoveredLinks.Count
  },
  ingest: {
    status: 'planned',          // Não implementado
    availability: 'coming_soon',
    count: 0,
    message: 'Phase 3 - Ingestion'
  },
  // ... demais estágios
};
```

---

## 3. Especificação de Segurança

### 3.1 Autenticação JWT

```csharp
// Configuração
services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(options => {
        options.TokenValidationParameters = new TokenValidationParameters {
            ValidateIssuer = true,
            ValidateAudience = true,
            ValidateLifetime = true,
            ValidateIssuerSigningKey = true,
            ValidIssuer = configuration["Jwt:Issuer"],
            ValidAudience = configuration["Jwt:Audience"],
            IssuerSigningKey = new SymmetricSecurityKey(
                Encoding.UTF8.GetBytes(configuration["Jwt:Key"])
            ),
            ClockSkew = TimeSpan.FromMinutes(5)
        };
    });
```

### 3.2 Autorização por Roles

```csharp
// Políticas
services.AddAuthorization(options => {
    options.AddPolicy("RequireAdmin", policy => 
        policy.RequireRole("Admin"));
    options.AddPolicy("RequireOperator", policy => 
        policy.RequireRole("Admin", "Operator"));
    options.AddPolicy("RequireViewer", policy => 
        policy.RequireRole("Admin", "Operator", "Viewer"));
});

// Uso
[Authorize(Roles = "Admin,Operator")]
[Authorize(Policy = "RequireOperator")]
```

### 3.3 Middleware Hardening Stack

```
Request Pipeline (ordem crítica):
┌─────────────────────────────────────────────────────────────┐
│ 1. ExceptionHandler      → Catch all, não expõe stack trace │
│ 2. HttpsRedirection      → Força HTTPS                      │
│ 3. Hsts                  → HTTP Strict Transport Security   │
│ 4. Cors                  → Restrito, whitelist              │
│ 5. RateLimiter           → Proteção contra abuse            │
│ 6. RequestSizeLimit      → Previne DOS por tamanho          │
│ 7. Authentication        → Valida JWT                       │
│ 8. Authorization         → Verifica permissões              │
│ 9. Endpoints             → Executa handlers                 │
└─────────────────────────────────────────────────────────────┘
```

### 3.4 Rate Limiting Configuration

```csharp
// Fixed Window - 100 requests/minuto para endpoints de leitura
// Token Bucket - 10 requests/minuto para operações de escrita
// Sliding Window - Login: 5 tentativas / 5 minutos
```

---

## 4. Novos Endpoints Especificados

### 4.1 Listar Links por Source (Paginado)

```
GET /api/v1/sources/{sourceId}/links?page=1&pageSize=20&status=pending&sort=discoveredAt_desc

Response 200:
{
  "data": [
    {
      "id": 12345,
      "url": "https://...",
      "status": "pending",
      "discoveredAt": "2025-02-12T10:30:00Z",
      "documentCount": 0,           // Extraído de metadata
      "contentHash": "abc123...",
      "nextStage": "ingest",        // Próxima fase disponível
      "nextStageStatus": "planned"  // Status da próxima fase
    }
  ],
  "pagination": {
    "page": 1,
    "pageSize": 20,
    "totalItems": 156,
    "totalPages": 8
  }
}
```

### 4.2 Detalhes de um Link

```
GET /api/v1/sources/{sourceId}/links/{linkId}

Response 200:
{
  "id": 12345,
  "sourceId": "tcu_acordaos",
  "url": "https://...",
  "status": "pending",
  "discoveredAt": "2025-02-12T10:30:00Z",
  "lastModified": "2025-01-15T08:00:00Z",
  "etag": "\"abc123\"",
  "contentLength": 15234,
  "contentHash": "sha256:...",
  "processAttempts": 0,
  "metadata": {
    "documentCount": 0,
    "contentType": "text/csv",
    "encoding": "utf-8"
  },
  "pipeline": {
    "discovery": { "status": "completed", "completedAt": "..." },
    "ingest": { "status": "planned", "message": "Phase 3" },
    "processing": { "status": "planned" },
    "embedding": { "status": "planned" },
    "indexing": { "status": "planned" }
  }
}
```

---

## 5. Plano de Implementação

### Fase 1: Contratos e API (Sem Segurança)
1. ✅ Criar novos DTOs (`DiscoveredLinkDetailDto`, `LinkListResponse`)
2. ✅ Implementar endpoints paginados
3. ✅ Adaptar `PipelineStage` para refletir realidade
4. ✅ Criar `LinkRepository` com paginação

### Fase 2: Segurança
1. Implementar JWT Authentication
2. Implementar Authorization Policies
3. Adicionar Rate Limiting
4. Hardening de middleware
5. Proteger todos endpoints

### Fase 3: Adaptação Frontend
1. Importar componentes React
2. Adaptar PipelineOverview para mostrar "planned"
3. Criar página de detalhes de source (lista de links)
4. Integrar com API real

### Fase 4: Testes
1. Testes de autenticação
2. Testes de autorização
3. Testes de paginação
4. Testes de rate limiting

---

## 6. Decisões Arquiteturais Críticas

### 6.1 Por que não simular dados dos estágios futuros?

**Princípio:** Não minta para o usuário. Mostrar estágios como "active" quando não estão implementados cria expectativas falsas e dívida técnica de UX.

**Solução:** Status `planned` com `availability: 'coming_soon'` comunica honestidade e mantém o roadmap visível.

### 6.2 Por que DocumentEntity agora?

Ainda que não tenhamos ingest implementado, criar a estrutura `metadata.documentCount` no `DiscoveredLink` permite:
- Migrar para entidade própria no futuro sem breaking changes
- Usar o mesmo contrato quando ingest for implementado
- Manter compatibilidade com o frontend

### 6.3 Por que JWT em vez de API Keys?

- JWT permite claims (roles, permissions, tenant)
- Stateless - escala horizontal sem shared storage
- Expiração nativa
- Revogação via blacklist (quando necessário)

---

## 7. Vulnerabilidades a Mitigar

| Vulnerabilidade | Mitigação | Implementação |
|-----------------|-----------|---------------|
| SQL Injection | EF Core parametrizado | ✅ Já implementado |
| Mass Assignment | DTOs sem setters públicos | ⚠️ Verificar |
| Overposting | `[BindNever]` em campos sensíveis | ⚠️ Adicionar |
| Path Traversal | Validar `sourceId` contra whitelist | ⚠️ Implementar |
| Stack Trace Exposure | Exception Handler global | ⚠️ Implementar |
| Brute Force | Rate Limiting em auth | ⚠️ Implementar |
| CORS Misconfig | Whitelist explícita | ⚠️ Restringir |
| JWT None Algorithm | Validar `alg` header | ✅ Configuração padrão |
| Timing Attacks | Constant-time comparison | ⚠️ Implementar |

---

## 8. Checklist de Implementação

- [ ] DTOs de link criados
- [ ] Repository com paginação
- [ ] Endpoints novos implementados
- [ ] Pipeline adaptado para realidade
- [ ] JWT Authentication configurado
- [ ] Authorization Policies definidas
- [ ] Rate Limiting implementado
- [ ] Middleware de segurança configurado
- [ ] Testes de autenticação
- [ ] Testes de autorização
- [ ] Testes de paginação
- [ ] Documentação atualizada
