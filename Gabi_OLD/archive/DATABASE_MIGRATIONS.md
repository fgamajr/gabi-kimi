# Database Migrations Strategy

## Visão Geral

Este documento descreve a estratégia de migrações de banco de dados do projeto GABI.

## Por que NÃO rodar migrações no startup?

### ❌ Anti-padrões (evitar)

```bash
# NÃO FAÇA ISSO no start-all.sh ou Program.cs
dotnet ef database update  # Automático no startup
```

**Problemas:**
1. **Lentidão**: Cada startup verifica todas as migrações
2. **Concorrência**: Múltiplos containers podem conflitar
3. **Rollback difícil**: Falhas deixam o banco inconsistente
4. **Segurança**: Aplicação com DDL permissions é risco
5. **Indeterminismo**: Startup pode falhar por problema de migração

### ✅ Melhor Prática

**Separação de responsabilidades:**
- **Infraestrutura** (`dev-up.sh`): Sobe containers
- **Migrações** (`migrate.sh`): Aplica alterações de schema
- **Aplicação**: Apenas lê o banco (DML)

## Scripts Disponíveis

### 1. First Time Setup (Executar UMA VEZ)

```bash
./scripts/first-time-setup.sh
```

**Faz:**
- Verifica dependências
- Sobe infraestrutura Docker
- Instala EF CLI
- Cria migration inicial (se necessário)
- Aplica migrações
- Seed de dados (opcional)

**Quando usar:**
- Quando clonar o projeto pela primeira vez
- Quando resetar o ambiente de desenvolvimento

### 2. Apply Migrations (Executar quando necessário)

```bash
./scripts/migrate.sh
```

**Faz:**
- Lista migrações pendentes
- Pergunta confirmação
- Aplica migrações

**Quando usar:**
- Após `git pull` que trouxe novas migrações
- Após criar uma nova migration

### 3. Create Migration (Executar ao alterar entidades)

```bash
./scripts/migrate-create.sh AddDocumentsTable
```

**Quando usar:**
- Quando alterar classes Entity
- Quando adicionar novas propriedades
- Quando criar índices

## Fluxo de Trabalho do Desenvolvedor

### Novo desenvolvedor

```bash
# 1. Clonar repo
git clone <repo>
cd gabi-kimi

# 2. Setup inicial (uma vez)
./scripts/first-time-setup.sh

# 3. Desenvolver
./scripts/dev-start.sh  # Sobe infra
# ... código ...

# 4. Shutdown
./scripts/dev-down.sh
```

### Desenvolvedor existente (após git pull)

```bash
# 1. Verificar se há novas migrações
./scripts/migrate.sh

# 2. Se houver, aplicar
# (o script pergunta confirmação)

# 3. Continuar desenvolvimento
./scripts/dev-start.sh
```

### Criando nova migration

```bash
# 1. Alterar entidades (ex: DocumentEntity.cs)
# ... fazer alterações ...

# 2. Criar migration
./scripts/migrate-create.sh AddDocumentMetadata

# 3. Revisar arquivos gerados
# src/Gabi.Postgres/Migrations/2025..._AddDocumentMetadata.cs

# 4. Aplicar e testar
./scripts/migrate.sh

# 5. Commit
# Incluir arquivos de migração no git!
```

## Produção (Fly.io)

### NUNCA rodar migrações automaticamente

```yaml
# fly.toml - NÃO fazer isso
[deploy]
  release_command = "dotnet ef database update"  # ❌ PERIGO
```

### ✅ Estratégia recomendada

1. **Migrações como job separado:**
```bash
# Deploy da aplicação (sem migração)
fly deploy

# Executar migração manualmente
fly ssh console -C "dotnet ef database update"
```

2. **Ou via CI/CD:**
```yaml
# .github/workflows/deploy.yml
- name: Deploy API
  run: fly deploy --app gabi-api --no-release

- name: Run Migrations
  run: fly ssh console -C "dotnet ef database update"

- name: Release
  run: fly deploy --app gabi-api --release-only
```

3. **Ou usando Release Phase do Fly.io:**
```toml
[deploy]
  release_command = "/app/migrate.sh"  # Só se tiver rollback automático
```

## Checklist de Migrações Seguras

### Antes de criar:
- [ ] Backup do banco de produção (se aplicável)
- [ ] Testar em ambiente de staging
- [ ] Migration deve ser reversível (`Down()` implementado)

### Arquivo de migration deve conter:
- [ ] Alterações incrementais (não refazer tudo)
- [ ] Índices para novas colunas (se necessário)
- [ ] Dados default para NOT NULL columns

### Code review:
- [ ] Revisar SQL gerado
- [ ] Verificar tempo de execução estimado
- [ ] Confirmar não há DROP de dados importantes

## Troubleshooting

### "Migration already applied"
```bash
# Se o banco está inconsistente
dotnet ef database update 0 --project src/Gabi.Postgres --startup-project src/Gabi.Api  # Reset
dotnet ef database update    # Reaplica tudo
```

### "Pending changes but no migration"
```bash
# Esqueceu de criar migration após alterar entidade
./scripts/migrate-create.sh FixMissingMigration
./scripts/migrate.sh
```

### Reset completo (DEV apenas!)
```bash
# Destrói e recria banco
./scripts/dev-down.sh
docker volume rm gabi-kimi_postgres_data
./scripts/first-time-setup.sh
```

## Resumo

| Script | Executar | Frequência |
|--------|----------|------------|
| `first-time-setup.sh` | Manual | 1x por dev |
| `migrate.sh` | Manual | Após git pull com novas migrations |
| `migrate-create.sh` | Manual | Ao alterar entidades |
| `dev-up.sh` | Manual | Cada sessão de dev |
| **NENHUM** | Auto no startup | **NUNCA** |
