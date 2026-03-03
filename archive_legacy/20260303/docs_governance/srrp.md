# Structural Residual Risk Protocol (SRRP)

## 1. Purpose

Prevent infinite adversarial loops when:
- All auditors converge on the same invariant
- The invariant cannot be eliminated within the current module boundary
- Further patches only reduce surface area, not root cause

## 2. Finding Classes

```
FIXABLE      Can be resolved within current module without architectural change.
STRUCTURAL   Requires redesign of lower abstraction layer.
THEORETICAL  Requires OS/kernel/hardware guarantees outside project scope.
NOISE        Style/opinion/low-signal finding without reproduction.
```

## 3. Escalation Trigger

A finding becomes STRUCTURAL when:

```
IF   >= 3 auditors flag the same invariant
AND  >= 2 rounds attempted mitigation
AND  root cause lies outside current abstraction layer
THEN classify as STRUCTURAL
```

This prevents infinite patching attempts.

## 4. Structural Convergence Rule

When a finding is classified as STRUCTURAL:

1. Stop patch attempts at current layer.
2. Document invariant explicitly in `governance/structural_risks.md`.
3. Open a redesign ticket in lower layer.
4. Mark current layer as: HARDENED (best-effort) WITH STRUCTURAL LIMITATION.

## 5. Documentation Template

Each structural risk entry in `governance/structural_risks.md` must contain:

```
ID:                   unique identifier (e.g., FREEZER-SEC-01)
Invariant:            what property cannot be guaranteed
Auditor Convergence:  which auditors flagged it, across how many rounds
Mitigation Attempts:  numbered list of patches tried
Why Structural:       which lower layer must change and why
Threat Context:       where exploitable vs where acceptable
Decision:             accepted / escalated / deferred
Next Action:          specific redesign task for lower layer
```

## 6. Auditor Prompt Extension

Add to each auditor system prompt:

```
You MUST classify each finding as one of:
- FIXABLE
- STRUCTURAL
- THEORETICAL
- NOISE

If STRUCTURAL, explain which layer must change.
```

This forces auditors to reason about architecture, not just code deltas.

## 7. Why This Matters

Without SRRP:
- Adversarial loops become infinite
- Executor becomes trapped in impossible proofs
- Compute waste increases linearly per round
- Development velocity collapses

With SRRP:
- Formal stop conditions exist for every finding class
- Bugs are distinguished from invariants
- Escalation preserves rigor without blocking progress
- Adversarial search terminates in bounded rounds

## 8. Proof of Need

First observed: 2026-03-02, harvest_cli.py TOCTOU convergence.

4 auditors flagged the same TOCTOU symlink race across 4 consecutive rounds.
Each round added path-validation layers. None eliminated the root cause.
Root cause: `freeze_range` uses path-string I/O, not fd-relative I/O.
CLI cannot fix the writer. Only the writer can fix the writer.

Without SRRP, the executor would loop indefinitely.
With SRRP, Round 4 declared structural convergence and escalated correctly.
