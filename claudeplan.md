Ready to code?
                                                                           
 Here is Claude's plan:                                                  
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌
 Plan: Edition Freezing Layer — Observational Archive

 Context

 The pipeline has 4 working layers (extraction, semantic enrichment,
 identity, completeness). All prove internal pipeline integrity. None can
 answer:

 "Prove that the system didn't reconstruct the past retroactively."

 Three threats to archival reliability:

 1. Late additions: DOU editions receive acts throughout the day. Freezing
  at 09:30 while the government adds 2 acts at 11:00 creates a
 cryptographically valid but historically incomplete archive.
 2. Stabilization ≠ closure: Even if the listing hash stops changing for
 hours, that doesn't prove the edition is final. A stable listing is only
 observationally stable, not legally final.
 3. Chronological order ≠ observation order: If the sampler captures dates
  out of order (e.g., 2018, then 2024, then 2019), using publication date
 order for closure would allow retroactive reconstruction — an adversary
 could argue the system "knew the future when it declared the past final."
  Closure must depend on capture order, not publication order.

 Formal Model: Two Independent Timelines

 Each edition has two timestamps:
 - publication_date — the government's time (when the edition was
 published)
 - captured_at — the observer's time (when our system first saw it) —
 audit metadata only

 The archive is a reconstruction of the official publication record.
 Closure depends on publication chronology. Capture metadata is stored for
  provenance audit but does not determine document finality.

 Three Concepts

 - Stabilization: prove the listing stopped changing (technical indício,
 not legal proof)
 - Closure: prove the edition is final because a later-published edition
 exists in the dataset (publication chronology)
 - Freezing: cryptographic sealing of closed editions (evidentiary
 artifact)

 Closure Rule

 Edition D is historically closed iff there exists edition E such that:

 publication_date(E) > publication_date(D)

 Capture metadata (captured_at, capture_sequence) is stored alongside for
 audit trail — proving when each edition was acquired — but does NOT
 participate in the closure decision.

 Implementation: Stage 1 — Sampler Evidence Upgrade

 Stage 1 modifies only corpus_sampler.py. No new modules, no CLI changes.
 The existing pipeline (extract → enrich → identity → completeness) must
 produce identical results — the new metadata fields are additive and
 unused by downstream consumers.

 ┌────────┬──────────────────────────────┬────────────────┐
 │ Action │             File             │ ~Lines changed │
 ├────────┼──────────────────────────────┼────────────────┤
 │ MODIFY │ validation/corpus_sampler.py │ ~60            │
 └────────┴──────────────────────────────┴────────────────┘

 NOT touched in Stage 1: edition_freezer.py (not created),
 historical_validate.py, semantic_resolver, identity_analyzer,
 completeness_validator, extractor, rules, html_tools.

 Future stages (freezer module, CLI integration) follow after Stage 1 is
 validated.

 ---
 Part 1: Sampler Enhancement (corpus_sampler.py)

 1a. Save listing HTML to disk

 _discover_articles_by_date() fetches listing HTML then discards it.
 Change:

 - Return type adds listing captures: tuple[list[dict], list[dict], dict |
  None]
 - After extracting article URLs, preserve listing metadata (html string,
 sha256, section, article_count)
 - In build(), save each listing to
 {year}/{mm}/{dd}/_listing_{section}.listing
 - Extension .listing (not .html) so rglob("*.html") in extractor (line
 113) and platform_classifier (line 25) skip them

 1b. SHA-256 article hashes at download time

 In build() article download loop (line 130-136), after self._get(u)
 returns HTML:
 - Compute hashlib.sha256(html.encode("utf-8")).hexdigest()
 - Add "sha256": hash to the item dict appended to idx

 1c. Capture timestamps and sequence numbers

 Every item and listing gets two forensic fields at capture time:
 - "captured_at": ISO 8601 UTC timestamp
 (datetime.now(timezone.utc).isoformat())
 - "capture_sequence": monotonic integer counter, incremented per captured
  entity (listing or article)

 The sequence number creates an immutable ordering that cannot be
 retroactively altered. It proves the system observed entities in this
 exact order.

 The sampler maintains self._capture_seq: int = 0 initialized at __init__,
  incremented on every successful listing save and every successful
 article download.

 1d. Enhanced index.json schema (backward-compatible)

 {
   "items": [
     { "date": "...", "listing_url": "...", "article_url": "...", "file":
 "...",
       "sha256": "a1b2...", "captured_at": "2026-03-01T09:15:00Z",
 "capture_sequence": 47 }
   ],
   "listings": [
     { "date": "...", "section": "do1", "listing_url": "...",
       "file": "2022/06/29/_listing_do1.listing", "sha256": "c3d4...",
 "article_count": 342,
       "captured_at": "2026-03-01T09:10:00Z", "capture_sequence": 3 }
   ]
 }

 Existing consumers that access only item["date"], item["file"], etc. are
 unaffected.

 1e. Checkpoint update

 _save_checkpoint() gains listings key and capture_sequence counter so
 both survive resume.

 ---
 Part 2: Freezer Module (validation/edition_freezer.py)

 2a. Edition Stabilization

 The stabilization phase proves an edition's inventory stopped changing.

 stabilize_editions(samples_dir, cfg) -> StabilizationResult:

 For each (date, section) found in index.json listings:
 1. Read stored listing SHA-256 from index.json (the initial capture)
 2. Re-fetch the listing URL from DOU
 3. Compute SHA-256 of the new listing HTML
 4. Compare with stored hash
 5. Record the observation: {check_timestamp, listing_sha256,
 matches_previous: bool}
 6. Repeat after stabilization_interval seconds
 7. After min_consecutive_matches consecutive identical hashes → section
 stabilized
 8. After max_checks without stabilization → mark edition_status:
 "provisional"

 Configuration (StabilizationConfig dataclass):
 stabilization_interval: float = 3600.0   # 1 hour between checks
 min_consecutive_matches: int = 2         # 2 consecutive identical hashes
  = stable
 max_checks: int = 6                      # give up after 6 checks (~6
 hours)
 delay_sec: float = 1.5                   # politeness delay between HTTP
 requests
 skip_historical: bool = True             # skip stabilization for dates >
  7 days old
 historical_days_threshold: int = 7       # dates older than this are
 presumed stable

 Historical dates exception: DOU editions from weeks/months/years ago are
 overwhelmingly stable — the site rarely alters old editions. For dates
 older than historical_days_threshold, stabilization is skipped and the
 edition is marked stabilized: true, stabilization_method:
 "historical_presumption". This allows retroactive freezing of the
 existing 200-article corpus without waiting.

 For recent dates (within the threshold), full observation is required.

 2b. Stabilization metadata per section

 @dataclass(slots=True)
 class StabilizationRecord:
     first_seen_at: str          # ISO timestamp of initial capture
     last_seen_at: str           # ISO timestamp of last check
     checks_performed: int
     consecutive_equal_hashes: int
     listing_hash_history: list[dict]  # [{timestamp, sha256,
 matches_previous}]
     stabilized: bool
     stabilization_method: str   # "observation" |
 "historical_presumption"

 2b-2. Edition Lifecycle States

 An edition progresses through 4 states:

 ┌─────────────────────┬──────────────────┬───────────────────────────┐
 │        State        │     Meaning      │         Condition         │
 ├─────────────────────┼──────────────────┼───────────────────────────┤
 │                     │ Captured but     │ Initial state after       │
 │ provisional         │ listing may      │ sampling                  │
 │                     │ still change     │                           │
 ├─────────────────────┼──────────────────┼───────────────────────────┤
 │                     │ Listing hash     │ Stabilization passed      │
 │ temporally_stable   │ converged        │ (observation or           │
 │                     │                  │ historical presumption)   │
 ├─────────────────────┼──────────────────┼───────────────────────────┤
 │                     │ Edition is final │                           │
 │ historically_closed │  — later edition │ Successor verification by │
 │                     │  was observed    │  capture order            │
 │                     │ AFTER it         │                           │
 ├─────────────────────┼──────────────────┼───────────────────────────┤
 │ frozen_final        │ Eligible for     │ historically_closed AND   │
 │                     │ legal proof      │ all validity checks pass  │
 └─────────────────────┴──────────────────┴───────────────────────────┘

 State transitions are monotonic: provisional → temporally_stable →
 historically_closed → frozen_final. An edition never goes backward.

 2b-3. Closure by Publication Chronology

 @dataclass(slots=True)
 class ClosureRecord:
     successor_date_seen: bool
     successor_date: str | None     # publication_date of the next edition
  in the dataset
     closure_method: str            # "successor_observed" | "none"

 Algorithm (no HTTP — pure data from index.json):

 1. Collect all distinct edition dates in the dataset
 2. Sort by publication_date (chronological order)
 3. For each date D: if there exists any date E where publication_date(E)
 > publication_date(D) → D is historically_closed, with successor_date =
 the smallest such E
 4. The latest publication_date in the dataset has no successor → stays
 temporally_stable

 This is deterministic, instant, and based on the official publication
 timeline.

 Capture metadata (captured_at, capture_sequence) is stored on every item
 and listing for audit provenance — proving when the system acquired each
 piece — but does NOT participate in closure logic. The archive
 reconstructs the official record; it is not a witness log of the
 crawler's traversal order.

 2c. Merkle Tree

 merkle_root(hashes: list[str]) -> str — deterministic:
 1. Sort hashes lexicographically
 2. If odd count, duplicate last
 3. Pairwise: sha256(left_hex + right_hex) (concatenate hex strings, UTF-8
  encode, hash)
 4. Repeat until 1 root
 5. Empty list → sha256(b"")

 2d. Freeze Logic

 freeze_edition(samples_dir, stabilization_cfg) -> FreezeManifest:

 1. Load index.json → extract edition dates, listings, items with capture
 metadata
 2. Run stabilization for all editions → each gets stabilized: bool
 3. For each edition/section:
   - Verify article hashes (re-compute from disk, compare with stored)
   - Verify listing hash
   - Build Merkle tree from article hashes
   - Run per-section validity checks
 4. Apply closure by publication chronology:
   - Sort edition dates chronologically
   - For each date D: find smallest date E > D in the dataset → D is
 historically_closed
   - Last date has no successor → stays temporally_stable
 5. Determine edition_status:
   - Not stabilized → "provisional"
   - Stabilized but not closed → "temporally_stable"
   - Stabilized + closed → "historically_closed"
   - historically_closed + all sections valid → "frozen_final"
 6. Write edition.manifest.json (editions ordered by capture_sequence for
 audit trail)

 Closure is pure data — no HTTP. Uses only publication_date ordering.

 2e. Freeze rules

 ┌────────────────────────┬───────────────────────────────────────────┐
 │          Rule          │                 Condition                 │
 ├────────────────────────┼───────────────────────────────────────────┤
 │ Edition is             │ All sections have stabilized == true      │
 │ temporally_stable      │                                           │
 ├────────────────────────┼───────────────────────────────────────────┤
 │ Edition is             │ temporally_stable AND a later             │
 │ historically_closed    │ publication_date exists in the dataset    │
 ├────────────────────────┼───────────────────────────────────────────┤
 │                        │ pagination_stable AND                     │
 │ Section is VALID       │ no_download_failures AND page_count >=    │
 │                        │ min AND merkle_root_computed              │
 ├────────────────────────┼───────────────────────────────────────────┤
 │ Edition is             │ historically_closed AND ALL sections      │
 │ frozen_final           │ valid                                     │
 ├────────────────────────┼───────────────────────────────────────────┤
 │ Latest publication     │ Always stays temporally_stable (no        │
 │ date                   │ successor in dataset)                     │
 └────────────────────────┴───────────────────────────────────────────┘

 Closure is per-edition (date level). All sections of a date share the
 same closure status. Closure uses publication chronology only.

 2f. Dataclasses

 FileHash:            file, sha256
 StabilizationRecord: (see 2b above)
 ClosureRecord:       successor_date_seen, successor_date, closure_method
  (see 2b-3)
 SectionFreeze:       section, listing_url, listing_file, listing_sha256,
                      article_count, sampled_count, article_hashes:
 list[FileHash],
                      merkle_root, valid,
                      stability: StabilizationRecord,
                      validation: dict[str, bool]
 EditionFreeze:       date, first_seen_at, capture_sequence,
                      sections: list[SectionFreeze], edition_valid,
                      edition_status: str,  # "provisional" |
 "temporally_stable" |
                                            # "historically_closed" |
 "frozen_final"
                      closure: ClosureRecord
 FreezeManifest:      manifest_version, created_at, sampler_config,
                      editions: list[EditionFreeze], summary: dict

 - first_seen_at and capture_sequence are audit metadata (when/in what
 order the system acquired this edition) — stored for provenance, NOT used
  in closure logic
 - closure uses only publication_date ordering
 - Manifest is ordered by capture_sequence for audit trail readability

 2g. edition.manifest.json structure

 Editions are ordered by capture_sequence (observation order), not by date
  (publication order).

 {
   "manifest_version": "1.0",
   "created_at": "2026-03-01T14:30:00Z",
   "canonical_order": "publication_date",
   "editions": [
     {
       "date": "2022-06-29",
       "first_seen_at": "2026-03-01T09:10:00Z",
       "capture_sequence": 3,
       "edition_status": "frozen_final",
       "edition_valid": true,
       "closure": {
         "successor_date_seen": true,
         "successor_date": "2022-07-15",
         "closure_method": "successor_observed"
       },
       "sections": [
         {
           "section": "do1",
           "listing_url": "https://...",
           "listing_file": "2022/06/29/_listing_do1.listing",
           "listing_sha256": "a1b2...",
           "article_count": 342,
           "sampled_count": 15,
           "merkle_root": "d4e5...",
           "valid": true,
           "stability": {
             "first_seen_at": "2026-03-01T09:10:00Z",
             "last_seen_at": "2026-03-01T09:10:00Z",
             "checks_performed": 0,
             "consecutive_equal_hashes": 0,
             "listing_hash_history": [],
             "stabilized": true,
             "stabilization_method": "historical_presumption"
           },
           "validation": {
             "stabilized": true,
             "pagination_stable": true,
             "no_download_failures": true,
             "page_count_above_minimum": true,
             "merkle_root_computed": true
           },
           "article_hashes": [...]
         }
       ]
     },
     {
       "date": "2024-11-02",
       "first_seen_at": "2026-03-01T09:25:00Z",
       "capture_sequence": 150,
       "edition_status": "temporally_stable",
       "edition_valid": false,
       "closure": {
         "successor_date_seen": false,
         "successor_date": null,
         "closure_method": "none"
       },
       "sections": [...]
     }
   ],
   "summary": {
     "total_editions": 50,
     "frozen_final": 49,
     "temporally_stable": 1,
     "provisional": 0,
     "total_listings_preserved": 150,
     "total_articles_hashed": 200,
     "frozen_at": "2026-03-01T14:30:00Z"
   }
 }

 The manifest has two ordering perspectives:

 ┌───────────┬──────────────────┬──────────────────────────────────────┐
 │   Order   │      Field       │               Purpose                │
 ├───────────┼──────────────────┼──────────────────────────────────────┤
 │ Physical  │ capture_sequence │ Audit trail — proves acquisition     │
 │           │                  │ chain of custody                     │
 ├───────────┼──────────────────┼──────────────────────────────────────┤
 │ Canonical │ publication_date │ Legal truth — the official           │
 │           │                  │ publication timeline                 │
 └───────────┴──────────────────┴──────────────────────────────────────┘

 canonical_order: "publication_date" makes this explicit for external
 auditors.

 The latest publication_date stays temporally_stable (no successor). All
 earlier dates that pass validation are frozen_final.

 2h. Retroactive freeze support

 Works on old samples/ directories:
 - No "listings" key → sections have listing_file: null
 - No "sha256" on items → computed from file on disk
 - All dates are historical → stabilization_method:
 "historical_presumption", stabilized: true
 - Full Merkle trees built from computed hashes

 2i. Helper functions

 - compute_sha256(path: Path) -> str — chunked file hash (8KB)
 - _extract_section(listing_url: str) -> str — parse secao= from URL query
 - _serialize(obj) -> dict — recursive dataclass → dict for JSON output

 ---
 Part 3: CLI Integration (historical_validate.py)

 New freeze subcommand

 python3 historical_validate.py freeze \
   --samples samples \
   [--min-page-count 1] \
   [--stabilization-interval 3600] \
   [--min-consecutive-matches 2] \
   [--max-checks 6] \
   [--historical-days 7] \
   [--skip-stabilization]          # for testing: skip observation, mark
 all as historical

 Output: editions=N frozen_final=N temporally_stable=N provisional=N
 listings=N articles_hashed=N

 Updated full command

 Insert freeze (with --skip-stabilization by default in full mode, since
 full mode is for testing/validation runs, not production archival):
 sample → freeze(skip_stabilization) → extract

 ---
 Architectural Invariant: Raw HTML is the Primary Record

 The freeze layer guarantees: raw HTML is preserved byte-for-byte as the
 evidentiary source, regardless of what happens downstream. If extraction
 fails to parse, if semantic rules miss a field, if identity hashing
 produces a fallback — none of that affects the archive's integrity.

 Freeze validity depends on capture completeness + edition stability. It
 does NOT depend on extraction success. An edition with 200 downloaded
 articles where 5 fail to parse is still a valid frozen edition.

 The evidence layer is independent of the interpretation layer.

 ---
 Output Structure

 samples/
 ├── index.json                          # enhanced: sha256 on items +
 listings array
 ├── edition.manifest.json               # NEW: cryptographic manifest
 with stability proof
 ├── unstable_days.json
 ├── 2022/06/29/
 │   ├── _listing_do1.listing            # NEW: preserved listing HTML
 │   ├── _listing_do2.listing
 │   ├── abc123def456.html               # article page (unchanged)
 │   └── def789abc012.html
 └── 2023/03/15/
     ├── _listing_do1.listing
     └── 7890abcdef12.html

 ---
 Edge Cases

 - Listing fetch fails: recorded in errors, no .listing file, section has
 listing_file: null
 - Article download fails: excluded from Merkle tree, section valid: false
 - File modified after download: re-computed hash ≠ stored, counted as
 failure
 - Extraction fails on a page: irrelevant to freeze — raw HTML and hash
 already sealed
 - Stabilization never converges: after max_checks, edition stays
 provisional — Merkle tree still built but edition_valid: false
 - Late addition detected: stabilization check finds different listing
 hash → resets consecutive counter, continues observation
 - Historical dates: presumed stable, no HTTP observation needed
 - Latest publication date in dataset: stays temporally_stable. Will
 become historically_closed when a later-published edition is added to the
  dataset.
 - Only one date in dataset: stays temporally_stable. No editions can
 reach frozen_final. Correct — cannot prove succession without a later
 edition.
 - Non-consecutive dates: successor is the next publication_date in the
 dataset, not the calendar next day. Gaps from random sampling are
 expected. 2022-06-29 → next sampled 2023-01-15 → 2023-01-15 is the
 successor.
 - Checkpoint resume: listing metadata + capture_sequence counter
 persisted in checkpoint

 ---
 Verification

 # 1. Sample with new code (small test — need >= 2 dates for successor
 verification)
 python3 historical_validate.py sample --out /tmp/test_freeze --dates 5
 --max-articles 10 --seed 42

 # 2. Verify listing files + hashes
 find /tmp/test_freeze -name "*.listing" | head
 python3 -c "
 import json; idx = json.load(open('/tmp/test_freeze/index.json'))
 print(f'items_with_sha256={sum(1 for i in idx[\"items\"] if \"sha256\" in
  i)}/{len(idx[\"items\"])}')
 print(f'listings={len(idx.get(\"listings\", []))}')
 "

 # 3. Freeze with skip-stabilization (all dates treated as historical)
 python3 historical_validate.py freeze --samples /tmp/test_freeze
 --skip-stabilization

 # 4. Inspect manifest — verify lifecycle states and closure by
 publication chronology
 python3 -c "
 import json; m =
 json.load(open('/tmp/test_freeze/edition.manifest.json'))
 s = m['summary']
 print(f'editions={s[\"total_editions\"]}')
 print(f'frozen_final={s[\"frozen_final\"]}
 temporally_stable={s[\"temporally_stable\"]}
 provisional={s[\"provisional\"]}')
 print(f'articles_hashed={s[\"total_articles_hashed\"]}')
 print()
 # Check lifecycle states
 for ed in m['editions']:
     c = ed['closure']
     succ = f'successor={c[\"successor_date\"]}' if
 c['successor_date_seen'] else 'no successor'
     print(f'  seq={ed[\"capture_sequence\"]} date={ed[\"date\"]}
 captured={ed[\"first_seen_at\"][:19]} status={ed[\"edition_status\"]}
 {succ}')
     for sec in ed['sections']:
         print(f'    {sec[\"section\"]}:
 merkle={sec[\"merkle_root\"][:16]}... valid={sec[\"valid\"]}')

 # Verify: only the latest publication_date is temporally_stable
 dates = [ed['date'] for ed in m['editions']]
 max_date = max(dates)
 for ed in m['editions']:
     if ed['date'] == max_date:
         assert ed['edition_status'] == 'temporally_stable',
 f'{ed[\"date\"]} should be temporally_stable'
     else:
         assert ed['edition_status'] == 'frozen_final', f'{ed[\"date\"]}
 should be frozen_final'
 print()
 print('Closure by publication chronology verified OK')
 "

 # 5. Verify extraction still works unchanged
 python3 historical_validate.py extract --rules sources_v3.yaml --html
 /tmp/test_freeze --out /tmp/test_extract

 # 6. Retroactive freeze on existing 200-article corpus
 python3 historical_validate.py freeze --samples
 /tmp/gabi_samples_200_guarded --skip-stabilization

 # 7. Verify existing pipeline still works end-to-end
 python3 historical_validate.py extract --rules sources_v3.yaml --html
 /tmp/gabi_samples_200_guarded --out /tmp/test_e
 python3 historical_validate.py enrich --parsed /tmp/test_e/parsed --out
 /tmp/test_enrich
 python3 historical_validate.py completeness --parsed
 /tmp/test_enrich/enriched --samples /tmp/gabi_samples_200_guarded --out
 /tmp/test_comp
╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌

 Claude has written up a plan and is ready to execute. Would you like to
 proceed?

 ❯ 1. Yes, clear context (39% used) and bypass permissions
   2. Yes, and bypass permissions
   3. Yes, manually approve edits
   4. Type here to tell Claude what to change

 ctrl-g to edit in VS Code · ~/.claude/plans/breezy-watching-hamming.md
