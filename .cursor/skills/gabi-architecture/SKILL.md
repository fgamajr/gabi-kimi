---
name: gabi-architecture
description: Enforces GABI layered architecture and dependency rules. Use when adding or modifying projects, changing dependencies between projects, introducing new interfaces or implementations, or when the user asks about layers, Contracts, or where to put code.
---

# GABI Architecture Skill

Apply this skill when changing **layer boundaries**, **project references**, or **where types live** (Contracts vs implementations).

## Layer Map (Strict)

| Layer | Projects | Rule |
|-------|----------|------|
| 0–1 | `Gabi.Contracts` | **Zero** references to any other GABI project |
| 2–3 | `Gabi.Postgres` | Infrastructure; EF Core, repositories |
| 4 | `Gabi.Discover`, `Gabi.Fetch`, `Gabi.Ingest`, `Gabi.Sync`, `Gabi.Jobs` | Domain logic; **must not** reference Postgres or EF Core |
| 5 | `Gabi.Api`, `Gabi.Worker` | Orchestration; DI registration, hosting |

**Dependency direction:** Higher layers depend on lower. Layer 4 depends only on Contracts; Layer 5 wires Layer 4 + Postgres.

## Unbreakable Rules

1. **Contracts**  
   Interfaces, DTOs, enums. No `using` to other `Gabi.*` projects. Safe to add new contracts here.

2. **Domain (Layer 4)**  
   Implements interfaces from Contracts. Must **not** reference `Gabi.Postgres` or use EF Core / `DbContext`. If you need persistence, define an interface in Contracts and implement it in Postgres.

3. **DI registration**  
   Done only in Layer 5: `Gabi.Api` or `Gabi.Worker` `Program.cs` (or their `ServiceCollectionExtensions`). Domain and infra are registered there; domain does not reference infra.

4. **New project**  
   Add to the correct layer; add reference from solution and from the right projects (e.g. Worker references Discover, Fetch, Ingest, Postgres, Contracts). Run architecture tests after.

## Quick Checks

- Adding a new interface? → Put it in `Gabi.Contracts`.
- Implementing a repository? → Implementation in `Gabi.Postgres`, interface in Contracts.
- New job executor? → Class in `Gabi.Worker`, interface/contract in Contracts if needed; register in Worker `Program.cs`.
- Domain class needing DB? → Define `IRepository` in Contracts, implement in Postgres, inject in Worker/Api.

## Verification

After any change that touches project references or new projects:

```bash
dotnet test tests/Gabi.Architecture.Tests
```

Must pass. If it fails, fix dependencies (usually: remove a reference from a domain project to Postgres, or move a type to Contracts).

## Additional Resources

- Full layer and contract details: repo root [AGENTS.md](../../AGENTS.md) (§ Layered Architecture).
- Deeper architecture narrative: [reference.md](reference.md).
