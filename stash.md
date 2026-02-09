Status Final
  - Relatório consolidado preparado abaixo.
  - Commit: 8a2372d8bce652047255307323fedbcc5e15188f



  - url_pattern agora suporta valores simbólicos (current, current_year, this_year, now) com coerção robusta de range.
  - Ajuste de ranges com step inválido/descendente.
  - Fallback de discovery para modos crawler e api_query no caminho de validação via orchestrator.
  Arquivos:
  - src/gabi/pipeline/discovery.py
  - src/gabi/pipeline/orchestrator.py
  2. Sync Pipeline (fetch/parse/embed/index)
  - sync passou a construir ContentFetcher por fonte com overrides de tamanho (max_size_mb / max_size_bytes).
  - Em validação com CSV, fetch/parse podem aceitar arquivos maiores sem quebrar amostragem por max_rows.
  - Parser CSV agora respeita max_parse_size_bytes configurável (com limites de segurança).
  - Embedding integrado no fluxo de sync (geração + persistência em document_chunks) com comportamento fail-open por padrão e fail-hard
    opcional (embedding.required=true).

  Arquivos:

  - src/gabi/tasks/sync.py


  - Classificação por tipo no resultado de sync:
      - source_content_too_large
      - source_http_error
      - internal_pipeline_regression
      - unknown
  - Agregação por fonte (error_summary) e flag derivada (source_unreachable).
  - Erros de parse agora entram explicitamente no relatório de erros.

  Arquivo:
  - src/gabi/tasks/sync.py

  4. Runner Agregado “All Sources”
  - Novo comando CLI ingest-all com leitura de sources.yaml.
      - failed_sources_external_unreachable
      - failed_sources_other
  - Mantém results por fonte + tempo total.


  - tests/unit/test_cli.py
  ———
  Resultados de Testes


  test_parser_security.py -q
  Resultado:

  - 91 passed in 11.58s
  Também validado anteriormente no ciclo:
  - tests/unit/tasks/test_sync.py (classificação e fluxo)


  Validação Operacional (Run Real)
  - ingest-all executou com nova estrutura agregada.
  - Isso não invalida a implementação do agregador; indica gap de infraestrutura de embedding no ambiente.

  ———



  - Reduzir ruído de retries quando backend está down (já parcialmente mitigado por circuit breaker).

  - Adicionar flags de runtime no CLI:
      - --disable-embeddings

  3. Observabilidade de execução agregada

  - Exportar os buckets do ingest-all para dashboard/monitoramento (Prometheus/Grafana).

  4. Classificação de falhas de infraestrutura local

  - Separar mais explicitamente erros locais de stack (ex.: DB/Redis/TEI indisponível) de erros externos de fonte.

  ———

  Commit e Push

  - Commit criado:
      - 8a2372d8bce652047255307323fedbcc5e15188f
      - mensagem: Add ingest-all aggregate classification and sync pipeline hardening
  - Arquivos no commit:
      - src/gabi/cli.py
      - src/gabi/pipeline/discovery.py
      - src/gabi/pipeline/orchestrator.py
      - src/gabi/pipeline/parser.py
      - src/gabi/tasks/sync.py
      - tests/unit/tasks/test_sync.py
      - tests/unit/test_cli.py
  - Push concluído:
      - kmi -> origin/kimi (hash remoto atualizado para 8a2372d)

  Se quiser, no próximo passo eu implemento já o ingest-all --disable-embeddings --max-docs-per-source 1 para você ter um runner de
  validação rápida pronto para uso diário.