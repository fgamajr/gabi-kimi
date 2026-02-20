# Skills Policy (GABI)

Objetivo: reduzir prescrição excessiva e manter apenas skills com valor operacional durável.

## 1) Core (uso padrão)

1. `zero-kelvin` (via script/fluxo do projeto): valida reconstrução E2E real.
2. `test-driven-development`: obrigatório para mudança de comportamento/bugfix.
3. `agent-browser`/`playwright-cli`/`chrome-devtools`: apenas quando houver tarefa web explícita.
4. `microsoft-docs`: somente quando precisar confirmar API/comportamento de stack Microsoft.

## 2) Optional (uso sob demanda)

1. `gabi-production-transition`
2. `prompt-engineering-guide`
3. `data-governance-audit`

## 3) Deprecated-by-default (evitar por padrão)

1. `brainstorming` para tarefas operacionais simples.
2. `skill-creator` em fluxo normal de engenharia de produto.

Regra: manter como optional/deprecated não implica remoção física imediata; remoção só após evidência de não uso + ausência de dependências.

## 4) Princípios de uso

1. Skill é meio, não fim; preferir código/testes/evidência no repositório.
2. Não usar skill para impor roteiros rígidos onde o código já define o padrão.
3. Qualquer skill usada deve reduzir risco operacional ou aumentar confiabilidade de entrega.
