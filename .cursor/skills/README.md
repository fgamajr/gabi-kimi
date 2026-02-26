# GABI Project Skills

Pasta de **skills** do projeto GABI: workflows e regras formalizados em Markdown para uso por agentes (Cursor, Claude, Codex, Gemini). Cada skill é uma pasta com `SKILL.md` (obrigatório) e opcionalmente `reference.md` ou outros anexos.

## Princípios (Skills, Explained)

- **Progressive disclosure:** O agente vê primeiro a descrição curta; só carrega o conteúdo completo do `SKILL.md` quando a skill for relevante.
- **Estrutura:** A organização em pastas transmite contexto; cada skill é um módulo reutilizável.
- **Recursos:** Skills podem referenciar `AGENTS.md`, scripts (`./scripts/dev`, `./tests/zero-kelvin-test.sh`) e documentação do repositório.

## Skills disponíveis

| Skill | Descrição resumida | Quando usar |
|-------|--------------------|-------------|
| **gabi-architecture** | Regras de camadas e dependências | Ao alterar projetos, referências entre projetos ou onde tipos vivem (Contracts vs implementações) |
| **gabi-pipeline** | Regras do pipeline ETL (streaming, memória, backpressure) | Ao implementar ou alterar estágios (Seed, Discovery, Fetch, Ingest, Embed, Index) ou job executors |
| **gabi-test-and-validate** | Testes e validação (xUnit, Zero Kelvin, migrations) | Ao rodar testes, escrever testes ou validar mudanças |

## Uso

- **Cursor:** As skills em `.cursor/skills/` são descobertas pelo agente; a descrição no frontmatter do `SKILL.md` define quando aplicá-las.
- **Claude / Codex / Gemini:** Podem usar a mesma estrutura: ler a descrição de cada `SKILL.md` para decidir qual abrir; depois ler o corpo do `SKILL.md` e, se necessário, o `reference.md`.

Não edite arquivos em `~/.cursor/skills-cursor/` — esse diretório é reservado para skills internas do Cursor.
