# Queue Hygiene (P1.6)

## Objetivo

Liberar estado zumbi de fila em ambiente local/teste, sem apagar histórico:

- `job_registry` preso em `processing` por muito tempo
- `hangfire.jobqueue.fetchedat` preso (mensagens reservadas e não devolvidas)

## Script

Arquivo: `scripts/queue-hygiene.sh`

### Dry-run

```bash
./scripts/queue-hygiene.sh --dry-run
```

### Aplicar limpeza

```bash
./scripts/queue-hygiene.sh --apply --stale-minutes 15
```

## O que o script faz

1. Marca registros stale de `job_registry` como `failed` com mensagem de recuperação.
2. Reabre entradas stale de `hangfire.jobqueue` (`fetchedat -> NULL`, `updatecount + 1`).
3. Mostra contadores remanescentes ao final.

## Segurança operacional

- Não remove linhas históricas.
- Não trunca tabelas de Hangfire.
- Atua apenas em itens acima do limiar temporal (`--stale-minutes`).
- Recomendado para local/staging e cenários de teste repetitivo (ex.: zero-kelvin).
