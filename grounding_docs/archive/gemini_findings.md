# Auditoria Técnica de Base Zero e Pre-Mortem: GABI

**Data da Auditoria:** 25 de Fevereiro de 2026  
**Escopo:** `src/Gabi.Worker`, `src/Gabi.Api`, `src/Gabi.Postgres`, `src/Gabi.Ingest`  
**Perfil da Análise:** Principal Software Architect & Site Reliability Engineer (SRE)

Este documento consolida os achados da due diligence técnica e da análise prospectiva de falhas (Pre-Mortem), incluindo a **Auditoria Forense Recente**. O objetivo é expor vetores de colapso estrutural, corrupção silenciosa de dados e vulnerabilidades arquiteturais, seguidos de um checklist de remediação estratégico.

---

## 🚨 1. Riscos Arquiteturais Críticos (Due Diligence)

### 1.1. SSRF (Server-Side Request Forgery) Irrestrito
*   **Mecanismo:** O `FetchJobExecutor` e o endpoint de upload de mídia baixam dados de URLs usando um `HttpClient` global.
*   **Status Atualizado:** ⚠️ MITIGADO parcialmente pela classe `UrlAllowlistValidator`, mas faixas privadas em provedores de nuvem precisam de atenção contínua.

### 1.2. Denial of Service (DoS) por Varredura Textual O(N)
*   **Mecanismo:** No `Gabi.Api/Program.cs`, o endpoint `GET /api/v1/search` (quando o Elasticsearch não responde) faz um fallback para o PostgreSQL usando `.Where(d => d.Content.ToLower().Contains(q))`.
*   **Impacto:** Isso força um *Sequential Scan* em textos longos. Poucas requisições derrubarão a CPU do banco para 100%.
*   **Severidade:** 🔴 CRÍTICA

### 1.3. Tarpitting Thread Starvation (Head-of-Line Blocking)
*   **Mecanismo:** O Hangfire Worker roda com `WorkerCount = 2`. O `HttpClient` lê os streams de destino limitados apenas por um timeout global de 30 minutos.
*   **Impacto:** Servidores governamentais lentos (Tarpitting) prenderão as únicas threads do Worker, congelando o pipeline inteiro por 30 minutos.
*   **Severidade:** 🟠 ALTA

### 1.4. Poison Pill OOM (Out Of Memory) via ParseAsync
*   **Mecanismo:** A leitura de payloads JSON no fetcher utiliza `using var doc = await JsonDocument.ParseAsync(stream)`.
*   **Impacto:** Payloads colossais não paginados estouram o limite do container (300MB budget), causando *CrashLoop* silencioso.
*   **Severidade:** 🟠 ALTA

### 1.5. Catastrophic Out-of-Memory (OOM) via Unbounded Buffer (Novo)
*   **Mecanismo:** `IngestJobExecutor.ExecuteAsync` carrega lotes massivos na memória: `.Take(MaxPendingDocsPerRun).ToListAsync(ct)` (onde `MaxPendingDocsPerRun = 5000`).
*   **Impacto:** Carregar 5000 documentos jurídicos completos de uma vez estoura violentamente o *budget* de 300MB, resultando em morte súbita do processo (SIGKILL) sem deixar logs estruturados (falha invisível).
*   **Severidade:** 🔴 CRÍTICA

### 1.6. Apagamento Total de Metadados na Busca / Corrupção Semântica (Novo)
*   **Mecanismo:** A classe interna de persistência `EsDocument` em `ElasticsearchDocumentIndexer.cs` omitiu o campo `Metadata`.
*   **Impacto:** Todo o trabalho de parsing legal (`normative_force`, datas, ids da norma) é descartado no momento da indexação. O índice Elasticsearch torna-se "cego" para filtros facetados. O dano é permanente no read-model.
*   **Severidade:** 🔴 CRÍTICA

---

## 💥 2. Cenários de Falha Silenciosa em Produção (Pre-Mortem)

### 2.1. Progress Update Database Collapse (Write-Amplification)
*   **Mecanismo:** `PumpProgressUpdatesAsync` dispara um `ExecuteUpdateAsync` no banco para *cada* evento do parser. O MVCC do PostgreSQL gera milhões de *Dead Tuples* (Bloat) em minutos, derrubando o I/O do banco.

### 2.2. "Vector Semantic Mush" (Corrupção Semântica Irreversível)
*   **Mecanismo:** Em espaços vetoriais longos, o ElasticsearchDocumentIndexer faz a média (*Mean Pooling*) de milhares de chunks, colapsando os embeddings na origem e retornando falsos negativos silenciosos.

### 2.3. The Mojibake Fallback
*   **Mecanismo:** `FetchJobExecutor.DecodeBytesToString` aplica um fallback genérico engolindo exceção (`Encoding.Latin1.GetString`). O ES indexa lixo textual, destruindo permanentemente a busca de keywords.

### 2.4. Race Condition na Conclusão do Pipeline (Novo)
*   **Mecanismo:** A verificação `allDone` (`_context.Documents.AllAsync`) no `IngestJobExecutor` sofre condição de corrida se workers concorrentes atualizarem documentos filhos simultaneamente. O `DiscoveredLink` pai fica eternamente órfão no status `pending`.

### 2.5. Drift de Identidade de Entidade (Novo)
*   **Mecanismo:** O `FetchJobExecutor` gera um `externalId` baseado no hash da URL + Título caso a origem não forneça um ID forte.
*   **Impacto:** Correções de erros de digitação nos títulos das fontes recriam um documento totalmente novo, ignorando o `ON CONFLICT` do PostgreSQL e fragmentando o histórico legal.

---

## ✅ 3. Plano de Ação Estratégico (Checklist de Correções)

### Fase 1: Estabilização Imediata (Alta Criticidade)
- [ ] **Debounce no Progress Pump:** Adicionar um limitador de tempo em `GabiJobRunner.PumpProgressUpdatesAsync` (ex: máx 1 atualização por segundo) para evitar colapso de I/O por write-amplification.
- [ ] **Limitar Fallback de Busca Textual:** Em `Gabi.Api/Program.cs`, obrigar o uso do Elasticsearch para bases grandes e desativar o `.Contains()` irrestrito no banco de dados relacional.
- [ ] **Resolver OOM no Ingest (Novo):** Substituir o `.ToListAsync()` em `IngestJobExecutor.cs` por um stream transacionado usando `IAsyncEnumerable`. Processar iterativamente em chunks e descartar da memória para respeitar o limite arquitetural estrito de 300MB.
- [ ] **Preservar Metadados no Elasticsearch (Novo):** Adicionar a propriedade `public IReadOnlyDictionary<string, object> Metadata { get; init; }` na classe interna `EsDocument` em `ElasticsearchDocumentIndexer.cs`. Mapear dinamicamente no cluster Elastic.

### Fase 2: Robustez de Dados e Identidade (Médio Prazo)
- [ ] **Mitigação SSRF Contínua:** Confirmar e estender a validação na `UrlAllowlistValidator` contra novos ranges de IP de metadados na nuvem.
- [ ] **Remover Mojibake Fallback:** Parar de usar `Latin1` ao engolir erro UTF-8 no Fetch. Implementar fallback seguro de charset via HTTP Headers / BOM.
- [ ] **Abolir o Mean Pooling Global:** Remover média matemática arbitrária de chunks em `ElasticsearchDocumentIndexer.cs`. Utilizar buscas híbridas (BM25 + Nested K-NN) mantendo a granularidade textual.
- [ ] **Estabilizar Identidade (Entity Drift) (Novo):** Refatorar geração do `externalId` no `FetchJobExecutor.cs` para usar apenas hashes constantes (como a URL limpa) sem envolver campos mutáveis como o Título, garantindo idempotência e prevenindo duplicação de dados nas atualizações.

### Fase 3: Resiliência Operacional (Longo Prazo)
- [ ] **Defesa contra Tarpitting:** No `HttpClient` do Fetch, implementar limite estrito e `CancellationToken` por bloco de bytes lido (*Read Timeout*) em vez de apenas no request inteiro.
- [ ] **Segurança em JSON Grandes:** Substituir `JsonDocument.ParseAsync` por paginação/streaming nativo via `Utf8JsonReader` para impedir *Poison Pill OOM* em payloads monolíticos.
- [ ] **Corrigir Race Condition do Pipeline (Novo):** Substituir a lógica frágil e concorrente de `AllAsync` no Ingest. Implementar Lock Pessimista (ex: `SELECT FOR UPDATE` no Link pai no Postgres) ou delegar a reconciliação do `DiscoveredLink` para um *Sweep Job* assíncrono separado.
- [ ] **Paginação no Discovery Engine:** Estender `IDiscoveryAdapter` para suportar `resume_cursor`, persistindo checkpoints nativos no banco para Web Crawls massivos.

---
*Nota: Este relatório foi unificado, filtrando meta-conversas da IA, e combina achados de due diligence prévios com a recém executada Auditoria Forense Operacional. Todas as remediações devem respeitar os invariantes em `AGENTS.md`.*