# Auditoria Técnica de Base Zero e Pre-Mortem: GABI
**Data:** 25 de Fevereiro de 2026  
**Escopo:** `Gabi.Worker`, `Gabi.Api`, `Gabi.Postgres`, `Gabi.Ingest`  
**Objetivo:** Consolidar a Due-Diligence de arquitetura/runtime com o mapa de gaps de Engenharia World-Class, priorizando riscos de produção.

---

## 🚨 1. Riscos Estruturais Críticos (Prioridade 0 - Bloqueantes de Produção)

* **1.1. Denial of Service (DoS) por Varredura Textual O(N):** O endpoint `GET /api/v1/search` realiza fallback para varredura completa (`ToLower().Contains()`) no PostgreSQL quando o Elasticsearch não está disponível. Poucas chamadas a esse endpoint esgotam a CPU do banco instantaneamente.
* **1.2. SSRF (Server-Side Request Forgery) Irrestrito no Worker:** O Worker processa URLs cegas oriundas de `sources_v2.yaml`. Qualquer URL na nuvem AWS/Fly apontando para metadados internos ou bancos locais passará sem validação DNS.
* **1.3. Tarpitting Thread Starvation (Head-of-Line Blocking):** O Hangfire Worker possui `WorkerCount=2` e o `HttpClient` não tem validação *Headers-First* ou timeouts granulares por chunk. Dois alvos governamentais lentos travam o pipeline do sistema inteiro por 30 minutos contínuos.
* **1.4. Poison Pill OOM (Out Of Memory):** Payloads imensos lidos via `JsonDocument.ParseAsync(stream)` no fetch excedem rapidamente os 300MB de limite do container, causando loops infinitos de morte do processo (CrashLoop) devolvendo os jobs para a fila sem tratamento.

---

## 💥 2. Cenários de Falha Silenciosa em Produção (Pre-Mortem)

* **2.1. Progress Update Database Collapse (Write-Amplification):** A emissão de logs a cada linha parseada em arquivos CSV pesados faz com que `GabiJobRunner.PumpProgressUpdatesAsync` inunde o banco com milhões de `.ExecuteUpdateAsync`. O PostgreSQL MVCC entra em colapso com *Dead Tuples*, travando todos os fluxos.
* **2.2. "Vector Semantic Mush" (Corrupção Semântica):** O sistema tira a média (*Mean Pooling*) de embeddings de todos os *chunks* de um documento longo. Isso dilui documentos densos para o "nada", inutilizando a busca vetorial de forma irreversível e sem gerar erros de código.
* **2.3. The Mojibake Fallback:** Falhas esporádicas de UTF-8 em páginas longas engolem a exceção e fazem um fallback ingênuo para `Latin1`. O texto se torna lixo criptográfico e arruína as keywords salvas no Elasticsearch permanentemente.
* **2.4. The Sisyphean Discovery Freeze:** Sem paginação baseada em estado salvo/cursor, qualquer crash de container num crawling governamental de 14 horas devolve o crawler de volta para a estaca zero, criando loops eternos.

---

## 🛡️ 3. Análise de Gaps de Engenharia World-Class (Ação Mitigadora)

Foram cruzados 38 itens avaliados pela auditoria de engenharia de software com os gaps sistêmicos encontrados. Segue o status e a prioridade dos itens não resolvidos com maior peso de risco.

| Risco / Funcionalidade Pendente | Status | Impacto | Ação Planejada |
| :--- | :--- | :--- | :--- |
| **Circuit Breakers Externos** | 🟡 PARCIAL | Alto | Falta circuit breaker (*Polly*) em Elasticsearch, Redis e Fetch. O sistema sucumbirá a falhas em cascata de dependências. |
| **Limite de Replay no DLQ** | 🟡 PARCIAL | Médio | Previne replays sequenciais rápidos, mas **não há limite na cadeia**. Replays em cascata podem atuar como amplificadores de ataque/carga para dependências externas. |
| **Testcontainers c/ PostgreSQL Real** | 🔴 NÃO RESOLVIDO | Alto | O InMemoryDatabase mascara falhas de transação concorrente (Locks, MVCC), ignorando testes reais sobre a fila do Hangfire e tabelas em produção. |
| **Smoke Tests Runtime (Live)** | 🔴 NÃO RESOLVIDO | Alto | O `zero-kelvin` é destrutivo. Não existe um teste periódico (`smoke-test.sh`) em staging/produção para validar saúde end-to-end do pipeline de API. |
| **Health Endpoints sem SLO** | 🔴 NÃO RESOLVIDO | Alto | O Endpoint `/health/ready` responde se o banco existe, mas não define *timeout* (ex: < 2s). E falta saúde do Elasticsearch e Redis no health check nativo da API. |
| **Migrations "Zero-Downtime"** | 🔴 NÃO RESOLVIDO | Alto | `CreateIndex()` sendo usado nas migrations sem a cláusula `CONCURRENTLY`. Em produção, criar índice numa tabela de 10 milhões de Documentos vai fazer *Lock Exclusivo* no DB, paralisando a Gabi.Api. |
| **Redis/Elasticsearch Desprotegidos** | 🔴 NÃO RESOLVIDO | Alto | `docker-compose.yml` sem senhas e `xpack.security.enabled=false`. O modelo permite infraestrutura local/staging desprotegida, facilitando vazamento de dados. |
| **Remoção de Dictionary<string, object>** | 🔴 NÃO RESOLVIDO | Médio | Contratos (ParsedDocument, IngestJob) ainda mantêm Dictionaries sem tipo forte (bypassando segurança *compile-time*), criando falhas na leitura via `IntentGuardrails`. |
| **Gabi.Ingest.Tests (Cobertura de Parse)**| 🟡 PARCIAL | Médio | Parse, normalizador, e *chunker* carecem completamente de cobertura. Regressões matemáticas de vetores ou textos quebrarão o Ingestor silenciosamente. |

---

## ✅ 4. Próximos Passos Táticos (Roadmap Restrito)

1. **Blindagem do PostgreSQL (Write-Amplification):** Adicionar limite em batch (debounce) para o avanço dos Job Progress.  
2. **Defesa do Trabalhador (DoS & OOM):** Limitar o `Contains` da API de buscas; Interceptar e abortar URLs com loopback/IPs Privados (SSRF); Instalar paginador rígido (Buffer) no JSON parser e limitação *Headers-first*.  
3. **Resgate da Integridade Semântica:** Descartar *Mean-Pooling* de vetores. Mover a busca para granulação Nested Chunk. Corrigir fallback para encoding estrito.  
4. **Infraestrutura Sustentável:** Incluir *Polly* para resiliência de dependências, converter a aplicação para *Testcontainers* reais com PostgreSQL, e impor a diretiva `CONCURRENTLY` no DB context de migrações.