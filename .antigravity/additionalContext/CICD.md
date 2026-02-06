# CI/CD

## Pull Request
- Lint
- Testes unitários
- Testes de contrato
- Testes de idempotência

## Idempotency Test
1. Drop índices
2. Reprocessar tudo
3. Comparar:
   - contagem
   - fingerprints
   - hashes

## Deploy
- Blue/Green
- Reindex assíncrono
- Zero downtime
