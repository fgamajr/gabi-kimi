# Invariantes do Sistema GabiSync (Leis Físicas)

> **Status:** BINDING — Estas regras NÃO podem ser violadas por código, agentes ou scripts.

---

## 1. Fonte de Verdade Única

- `config/sources.yaml` é a **única** definição de fontes.
- Nenhum código pode conter URLs, schemas ou lógicas hardcoded.
- Toda configuração deve ser carregada de fontes externas declarativas.

```csharp
// ❌ ERRADO
var url = "https://www.tcu.gov.br/acordaos/...";

// ✅ CORRETO
var source = await _sourceLoader.LoadAsync("tcu_acordaos");
var url = source.Discovery.Url;
```

---

## 2. Idempotência de Execução

Executar o pipeline duas vezes sem mudança externa **NÃO** pode gerar:
- Downloads repetidos
- Reindexações desnecessárias
- Novos embeddings
- Documentos duplicados

```csharp
// O SyncEngine deve garantir idempotência
public async Task<SyncResult> ExecuteDeltaAsync(...)
{
    // 1. Verificar change_detection_cache
    // 2. Se não mudou → skip
    // 3. Se mudou → processar
}
```

---

## 3. Detecção de Mudança Obrigatória

Toda requisição HTTP deve usar, quando disponível:
- `ETag`
- `Last-Modified`
- `Content-Length`
- Hash de conteúdo (SHA-256)

Cache persistido em `change_detection_cache` (PostgreSQL).

```csharp
public record ChangeDetectionCache
{
    public string Url { get; init; } = string.Empty;
    public string? Etag { get; init; }
    public string? LastModified { get; init; }
    public long? ContentLength { get; init; }
    public string? ContentHash { get; init; }
    public DateTime CheckedAt { get; init; }
}
```

---

## 4. Soft Delete

Nenhum documento é fisicamente removido.

Exclusões externas resultam em:
```csharp
// Modelo Document
public bool IsDeleted { get; set; }
public DateTime? DeletedAt { get; set; }
public DocumentStatus Status { get; set; } // Active | Updated | Deleted
```

---

## 5. Fingerprint Canônico

Cada documento possui fingerprint imutável:
- **Algoritmo:** SHA-256
- **Base:** conteúdo normalizado
- **Uso:** deduplicação cross-source

```csharp
public static string ComputeFingerprint(string normalizedContent)
{
    using var sha256 = SHA256.Create();
    var bytes = Encoding.UTF8.GetBytes(normalizedContent);
    var hash = sha256.ComputeHash(bytes);
    return Convert.ToHexString(hash).ToLowerInvariant();
}
```

---

## 6. Separação de Stores

| Store | Função | Regra |
|-------|--------|-------|
| **PostgreSQL** | Verdade canônica | Sempre vence |
| **Elasticsearch** | Índice derivado | Reconstruível |
| **pgvector** | Vetores derivados | Descartáveis |

```csharp
// Regra: Postgres sempre vence
if (pgDocument != null && esDocument == null)
    // Reindexar no ES
else if (pgDocument == null && esDocument != null)
    // Remover do ES (stale)
```

---

## 7. Agentes Não Criam Infra

Docker, bancos, índices e volumes já devem existir ou ser definidos fora do swarm.

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:16
    volumes:
      - postgres_data:/var/lib/postgresql/data  # Já existe
    
volumes:
  postgres_data:  # Definido fora, não criado pelo código
    external: true
```

---

## 8. Contratos Imutáveis

Uma vez definidos em `Gabi.Contracts`, os tipos NÃO podem ser alterados (apenas estendidos).

```csharp
// ❌ NUNCA modifique um record existente
public record ParsedDocument(
    string DocumentId,
    string SourceId,
    // string NewField  // ❌ Quebra compatibilidade!
);

// ✅ Use extensão via composição ou novo tipo
public record ParsedDocumentV2 : ParsedDocument
{
    public string? NewField { get; init; }
}
```

---

## Checklist de Validação

Antes de commitar código, verifique:

- [ ] Nenhuma URL hardcoded
- [ ] Fingerprint sempre SHA-256
- [ ] Soft delete implementado
- [ ] Change detection em HTTP requests
- [ ] Separação PostgreSQL/ES mantida
- [ ] Contratos não modificados
