# Próximos Passos — RAG Improvement

## Item 1 — Teste gabi_answer ponta a ponta

**Objetivo:** verificar qualidade real das respostas RAG antes de qualquer refactor.

**Prompt para Claude Code:**
```
Use gabi_answer("o que é dispensa de licitação por valor limite") e gabi_answer("quais são os requisitos para aposentadoria compulsória no serviço público").

Para cada resposta avalie:
1. Citações corretas? Use es_document() nos doc_ids citados para verificar
2. Resposta coerente com os documentos retornados?
3. Risk flags ativados? (use gabi_answer_trace para ver o trace)
4. Latência aceitável?

Reporte problemas encontrados com severidade: CRÍTICO / MÉDIO / BAIXO
```

**Prompt para Cursor (via @gabi-dou MCP):**
```
@gabi-dou Use gabi_answer para testar 3 queries jurídicas típicas do DOU/TCU.
Verifique as citações com es_document() e reporte qualidade das respostas.
```

---

## Item 2 — Reindexar repo diariamente (launchd)

**Objetivo:** manter `.ai/repo_index.db` atualizado sem intervenção manual.

**Prompt para Claude Code:**
```
Crie um launchd plist em ~/Library/LaunchAgents/com.gabi.reindex-repo.plist
que execute diariamente às 06:30 o comando:
  /Users/fgamajr/dev/gabi-kimi/.venv/bin/python3 -m src.backend.repo_index build

- WorkingDirectory: /Users/fgamajr/dev/gabi-kimi
- stdout/stderr: /tmp/gabi-reindex-repo.log
- Usar repo_query("launchd plist ingest") para ver padrão já adotado no projeto
- Ativar com: launchctl load ~/Library/LaunchAgents/com.gabi.reindex-repo.plist
- Testar com: launchctl start com.gabi.reindex-repo
```

---

## Item 3 — Embeddings no repo_index

**Objetivo:** buscas conceituais além de BM25 (ex: "onde é feito o chunking dos documentos" sem mencionar a palavra "chunk").

**Prompt para Claude Code:**
```
Use repo_query("embedding provider OpenAI repo_index config") para entender
a estrutura atual de embeddings em src/backend/repo_index/.

Depois:
1. Verifique se há OPENAI_API_KEY ou EMBED_API_KEY no .env
2. Execute o build com embeddings:
   .venv/bin/python3 -m src.backend.repo_index build --with-embeddings
3. Teste a diferença: compare repo_query("onde fica a lógica de chunking", mode="lexical")
   vs repo_query("onde fica a lógica de chunking", mode="hybrid")
4. Se qualidade melhorar, atualizar o launchd do Item 2 para incluir --with-embeddings
```

---

## Bonus — E2E tests (usar a skill /e2e)

**Prompt para Claude Code:**
```
/e2e

Crie testes E2E Playwright para o GABI cobrindo:
1. Busca simples → resultados aparecem
2. Click em resultado → página /documento/ carrega
3. Query que aciona gabi_answer → bloco de resposta com citações aparece

Antes de criar os testes, use repo_query("playwright test frontend") para
verificar se já existe alguma configuração ou teste existente.
Base URL: http://localhost:8081
API: http://localhost:8001
```

**Para Cursor:** use `@e2e` (regra em `.cursor/rules/e2e.mdc` já criada).
