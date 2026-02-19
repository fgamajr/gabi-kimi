# Deploy no Fly.io: Decisão e Guia

## 1. Decisão: Apps separados (recomendado)

Recomendamos **dois apps Fly.io**:

| App           | Tipo        | Descrição                    | Dockerfile / contexto      |
|---------------|-------------|------------------------------|-----------------------------|
| `gabi-api`    | HTTP        | REST API (Minimal API)       | `src/Gabi.Api/Dockerfile`   |
| `gabi-worker` | Process     | Background worker (sync)     | `Dockerfile` (raiz)         |

### Por que apps separados (e não um app com process groups)?

| Critério            | Apps separados                    | Um app + process groups              |
|---------------------|-----------------------------------|--------------------------------------|
| Escala              | API e Worker escalam independente | Mesmo VM; escala junto               |
| Custo               | Paga por app (pode scale-to-zero em um) | Um único bill                    |
| Deploy              | Deploy só do que mudou            | Sempre o mesmo artefato              |
| Config/secrets      | Por app (API não vê secrets do worker) | Tudo no mesmo app                |
| Health / restart    | Fly reinicia só o app que falhou  | Process group pode reiniciar sozinho |
| Fly Machines        | Uma machine por app (ou mais)     | Várias processes na mesma machine   |

**Conclusão:** Para API (HTTP) e Worker (long-running sem HTTP), **apps separados** são mais claros, seguros e alinhados ao modelo do Fly (Machines por app). Process groups fazem sentido quando vários processos precisam compartilhar a mesma machine (ex.: sidecar); não é o caso aqui.

### Quando considerar um único app com process groups?

- Staging mínimo com tudo na mesma região e um único `fly.toml`.
- Protótipo rápido com API + Worker no mesmo deploy.

Para produção e migração “sem retrabalho”, manter **dois (ou três) apps** desde já.

---

## 2. Estrutura de arquivos recomendada

```
.
├── Dockerfile                    # Worker (Fly.io) — já existe
├── fly.worker.toml               # Config do app gabi-worker (ou fly.toml atual)
├── fly.api.toml                  # Config do app gabi-api (novo)
├── src/
│   ├── Gabi.Api/
│   │   └── Dockerfile            # API — já existe
│   └── Gabi.Worker/
│       └── ...
└── docs/infrastructure/
    ├── DEPLOY_LAYOUT.md
    └── FLY_DEPLOY.md             # Este arquivo
```

O `fly.toml` na raiz pode continuar como config do **worker** (padrão de `fly deploy` na raiz). Para a API, usar `fly.api.toml` e deploy com `fly deploy --config fly.api.toml` (ou um app em subpasta).

---

## 3. Configuração por app

### 3.1 gabi-worker (processo, sem HTTP)

Arquivo: `fly.toml` (raiz) ou `fly.worker.toml`.

- **Build:** `Dockerfile` na raiz (multi-stage, publica `Gabi.Worker`).
- **Process:** `dotnet Gabi.Worker.dll` (não expõe portas).
- **Secrets:** `ConnectionStrings__Default`, `GABI_ELASTICSEARCH_URL`, `GABI_REDIS_URL` (se usar).
- **Sources:** Não embutir `sources_v2.yaml` na imagem em prod; usar volume montado ou URL (configurar via env/secrets). Para transição, manter COPY na imagem e sobrescrever com volume se necessário.

### 3.2 gabi-api (HTTP)

Arquivo: `fly.api.toml` (criado neste repo).

- **Build:** `context: .` + `dockerfile: src/Gabi.Api/Dockerfile`.
- **Porta:** 8080 (ASP.NET).
- **Secrets:** `ConnectionStrings__Default` (quando API usar DB), `GABI_SOURCES_PATH` ou equivalente.
- **Health:** `GET /health` (já existe).

---

## 4. Passos para deploy (checklist)

### Primeira vez (Worker)

```bash
fly auth login
fly apps create gabi-worker   # ou usar nome existente
fly postgres create --name gabi-db   # ou anexar DB existente
fly secrets set ConnectionStrings__Default="Host=...;Port=5432;Database=gabi;..."
fly deploy
```

### Primeira vez (API)

```bash
fly apps create gabi-api
fly deploy --config fly.api.toml
fly secrets set ConnectionStrings__Default="..."   # quando API usar DB
```

### Deploys seguintes

```bash
# Só worker
fly deploy

# Só API
fly deploy --config fly.api.toml
```

---

## 5. Secrets e variáveis (resumo)

Configurar no Fly (por app):

```bash
# Worker
fly secrets set -a gabi-worker \
  ConnectionStrings__Default="Host=xxx.flycast;Port=5432;Database=gabi;User=...;Password=..." \
  GABI_ELASTICSEARCH_URL="https://..." \
  GABI_REDIS_URL="redis://..."

# API (quando precisar de DB/sources)
fly secrets set -a gabi-api \
  ConnectionStrings__Default="..." \
  GABI_SOURCES_PATH="/app/sources_v2.yaml"
```

Para não assar `sources_v2.yaml` na imagem da API, usar volume:

```toml
# fly.api.toml
[mounts]
  source = "gabi_sources"
  destination = "/app/sources"
```

E definir secret `GABI_SOURCES_PATH=/app/sources/sources_v2.yaml` após criar o volume e colocar o ficheiro (via release ou pipeline).

---

## 6. Migração “seamless”: o que falta

Para a migração para Fly.io ser o mais suave possível:

1. **Já feito:** Dockerfiles, fly.toml do worker, scripts dev-up/down, healthchecks de infra.
2. **Ajustes feitos neste repo:** ver [DOCKER.md](../../DOCKER.md#mudanças-mínimas) — remoção de `container_name`, documentação de recursos, runtime enxuto no Worker, `fly.api.toml` para a API.
3. **A fazer quando subir API em Fly:** `fly.api.toml`, secrets da API, volume ou URL para `sources_v2.yaml` se não quiser na imagem.
4. **Opcional:** Fly Redis/Upstash, Elasticsearch gerenciado — só quando o pipeline e a busca exigirem.

Com isso, o switch para Fly.io fica alinhado ao layout de deploy (dev/staging/prod) e à decisão de **apps separados**.
