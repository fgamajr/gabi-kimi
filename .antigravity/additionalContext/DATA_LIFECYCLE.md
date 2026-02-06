# Ciclo de Vida dos Dados

## 1. Discovery
- Produz URLs
- Não baixa conteúdo

## 2. Fetch
- Verifica change_detection_cache
- Se não mudou → skip
- Se mudou → download

## 3. Parse
- Converte para texto estruturado
- Produz metadados brutos

## 4. Normalize
- Aplica transforms declarativos
- Gera conteúdo canônico

## 5. Deduplicate
- Compara fingerprint
- Atualiza versão se necessário

## 6. Index
- Atualiza Elasticsearch
- Marca es_indexed=true

## 7. Chunk + Embed
- Chunk determinístico
- Embeddings descartáveis
