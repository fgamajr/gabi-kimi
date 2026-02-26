# Staging Validation Playbook — Experimentos de Confiabilidade

**Alvo:** Gabi-Kimi (Sistema de Ingestão Jurídica TCU)  
**Modo:** Staging Validation Playbook

Este documento define invariantes de steady state, um catálogo de experimentos de chaos, procedimentos de segurança/rollback e a matriz de cobertura de confiabilidade. **Chaos tests só devem rodar em ambiente não-Production** (ex.: Staging ou Development). O script `tests/chaos-test.sh` recusa execução se `DOTNET_ENVIRONMENT=Production`.

---

## A — Steady State Definition

(Invariantes mensuráveis que definem um sistema saudável.)

1. **Job Completion Rate:** Todo job inserido na JobRegistry transita de `pending` → `processing` → `completed` (ou `failed`) em tempo previsível (menos de 5 minutos para chunks normais), e a JobQueue não sofre acúmulo contínuo.
2. **Idempotency Invariant:** Se o endpoint `dashboard/sources/{sourceId}/phases/fetch` for acionado duas vezes consecutivas sem mudança de ETags/Last-Modified na origem, o Documents count no PostgreSQL (`SELECT COUNT(*) FROM documents`) e o total de `linksTotal` na `discovery_runs` não devem se alterar.
3. **Memory Confinement:** O uso de memória residente (RSS) do container `gabi-worker` sob carga máxima constante de Ingest nunca excede 300MB (`docker stats --no-stream`).
4. **Data Consistency Invariant:** Para cada registro com `status = completed` na tabela `documents` (PostgreSQL), deve existir exatamente um `EsDocument` no índice `gabi-docs` do Elasticsearch.

---

## B — Chaos Experiment Catalog

### 1. "The Transient Database Hiccup" (PostgreSQL Stall)

- **Hypothesis:** O sistema tolera quedas rápidas no banco de dados sem perder a integridade da fila (via políticas de Retry nativas do Hangfire) e sem vazar logs de exceção que exijam reprocessamento manual.
- **Fault Injection Method:** Executar `docker pause postgres` por exatamente 15 segundos durante o tráfego pesado de Fetch, seguido de `docker unpause postgres`.
- **Expected System Behavior:** Threads de HttpClient ou conexões EF Core lançam Transient DB capacity ou timeout. O DlqFilter intercepta o estado de FailedState, planeja o Exponential Backoff usando a categoria Transient, e reagenda. Assim que o banco retorna, os jobs recomeçam sem perdas.
- **Failure Signal:** Jobs caindo na DLQ (`dlq_entries`) com ErrorType de banco, ou Workers morrendo de vez e precisando ser reiniciados via orquestrador.
- **Observability Required:** Logs de RetryPolicy (Category=Transient), contagem de registros na DLQ, e métricas de Dead Tuples (se a transação travar).
- **Blast Radius:** Fila do Hangfire e Worker pool.

**Rollback:** `docker unpause postgres` (ou nome do container Postgres no docker-compose).

---

### 2. "The Indestructible Tarpit" (Slow External Dependency)

- **Hypothesis:** Fontes de rede propositalmente lentas não devem monopolizar o limitadíssimo pool do Worker (WorkerCount=2), e sim falhar o Job de maneira gracefully por timeout imposto no chunk, preservando throughput em outras fontes.
- **Fault Injection Method:** Configurar em `sources_v2.yaml` um servidor HTTP local simulado (com Toxiproxy ou NGINX) que aceita conexões TCP imediatamente, mas envia o conteúdo do CSV à taxa de 1 Byte a cada 5 segundos. Acionar `/dashboard/sources/toxiproxy/phases/fetch`.
- **Expected System Behavior:** O HttpClient (que possui Timeout = 30min) é interrompido antes graças a um CancellationToken por chunk, ou falha gracefully. O Worker aborta a task, não travando sua thread indefinidamente.
- **Failure Signal:** Todos os logs de Progress do Worker para todas as fontes do país param simultaneamente. O Dashboard reporta o worker farm como inativo/paralisado.
- **Observability Required:** Trace spans OTel pipeline.fetch, latência global de progresso de outras filas, monitoramento de Threads em uso do dotnet.
- **Blast Radius:** Worker thread pool e pipeline de extração de dados HTTP.

**Rollback:** Remover a fonte tarpit do YAML ou parar o servidor lento; reiniciar worker se necessário.

---

### 3. "The Poison Pill Bomb" (Unbounded Data Payload)

- **Hypothesis:** O limite de recursos de processamento local (Memória RAM do container) bloqueia alocações maliciosas. Documentos malformados gigantes falham isoladamente (category=Permanent) sem derrubar o container.
- **Fault Injection Method:** Modificar uma fonte simulada governamental para entregar uma string JSON perfeitamente válida estruturalmente, porém com 1 Gigabyte de texto ininterrupto num único campo. Disparar a extração `JsonDocument.ParseAsync`.
- **Expected System Behavior:** A aplicação detecta um ContentLength abusivo ou o Utf8JsonReader corta o stream. O job recebe status "Failed" (Permanent), cai na DLQ para auditoria, e o container continua vivo e consumindo o resto da fila.
- **Failure Signal:** O container reporta OOM (Out of Memory) (Exit Code 137). O job morre invisivelmente e é reagendado pelo InvisibilityTimeout, criando o CrashLoop.
- **Observability Required:** Gráfico de métricas de heap GC .NET, docker stats Memory RSS, logs de stdout para mensagens SIGKILL.
- **Blast Radius:** Container do Gabi.Worker local (Node).

**Rollback:** Remover a fonte poison pill; reiniciar worker; em caso de estado persistente, `./tests/zero-kelvin-test.sh docker-only`.

---

### 4. "Network Split-Brain" (Partial Elasticsearch Outage)

- **Hypothesis:** A Ingestão no PostgreSQL (camada canônica) nunca se descasa do Elasticsearch (camada derivada) se o Elastic ficar inacessível na última milha do processo de IndexAsync.
- **Fault Injection Method:** Adicionar uma regra de iptables no host do container do Worker: `iptables -A OUTPUT -p tcp --dport 9200 -j DROP` durante a execução paralela de Ingests normais. Manter por 2 minutos e remover.
- **Expected System Behavior:** O ElasticsearchDocumentIndexer retorna IndexingStatus.Failed. O IngestJobExecutor cancela a operação lógica antes de comitar a transação de "Sucesso" no PostgreSQL. Job entra em Retry (Transient) pelo Hangfire.
- **Failure Signal:** job_registry e a tabela documents marcam os itens como "completed" ou "success", enquanto o Elasticsearch não contém os chunks associados (violação da invariante de separação de stores e sincronia).
- **Observability Required:** Queries de reconciliação de contagem (Postgres COUNT(*) vs ES CountAsync).
- **Blast Radius:** Indexação semântica, integridade de pesquisa na API REST.

**Rollback:** `iptables -F` (ou remover a regra específica no OUTPUT); garantir que ES esteja acessível.

---

### 5. "The Ghost Deploy" (Interrupted Progress/Deployment during processing)

- **Hypothesis:** Enviar um sinal SIGTERM ao Worker garante Graceful Shutdown completo: as transações do Entity Framework finalizam limpas, e o estado parcial não fica preso no banco, impedindo reinícios sujos.
- **Fault Injection Method:** Enviar um sinal `docker kill --signal=SIGTERM gabi-worker` no momento exato em que um CSV de 50.000 linhas bate ProgressPercent = 50% (PumpProgressUpdatesAsync).
- **Expected System Behavior:** O IHostedService recebe cancelamento. O Worker para de ler novas linhas do channel, termina o processamento e o COMMIT do batch atual (dentro de um timeout máximo configurado). O job retorna para a fila sem deixar a tabela travada em "Processing".
- **Failure Signal:** O Job fica órfão com Status="processing" (Zumbi). A transação de persistência de URLs ou Fetch Items falha ou perde os progressos salvos na metade.
- **Observability Required:** Status da tabela job_registry após shutdown; tempos de latência em spans pipeline.job no OTel; estado do Hangfire Dashboard (Servers list).
- **Blast Radius:** O processamento em voo da fila Hangfire.

**Rollback:** Se job zumbi persistir, executar `./tests/zero-kelvin-test.sh docker-only` para recriar do zero (conforme Safety & Rollback Plan).

---

### 6. "The Replay Amplification Surge"

- **Hypothesis:** O endpoint manual da DLQ (`POST /api/v1/dlq/{id}/replay`) possui throttling real em profundidade por IP e Item, impedindo amplificação de tráfego de ataques.
- **Fault Injection Method:** Injetar um script de carga (via Apache Benchmark ou K6) disparando 500 requests HTTP/s com Token de Operador válido no endpoint de replay para um único ID de falha de Rate Limit/429.
- **Expected System Behavior:** Os três primeiros requests completam (sob quota), os demais retornam 429 Too Many Requests (ou bloqueio similar) oriundo da regra definida no DlqService (limit 1 replay/min).
- **Failure Signal:** O banco de dados Hangfire enche de réplicas de execução; o serviço externo TCU engasga e reage banindo os IPs do nosso servidor; Worker atinge saturação de thread.
- **Observability Required:** Response Codes da API. Tamanho do log de falhas do Hangfire.
- **Blast Radius:** Tráfego de rede API interna → rede de terceiros.

**Rollback:** Parar o script de carga; rate limiter e throttle de replay restauram o estado normal.

---

### 7. "The Duplicate Delivery Test" (Idempotency Override)

- **Hypothesis:** Se o PostgreSQL receber um IngestJob perfeitamente duplicado que sobreviveu à etapa do IX_IngestJobs_PayloadHash (hash do payload), o executor não fará operações destrutivas ou inserções duplicadas no Elasticsearch.
- **Fault Injection Method:** Forçar via script SQL a inserção manual de um job identicamente formatado na fila Hangfire (Hangfire.Job table) e no JobRegistry, duplicando um UUID já percorrido e validado.
- **Expected System Behavior:** O código de Ingest executa a rotina normal de Update ou Upsert. Ele atualiza as datas em Documents mas percebe SkippedUnchanged = true no Fetch, não criando versões repetidas e retornando Sucesso sem tráfego de rede.
- **Failure Signal:** Multiplicação da contagem total no Elasticsearch para a mesma fonte, ou lançamentos de Unique Constraint Violation em DiscoveredLinks.
- **Observability Required:** Tamanho lógico da tabela Postgres e Hits do ES.
- **Blast Radius:** Acurácia do motor de busca, armazenamento e faturamento do Elasticsearch.

**Rollback:** Reverter inserções manuais se necessário; limpar jobs duplicados na fila.

---

### 8. "Clock Skew Anomaly" (Time Travel)

- **Hypothesis:** A geração de UpdatedAt e verificação `ReplayedAt.Value >= DateTime.UtcNow.AddMinutes(-1)` utilizam sempre tempos canônicos sem assumir precisão de relógio entre DB e Worker, prevenindo rejeição sistêmica de tarefas ou jobs instantaneamente declarados zumbis.
- **Fault Injection Method:** Adulterar temporariamente a hora do sistema do container gabi-worker com libfaketime adicionando um drift instantâneo de +5 minutos no futuro em relação ao PostgreSQL host. Disparar uma carga leve de discovery.
- **Expected System Behavior:** Prazos de timeouts do Hangfire baseiam-se nos relógios da base de dados (ou são coerentes nos deltas), ou a aplicação é robusta a pequenos drifts.
- **Failure Signal:** Jobs criados como "Stale" magicamente abortam; timeouts de "Invisibility" do Hangfire disparam em loop; ou Replays de DLQ bloqueados ad-eternum.
- **Observability Required:** Logs do Hangfire Server, timestamps inseridos no job_registry.
- **Blast Radius:** Sincronismo da coordenação do Job Scheduler.

**Rollback:** Remover libfaketime e reiniciar container com relógio correto.

---

## C — Safety & Rollback Plan

- **Rollback Procedure Geral:** Todos os experimentos de Chaos descritos operam independentes do estado de configuração persistido e afetam apenas camadas "Transitórias".
  1. Para `docker pause`, o `unpause` é a recuperação natural.
  2. Para redes e iptables, flush das regras recria fluxo livre.
  3. Para falhas fatais persistentes (como locks órfãos Zumbis do Experimento 5), executar `scripts/dev db apply` não servirá; a mitigação imediata de teste será o script `./tests/zero-kelvin-test.sh docker-only` para recriar a arquitetura a partir do marco zero com segurança e reprodutibilidade (já provado estável no repositório).

- **Data Safety:** Os testes operam estritamente em ambiente de **Staging** (docker-compose local). Os scripts **não podem rodar** se a variável `DOTNET_ENVIRONMENT=Production`. Nenhum dado sensível judicial sofre mutação cruzada. O Elasticsearch de teste opera em volume transiente que é destruído entre runs.

- **Maximum Execution Time:** Todo Chaos Test deve ser encapsulado num test runner script (ex.: `tests/chaos-test.sh`) que impõe um limite rígido de **15 minutos** via `timeout 900`. Passado o limite, os comandos de flush docker e recriação de infra forçam a volta do Steady State.

---

## D — Reliability Coverage Matrix

| Category            | Covered? | Experiment Association                    |
| ------------------- | -------- | ----------------------------------------- |
| Crash recovery      | Yes      | Exp 5 (The Ghost Deploy)                   |
| Retry safety        | Yes      | Exp 1 (The Transient Database Hiccup)     |
| Idempotency         | Yes      | Exp 7 (The Duplicate Delivery Test)       |
| Backpressure        | No       | (Identificada ausência na auditoria)      |
| Dependency outage   | Yes      | Exp 4 (Network Split-Brain)               |
| Slow dependency     | Yes      | Exp 2 (The Indestructible Tarpit)         |
| Partial writes      | Yes      | Exp 4 e Exp 5                              |
| Data consistency    | Yes      | Exp 4 (Postgres vs ElasticSync)           |
| Deployment safety   | Yes      | Exp 5 (SIGTERM Handling)                   |
| Resource exhaustion | Yes      | Exp 3 (The Poison Pill Bomb)              |

---

## E — Confidence Assessment

**Rating:** Moderate confidence

**Justification:** O sistema demonstra excelência por depender fortemente de frameworks resilientes de mercado (Entity Framework com RetryPolicies integráveis e o engine do Hangfire, cobrindo com folga os testes de Database Outage e Retry Safety). No entanto, o sistema pontua na zona moderada (e não Production-grade) porque a arquitetura de processamento assíncrono em pipelines pesados (como I/O bound e rede HTTP sem validação estrita de Headers / Timeout limitadores em streaming de CSV) e a gestão reativa a SIGKILLs (não Graceful) representam brechas severas de vazamento de estabilidade. Rodar o catálogo provará o Head-Of-Line blocking imediatamente e forçará a correção das Invariantes.

---

## Mapeamento: Experimentos vs Código Atual

| Experimento                 | Suporte atual | Gap / observação |
| --------------------------- | ------------- | ----------------- |
| 1 – Transient DB Hiccup     | DlqFilter + ErrorClassifier (Transient); retry com backoff no FetchJobExecutor | Alinhado; observabilidade em parte |
| 2 – Indestructible Tarpit   | CancellationToken propaga; sem timeout por request no fluxo CSV | Gap: timeout granular por chunk/request (ex.: 60–120s) |
| 3 – Poison Pill            | link_only usa ReadAllBytesWithLimitAsync (20MB); json_api usa JsonDocument.ParseAsync(stream) sem limite | Gap: json_api pode OOM; limitar stream antes de ParseAsync |
| 4 – Network Split-Brain    | IngestJobExecutor: IndexAsync antes de commit; Failed/RolledBack lança exceção | Alinhado |
| 5 – Ghost Deploy           | JobWorkerHostedService.StopAsync com ShutdownTimeout | Alinhado se ShutdownTimeout configurado |
| 6 – Replay Amplification   | DlqService 1 replay/min por entrada; rate limit write 10/min | Alinhado |
| 7 – Duplicate Delivery     | ON CONFLICT em InsertBatchAsync; Ingest update/upsert | Verificar índice/constraint em job_registry |
| 8 – Clock Skew             | DateTime.UtcNow no throttle; Hangfire usa relógio do servidor | Risco moderado; experimento valida na prática |
