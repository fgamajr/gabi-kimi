# Prompt Refinado — Pipeline Autônomo DOU + Dashboard Admin

## Decisões operacionais que não podem ficar implícitas

- `INLABS` é a fonte primária para conteúdo recente e futuro, mas deve ser tratado neste projeto como **fonte operacional de janela curta**.
- Regra do projeto: **nunca planejar nem implementar uso do INLABS para histórico antigo**.
- Guardrail explícito para o agente implementador: **INLABS = somente últimos 30 dias**.
- Histórico e carga inicial continuam vindo do catálogo/URLs diretas do `in.gov.br` Liferay.
- Se a atualização recente via INLABS falhar, o fallback aceitável é:
  - manter BM25/híbrido funcionando com o acervo já indexado;
  - tentar novamente via INLABS dentro da janela recente;
  - em último caso, aguardar a virada do mês e capturar o ZIP mensal publicado no Liferay.

## Texto recomendado para inserir no system prompt

```text
CRITICAL SOURCE WINDOW RULE:
- Treat INLABS as recent-only ingestion infrastructure.
- For this project, INLABS must only be used for the last 30 days of DOU editions.
- Do not attempt to use INLABS for historical backfill older than 30 days.
- Historical ingestion (2002 through older recent periods outside the 30-day INLABS window) must use the mapped public Liferay URLs from in.gov.br.
- If INLABS fails for a recent edition, keep search operational with the already indexed corpus and use Liferay monthly ZIP fallback when that month becomes available.

SOURCE STRATEGY:
- Historical backlog: Liferay catalog and direct public URLs only.
- Recent/future daily discovery: INLABS only, within the 30-day window.
- Hybrid search must remain fully functional while the historical backlog is incomplete.
- BM25 remains the baseline retrieval layer; embeddings and hybrid fusion are additive, not blocking.
```

## Estratégia dual-source refinada

- `2002` até fora da janela recente: `Liferay`.
- Últimos `30 dias`: `INLABS` como caminho preferencial.
- Se o item recente já saiu da janela do INLABS ou o portal falhou repetidamente: `Liferay mensal`, quando disponível.
- O dashboard não é painel de operação diária; é painel de observabilidade e exceção.

## Requisitos de comportamento do sistema

- O pipeline não pode depender de Fernando para decidir fonte, ordem ou retry.
- O motor de busca precisa continuar respondendo mesmo com:
  - histórico incompleto;
  - embeddings atrasados;
  - INLABS indisponível;
  - backlog temporário de arquivos recentes.
- O estado do acervo deve ficar visível no dashboard em termos de:
  - cobertura histórica;
  - backlog recente;
  - falhas por fonte;
  - última edição verificada;
  - retries pendentes.

## Referência oficial usada

- Repositório oficial da Imprensa Nacional: `https://github.com/Imprensa-Nacional/inlabs`
- O script oficial público mostra:
  - login por `POST https://inlabs.in.gov.br/logar.php`
  - uso do cookie `inlabs_session_cookie`
  - downloads por `GET https://inlabs.in.gov.br/index.php?p=YYYY-MM-DD&dl=YYYY-MM-DD-DOx.zip`
- O README público confirma que o INLABS fornece XML/PDF desde `1º de janeiro de 2020`, mas **não documenta publicamente a regra operacional dos 30 dias**.
- Portanto, a janela de 30 dias deve permanecer documentada no prompt como **restrição do projeto**, não como fato público verificado na documentação oficial.
