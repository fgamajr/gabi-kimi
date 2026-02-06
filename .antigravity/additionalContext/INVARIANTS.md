# Invariantes do Sistema (Leis Físicas)

Estas regras NÃO podem ser violadas por agentes, humanos ou scripts.

## 1. Fonte de Verdade Única
- `config/sources.yaml` é a única definição de fontes.
- Nenhum código pode conter URLs, schemas ou lógicas hardcoded.

## 2. Idempotência de Execução
- Executar o pipeline duas vezes sem mudança externa
  NÃO pode gerar:
  - downloads repetidos
  - reindexações desnecessárias
  - novos embeddings

## 3. Detecção de Mudança Obrigatória
Toda requisição HTTP deve usar, quando disponível:
- ETag
- Last-Modified
- Content-Length
- Hash de conteúdo

Cache persistido em `change_detection_cache`.

## 4. Soft Delete
- Nenhum documento é fisicamente removido.
- Exclusões externas resultam em:
  is_deleted = true
  deleted_at != null

## 5. Fingerprint Canônico
Cada documento possui fingerprint imutável:
- Algoritmo: SHA-256
- Baseado no conteúdo normalizado
- Usado para deduplicação cross-source

## 6. Separação de Stores
- PostgreSQL: verdade canônica
- Elasticsearch: índice derivado
- Vetores: derivados e descartáveis

Postgres sempre vence.

## 7. Agentes Não Criam Infra
- Docker, bancos, índices e volumes
  já devem existir ou ser definidos fora do swarm.
