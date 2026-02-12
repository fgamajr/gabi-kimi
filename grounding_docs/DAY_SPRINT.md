# Day Sprint - GABI-SYNC v2.0 (C# .NET 8)

**Data:** 2026-02-12  
**Stack:** C# .NET 8 + PostgreSQL 16 + pgvector  
**Status:** Planejamento completo, pronto para implementação

---

## 🎯 Visão Geral

Reescrita completa de GABI-KIMI (Python) para **GABI-SYNC** (C#) com arquitetura modular plugável.

**Por que C#?**
- Arquitetura plugável é natural (projetos = apps isolados)
- DI nativa (`IServiceCollection`)
- `IAsyncEnumerable` + `System.Threading.Channels` superior
- `BackgroundService` elimina Celery
- Long-term maintenance superior

---

## 📊 Arquitetura de Apps

```
Gabi.Contracts       Layer 0-1  Records, Enums, Interfaces
Gabi.Postgres        Layer 2-3  EF Core, Migrations, Repositories  
Gabi.Discover        Layer 4a   URL discovery, change detection
Gabi.Ingest          Layer 4b   Fetch, Parse, Fingerprint, Dedup, Chunk
Gabi.Sync            Layer 5    Diff/Merge (bypass, insert, update, delete)
Gabi.Worker          Entry      Orchestrador (BackgroundService)
```

**Stack:**
- **Banco:** PostgreSQL 16 + pgvector (migrations via EF Core)
- **HTTP:** HttpClient nativo com streaming
- **CSV:** CsvHelper com `IAsyncEnumerable`
- **Config:** IOptions<T> + appsettings.json

---

## 🗓️ Cronograma (5 Semanas)

### Semana 1: Foundation
- [ ] Criar `GabiSync.sln` com 6 projetos
- [ ] `Gabi.Contracts`: Records, interfaces, enums
- [ ] `Gabi.Postgres`: DbContext, migrations iniciais
- [ ] Configurar DI e build
- **Entregável:** `dotnet build` passa, migrações criam tabelas

### Semana 2: Discover + Ingest(Fetcher)
- [ ] `Gabi.Discover`: URL patterns, static URLs
- [ ] `Gabi.Ingest.Fetcher`: HTTP, streaming, SSRF
- **Entregável:** Descobre URLs e faz download

### Semana 3: Ingest(Parser + Process)
- [ ] `Gabi.Ingest.Parser`: CSV, HTML, PDF, JSON
- [ ] `Gabi.Ingest.Fingerprint`
- [ ] `Gabi.Ingest.Deduplication`
- [ ] `Gabi.Ingest.Chunker`
- **Entregável:** Parse completo, gera chunks

### Semana 4: Sync + Worker
- [ ] `Gabi.Sync`: Bypass, Insert, Update, Delete
- [ ] `Gabi.Worker`: Orchestration, DI
- [ ] Docker compose
- **Entregável:** Pipeline end-to-end

### Semana 5: Polish + Tests
- [ ] Testes integração
- [ ] Docker profiles
- [ ] Deploy scripts
- **Entregável:** Produção-ready

---

## 📁 Documentação

| Arquivo | Descrição |
|---------|-----------|
| `PLANEJAMENTO_GABI_SYNC_v2.md` | Plano completo detalhado |
| `docs/adr/001-gabi-sync-modular-architecture.md` | Decisão arquitetural |
| `docs/adr/002-sources-yaml-v2.md` | Evolução sources.yaml |
| `docs/adr/003-gabi-apps-definition.md` | Definição de apps |
| `sources_v2.yaml` | Nova estrutura de configuração |
| `ARCHITECTURE_OVERVIEW.md` | Visão geral arquitetura |

---

## 🐳 Docker Profiles

```bash
# Hoje: só core
docker compose --profile core up

# Futuro: + embeddings
docker compose --profile core --profile embed up

# Futuro: tudo
docker compose --profile full up
```

---

## ⚠️ Código Legado

Python preservado em `old_python_implementation/` para referência.

---

## 🚀 Próximo Passo

**Aprovar planejamento** → Criar branch → Iniciar Semana 1
