# Reliability Lab

Plataforma de validacao de confiabilidade (Reliability Lab) para o pipeline GABI. Separa definicao do experimento, execucao, observacao, avaliacao e report.

## Projetos

- **Gabi.ReliabilityLab** — Core: engine de experimentos, politicas, verificacao, telemetria, reporting (sem dependencias de dominio).
- **Gabi.ReliabilityLab.Environment** — Controlador de infra: `TestcontainersController` (sobe containers) ou `DockerComposeController` (usa compose ja rodando).
- **Gabi.ReliabilityLab.Pipeline** — Cenarios e checks do pipeline (ZeroKelvinScenario, integridade, semantica, continuidade).
- **Gabi.ReliabilityLab.Tests** — Adapter xUnit: testes que chamam `ExperimentRunner.RunAsync` e avaliam `PolicyVerdict`.

## Executar testes do Lab

```bash
# Apenas testes do Reliability Lab (Tier 3)
dotnet test tests/ReliabilityLab/Gabi.ReliabilityLab.Tests --filter "Category=ReliabilityLab"

# Excluir do CI rapido
dotnet test GabiSync.sln --filter "Category!=ReliabilityLab"
```

### Requisito: Docker estavel (Testcontainers)

Os testes do Lab sobem Postgres, Redis e Elasticsearch via **Testcontainers**. Eles podem falhar se o ambiente remover containers antes do `Stop` (ex.: "No such container"), comum em OrbStack/Docker Desktop com limpeza agressiva ou CI sem Docker dedicado.

- **Recomendacao:** rodar em ambiente com Docker estavel (runner com Docker-in-Docker ou host com `docker compose` sempre ativo).
- **Alternativa local:** levante a infra com `./scripts/dev infra up` e use `DockerComposeController` nos testes (nao inicia/para containers; usa Postgres/Redis/ES do compose). Exemplo: instanciar `DockerComposeController.CreateLocal()` e passar ao `ExperimentRunner` no lugar de `TestcontainersController`; portas padrao: Postgres 5433, Redis 6380, ES 9200.

## Artefatos

Cada execucao gera em `artifacts/reliability/{correlationId}/`:

- `summary.json` — resultado e verdict
- `metrics.json` — metricas de recurso e por stage
- `timeline.json` — trace de execucao
- `verification.json` — resultados dos checks
- `failures.md` — analise de falhas (se houver violations)
- `raw/` — telemetria bruta para post-mortem

## Scripts bash deprecated

Os scripts em `tests/*.sh` estao marcados como DEPRECATED e serao migrados para cenarios do Lab. Ver cabecalho de cada script.
