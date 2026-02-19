Segue um desenho de sincronização fonte → base alinhado a boas práticas, para a base espelhar a fonte de forma profissional.
1. Princípio: fonte como verdade (Source of Truth)
A fonte (TCU CSV, API Câmara, crawl) é a verdade.
A base é um espelho que deve ser atualizado para refletir o estado atual da fonte.
Toda alteração na base (insert/update/delete) deriva do que a fonte “diz” naquele momento.
2. Padrão: Snapshot + Diff + Reconcile
Fluxo em alto nível:
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐     ┌──────────────┐│   Fonte     │────►│ Obter snapshot  │────►│ Comparar com   │────►│ Aplicar diff ││ (TCU/Câmara)│     │ atual (lista)   │     │ estado na base │     │ na base      │└─────────────┘     └──────────────────┘     └─────────────────┘     └──────────────┘
Snapshot: para cada source, obter a lista atual de itens (identificadores estáveis: URL, external_id, ou chave composta).
Diff: comparar essa lista com o que existe na base para aquela source_id.
Reconcile: aplicar o diff (inserir, atualizar, marcar removidos/remover).
Isso é o mesmo espírito de “full refresh + merge” usado em data lakes e pipelines de integração.
3. Identificador estável por documento (Natural Key)
Cada item na fonte deve ter um ID estável que não mude entre runs:
CSV: coluna de ID externo ou combinação (ex.: número + ano).
API: ID retornado pela API.
PDF/HTML: URL canônica do recurso.
Na base, esse identificador vira a natural key por source: (source_id, external_id) ou (source_id, doc_url).
O hash do conteúdo entra como deduplicação e detecção de “conteúdo mudou” (update), não como substituto do “está ou não na lista da fonte”.
4. Ciclo de sincronização por source
Um ciclo completo por fonte pode ser:
Discovery
Obter a lista atual de “documentos” da fonte (URLs, IDs, metadados mínimos).
Saída: snapshot atual = conjunto de identificadores + metadados leves (título, data, URL).
Fetch (quando necessário)
Para cada item do snapshot, buscar conteúdo e metadados completos (streaming, paginação, etc.).
Opcional: fazer em lotes e com paralelismo controlado.
Reconciliação
Entrada: snapshot atual (lista de identificadores) + estado atual na base para essa source_id.
Regras:
Na fonte e não na base → INSERT (criar doc + jobs de hash/parse/etc.).
Na fonte e na base → UPDATE se conteúdo/metadados mudaram (ex.: via content hash); senão skip (idempotente).
Na base e não na fonte → REMOVER (soft delete recomendado no início).
Persistir estado da sync
Guardar por source: last_sync_at, opcionalmente last_snapshot_hash (para pular reconcile quando nada mudou) e contagens (added/updated/deleted).
Assim, “TCU apagou uma linha” → no próximo ciclo essa linha não entra no snapshot → na reconciliação o documento correspondente é removido (ou marcado removido).
5. Soft delete para itens removidos na fonte
Boa prática: não apagar fisicamente na hora.
Campo tipo removed_from_source_at (timestamp) ou sync_status = 'removed_from_source'.
Vantagens: auditoria, rollback, métricas (“quantos sumiram”), re-processamento em caso de bug.
Job periódico (ex.: após 30 dias) pode fazer hard delete ou arquivar.
6. Idempotência e segurança
Mesmo run duas vezes deve levar ao mesmo estado:
Snapshot é determinístico para o mesmo estado da fonte.
Reconcile usa “estado atual da base” e “lista atual da fonte” → resultado único.
Transações: reconciliar por source em transação (ou por lote de documentos) para não deixar base pela metade em caso de falha.
Lock/visibility: durante a reconciliação de uma source, evitar que outro processo altere os mesmos documentos (ex.: um job por source por vez, ou lock otimista).
7. Incremental quando possível (opcional)
Quando a fonte permitir:
Cursor/watermark: ex. “última data de alteração” ou “último ID”.
Só buscar itens novos ou alterados desde o último run.
Periódico full: de tempos em tempos (ex.: 1x por semana) rodar snapshot completo + reconcile para corrigir qualquer desvio (e captar deleções).
Para CSV estático (TCU) muitas vezes o “snapshot” já é baixar o CSV e extrair a lista; para API (Câmara) pode ser “página 1…N” com filtro de data. O importante é que, no mínimo, você consiga construir a lista atual de identificadores para fazer o diff.
8. Observabilidade
Por run de sync: source_id, started_at, finished_at, status (success/partial/failed).
Métricas: documents_added, documents_updated, documents_removed, documents_unchanged, errors_count.
Logs: erros por documento (ex.: fetch falhou) para retry ou DLQ.
Health: “última sync por source” e alertas se passar X horas sem sucesso.
9. Onde isso encaixa no seu pipeline
Discovery → produz o “snapshot atual” (lista de links/IDs por source).
Fetch → enriquece com conteúdo/metadados.
Reconcile (nova fase explícita) → diff snapshot vs base e aplica insert/update/remove (com soft delete).
Jobs por documento (hash, parse, chunk, etc.) → continuam depois do insert/update; documentos “removed” não entram em novos jobs.
Ou seja: a “sincronização profissional” é Snapshot + Diff + Reconcile + identificador estável + soft delete + idempotência + observabilidade. Os dois hashes (doc + source) ajudam em dedup e proveniência; o “espelho perfeito” vem dessa fase de reconciliação com a lista atual da fonte.
Se quiser, no próximo passo dá para colocar isso no plano como “Fase de Reconciliação e estratégia de sync (Source of Truth)” com checklist (identificador estável, soft delete, métricas, full vs incremental).

Brainstorming: antes de implementar cada parte nova (Reconciliação, Crawler, etc.) — uma pergunta por vez, 2–3 abordagens, design em seções de 200–300 palavras, salvar em docs/plans/.



TDD: para cada feature/bugfix — teste que falha primeiro, código mínimo para passar, refactor; sem código de produção sem teste que falhou antes.



Data Governance: schema (PKs, FKs, audit trail), retenção (soft delete com removed_from_source_at), classificação de dados, checklist de compliance se aplicável (LGPD para dados pessoais).



Zero Kelvin: critério de aceitação global; cada sprint deve manter ou melhorar a capacidade de “destruir tudo e subir de novo” com o mesmo resultado; script tests/zero-kelvin-test.sh como gate.



2. Fases do plano (resumo)







Fase



Objetivo



Skills usados



Gate





0



Design da sincronização (Snapshot + Diff + Reconcile)



Brainstorming



docs/plans/YYYY-MM-DD-sync-reconciliation-design.md





1



Foundation (Gabi.Jobs, Pipeline, schema)



TDD + Zero Kelvin



./scripts/setup.sh + build + testes verdes





2



Fetch + Hash + Reconciliação



TDD + Data Governance (audit trail)



Zero Kelvin + reconcile testado





3



Crawler + Discovery expandido



TDD + Brainstorming (por strategy)



Zero Kelvin





4



API + Zero Kelvin formal



TDD



tests/zero-kelvin-test.sh passa



3. Regras transversais





TDD: Nenhum código de produção sem um teste que falhou antes (Red → Green → Refactor). Testes escritos depois não contam como TDD.



Zero Kelvin: Após cada sprint, executar docker compose down -v, ./scripts/setup.sh, ./scripts/dev app start e validar health + um fluxo mínimo; idempotência de setup.sh deve ser mantida.



Brainstorming: Novas features (ex.: reconciliação, nova strategy de crawl) → explorar com perguntas, 2–3 opções, design em seções, validar antes de codar; documentar em docs/plans/.



Data Governance: Tabelas com created_at/updated_at; tabelas de documento com removed_from_source_at para soft delete; unicidade (ContentHash, SourceId); considerar checklist de auditoria para tabelas que guardem dados sensíveis.