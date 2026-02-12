  Apps Core:

  1. Gabi.Contracts - contratos
  2. Gabi.Postgres - infra do banco, migrations, ORM, repositórios
  3. Gabi.Discover - descoberta de fontes
  4. Gabi.Ingest - fetch, parse, transform, dedup, chunk
  5. Gabi.Sync - orquestrador que coordena Discover + Ingest + Postgres
  6. Gabi.Worker - entry point (BackgroundService)

  Ou o usuário quer:

  • Gabi.Sync = lógica de sincronização (diff, merge, upsert operations)
  • Gabi.Orchestrator = orquestração do pipeline


     Semana   Foco                 Entregável
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   1        Foundation           Solution + 6 projetos, migrations funcionando
   2        Discover + Fetcher   Download streaming funcionando
   3        Parser + Process     Parse completo, chunks gerados
   4        Sync + Worker        Pipeline end-to-end
   5        Polish               Testes, Docker, produção-ready