# Como Configurar o GABI-DOU no Seu IDE

GABI-DOU é um servidor MCP (Model Context Protocol) que dá acesso a mais de 16 milhões de documentos do Diário Oficial da União e ao acervo jurisprudencial do TCU — você pode pesquisar, filtrar e buscar informações usando linguagem natural através do seu assistente de IA favorito.

---

## Endpoint Canônico de Produção

| Transport | URL | Indicado para |
|-----------|-----|---------------|
| **SSE** | `https://gabi-mcp.gabidou.top/mcp/sse` | Claude Desktop, Cursor, Trae, VSCode, OpenCode |
| **Streamable HTTP** | `https://gabi-mcp.gabidou.top/mcp-http/` | Codex e clientes MCP mais novos |
| **stdio** | processo direto | Claude Code CLI |

Endpoint legado (`gabidou.top/mcp/sse`) continua funcional durante a transição.

---

## Matriz de Transporte — Status de Validação

| Cliente | Transport | Endpoint | Status |
|---------|-----------|----------|--------|
| **Claude Code CLI** | stdio | — (processo direto) | ✅ Validado |
| **Claude Desktop** | SSE (via mcp-remote) | `/mcp/sse` | ✅ Validado |
| **Cursor** | SSE | `/mcp/sse` | ✅ Validado |
| **Trae** | SSE | `/mcp/sse` | ✅ Validado |
| **VSCode** (Extensão MCP) | SSE | `/mcp/sse` | ✅ Validado |
| **OpenCode** | SSE | `/mcp/sse` | 🔲 A validar |
| **Codex** | Streamable HTTP | `/mcp-http/` | 🔲 A validar |

---

## Configuração Rápida

Você precisa de um token de acesso — solicite ao administrador.

---

## VSCode

**1. Instale a extensão "MCP"** no VSCode (busque por "MCP" na marketplace).

**2. Edite o arquivo de configuração:**
```
~/Library/Application Support/Code/User/mcp.json
```

```json
{
  "servers": {
    "gabi-dou": {
      "url": "https://gabi-mcp.gabidou.top/mcp/sse",
      "headers": {
        "Authorization": "Bearer SEU_TOKEN_AQUI"
      }
    }
  }
}
```

**3. Reinicie o VSCode.**

---

## Trae

**Edite (ou crie) o arquivo:**
```
~/Library/Application Support/Trae/User/mcp.json
```

```json
{
  "mcpServers": {
    "gabi-dou": {
      "url": "https://gabi-mcp.gabidou.top/mcp/sse",
      "headers": {
        "Authorization": "Bearer SEU_TOKEN_AQUI"
      }
    }
  }
}
```

Reinicie o Trae.

---

## Cursor

**Edite:**
```
~/.cursor/mcp.json
```

```json
{
  "mcpServers": {
    "gabi-dou": {
      "url": "https://gabi-mcp.gabidou.top/mcp/sse",
      "headers": {
        "Authorization": "Bearer SEU_TOKEN_AQUI"
      }
    }
  }
}
```

Reinicie o Cursor.

### Fallback para Cursor (se `es_search` não aparecer)

Alguns builds do Cursor podem não materializar ferramentas com schema grande.  
Se isso acontecer, use `es_search_basic` (mesma busca, schema reduzido).

Exemplo:
```
/mcp gabi-dou es_search_basic "portaria receita federal 2026" --source dou --page_size 3
```

---

## Claude Code (CLI)

```bash
claude mcp add --transport sse gabi-dou https://gabi-mcp.gabidou.top/mcp/sse \
  --header "Authorization: Bearer SEU_TOKEN_AQUI"
```

**Verificar:**
```bash
claude mcp list
```

---

## Claude Desktop (macOS/Windows)

**Edite:**
```
~/Library/Application Support/Claude/claude_desktop_config.json
```

```json
{
  "mcpServers": {
    "gabi-dou": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "https://gabi-mcp.gabidou.top/mcp/sse",
        "--header",
        "Authorization: Bearer SEU_TOKEN_AQUI"
      ]
    }
  }
}
```

Reinicie o Claude Desktop.

---

## Codex (Streamable HTTP)

Codex suporta o protocolo MCP Streamable HTTP. Use o endpoint `/mcp-http/`:

```json
{
  "mcpServers": {
    "gabi-dou": {
      "url": "https://gabi-mcp.gabidou.top/mcp-http/",
      "headers": {
        "Authorization": "Bearer SEU_TOKEN_AQUI"
      }
    }
  }
}
```

Se o Codex não suportar Streamable HTTP, use o endpoint SSE como fallback.

---

## Ferramentas Disponíveis (21)

### Busca e Descoberta

| Ferramenta | O que faz |
|------------|-----------|
| `es_search` | **Ferramenta principal** — busca híbrida BM25+kNN em DOU, TCU acórdãos, normas, BTCU e publicações |
| `es_search_basic` | Fallback de schema reduzido para clientes MCP com limitação de descriptor (ex.: Cursor) |
| `es_suggest` | Autocomplete de termos e órgãos |
| `es_document` | Busca documento completo por ID (sempre use IDs vindos de `es_search`) |
| `es_more_like_this` | Encontra documentos similares a um dado doc_id |
| `es_significant_terms` | Termos mais distintivos de um tema |
| `es_cross_reference` | Encontra documentos que citam uma lei ou norma |
| `es_tcu_semantic_search` | Busca semântica kNN em acórdãos TCU (requer embeddings) |
| `es_tcu_similar` | Documentos TCU similares por vetor (requer embeddings) |

### Análise e Tendências

| Ferramenta | O que faz |
|------------|-----------|
| `es_timeline` | Volume de publicações ao longo do tempo |
| `es_trending` | Tópicos em alta nos últimos dias |
| `es_organ_profile` | Perfil completo de publicações de um órgão |
| `es_compare_periods` | Compara atividade entre dois períodos |
| `es_facets` | Distribuição por seção, tipo, órgão e data |

### Evidência e Auditoria

| Ferramenta | O que faz |
|------------|-----------|
| `es_evidence_bundle` | Recuperação com citação pronta (use após `es_search`) |
| `es_parent_expand` | Expande chunk DOU para contexto do documento pai |
| `es_audit_query` | Recupera trace de auditoria de busca armazenado |

### Utilitários

| Ferramenta | O que faz |
|------------|-----------|
| `es_health` | Saúde do cluster Elasticsearch |
| `es_explain` | Explica por que um documento apareceu no ranking |
| `es_btcu_search` | ⚠️ DEPRECATED — use `es_search(source='btcu')` |
| `es_publicacoes_search` | ⚠️ DEPRECATED — use `es_search(source='publicacoes')` |

### Roteamento correto de ferramentas

```
Precisa buscar documentos?        → es_search  (sempre começar aqui)
Precisa de autocomplete?          → es_suggest  (não es_search)
Tem um doc_id de um resultado?    → es_document  (nunca construir IDs manualmente)
Quer entender o ranking?          → es_explain
```

### Fontes disponíveis em `es_search`

| source= | Corpus |
|---------|--------|
| (omitir) | Federated: DOU + TCU + normas + BTCU + publicações |
| `dou` | Diário Oficial da União |
| `tcu` | TCU acórdãos |
| `tcu_normas` ou `normas` | TCU normas |
| `btcu` | TCU Boletins (BTCU) |
| `publicacoes` | TCU Publicações Institucionais |
| `all` | Todos os corpora acima |

---

## Exemplos de Uso

```
"Busque decretos presidenciais de 2025 sobre meio ambiente"
→ es_search(query="decreto meio ambiente", date_from="2025-01-01", date_to="2025-12-31")

"Encontre portarias do MEC sobre concursos"
→ es_search(query="portaria concurso", issuing_organ="MEC", topic="concurso_selecao")

"Quais acórdãos do TCU falam sobre nepotismo?"
→ es_search(query="nepotismo", source="tcu", page_size=10)

"Relatórios de auditoria de obras"
→ es_search(query="auditoria obras", source="publicacoes")

"Mostre o documento completo ACORDAO-COMPLETO-31652"
→ es_document(doc_id="ACORDAO-COMPLETO-31652", source="tcu")
```

---

## Problemas Comuns

| Problema | Causa | Solução |
|----------|-------|---------|
| Ferramentas não aparecem | Config não carregada | Reinicie o IDE depois de editar o config |
| `401 Unauthorized` | Token inválido ou expirado | Solicite um novo token ao administrador |
| `Session not found` | Streamable HTTP — sessão expirou | Use o endpoint SSE como fallback |
| `421 Misdirected Request` | Host não autorizado | Verifique `GABI_ALLOWED_HOSTS` no servidor |
| Connection timeout | Servidor reiniciando | Aguarde 30s e tente novamente |
| Erro de schema no Claude Desktop | JSON malformado | Verifique vírgulas e aspas no arquivo JSON |

---

## Precisa de Ajuda?

- Repositório: `https://github.com/fgamajr/gabi-kimi`
- MCP setup: `docs/mcp-setup.md`
