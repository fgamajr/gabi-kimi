# Avaliação de Infraestrutura

Documento que consolida o veredito e as recomendações de infra (orquestração, Fly.io, melhorias).

---

## 1. Orquestração e estratégia de containers

**Conclusão:** A ideia de orquestrar a infraestrutura (Postgres, ES, Redis) via Docker e manter os apps (Gabi.Api, Gabi.Worker) como unidades separadas está **correta e é a recomendada**.

- **Vários containers (API + Worker separados)** é o caminho certo.
- No Fly.io isso permite:
  - **API:** escalar horizontalmente com base em tráfego HTTP.
  - **Worker:** escalar de forma independente com base na carga de processamento.
- **Isolamento de falhas:** Se o Worker consumir muita memória e for morto (ex.: OOM killer), a API continua no ar para o usuário ver o status do sistema.

---

## 2. Switch para o Fly.io

O switch será **muito suave (80–90% seamless)** porque:

- Dockerfiles multi-stage estão limpos.
- `fly.toml` e `fly.api.toml` estão configurados.
- Scripts de dev (dev-up/dev-down) e documentação (DEPLOY_LAYOUT, FLY_DEPLOY) estão alinhados.

**Ponto de fricção:** Persistência do `sources_v2.yaml`. Se o arquivo for “assado” na imagem (`COPY`), será necessário novo deploy para cada mudança na lista de fontes.

**Recomendação:** Usar **Fly Volumes** ou baixar o YAML de uma **URL privada** via variável de ambiente (ex.: `GABI_SOURCES_PATH` ou `GABI_SOURCES_URL`), em vez de depender apenas do COPY na imagem.

---

## 3. Melhorias implementadas

### 3.1 Externalização de configurações

- **Fly.io:** Usar `fly secrets set` para `ConnectionStrings__Default` e demais segredos. Não deixar segredos em `appsettings.json` (apenas valores não sensíveis ou defaults de dev).
- **Referência:** [FLY_DEPLOY.md](FLY_DEPLOY.md) e [env.example](../../env.example).

### 3.2 Health checks detalhados (Gabi.Api)

- Adicionado `AddHealthChecks()` com:
  - Check **"self"** (tag `live`) para liveness.
  - **Npgsql** (tag `ready`) quando `ConnectionStrings__Default` estiver configurado.
- `/health` → liveness (só check self); Fly usa para decidir se reinicia o processo.
- `/health/ready` → readiness (todos os checks, incluindo Postgres); Fly pode usar para rotear tráfego quando o app estiver pronto (ex.: após migrações).
- Assim o Fly.io sabe se o app está pronto para receber tráfego com base na saúde do banco.

### 3.3 Logging estruturado (Gabi.Api)

- **Serilog** configurado com:
  - **Produção:** saída em JSON (Compact) no console; o Fly.io captura e facilita depuração via `fly logs`.
  - **Desenvolvimento:** leitura de nível/formato via `appsettings` (pode manter console legível).
- Configuração em `appsettings.json` (seção `Serilog`) e bootstrap em `Program.cs`.

### 3.4 Reserva de memória (Worker)

- No `fly.toml` do Worker, 1 GB está adequado ao uso do MemoryManager e ao cenário serverless.
- **Recomendação:** Monitorar o uso real (ex.: métricas Fly ou logs) e ajustar tamanho da VM para equilibrar estabilidade e custo.

---

## 4. Veredito

A infraestrutura atual está em estado **Ready for Production** do ponto de vista arquitetural. Os ajustes finos (tamanho de VM, volumes para `sources_v2.yaml`, opcionais como Redis/ES gerenciados) podem ser feitos conforme a carga e o uso aumentarem.

| Aspecto              | Status        | Observação                                      |
|----------------------|---------------|-------------------------------------------------|
| Orquestração         | Ok            | Infra em Docker; API e Worker separados         |
| Fly.io               | Ok            | Dois apps; deploy e secrets documentados       |
| Health checks        | Implementado  | Liveness + readiness com Npgsql opcional        |
| Logging estruturado  | Implementado  | Serilog JSON em produção na API                 |
| Secrets              | Documentado   | Uso de `fly secrets set`; nada sensível em appsettings |
| sources_v2.yaml      | Recomendado   | Volume ou URL em prod para evitar redeploy      |
