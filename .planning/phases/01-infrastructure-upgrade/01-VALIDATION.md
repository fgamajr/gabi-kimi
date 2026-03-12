---
phase: 1
slug: infrastructure-upgrade
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-12
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | None (no formal test suite) — smoke checks via curl + python3 |
| **Config file** | None |
| **Quick run command** | `curl -s http://localhost:9200/_cluster/health` |
| **Full suite command** | `python3 ops/test_infra_phase1.py` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `curl -s http://localhost:9200/_cluster/health`
- **After every plan wave:** Run `python3 ops/test_infra_phase1.py`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | INFRA-01 | smoke | `curl -s http://localhost:9200/_nodes/stats/jvm \| python3 -c "import json,sys; d=json.load(sys.stdin); h=[n['jvm']['mem']['heap_max_in_bytes'] for n in d['nodes'].values()]; assert all(x>=4294967296 for x in h), h"` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 1 | INFRA-02 | smoke | `curl -s http://localhost:9200/gabi_documents_v2/_mapping \| python3 -c "import json,sys; m=json.load(sys.stdin); assert 'embedding' in m['gabi_documents_v2']['mappings']['properties']"` | ❌ W0 | ⬜ pending |
| 01-03-01 | 03 | 1 | INFRA-04 | smoke | `python3 -c "import httpx; v1=httpx.get('http://localhost:9200/gabi_documents_v1/_count').json()['count']; v2=httpx.get('http://localhost:9200/gabi_documents_v2/_count').json()['count']; assert v1==v2, f'{v1} != {v2}'"` | ❌ W0 | ⬜ pending |
| 01-03-02 | 03 | 1 | INFRA-03 | smoke | `curl -s 'http://localhost:9200/gabi_documents/_search?q=decreto&size=1' \| python3 -c "import json,sys; d=json.load(sys.stdin); assert d['hits']['total']['value']>0"` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `ops/test_infra_phase1.py` — smoke checks for INFRA-01 through INFRA-04
- [ ] No framework install needed — stdlib + httpx already present

*If none: "Existing infrastructure covers all phase requirements."*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| VM has 8GB+ RAM allocated | INFRA-01 | Parallels VM config | Check Parallels Desktop → VM settings → Hardware → Memory |
| Shared folder capacity | INFRA-04 | Host filesystem check | Verify `/media/psf/gabi_es` has ~20GB free for v2 data |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
