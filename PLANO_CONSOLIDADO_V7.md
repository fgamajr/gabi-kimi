# Plano Consolidado v7 (World-Class Excellence)

**Versão:** 1.0  
**Data base:** 23 de fevereiro de 2026  
**Status:** Assessment backlog (pós-V6)  
**Objetivo:** Elevar GABI a nível world-class de engenharia de software  
**Avaliações:** 67 avaliações distribuídas em 10 dimensões técnicas  
**Total estimado:** ~246 horas (P0: 60h, P1: 78h, P2: 108h)

---

## 1. Resumo Executivo

O **V6** estabilizou o sistema (pipeline funcional, testes, observabilidade básica). O **V7** foca em **excelência técnica** — otimização, resiliência avançada, segurança enterprise e práticas de engenharia de ponta.

**Diferença fundamental:**
- **V6:** "Faça funcionar corretamente" (correção + fundamentos)
- **V7:** "Faça funcionar excelentemente" (performance + world-class)

**Pré-requisito:** V6 100% concluído (Fases 1-4) antes de iniciar V7.

---

## 2. Avaliações World-Class por Dimensão

### Sumário das Dimensões

| Dimensão | Itens | Horas P0 | Horas P1 | Horas P2 |
|----------|-------|----------|----------|----------|
| 2.1 Performance & Efficiency | 6 | 4h | 14h | 18h |
| 2.2 Resiliência Avançada | 6 | 14h | 16h | 14h |
| 2.3 Observabilidade World-Class | 4 | 8h | 6h | 8h |
| 2.4 Arquitetura & Design | 10 | 6h | 8h | 16h |
| 2.4b Qualidade de Código C# | 5 | 14h | 12h | 4h |
| 2.4c API Design | 5 | 4h | 12h | 4h |
| 2.4d Schema & Dados | 4 | 4h | 20h | 4h |
| 2.5 Segurança Enterprise | 12 | 18h | 12h | 10h |
| 2.6 CI/CD & DevEx | 9 | 12h | 12h | 20h |
| 2.7 Operações & Runbook | 6 | 18h | 8h | 10h |
| **Total** | **67** | **60h** | **78h** | **108h** |

---

### 2.1 Performance & Efficiency

| ID | Avaliação | O que medir | Ferramenta | P | Estimativa |
|----|-----------|-------------|------------|---|------------|
| **P1** | **Async/await correctness** | `ConfigureAwait(false)` consistente, async void, deadlock potencial, ValueTask onde cabe | Roslyn Analyzers + Code review | **P0** | 4h |
| **P2** | **Heap allocation profiling** | Alocações por request/job, boxing em hot paths, closures em loops | BenchmarkDotNet + dotMemory | **P1** | 8h |
| **P3** | **EF Core query plan audit** | N+1 queries, cartesian explosion em Include, índices usados vs table scan | EF Core logging + EXPLAIN ANALYZE | **P1** | 6h |
| **P4** | **Memory pool usage** | ArrayPool<T>, Memory<T>, Span<T> em hot paths | dotMemory + BenchmarkDotNet | **P2** | 8h |
| **P5** | **IAsyncEnumerable backpressure** | Consumer consegue sinalizar pressão de volta ao producer | Teste de carga específico | **P2** | 6h |
| **P6** | **LOH fragmentation** | Objetos > 85KB causando GC pressure | dotMemory | **P2** | 4h |

**P0 (Must-have):** Async/await correctness — bugs silenciosos em produção  
**P1 (Should-have):** Alocações e queries — impacto direto em custo/performance  
**P2 (Nice):** Micro-otimizações — ganhos marginais

---

### 2.2 Resiliência & Confiabilidade Avançada

| ID | Avaliação | O que medir | Ferramenta | P | Estimativa |
|----|-----------|-------------|------------|---|------------|
| **R1** | **Polly / Circuit Breaker** | CB nas chamadas ao ES, Redis, TCU — ou apenas retries ingênuos? | Code review + teste de falha | **P0** | 8h |
| **R2** | **Graceful shutdown** | `IHostedService.StopAsync` aguarda jobs em andamento ou corta abruptamente? | Teste com SIGTERM em Fly.io | **P0** | 4h |
| **R3** | **Idempotência end-to-end** | Pipeline completo (Discovery→Fetch→Ingest) é seguro para retry sem duplicatas? | Teste de injeção de falha por estágio | **P0** | 12h |
| **R4** | **Chaos Engineering** | Comportamento sob falhas: ES cai, PG lento, Redis indisponível | Gremlin/Chaos Monkey ou scripts custom | **P2** | 16h |
| **R5** | **Bulkhead isolation** | Falha no ES bloqueia também o PostgreSQL path? | Polly Bulkhead audit | **P1** | 6h |
| **R6** | **Graceful degradation** | Funciona sem ES? Funciona sem Redis? | Testes de integração com mocks | **P1** | 8h |

**Nota sobre V6 vs V7:**
- V6 implementa **taxonomia de erros** (classificação)
- V7 implementa **Polly/Circuit Breaker** (ação preventiva)
- V6 valida **idempotência unitária**
- V7 valida **idempotência end-to-end** (pipeline completo)

---

### 2.3 Observabilidade Avançada (Evolução do V6)

| ID | Avaliação | O que medir | Ferramenta | P | Estimativa |
|----|-----------|-------------|------------|---|------------|
| **O1** | **Distributed tracing completeness** | 100% dos requests têm trace ID? Spans aninhados corretos? | Jaeger/Tempo validation | **P1** | 6h |
| **O2** | **SLO/SLI definição e medição** | Latência P99, error budget, burn rate | Prometheus + AlertManager | **P0** | 8h |
| **O3** | **Log aggregation e correlação** | Logs estruturados com trace_id em todos os serviços | Loki/ELK + validation | **P1** | 6h |
| **O4** | **Profiling contínuo** | CPU hot paths em produção (não só dev) | Pyroscope/Parca | **P2** | 8h |

**Diferença V6→V7:**
- **V6:** OTel básico (spans, métricas simples)
- **V7:** SLOs formais, error budgets, profiling contínuo

---

### 2.4 Arquitetura & Design (Validação pós-V6)

| ID | Avaliação | O que medir | Ferramenta | P | Estimativa |
|----|-----------|-------------|------------|---|------------|
| **A1** | **Test coverage estratificada** | Unit vs Integration vs E2E ratio | Coverlet + relatório | **P0** | 4h |
| **A2** | **Cyclomatic complexity** | Métodos > 10, classes > 300 linhas | SonarQube/Roslyn Analyzers | **P1** | 4h |
| **A3** | **Coupling entre módulos** | Afferent/Efferent coupling, instabilidade | NDepend/ArchUnit | **P2** | 6h |
| **A4** | **Mutation testing score** | Testes realmente testam ou só passam? | Stryker.NET | **P2** | 8h |
| **A5** | **API versioning strategy** | Como quebrar contratos sem quebrar clientes | Review de design | **P1** | 4h |
| **A6** | **Dead code detection** | Métodos/classes não referenciados | Roslyn Analyzers + vulture | **P2** | 4h |
| **A7** | **ADRs (Architecture Decision Records)** | Decisões arquiteturais documentadas? (por que Hangfire vs RabbitMQ? ES vs pgvector?) | Audit de docs/ | **P2** | 4h |
| **A8** | **Dependency direction enforcement** | Camadas Infrastructure → Domain → Contracts nunca invertem | NetArchTest | **P0** | 2h |
| **A9** | **Bounded context clarity** | Conceito de "Fonte", "Documento", "Chunk" tem semântica consistente? | Glossário + code review | **P1** | 4h |
| **A10** | **Event-driven readiness** | Sistema poderia emitir eventos de domínio sem reescrita? | Design review | **P2** | 6h |

---

### 2.4b Qualidade de Código C# (Específico da Linguagem)

| ID | Avaliação | O que medir | Ferramenta | P | Estimativa |
|----|-----------|-------------|------------|---|------------|
| **Q1** | **Nullable reference types** | `#nullable enable` em todos os projetos, supressões `!` desnecessárias | `.csproj` config + `dotnet build /warnaserror` | **P0** | 4h |
| **Q2** | **Cyclomatic complexity** | Métodos com complexidade > 10 (hotspots de bug) | `dotnet-coverage` + SonarQube | **P1** | 4h |
| **Q3** | **Roslyn analyzers** | Quais rule sets estão ativos (CA, SA, MA) e quantas supressões existem | `.editorconfig` audit | **P1** | 4h |
| **Q4** | **Dead code** | Interfaces não implementadas, métodos public sem caller, #if branches mortas | Rider "Code Issues" + `dotnet-outdated` | **P2** | 4h |
| **Q5** | **Captive dependency** | Singleton dependendo de Scoped no DI container (bugs silenciosos) | `IServiceProviderIsService` + testes de escopo | **P0** | 6h |

**Nota:** Q5 (Captive dependency) é crítico — causa bugs em produção difíceis de reproduzir.

---

### 2.4c API Design (REST & Contracts)

| ID | Avaliação | O que medir | Ferramenta | P | Estimativa |
|----|-----------|-------------|------------|---|------------|
| **D1** | **REST maturity (Richardson Model)** | Nível atual: resources, verbos corretos, HATEOAS, hypermedia | Code review de controllers | **P2** | 4h |
| **D2** | **Versioning strategy** | Como quebras de contrato são gerenciadas (/v1/, headers, etc.) | API audit | **P1** | 2h |
| **D3** | **Paginação e cursor** | Offset vs cursor-based pagination para listas grandes | Load test com dataset grande | **P1** | 6h |
| **D4** | **Idempotency keys na API** | POST /seed é idempotente? Cliente pode reenviar com segurança? | Spec review | **P0** | 4h |
| **D5** | **OpenAPI / contract completeness** | Swagger gerado cobre todos os cenários de erro (400, 409, 422, 503) | `dotnet-openapi` diff | **P1** | 4h |

---

### 2.4d Schema & Dados (PostgreSQL + Elasticsearch)

| ID | Avaliação | O que medir | Ferramenta | P | Estimativa |
|----|-----------|-------------|------------|---|------------|
| **D6** | **PostgreSQL index strategy** | Índices parciais, compostos, BRIN para timestamps, bloat | `pg_stat_user_indexes` + pganalyze | **P1** | 6h |
| **D7** | **Elasticsearch mapping audit** | `dynamic: strict` vs `true`, analyzer por campo, `_source` filtering | `GET /_mapping` review | **P1** | 4h |
| **D8** | **Migration safety** | Todas as migrations são zero-downtime? | Checklist por migration | **P0** | 4h |
| **D9** | **Elasticsearch relevance** | Ranking de documentos jurídicos corresponde à relevância real? (BM25 tuning) | Teste de relevância com queries reais | **P2** | 8h |

---

### 2.5 Segurança Enterprise (Além do V6)

| ID | Avaliação | O que medir | Ferramenta | P | Estimativa |
|----|-----------|-------------|------------|---|------------|
| **S1** | **NuGet dependency audit** | CVEs em dependências transitivas | `dotnet list package --vulnerable` em CI | **P0** | 2h |
| **S2** | **Secrets management** | Connection strings em config vs vault, secrets em logs | Auditoria IConfiguration + Serilog | **P0** | 4h |
| **S3** | **PII em logs** | Dados pessoais logados sem mascaramento | Grep estruturado + Serilog policies | **P1** | 4h |
| **S4** | **OWASP API Security Top 10** | Rate limiting, mass assignment, BOLA, etc. | Checklist por endpoint | **P0** | 8h |
| **S5** | **Dependency license compliance** | Licenças GPL/LGPL conflitantes | dotnet-project-licenses | **P2** | 4h |
| **S6** | **SAST (Static Analysis)** | SQL injection, XSS, path traversal | Semgrep/SonarQube | **P1** | 6h |
| **S7** | **Container security** | Imagem com vulnerabilidades? Non-root user? | Trivy/Grype + Docker Scout | **P1** | 4h |
| **S8** | **Supply chain security** | SBOM gerado? Assinatura de artefatos? | Syft + Cosign | **P2** | 6h |
| **S9** | **Path traversal protection** | Upload/local-file valida path normalization | Code review | **P0** | 2h |
| **S10** | **SSRF prevention** | URLs em upload validam against allowlist | Code review | **P0** | 2h |
| **S11** | **Content type verification** | Uploads validam magic bytes, não só extensão | Code review | **P1** | 2h |
| **S12** | **Audit logging** | Ações administrativas (seed, DLQ replay) são auditadas? | Log inspection | **P1** | 4h |

**P0 (Critical):** Dependências vulneráveis, secrets expostos, OWASP Top 10, Path Traversal, SSRF  
**P1 (Important):** PII, SAST, container security, content type, audit logging  
**P2 (Advanced):** Licenças, supply chain

---

### 2.6 CI/CD & DevEx

| ID | Avaliação | O que medir | Ferramenta | P | Estimativa |
|----|-----------|-------------|------------|---|------------|
| **C1** | **Build reproducibility** | Mesmo commit gera mesmo binário | Docker buildx + checksum | **P0** | 4h |
| **C2** | **DORA metrics** | Deployment frequency, lead time, MTTR, change failure rate | CI/CD analytics | **P1** | 4h |
| **C3** | **Rollback time** | Tempo para voltar versão anterior | Teste manual + runbook | **P1** | 4h |
| **C4** | **Feature flags** | Consegue desligar feature sem deploy? | LaunchDarkly/unleash/custom | **P2** | 8h |
| **C5** | **Trunk-based development** | Branches vivem < 1 dia? | Git metrics | **P2** | 2h |
| **C6** | **CI pipeline speed** | Build + test < 10 min? | CI logs analysis | **P1** | 4h |
| **C7** | **Chaos engineering** | Testes de resiliência (kill postgres, ES unavaible) em CI? | Chaos Monkey / Toxiproxy | **P2** | 12h |
| **C8** | **Release automation** | PR merge → produção é automático ou manual? | GitHub Actions audit | **P1** | 4h |
| **C9** | **GitHub Actions security** | Actions com `uses: ***@main` (pin to SHA), secrets não logados | `actionlint` + security audit | **P0** | 4h |

---

### 2.7 Operações & Runbook (Gerenciamento em Produção)

| ID | Avaliação | O que medir | Ferramenta | P | Estimativa |
|----|-----------|-------------|------------|---|------------|
| **O5** | **Runbook completeness** | Existe play-by-play para "PostgreSQL down", "ES não indexa", "memory spike"? | `docs/runbooks/` audit | **P0** | 6h |
| **O6** | **Alert fatigue check** | Quantos alerts/por dia? Qual % é acionável? | AlertManager history | **P1** | 4h |
| **O7** | **Incident response time** | MTTD (Mean Time To Detect) vs MTTR para diferentes severidades | Incident logs | **P1** | 4h |
| **O8** | **Cost visibility** | Tracking de custos por ambiente/funcionalidade | Billing dashboard + tags | **P2** | 4h |
| **O9** | **Capacity planning** | Projeção de crescimento de dados (quando precisa de mais storage?) | Growth modeling | **P2** | 6h |
| **O10** | **Disaster recovery (DR)** | RPO/RTO definidos? Testado recentemente? | DR drill | **P0** | 12h |

**Diferença O1-O4 (Observabilidade) vs O5-O10 (Operações):**
- **Observabilidade:** "Conseguimos ver o que está acontecendo?"
- **Operações:** "Sabemos o que fazer quando algo acontece?"

---

## 3. Backlog Priorizado

### P0 (Must-have para world-class)
Total: ~60 horas

**Performance:**
- [ ] P1: Async/await correctness

**Resiliência:**
- [ ] R1: Polly / Circuit Breaker
- [ ] R2: Graceful shutdown
- [ ] R3: Idempotência end-to-end

**Observabilidade:**
- [ ] O2: SLO/SLI definição

**Arquitetura:**
- [ ] A1: Test coverage estratificada
- [ ] A8: Dependency direction enforcement (NetArchTest)

**Qualidade de Código:**
- [ ] Q1: Nullable reference types
- [ ] Q5: Captive dependency (crítico)

**API Design:**
- [ ] D4: Idempotency keys na API

**Segurança:**
- [ ] S1: NuGet dependency audit
- [ ] S2: Secrets management audit
- [ ] S4: OWASP API Security Top 10
- [ ] S9: Path traversal protection
- [ ] S10: SSRF prevention

**CI/CD:**
- [ ] C1: Build reproducibility
- [ ] C9: GitHub Actions security

**Operações:**
- [ ] O5: Runbook completeness
- [ ] O10: Disaster recovery (DR)

### P1 (Should-have)
Total: ~78 horas

- [ ] P2: Heap allocation profiling
- [ ] P3: EF Core query plan audit
- [ ] R5: Bulkhead isolation
- [ ] R6: Graceful degradation
- [ ] O1: Distributed tracing completeness
- [ ] O3: Log aggregation
- [ ] O6: Alert fatigue check
- [ ] O7: Incident response time
- [ ] A2: Cyclomatic complexity
- [ ] A5: API versioning strategy
- [ ] A9: Bounded context clarity
- [ ] Q2: Cyclomatic complexity analysis
- [ ] Q3: Roslyn analyzers config
- [ ] D3: Paginação e cursor
- [ ] D5: OpenAPI completeness
- [ ] D6: PostgreSQL index strategy
- [ ] D7: Elasticsearch mapping audit
- [ ] D8: Migration safety
- [ ] S3: PII em logs
- [ ] S6: SAST
- [ ] S7: Container security
- [ ] S11: Content type verification
- [ ] S12: Audit logging
- [ ] C2: DORA metrics
- [ ] C3: Rollback time
- [ ] C6: CI pipeline speed
- [ ] C8: Release automation

### P2 (Nice-to-have)
Total: ~108 horas

- [ ] P4: Memory pool usage
- [ ] P5: IAsyncEnumerable backpressure
- [ ] P6: LOH fragmentation
- [ ] R4: Chaos Engineering
- [ ] O4: Profiling contínuo
- [ ] O8: Cost visibility
- [ ] O9: Capacity planning
- [ ] A3: Coupling analysis
- [ ] A4: Mutation testing
- [ ] A6: Dead code detection
- [ ] A7: ADRs (Architecture Decision Records)
- [ ] A10: Event-driven readiness
- [ ] Q4: Dead code detection
- [ ] D1: REST maturity (Richardson Model)
- [ ] D2: Versioning strategy
- [ ] D9: Elasticsearch relevance tuning
- [ ] S5: License compliance
- [ ] S8: Supply chain security
- [ ] C4: Feature flags
- [ ] C5: Trunk-based development
- [ ] C7: Chaos engineering em CI

---

## 4. Critérios de Aceite World-Class

O GABI atinge nível world-class quando:

### Performance
- [ ] Zero `async void`, `ConfigureAwait(false)` consistente
- [ ] < 100KB alocações por request típico
- [ ] Zero N+1 queries em hot paths
- [ ] P99 latência < 200ms para queries simples

### Resiliência
- [ ] Circuit breakers em todos os serviços externos
- [ ] Graceful shutdown aguarda jobs em andamento
- [ ] Pipeline idempotente (retry seguro)
- [ ] Funciona (degradado) sem ES ou Redis

### Observabilidade
- [ ] SLOs definidos e medidos (latência, disponibilidade)
- [ ] Error budget < 0.1% ao mês
- [ ] 100% de requests com trace ID
- [ ] Alertas em < 1min para anomalias

### Segurança
- [ ] Zero CVEs críticos/alto em dependências
- [ ] Zero secrets em código/config
- [ ] Zero vulnerabilidades OWASP Top 10
- [ ] PII mascarado em todos os logs

### CI/CD
- [ ] Deploys reproduzíveis (mesmo binário)
- [ ] Rollback < 5 minutos
- [ ] DORA: Lead time < 1 dia, MTTR < 1 hora

---

## 5. Ferramentas Recomendadas

### Análise Estática
- **SonarQube/SonarCloud:** Complexidade, code smells, security hotspots
- **Roslyn Analyzers:** Async/await, dispose patterns, nullable
- **Semgrep:** SAST custom rules
- **Stryker.NET:** Mutation testing

### Performance
- **BenchmarkDotNet:** Micro-benchmarks
- **dotMemory/dotTrace:** Profiling memória e CPU
- **EF Core logging:** Query plans
- **K6/ NBomber:** Load testing

### Segurança
- **Snyk/Dependabot:** Dependency scanning
- **Trivy/Grype:** Container scanning
- **GitLeaks:** Secrets detection
- **OWASP ZAP:** API security testing

### Observabilidade
- **Jaeger/Tempo:** Distributed tracing
- **Grafana:** Dashboards e alertas
- **Prometheus:** Métricas
- **Pyroscope:** Profiling contínuo

---

## 6. Metodologia de Execução

**NÃO execute tudo de uma vez.** Use abordagem iterativa:

### Fase 1: Assessment (2-3 dias)
Rodar todas as ferramentas de análise, gerar relatório baseline.

### Fase 2: P0 Items (1-2 semanas)
Focar nos must-haves, criar tickets, implementar.

### Fase 3: P1 Items (2-3 semanas)
Should-haves, otimizações significativas.

### Fase 4: P2 Items (contínuo)
Nice-to-haves, melhorias incrementais.

### Fase 5: Validação contínua (CI)
Incorporar ferramentas ao pipeline:
- SAST em cada PR
- Dependency audit diário
- Performance regression em releases

---

## 7. Relação com V6

| V6 | V7 |
|----|----|
| Estabilização | Otimização |
| Fundamentos | Excelência |
| "Funciona" | "Funciona muito bem" |
| Correção | Performance |
| Testes básicos | Testes avançados (mutation, chaos) |
| OTel básico | SLOs formais |
| Taxonomia de erros | Polly/Circuit Breaker |
| Idempotência unitária | Idempotência end-to-end |

**Gateway:** V6 100% → inicia V7

---

## 8. Checklist de Prontidão para V7

Antes de iniciar V7, confirme:

- [ ] V6 Fase 4 concluída (API REST + Ingest.Tests + Smoke tests)
- [ ] Zero-kelvin all-sources PASS
- [ ] OpenTelemetry básico funcionando
- [ ] Taxonomia de erros implementada
- [ ] Build verde (0 erros, 0 warnings)
- [ ] Testes > 80% coverage

---

## 9. Recursos

### Leituras Recomendadas
- "Building Secure & Reliable Systems" — Google SRE Book
- "The Art of Unit Testing" — Roy Osherove (mutation testing)
- "Chaos Engineering" — Netflix (case studies)
- "Software Architecture: The Hard Parts" — Neal Ford

### Cursos
- "Polly: Resilience in .NET" — Pluralsight
- "OWASP API Security Top 10" — OWASP
- "Distributed Tracing with OpenTelemetry" — CNCF

---

## 10. Histórico de Revisões

| Data | Versão | Mudanças |
|------|--------|----------|
| 2026-02-23 | 1.0 | Criação inicial do V7 com 40+ avaliações world-class |

---

*Este documento é um assessment backlog. Não execute até V6 estar 100% concluído.*
