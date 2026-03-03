# Structural Residual Risk Log

## FREEZER-SEC-01: TOCTOU race between path validation and file write

**Invariant:**
Atomicity gap between output directory validation and file writes.
Path-level checks cannot prevent symlink substitution between check and use.

**Auditor Convergence:**
codex, qwen, kimi, glm (4/4) across 4 consecutive rounds.

**Mitigation Attempts (Rounds 1-4):**
1. Pre-mkdir symlink check on output_dir
2. Post-mkdir resolve validation comparing resolved vs absolute
3. Component-walk symlink check on all path parts before mkdir
4. Post-mkdir `is_symlink()` recheck on output_dir
5. Post-resolve component walk on resolved path
6. Pass `resolved` (not `output_dir`) to `freeze_range`

**Why Structural:**
Elimination requires fd-relative I/O with `O_NOFOLLOW` and `os.openat()`,
which must be implemented inside `harvest/freezer.py` — the file writer.
The CLI layer (`harvest_cli.py`) does not control how files are opened and written.
No amount of path-string validation can provide atomic guarantees against
concurrent filesystem mutation.

**Threat Context:**
- NOT exploitable in: local batch CLI, single-user workstation, CI pipeline
- Exploitable in: setuid binary, multi-tenant server, shared /tmp with untrusted users

**Decision:**
CLI layer marked **HARDENED** (best-effort, 6-layer mitigation).
Risk **ACCEPTED** at current abstraction for Phase 1 batch tooling context.

**Next Action:**
Rewrite `freezer.py` file writes using `os.open(path, O_WRONLY | O_CREAT | O_NOFOLLOW)`
and `os.openat(dir_fd, name, flags)` to eliminate path re-resolution entirely.
Track as: `FREEZER-SEC-01` in freezer module backlog.
