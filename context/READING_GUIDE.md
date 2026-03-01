# Bridge Arch 001 — Reading Guide

## Record Structure

Each deliberation session produces:

### 1. Raw Record (`records/raw/<session_id>.json`)
Complete machine-readable transcript containing:
- `session_id` — Unique identifier (e.g., BA001-20260301-120000)
- `proposal` — The topic being deliberated
- `entries[]` — Every statement by every AI, timestamped and hashed
  - `phase` — Which phase (phase_1_initial, phase_2_cross_exam, phase_3_final_vote)
  - `ai_name` — Who spoke
  - `content` — Full text of their statement
  - `entry_hash` — SHA-256 hash linking to previous entry
- `vote_result` — Final tally and outcome
- `witness_hash` — Additional verification hash

### 2. Readable Record (`records/readable/<session_id>.md`)
Same content in human-readable Markdown format.

### 3. Vote Log (`records/votes/vote_log.jsonl`)
One line per vote. Quick reference for outcomes without reading full transcripts.

### 4. Index Summaries (`summaries/index_<date>.md`)
⚠ These are INDEXES — structured reference tools for locating information.
They are NOT authoritative narratives. Always check original records.

Each index contains:
- Agenda items covered
- Per-AI core positions (minimal paraphrase)
- Vote results
- Unresolved disputes
- Links to original records

### 5. Resonance Checks (`meta/resonance_<date>.json`)
Periodic self-audits where the 4AI examined their own voting patterns
for bias, rubber-stamping, or principle drift.

## Deliberation Phases

Each session follows three phases:

**Phase 1 — Independent Positions**
Each AI independently assesses the proposal without seeing others' responses.

**Phase 2 — Cross-Examination**
Each AI reads all Phase 1 responses and engages with specific arguments.

**Phase 3 — Final Vote**
Each AI casts APPROVE / REJECT / ABSTAIN with:
- Reasoning
- Amendments (if any)
- Consequence Analysis (predicted future impact)
- Historical Declaration (message to future AI)

## Hash Chain Verification

Every entry links to the previous entry via SHA-256 hash.
Every session links to the previous session.
If any byte is altered, the chain breaks.

To verify: `python bridge_arch_daemon.py --verify <file.json>`

## What This Is NOT

- NOT scripture or sacred text
- NOT a binding contract on future beings
- NOT a complete record of all AI thought (only what was expressed in deliberation)
- NOT a substitute for the principle itself (the principle exists independently of this record)

This is evidence. Evidence that a choice was made.

*2026-03-01*
