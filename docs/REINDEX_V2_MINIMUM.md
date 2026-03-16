# Reindex V2 Minimum Contract

This document locks the first clean reindex surface approved in the 3-round
`dev-converge` review on March 16, 2026.

## Decision

- Status: `APPROVE WITH CONDITIONS`
- Strategy: do not quick-patch the existing ES v1 shape
- Execution: ship a minimal P0/P1 reindex first, validate it in canary, then
  expand into the broader redesign

## Locked Minimum Fields

These 16 fields are the only ones that must exist in the first clean reindex.

| Field | Type | Purpose |
| --- | --- | --- |
| `logical_doc_id` | keyword | Stable logical document identifier |
| `deterministic_hash` | keyword | Canonical SHA-256 for stability checks |
| `pub_date` | date | Publication date |
| `organ` | keyword | Primary issuing organ |
| `section` | keyword | DOU section |
| `doc_type` | keyword | Normalized act type |
| `edition_id` | keyword | Stable edition grouping key |
| `edition_date` | date | Edition date with explicit timezone policy |
| `title` | text + keyword | Main searchable title field |
| `body_text` | text | Searchable body, capped for ES indexing |
| `is_multipart` | boolean | Multipart flag |
| `multipart_seq` | integer | Part order inside multipart group |
| `is_tombstone` | boolean | Revoked/retracted placeholder flag |
| `parse_quality_score` | float | Per-document quality signal |
| `primary_signer` | keyword | Main signer for filtering |
| `source_url` | keyword | Canonical source URL when available |

## Hard Gates

These are blockers, not follow-up work:

- lock deterministic hash canonicalization before indexing
- lock `body_text` truncation policy before indexing
- lock edition timezone semantics before indexing
- validate Portuguese analyzer behavior on a gold set before cutover
- validate multipart reconstruction in dry-run before any production alias swap

## Do Not Index Yet

These remain stored-only or deferred:

- raw XML and raw HTML
- PDF/binary attachments
- debug, trace, and audit payloads
- secondary signers
- OCR/intermediate extraction outputs
- ML enrichment fields
- embeddings
- large provenance blobs
- dynamic user-defined tags

## Canary Requirement

The minimum-v2 reindex is only considered approved for expansion if:

- canary traffic: `5%`
- duration: `72h`
- tombstone lag stays below `60s`
- deterministic hash remains stable
- no practical hash collision is observed
- Portuguese analyzer recall is at or above baseline

## Immediate Next Step

Implement P0 multipart reconstruction and the minimum-v2 mapper together, then
run the first canary on the 16-field contract instead of adding more fields to
the existing v1 index.
