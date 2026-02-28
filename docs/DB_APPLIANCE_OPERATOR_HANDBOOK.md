# Local Database Appliance Operator Handbook

## 1) Prerequisites

### What this operation does
Confirms required tools and access are available before any infra command.

### When to use it
Before first setup and when onboarding a new machine.

### Commands
```bash
docker --version
docker compose version
docker info
python3 --version
pwd
ls -la
```

### Expected result
- Docker CLI and Compose return version info.
- `docker info` succeeds (daemon running).
- Python 3 is available.
- You are in the project root folder.

### Safety warning
None.

---

## 2) First Installation

### What this operation does
Creates and starts the reusable PostgreSQL appliance for the first time.

### When to use it
On a fresh environment or after full infra destruction.

### Commands
```bash
python3 infra/infra_manager.py up
python3 infra/infra_manager.py status
docker exec gabi-postgres-appliance pg_isready -U gabi -d gabi
docker exec -e PGPASSWORD=gabi gabi-postgres-appliance \
  psql -U gabi -d gabi -c "SELECT current_database(), current_user;"
```

### Expected result
- `up` returns `ok: true`.
- `status` shows container exists and running.
- `pg_isready` reports accepting connections.
- SQL query returns `gabi` / `gabi`.

### Safety warning
None.

---

## 3) Starting the Infrastructure

### What this operation does
Ensures PostgreSQL is running without deleting any data.

### When to use it
At the beginning of a dev/test session.

### Commands
```bash
python3 infra/infra_manager.py up
python3 infra/infra_manager.py status
```

### Expected result
- Container is running on port `5433`.
- Existing data remains intact.

### Safety warning
None.

---

## 4) Stopping the Infrastructure

### What this operation does
Stops PostgreSQL container while preserving data volume.

### When to use it
When ending work or freeing machine resources.

### Commands
```bash
python3 infra/infra_manager.py down
python3 infra/infra_manager.py status
```

### Expected result
- Container is stopped.
- Data is preserved for next startup.

### Safety warning
None.

---

## 5) Resetting Database (FAST CLEAN)

### What this operation does
Wipes schema objects quickly while keeping container and volume.

### When to use it
Default development workflow between runs/tests.

### Commands
```bash
python3 infra/infra_manager.py reset_db
python3 infra/infra_manager.py status
```

### Expected result
- All tables/views/functions in `public` are removed.
- Container remains running.
- Database is immediately ready for migrations.

### Safety warning
Destructive to database contents (schema-level).

---

## 6) Recreate Database (CLEAN STATE)

### What this operation does
Ensures DB is running and applies a full schema reset in one command.

### When to use it
Before fresh migration + seed cycles.

### Commands
```bash
python3 infra/infra_manager.py recreate
python3 infra/infra_manager.py status
```

### Expected result
- Running container.
- Clean schema state.
- Ready for migration execution.

### Safety warning
Destructive to database contents (schema-level).

---

## 7) Soft Delete Data

### What this operation does
Performs logical cleanup of application data without infra/container changes.

### When to use it
When you need selective cleanup and want to keep schema/migrations.

### Commands
```bash
docker exec -e PGPASSWORD=gabi gabi-postgres-appliance \
  psql -U gabi -d gabi -c "BEGIN; /* add your DELETE statements */ COMMIT;"
```

Example:
```bash
docker exec -e PGPASSWORD=gabi gabi-postgres-appliance \
  psql -U gabi -d gabi -c "DELETE FROM your_table WHERE created_at < now() - interval '30 days';"
```

### Expected result
- Selected rows are removed.
- Container and schema remain unchanged.

### Safety warning
Potential data loss if WHERE clauses are wrong.

---

## 8) Hard Delete Data

### What this operation does
Deletes all data by resetting schema while keeping the same running container.

### When to use it
When you need complete data wipe but do not want infra teardown.

### Commands
```bash
python3 infra/infra_manager.py reset_db
```

### Expected result
- All data objects in `public` removed.
- Container remains available on `5433`.

### Safety warning
Irreversible data deletion.

---

## 9) Destroy Infrastructure

### What this operation does
Fully removes PostgreSQL container and persistent volume.

### When to use it
When you need absolute clean slate (no data retained).

### Commands
```bash
python3 infra/infra_manager.py destroy
python3 infra/infra_manager.py status
```

### Expected result
- Container removed.
- Volume removed.
- `status` shows `exists: false`.

### Safety warning
Irreversible: all database data is permanently deleted.

---

## 10) Recovery Guide

### A) Container not starting

#### What this operation does
Checks runtime state and restarts cleanly.

#### Commands
```bash
python3 infra/infra_manager.py status
docker ps -a --filter name=gabi-postgres-appliance
python3 infra/infra_manager.py up
```

#### Expected result
Container transitions to running/healthy.

#### Safety warning
None.

---

### B) Port `5433` already in use

#### What this operation does
Finds conflicting process/container and clears conflict.

#### Commands
```bash
ss -ltnp | grep 5433 || true
docker ps --format "table {{.ID}}\t{{.Names}}\t{{.Ports}}"
```

If conflict is another container:
```bash
docker stop <container_id>
docker rm <container_id>
python3 infra/infra_manager.py up
```

#### Expected result
`5433` bound by `gabi-postgres-appliance`.

#### Safety warning
Stopping wrong container can impact other services.

---

### C) Database connection refused

#### What this operation does
Verifies DB readiness and connectivity.

#### Commands
```bash
python3 infra/infra_manager.py up
docker exec gabi-postgres-appliance pg_isready -U gabi -d gabi
```

If still failing:
```bash
python3 infra/infra_manager.py recreate
```

#### Expected result
`pg_isready` reports accepting connections.

#### Safety warning
`recreate` wipes schema/data.

---

### D) Corrupted or inconsistent data

#### What this operation does
Resets schema to known clean state.

#### Commands
```bash
python3 infra/infra_manager.py reset_db
# then run your migrations and seed process
```

If issue persists:
```bash
python3 infra/infra_manager.py destroy
python3 infra/infra_manager.py up
# then run migrations and seed process
```

#### Expected result
Clean, deterministic DB state.

#### Safety warning
Destructive to all current data.

---

### E) Docker daemon stopped

#### What this operation does
Restarts Docker service and revalidates infra.

#### Commands
```bash
sudo systemctl start docker
docker info
python3 infra/infra_manager.py up
```

#### Expected result
Docker reachable; DB appliance starts normally.

#### Safety warning
Requires host privileges (`sudo`).
