# Contribuindo

## CI em toda PR

O pipeline de CI roda em **toda pull request direcionada a `main`**. No **push para `main`**, o workflow de Deploy executa o CI e em seguida o deploy (veja [DEPLOY.md](DEPLOY.md)).

- **Backend**: lint (ruff check), format check (ruff format), compile check, testes (`pytest`).
- **Frontend**: lint, type check (`tsc --noEmit`), build.

Antes de abrir ou atualizar uma PR, rode localmente o que fizer sentido para sua alteração (por exemplo `ruff check src/backend/` e `python -m pytest tests/` no backend, ou `npm run lint` e `npm run build` no frontend).

## Branch protection (main)

Depois que o CI estiver verde de forma estável em `main`, vale ativar a proteção de branch no repositório:

- Exigir que o workflow **CI** passe antes de permitir merge em `main`.
- Opcional: exigir revisão de um aprovedor.

Configuração: repositório → Settings → Branches → Add rule para `main` → marcar "Require status checks to pass" e selecionar o job **CI**.
