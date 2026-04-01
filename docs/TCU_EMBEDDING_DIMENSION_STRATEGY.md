# Estratégia de dimensões — DOU vs TCU

## Resumo executivo

| Corpus | Campo ES | `dims` no mapping | Origem típica do vetor no documento |
|--------|----------|-------------------|-------------------------------------|
| DOU / documentos v3 | `embedding` | **384** | Servidor de embedding configurado para ingestão híbrida ([`es_index_v3_full.json`](../src/backend/search/es_index_v3_full.json)) |
| TCU acórdãos, normas, BTCU, publicações | `embedding` | **1536** | Pipeline OpenAI em [`tcu_embed.py`](../src/backend/ingest/tcu_embed.py) (`text-embedding-3-small`, `_DIMS = 1536`), alinhado aos mappings [`es_tcu_mapping.json`](../src/backend/search/es_tcu_mapping.json) etc. |

Não é um “bug” de mapping: são **dois pipelines de embedding** com objetivos e infraestruturas diferentes. O risco operacional é usar **um vetor de query com dimensão A** num índice que espera **dimensão B**.

## Caminho de busca hoje (visão de alto nível)

- **DOU (híbrido):** [`hybrid.py`](../src/backend/search/hybrid.py) obtém embedding da query via servidor configurado (`EMBED_SERVER_URL` / fluxo interno) e usa kNN + RRF no índice principal — dimensão deve bater com **384** no índice alvo.
- **TCU (API em `main.py`):** a rota usa `_get_openai_query_embedding` e reordenação por similaridade com embeddings **já armazenados** nos hits (fluxo distinto do hybrid DOU). Os documentos TCU foram pensados para **1536** dims.

## Decisão arquitetural recomendada

1. **Curto prazo (menor risco):** tratar DOU (384) e TCU (1536) como **silos**: nunca enviar o vetor de query do servidor 384 para operações kNN/ES que esperam 1536, nem o inverso.
2. **Médio prazo (opcional — custo alto):** unificar tudo numa única dimensão + modelo exige:
   - novo mapping (ou novo índice),
   - reindexação/backfill de vetores,
   - alinhamento de **query embedding** e de **ingest** para o mesmo modelo.

## Quando reindexar TCU

- Só faz sentido se a decisão for **mudar de modelo** (ex.: sair de `text-embedding-3-small`) ou **reduzir dimensão** para igualar ao DOU — sempre com benchmark e plano de índice paralelo.

## Checklist antes de “ligar kNN em tudo”

- [ ] Confirmar `dims` no `_mapping` real do cluster (não só no JSON do repo).
- [ ] Confirmar dimensão do vetor retornado pelo serviço de embedding da **query**.
- [ ] Para cada índice participante da busca, `POST .../_count` com `exists` no campo `embedding` (ver `ops/rag_rollout_checks.py`).
