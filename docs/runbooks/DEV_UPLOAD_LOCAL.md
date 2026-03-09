# Admin Upload em ambiente local (dev)

Como configurar e rodar o fluxo de upload (XML/ZIP → storage → worker → ingest) **tudo em dev**, sem Fly.io.

## Visão geral

- **Backend (FastAPI)** e **worker (ARQ)** rodam na sua máquina.
- **Storage:** MinIO (S3-compatible) no Docker, no lugar do Tigris.
- **Fila:** Redis no Docker (mesmo que já usa para cache de busca).
- **Frontend:** Vite dev server; API pode ser proxy ou URL explícita.

## 0. Dependências Python

Na raiz do repositório, instale as dependências do backend (inclui `boto3`, `arq`, `python-multipart`):

```bash
pip install -r requirements.txt
# ou: .venv/bin/pip install -r requirements.txt
```

## 1. Subir a pilha local (Docker)

Na raiz do repositório:

```bash
cd ops/local
docker compose up -d
```

Isso sobe: Postgres (5433), Elasticsearch (9200), Redis (6380), **MinIO (9000 API, 9001 console)**.

## 2. Criar o bucket no MinIO (uma vez)

1. Abra **http://localhost:9001**
2. Login: `minioadmin` / `minioadmin`
3. Crie um bucket chamado **`gabi-dou-uploads`** (Create Bucket).

## 3. Variáveis de ambiente (`.env`)

Copie o exemplo e ajuste:

```bash
cp .env.example .env
```

No `.env`, **descomente e deixe assim** o bloco do MinIO (upload em dev):

```env
# Admin upload — MinIO local
AWS_ENDPOINT_URL_S3=http://localhost:9000
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin
BUCKET_NAME=gabi-dou-uploads
S3_PATH_STYLE=true
```

Confirme também:

- **Postgres** — mesmo DSN/porta que você já usa (ex.: `PGHOST=localhost`, `PGPORT=5433`, etc.).
- **Redis** — para a fila do worker e do upload: `REDIS_URL=redis://localhost:6380/0`.
- **Admin** — pelo menos um token com role admin, ex.: `GABI_API_TOKENS=admin:seu-token-admin` e `GABI_ADMIN_TOKEN_LABELS=admin` (ou o padrão que o projeto usa para marcar admin).

Opcional: `GABI_SERVE_FRONTEND=true` se quiser que o FastAPI sirva o build do frontend; para dev com Vite, normalmente você roda o Vite separado.

## 4. Schema do worker (jobs)

O backend aplica o schema `admin.worker_jobs` no startup. Subir o web uma vez já cria as tabelas. Se usar migrations separadas, rode-as antes.

## 5. Rodar backend (web)

Na raiz do repo (com `src` no `PYTHONPATH` ou a partir do diretório que contém `src`):

```bash
# Exemplo típico
export $(cat .env | xargs)   # ou use diretório onde está o .env
python -m uvicorn src.backend.apps.web_server:app --host 0.0.0.0 --port 8000
# ou: python ops/bin/web_server.py (conforme seu projeto)
```

Verifique:

- **Storage:** `GET /api/admin/storage-check` com header `Authorization: Bearer <seu-token-admin>`. Deve retornar 200 e `{"ok": true}`.

## 6. Rodar o worker (ARQ)

Em **outro terminal**, na raiz do repo:

```bash
export REDIS_URL=redis://localhost:6380/0
# Se usar .env: export $(cat .env | xargs)
arq src.backend.workers.arq_worker.WorkerSettings
```

O worker consome jobs da fila (Redis). Sem ele, o upload retorna 202 e o job fica em `queued` até o worker processar.

## 6.1 Rodar o worker HTTP do dashboard

Se você for usar o painel `/pipeline`, rode também o worker HTTP em outro terminal:

```bash
export WORKER_URL=http://127.0.0.1:8081
python -m src.backend.worker.main
```

Sem esse processo, todas as rotas `/api/worker/*` do dashboard ficam indisponíveis. Em ambiente local, o backend agora tenta um fallback embutido, mas o caminho preferencial continua sendo rodar o worker HTTP explicitamente.

## 7. Rodar o frontend (Vite)

No projeto React (ex.: `src/frontend/web`):

```bash
cd src/frontend/web
npm run dev
```

Se o frontend chama a API em outro host/porta, defina a base URL da API no `.env` do frontend ou ao rodar o dev (variável `VITE_API_BASE_URL`). Ex.: backend em `http://localhost:8000` → use o valor que o seu `resolveApiUrl` espera (pode ser `http://localhost:8000` ou `http://localhost:8000/api` conforme o projeto).

## 8. Testar o fluxo

1. Acesse o app (ex.: http://localhost:8080) e faça login com um usuário **admin** (ou use o token configurado em `GABI_API_TOKENS` / `GABI_ADMIN_TOKEN_LABELS`).
2. Vá em **Upload DOU** (ou `/admin/upload`).
3. Envie um XML ou ZIP válido (ex.: um XML de ato do DOU).
4. Deve aparecer 202, job_id e indicador de progresso; na lista **Jobs** (`/admin/jobs`) o job deve passar de `queued` → `processing` → `completed` (ou `failed`/`partial` com mensagem).

Se o job ficar em `queued` para sempre, confira: **REDIS_URL** no `.env` do web e do worker, e se o processo do worker está de fato rodando.

## Resumo rápido

| Componente   | Comando / URL |
|-------------|----------------|
| Pilha       | `docker compose up -d` em `ops/local` |
| Bucket      | http://localhost:9001 → criar `gabi-dou-uploads` |
| .env upload | MinIO: `AWS_*`, `BUCKET_NAME`, `S3_PATH_STYLE=true`; `REDIS_URL=redis://localhost:6380/0` |
| Web         | `uvicorn ...` ou `python ops/bin/web_server.py` (porta 8000) |
| Worker      | `arq src.backend.workers.arq_worker.WorkerSettings` |
| Frontend    | `npm run dev` (e opcionalmente `VITE_API_BASE_URL=...`) |

### Teste E2E (opcional)

Script que valida: storage-check 200, upload 202 + job_id, e (opcionalmente) job em status terminal:

```bash
GABI_ADMIN_TOKEN=dev-admin-token ./ops/scripts/e2e_admin_upload.sh
```

Se o worker estiver rodando um sync completo para o ES, o job pode demorar; o script faz poll por até 2 minutos. Garanta que `boto3`, `arq` e `python-multipart` estão instalados (`pip install -r requirements.txt`).
