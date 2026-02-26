---
name: gabi-test-and-validate
description: Runs and writes GABI tests and validations: xUnit, architecture tests, Zero Kelvin E2E, and database migrations. Use when running tests, debugging test failures, adding or modifying tests, applying migrations, or when the user asks how to test or validate changes.
---

# GABI Test and Validate Skill

Use when **running tests**, **writing or changing tests**, or **validating** the build and pipeline.

## Test Commands (from repo root)

```bash
# All tests
dotnet test GabiSync.sln

# Single test by name
dotnet test --filter "FullyQualifiedName~HealthEndpoint_ReturnsSuccess"

# Single test with detailed output (debugging)
dotnet test --filter "FullyQualifiedName~JobStateMachineTests" --logger "console;verbosity=detailed"

# By class
dotnet test --filter "FullyQualifiedName~JobStateMachineTests"

# By project
dotnet test tests/Gabi.Api.Tests
dotnet test tests/Gabi.Postgres.Tests
dotnet test tests/Gabi.Architecture.Tests
```

**Architecture tests are mandatory** before committing dependency or new-project changes:

```bash
dotnet test tests/Gabi.Architecture.Tests
```

## Test Conventions

- **Framework:** xUnit.
- **Naming:** `MethodName_Scenario_ExpectedResult`.
- **Shared context:** `IClassFixture<T>` where needed (e.g. `WebApplicationFactory`, Postgres fixture).
- **Integration tests:** Use `CustomWebApplicationFactory` in API tests; Postgres tests may use Testcontainers or a fixture.

## Zero Kelvin (E2E)

Validates the full pipeline from scratch (destroys and recreates). Run from repo root:

```bash
./tests/zero-kelvin-test.sh
```

With options (examples):

```bash
./tests/zero-kelvin-test.sh docker-only --source tcu_sumulas --phase discovery
./tests/zero-kelvin-test.sh docker-only --source tcu_acordaos --phase full --max-docs 20000
```

Use when you need to confirm pipeline behavior end-to-end after changes.

## Database Migrations

- **Apply migrations:** `./scripts/dev db apply`
- **Create new migration:** `./scripts/dev db create NomeDaMigration` (or `dotnet ef migrations add NomeDaMigration --project src/Gabi.Postgres`)
- **Rule:** Additive only — never edit existing migrations. Use `CONCURRENTLY` for indexes where applicable.

## Validation Checklist After Code Changes

1. **Build:** `dotnet build GabiSync.sln`
2. **Architecture (if deps/layers touched):** `dotnet test tests/Gabi.Architecture.Tests`
3. **Relevant unit/integration tests:** e.g. `dotnet test tests/Gabi.Api.Tests` or the project you changed
4. **Optional E2E:** `./tests/zero-kelvin-test.sh` for pipeline-impacting changes

## Common Issues

| Issue | Action |
|-------|--------|
| "Project file does not exist" | Run from **repo root** |
| Port 5100 in use | `pkill -f "dotnet.*Gabi.Api"` |
| Architecture test fails | Fix layer references (domain must not reference Postgres) |

## Additional Resources

- [AGENTS.md](../../AGENTS.md) — Build/Lint/Test section, Test Conventions, Database & Migrations, Common Issues.
- [reference.md](reference.md) — Test project layout and chaos/staging validation.
