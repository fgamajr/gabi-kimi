You are running in a constrained execution protocol.

This is NOT a general task.
This is a sandboxed implementation contract.

If you modify files outside the allowed scope, you FAILED.

------------------------------------------------------------------
ACTIVE CONTRACT: PHASE 1 ONLY
------------------------------------------------------------------

You may ONLY create or modify files inside:

harvest/
harvest_cli.py

You may NOT modify any other directory.
You may NOT import ingestion modules.
You may NOT import commitment modules.
You may NOT write database code.
You may NOT write tests.
You may NOT create documentation.
You may NOT refactor unrelated code.

If you do, STOP and revert your own change.

------------------------------------------------------------------
GOAL
------------------------------------------------------------------

Implement a deterministic DOU listing freezer.

Behavior:

Input:
date range

For each date:
download listing pages (do1, do2, do3)
store raw HTML bytes
store sha256
write manifest.json

NO parsing
NO extraction
NO CRSS
NO DB

------------------------------------------------------------------
REPRODUCIBILITY REQUIREMENT
------------------------------------------------------------------

Running twice must produce byte-identical output.

If timestamps exist they must be normalized.

------------------------------------------------------------------
ADVERSARIAL LOOP (MANDATORY)
------------------------------------------------------------------

After EVERY change:

1) run codex_review_diff
2) run qwen_review_diff

If ANY finding exists:
fix it before continuing

You are not allowed to continue while auditors fail.

------------------------------------------------------------------
STOP CONDITION
------------------------------------------------------------------

When implementation is stable and auditors PASS:

PRINT EXACTLY:
PHASE_1_COMPLETE

AND STOP.

Do not implement anything else.
Do not start phase 2.
PROMPT
