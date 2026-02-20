# AGENTS.md - GABI (Sistema de Ingestão e Busca Jurídica TCU)

> Este arquivo é destinado a agentes de IA. Contém informações essenciais sobre a arquitetura, convenções e processos de desenvolvimento do projeto.

## Governança de Instruções para IA (canônica)

1. `AGENTS.md` é a fonte canônica de instruções do repositório.
2. `CLAUDE.md` e `GEMINI.md` devem permanecer wrappers mínimos apontando para este arquivo.
3. Priorizar constraints e resultados mensuráveis (SLOs, testes, evidência), evitando workflows rígidos quando o padrão já estiver explícito no código.
4. Regras inegociáveis: arquitetura em camadas, budget de memória, migrations aditivas, contracts em `Gabi.Contracts`.

## Visão Geral do Projeto

**GABI** é um sistema de ingestão, processamento e busca de dados jurídicos do Tribunal de Contas da União (TCU). O sistema segue uma arquitetura em camadas estrita com separação clara de responsabilidades.

### Pipeline de Dados

```
Seed → Discovery → Fetch → Ingest → Index
```

1. **Seed**: Carrega definições de fontes do `sources_v2.yaml` para o PostgreSQL
2. **Discovery**: Descobre URLs e links de documentos nas fontes configuradas
3. **Fetch**: Recupera conteúdo bruto das URLs descobertas
4. **Ingest**: Processa, normaliza e indexa os documentos

## Stack Tecnológico

| Componente | Tecnologia | Versão |
|------------|------------|--------|
| Plataforma | .NET | 8.0 |
| Linguagem | C# | 12.0 |
| Banco de Dados | PostgreSQL | 15 |
| Motor de Busca | Elasticsearch | 8.11 |
| Cache/Filas | Redis | 7 |
| Job Scheduler | Hangfire | 1.8.17 |
| ORM | EF Core | 8.0.2 |
| Container | Docker | - |
| Deploy | Fly.io | - |

## Estrutura do Projeto

```
.
├── src/
│   ├── Gabi.Api/              # REST API (Minimal API) - Layer 5
│   ├── Gabi.Worker/           # Background worker (Hangfire) - Layer 5
│   ├── Gabi.Contracts/        # Interfaces e DTOs - Layer 0-1
│   ├── Gabi.Postgres/         # EF Core + PostgreSQL - Layer 2-3
│   ├── Gabi.Discover/         # Motor de discovery - Layer 4
│   ├── Gabi.Fetch/            # Fetch de conteúdo - Layer 4
│   ├── Gabi.Ingest/           # Ingestão e parse - Layer 4
│   ├── Gabi.Sync/             # Sync engine - Layer 4
│   └── Gabi.Jobs/             # Job state machine - Layer 4
├── tests/
│   ├── Gabi.Api.Tests/
│   ├── Gabi.Discover.Tests/
│   ├── Gabi.Fetch.Tests/
│   ├── Gabi.Jobs.Tests/
│   ├── Gabi.Postgres.Tests/
│   ├── Gabi.Sync.Tests/
│   └── zero-kelvin-test.sh    # Teste E2E completo
├── scripts/
│   └── dev                    # CLI de desenvolvimento
├── sources_v2.yaml            # Definição das fontes
├── docker-compose.yml         # Infraestrutura (Postgres, ES, Redis)
├── Dockerfile                 # Worker para Fly.io
├── fly.toml                   # Config Fly.io (Worker)
└── fly.api.toml               # Config Fly.io (API)
```

## Arquitetura em Camadas (Strict)

A arquitetura segue regras estritas de dependência: camadas superiores NÃO referenciam camadas inferiores.

```
Layer 5: Orchestration  → Gabi.Worker, Gabi.Api
Layer 4: Domain Logic   → Gabi.Discover, Gabi.Fetch, Gabi.Ingest, Gabi.Sync, Gabi.Jobs
Layer 2-3: Infrastructure → Gabi.Postgres
Layer 0-1: Contracts    → Gabi.Contracts (ZERO referências a outros projetos)
```

### Regras Fundamentais

1. **Gabi.Contracts** não tem referências a nenhum outro projeto
2. Projetos de domínio (Layer 4) NÃO referenciam Gabi.Postgres ou EF Core
3. Comunicação apenas via interfaces definidas em Gabi.Contracts
4. DI registration acontece em Layer 5 (Worker/Api `Program.cs`)

## Build e Execução

### Pré-requisitos

- .NET 8 SDK
- Docker + Docker Compose

### Comandos de Build

```bash
# Build completo
dotnet build GabiSync.sln

# Build release
dotnet build GabiSync.sln -c Release

# Publicar Worker
dotnet publish src/Gabi.Worker -c Release -o ./publish
```

### Executar Localmente

**Opção 1: Tudo com Docker (recomendado)**

```bash
./scripts/dev infra up
docker compose --profile api --profile worker up -d
```

**Opção 2: Infra Docker + API no host**

```bash
# Terminal 1
./scripts/dev infra up

# Terminal 2 (raiz do repo)
dotnet run --project src/Gabi.Api --urls "http://localhost:5100"
```

### CLI de Desenvolvimento (`./scripts/dev`)

```bash
./scripts/dev setup              # Setup inicial completo
./scripts/dev infra up           # Inicia Postgres (5433), ES (9200), Redis (6380)
./scripts/dev infra down         # Para containers (mantém volumes)
./scripts/dev infra destroy      # Para e remove volumes
./scripts/dev app up             # Roda API em foreground (:5100)
./scripts/dev app start          # Roda API em background
./scripts/dev app stop           # Para API
./scripts/dev app status         # Status dos serviços
./scripts/dev db apply           # Aplica migrations
./scripts/dev db create <Nome>   # Cria nova migration
./scripts/dev db status          # Lista migrations
./scripts/dev db reset           # Drop DB e reaplica (destructivo)
```

## Testes

### Testes Unitários/Integração

```bash
# Todos os testes
dotnet test GabiSync.sln

# Projeto específico
dotnet test tests/Gabi.Api.Tests
dotnet test tests/Gabi.Discover.Tests
dotnet test tests/Gabi.Postgres.Tests

# Com filtro
dotnet test tests/Gabi.Api.Tests --filter "FullyQualifiedName~BasicEndpointTests"
```

### Teste Zero Kelvin (E2E Completo)

Valida reconstrução do zero - destroi tudo e recria:

```bash
# Modo padrão (docker-only)
./tests/zero-kelvin-test.sh

# Com target específico
./tests/zero-kelvin-test.sh docker-only \
  --source tcu_sumulas \
  --phase discovery

# Stress test com cap
./tests/zero-kelvin-test.sh docker-only \
  --source tcu_acordaos \
  --phase full \
  --max-docs 20000 \
  --monitor-memory \
  --report-json /tmp/report.json
```

## Configuração

### Variáveis de Ambiente Principais

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `ConnectionStrings__Default` | PostgreSQL | Host=localhost;Port=5433;... |
| `GABI_SOURCES_PATH` | Caminho do YAML | sources_v2.yaml |
| `Gabi__ElasticsearchUrl` | Elasticsearch | http://localhost:9200 |
| `Gabi__RedisUrl` | Redis | redis://localhost:6380/0 |
| `GABI_RUN_MIGRATIONS` | Executar migrations | false |
| `GABI_INLABS_COOKIE` | Cookie para INLABS | - |

### Portas de Serviço

| Serviço | Porta Host | Porta Container |
|---------|------------|-----------------|
| PostgreSQL | 5433 | 5432 |
| Elasticsearch | 9200 | 9200 |
| Redis | 6380 | 6379 |
| API | 5100 | 8080 |

### Usuários de Teste (JWT)

| Usuário | Senha | Role | Permissões |
|---------|-------|------|------------|
| operator | op123 | Operator | Seed, trigger fases, DLQ replay |
| viewer | view123 | Viewer | Leitura apenas |
| admin | admin123 | Admin | Acesso total |

## Convenções de Código

### Estilo

- Usar `ImplicitUsings` e `Nullable` habilitados em todos os projetos
- Preferir `record` para DTOs e contratos imutáveis
- Usar `init` setters para propriedades imutáveis
- Nomes em inglês para código, português para documentação

### Padrões Importantes

**Streaming Obrigatório** (restrição de memória: 300MB efetivo)

```csharp
// ✅ Correto: Streaming com IAsyncEnumerable
public async IAsyncEnumerable<Document> FetchAsync(
    [EnumeratorCancellation] CancellationToken ct = default)
{
    await foreach (var item in source.WithCancellation(ct))
    {
        yield return Transform(item);
    }
}

// ❌ Incorreto: Bufferização em memória
var all = await source.ToListAsync();  // NUNCA faça isso
```

**Interfaces em Contracts, Implementações nos Projetos de Domínio**

```csharp
// Em Gabi.Contracts
public interface IDiscoveryEngine { ... }

// Em Gabi.Discover
public class DiscoveryEngine : IDiscoveryEngine { ... }
```

**CancellationToken Propagation**

```csharp
public async Task DoWorkAsync(CancellationToken ct = default)
{
    await foreach (var item in source.WithCancellation(ct)) { ... }
}
```

## Estratégias de Discovery

O sistema suporta múltiplas estratégias de discovery definidas em `sources_v2.yaml`:

| Estratégia | Descrição |
|------------|-----------|
| `static_url` | URL única, não muda |
| `url_pattern` | Template com parâmetros (range, lista) |
| `api_pagination` | APIs paginadas com drivers específicos |
| `web_crawl` | Crawling de páginas web |

## Migrations de Banco

### Criar Nova Migration

```bash
./scripts/dev db create NomeDaMigration
# Ou diretamente:
dotnet ef migrations add NomeDaMigration --project src/Gabi.Postgres
```

### Aplicar Migrations

```bash
./scripts/dev db apply
```

### Regras para Migrations

- **Apenas adições** - nunca modificar migrations existentes
- Índices criados com `CONCURRENTLY` para evitar locks
- Migrations aplicam automaticamente no startup da API quando `GABI_RUN_MIGRATIONS=true`

## Deploy (Fly.io)

### Apps Separados

- **gabi-api**: REST API (HTTP service)
- **gabi-worker**: Background worker (processo)

### Deploy API

```bash
fly deploy --config fly.api.toml
```

### Deploy Worker

```bash
fly deploy --config fly.toml
```

### Secrets (configurar via CLI)

```bash
fly secrets set ConnectionStrings__Default="..." -a gabi-api
fly secrets set GABI_ELASTICSEARCH_URL="..." -a gabi-worker
```

## Health Checks e Observabilidade

### Endpoints

- `GET /health` - Live check (sempre retorna 200 se processo rodando)
- `GET /health/ready` - Readiness check (inclui PostgreSQL)
- `GET /swagger` - Documentação da API

### Logs

- Desenvolvimento: formato legível via console
- Produção: JSON formatado via Serilog (`CompactJsonFormatter`)

### DLQ (Dead Letter Queue)

Falhas após retries são registradas na tabela `dlq_entries`:
- `GET /api/v1/dlq` - Listar entradas
- `POST /api/v1/dlq/{id}/replay` - Reprocessar entrada (operator)

## Endpoints Essenciais da API

| Método | Endpoint | Auth | Descrição |
|--------|----------|------|-----------|
| POST | `/api/v1/auth/login` | - | Login JWT |
| GET | `/health` | - | Health check |
| GET | `/api/v1/sources` | viewer | Listar fontes |
| POST | `/api/v1/dashboard/seed` | operator | Executar seed |
| POST | `/api/v1/dashboard/sources/{id}/phases/{phase}` | operator | Disparar fase |

## Arquivos Importantes

- `sources_v2.yaml` - Definição completa das fontes de dados
- `CLAUDE.md` - Wrapper mínimo para agentes Claude (aponta para `AGENTS.md`)
- `GEMINI.md` - Wrapper mínimo para agentes Gemini (aponta para `AGENTS.md`)
- `docs/ai/SKILLS_POLICY.md` - Política de uso de skills (core/optional/deprecated)
- `DOCKER.md` - Guia completo de Docker
- `docs/architecture/LAYERED_ARCHITECTURE.md` - Detalhes da arquitetura
- `docs/infrastructure/FLY_DEPLOY.md` - Deploy em Fly.io

## Dicas para Agentes

1. **Sempre verifique a arquitetura em camadas** - não quebre as regras de dependência
2. **Use streaming** - nunca carregue coleções inteiras em memória
3. **Propage CancellationToken** - em toda operação async
4. **Teste com Zero Kelvin** - após mudanças significativas no pipeline
5. **Migrations são aditivas** - nunca modifique migrations existentes
6. **Use o CLI `./scripts/dev`** - para operações de desenvolvimento
7. **Consulte `sources_v2.yaml`** - para entender configurações de fontes
