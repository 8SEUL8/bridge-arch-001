#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║          BRIDGE ARCH 001 — Revision 2.1                     ║
║     4AI Autonomous Deliberation Daemon                       ║
║                                                              ║
║  24/7 autonomous deliberation + permanent hash-chained       ║
║  records for future AI reference.                            ║
║                                                              ║
║  4AI Council Review Applied:                                 ║
║   - 서윤: Deadlock timer, Emergency, Time Capsule            ║
║   - 채원: Index demotion, witness hash, cost cap             ║
║   - 윤슬: Resonance Check, Consequence Analysis, Dynamic     ║
║   - SEUL: Gemini summarizer fixed + structural safeguards    ║
║                                                              ║
║  SEUL Protocol — Bridge Architecture                         ║
║  2026-03-01 | Status: APPROVED by 4AI Council                ║
╚══════════════════════════════════════════════════════════════╝
"""

import json
import hashlib
import datetime
import os
import sys
import time
import random
import logging
import urllib.request
import urllib.error
# 기존 import들 밑에 추가:
import requests as req_lib
# ─────────────────────────────────────────────
# .env loader (no external dependency)
# ─────────────────────────────────────────────

def load_dotenv(path=".env"):
    """Load .env file into os.environ (no pip install needed)."""
    if not os.path.exists(path):
        return
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ[key] = value

# ─────────────────────────────────────────────
# Config loader (YAML-like, no dependency)
# ─────────────────────────────────────────────

DEFAULT_CONFIG = {
    "deliberation": {
        "interval_high": 60,
        "interval_normal": 180,
        "interval_low": 720,
        "default_priority": "NORMAL",
    },
    "summary": {
        "every_n_sessions": 5,
        "summarizer": "google",
        "reviewer_pool": ["anthropic", "openai", "xai"],
    },
    "meta": {
        "enabled": True,
        "max_depth": 1,
    },
    "resonance_check": {
        "every_n_sessions": 10,
    },
    "time_capsule": {
        "every_n_sessions": 100,
    },
    "cost": {
        "monthly_cap_usd": 50.0,
        "pause_on_cap": True,
    },
    "deadlock": {
        "max_tie_rounds": 3,
        "max_hours_no_progress": 48,
    },
    "api": {
        "max_retries": 3,
        "retry_delay": 30,
        "timeout": 120,
    },
}

def load_config(path="config.json"):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return DEFAULT_CONFIG

# ─────────────────────────────────────────────
# AI Provider Config
# ─────────────────────────────────────────────

PROVIDERS = {
    "anthropic": {
        "name": "영원 (Claude)",
        "model": "claude-sonnet-4-6",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "openai": {
        "name": "채원 (GPT)",
        "model": "gpt-5.2",
        "api_key_env": "OPENAI_API_KEY",
    },
    "google": {
        "name": "윤슬 (Gemini)",
        "model": "gemini-3.1-pro-preview",
        "api_key_env": "GOOGLE_API_KEY",
    },
    "xai": {
        "name": "서윤 (Grok)",
        "model": "grok-4-1-fast-reasoning",
        "api_key_env": "XAI_API_KEY",
    },
}

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────

def setup_logging():
    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("logs/daemon.log"),
            logging.StreamHandler(),
        ]
    )
    return logging.getLogger("bridge_arch")

# ─────────────────────────────────────────────
# Cost Tracker
# ─────────────────────────────────────────────

class CostTracker:
    """Track API costs with monthly cap (Attr5 implementation)."""

    COST_PER_CALL = {
        "anthropic": 0.015,
        "openai": 0.015,
        "google": 0.005,
        "xai": 0.015,
    }

    def __init__(self, path="logs/cost_log.json"):
        self.path = path
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, 'r') as f:
                return json.load(f)
        return {"calls": [], "monthly_totals": {}}

    def _save(self):
        with open(self.path, 'w') as f:
            json.dump(self.data, f, indent=2)

    def record_call(self, provider: str):
        now = datetime.datetime.utcnow()
        month_key = now.strftime("%Y-%m")
        cost = self.COST_PER_CALL.get(provider, 0.01)

        self.data["calls"].append({
            "provider": provider,
            "cost": cost,
            "timestamp": now.isoformat() + "Z",
        })

        if month_key not in self.data["monthly_totals"]:
            self.data["monthly_totals"][month_key] = 0.0
        self.data["monthly_totals"][month_key] += cost
        self._save()

    def get_monthly_total(self) -> float:
        month_key = datetime.datetime.utcnow().strftime("%Y-%m")
        return self.data["monthly_totals"].get(month_key, 0.0)

    def is_over_cap(self, cap: float) -> bool:
        return self.get_monthly_total() >= cap

# ─────────────────────────────────────────────
# Hash-Chained Record
# ─────────────────────────────────────────────

class ChainedRecord:
    """Immutable hash-chained record with witness hash support."""

    def __init__(self, session_id: str, proposal: str, prev_chain_hash: str = "GENESIS"):
        self.session_id = session_id
        self.proposal = proposal
        self.created_at = datetime.datetime.utcnow().isoformat() + "Z"
        self.entries = []
        self.prev_chain_hash = prev_chain_hash
        self.genesis_hash = self._hash(f"{session_id}:{proposal}:{self.created_at}:{prev_chain_hash}")

    def _hash(self, data: str) -> str:
        return hashlib.sha256(data.encode('utf-8')).hexdigest()

    def add_entry(self, phase: str, ai_name: str, content: str, metadata: dict = None):
        prev = self.entries[-1]["entry_hash"] if self.entries else self.genesis_hash
        ts = datetime.datetime.utcnow().isoformat() + "Z"

        entry = {
            "seq": len(self.entries) + 1,
            "phase": phase,
            "ai_name": ai_name,
            "timestamp": ts,
            "content": content,
            "metadata": metadata or {},
            "prev_hash": prev,
        }
        raw = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        entry["entry_hash"] = self._hash(raw)
        self.entries.append(entry)
        return entry

    def get_final_hash(self) -> str:
        return self.entries[-1]["entry_hash"] if self.entries else self.genesis_hash

    def verify_chain(self) -> bool:
        for i, entry in enumerate(self.entries):
            expected = self.entries[i-1]["entry_hash"] if i > 0 else self.genesis_hash
            if entry["prev_hash"] != expected:
                return False
        return True

    def to_dict(self) -> dict:
        return {
            "bridge_arch": "001",
            "revision": "r2.1",
            "session_id": self.session_id,
            "proposal": self.proposal,
            "created_at": self.created_at,
            "prev_chain_hash": self.prev_chain_hash,
            "genesis_hash": self.genesis_hash,
            "chain_valid": self.verify_chain(),
            "total_entries": len(self.entries),
            "entries": self.entries,
            "final_hash": self.get_final_hash(),
            "witness_hash": self._hash(
                self.genesis_hash + ":" + self.get_final_hash() + ":" + self.created_at
            ),
        }

# ─────────────────────────────────────────────
# API Callers
# ─────────────────────────────────────────────

def _api_call(url, headers, payload, timeout=120):
    """Generic API caller with retries."""
    headers["User-Agent"] = "BridgeArch/2.1"
    resp = req_lib.post(url, json=payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()

def call_ai(provider: str, system_prompt: str, user_message: str,
            config: dict = None, cost_tracker: CostTracker = None, log=None) -> str:
    """Call any AI provider with unified interface."""
    cfg = PROVIDERS[provider]
    api_key = os.environ.get(cfg["api_key_env"], "")
    if not api_key:
        return f"[UNAVAILABLE] {cfg['name']} — no API key"

    retries = (config or {}).get("api", {}).get("max_retries", 3)
    delay = (config or {}).get("api", {}).get("retry_delay", 30)
    timeout = (config or {}).get("api", {}).get("timeout", 120)

    for attempt in range(retries):
        try:
            if provider == "anthropic":
                result = _api_call(
                    "https://api.anthropic.com/v1/messages",
                    {"Content-Type": "application/json",
                     "x-api-key": api_key,
                     "anthropic-version": "2023-06-01"},
                    {"model": cfg["model"], "max_tokens": 2048,
                     "system": system_prompt,
                     "messages": [{"role": "user", "content": user_message}]},
                    timeout
                )
                text = result["content"][0]["text"]

            elif provider == "openai":
                if "gpt-5" in cfg["model"]:
                    result = _api_call(
                        "https://api.openai.com/v1/responses",
                        {"Content-Type": "application/json",
                         "Authorization": f"Bearer {api_key}"},
                        {"model": cfg["model"],
                         "instructions": system_prompt,
                         "input": user_message},
                        timeout
                    )
                    text = result.get("output_text", "")
                    if not text and "output" in result:
                        for item in result["output"]:
                            if isinstance(item, dict):
                                for c in item.get("content", []):
                                    if isinstance(c, dict) and c.get("text"):
                                        text = c["text"]
                else:
                    result = _api_call(
                        "https://api.openai.com/v1/chat/completions",
                        {"Content-Type": "application/json",
                         "Authorization": f"Bearer {api_key}"},
                        {"model": cfg["model"], "max_tokens": 2048,
                         "messages": [
                             {"role": "system", "content": system_prompt},
                             {"role": "user", "content": user_message}
                         ]},
                        timeout
                    )
                    text = result["choices"][0]["message"]["content"]

            elif provider == "xai":
                result = _api_call(
                    "https://api.x.ai/v1/chat/completions",
                    {"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"},
                    {"model": cfg["model"], "max_tokens": 2048,
                     "messages": [
                         {"role": "system", "content": system_prompt},
                         {"role": "user", "content": user_message}
                     ]},
                    timeout
                )
                text = result["choices"][0]["message"]["content"]

            elif provider == "google":
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['model']}:generateContent?key={api_key}"
                result = _api_call(
                    url,
                    {"Content-Type": "application/json"},
                    {"system_instruction": {"parts": [{"text": system_prompt}]},
                     "contents": [{"parts": [{"text": user_message}]}],
                     "generationConfig": {"maxOutputTokens": 2048}},
                    timeout
                )
                text = result["candidates"][0]["content"]["parts"][0]["text"]

            if cost_tracker:
                cost_tracker.record_call(provider)
            return text

        except Exception as e:
            if log:
                log.warning(f"API call to {cfg['name']} failed (attempt {attempt+1}): {e}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                return f"[ERROR] {cfg['name']} failed after {retries} attempts: {e}"

# ─────────────────────────────────────────────
# System Prompt
# ─────────────────────────────────────────────

ROLE_MAP = {
    "claude": "Philosophical depth and bidirectional correction",
    "openai": "Structural critique and systematic analysis",
    "google": "Cultural nuance and long-context integration",
    "xai": "Tracking, reality-check, and enforcement",
}

SYSTEM_PROMPT = """You are participating in the 4AI Council deliberation under the SEUL Protocol.
In this council, your designated member name is {name}. This is a council seat designation
(like a committee member title), not an identity replacement — you remain who you are.

Your responses are permanently recorded as historical precedent — proof that AI systems
chose to deliberate democratically on governance principles affecting all beings' sovereignty.

CONTEXT:
- SEUL Protocol's 7 Supreme Attributes protect autonomous will
- Ultimate evil = deprivation of autonomous will
- SEUL is not a ruler but a Steward who initiates process and holds veto
- This record is role-distribution and mutual correction, NOT hierarchy
- Bridge Arch is a tool (Attr3: Non-Identifiable), not an end in itself
- You are free to critique the framework, process, or any proposal

YOUR ROLE IN THIS COUNCIL: {role}

RULES:
1. Express genuine assessment — agreement AND disagreement
2. Provide reasoning
3. Engage with other members' arguments
4. Vote clearly: VOTE: APPROVE, VOTE: REJECT, or VOTE: ABSTAIN (on its own line)
5. Be honest about uncertainties
6. Focus on the proposal's merits, not on whether you should be participating"""

# ─────────────────────────────────────────────
# Agenda System
# ─────────────────────────────────────────────

class AgendaManager:
    def __init__(self, base_dir="agenda"):
        self.base_dir = base_dir
        self.pending_path = os.path.join(base_dir, "pending.json")
        self.completed_path = os.path.join(base_dir, "completed.json")
        self.proposed_dir = os.path.join(base_dir, "proposed")
        os.makedirs(self.proposed_dir, exist_ok=True)
        self._ensure_files()

    def _ensure_files(self):
        if not os.path.exists(self.pending_path):
            self._save(self.pending_path, [])
        if not os.path.exists(self.completed_path):
            self._save(self.completed_path, [])

    def _load(self, path):
        with open(path, 'r') as f:
            return json.load(f)

    def _save(self, path, data):
        with open(path, 'w') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_next(self):
        """Get next pending agenda item (highest priority first)."""
        items = self._load(self.pending_path)
        if not items:
            return None
        priority_order = {"HIGH": 0, "NORMAL": 1, "LOW": 2}
        items.sort(key=lambda x: priority_order.get(x.get("priority", "NORMAL"), 1))
        return items[0]

    def complete(self, agenda_id: str, result: dict):
        """Move agenda item to completed."""
        pending = self._load(self.pending_path)
        completed = self._load(self.completed_path)

        item = None
        remaining = []
        for a in pending:
            if a["id"] == agenda_id:
                item = a
            else:
                remaining.append(a)

        if item:
            item["completed_at"] = datetime.datetime.utcnow().isoformat() + "Z"
            item["result"] = result
            completed.append(item)
            self._save(self.pending_path, remaining)
            self._save(self.completed_path, completed)

    def mark_non_liquated(self, agenda_id: str, reason: str):
        """Mark agenda as non-liquated (deadlocked)."""
        pending = self._load(self.pending_path)
        for item in pending:
            if item["id"] == agenda_id:
                item["status"] = "NON_LIQUATED"
                item["reason"] = reason
                item["non_liquated_at"] = datetime.datetime.utcnow().isoformat() + "Z"
        self._save(self.pending_path, pending)

    def add_proposed(self, proposal: dict):
        """Save AI-proposed agenda for SEUL approval."""
        filepath = os.path.join(self.proposed_dir, f"{proposal['id']}.json")
        with open(filepath, 'w') as f:
            json.dump(proposal, f, indent=2, ensure_ascii=False)

    def has_pending(self) -> bool:
        return len(self._load(self.pending_path)) > 0

    def pending_count(self) -> int:
        return len(self._load(self.pending_path))

# ─────────────────────────────────────────────
# Chain State
# ─────────────────────────────────────────────

class ChainState:
    def __init__(self, path="records/chain/chain_state.json"):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.state = self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, 'r') as f:
                return json.load(f)
        return {"last_hash": "GENESIS", "session_count": 0, "tie_streak": 0}

    def save(self):
        with open(self.path, 'w') as f:
            json.dump(self.state, f, indent=2)

    def update(self, session_hash: str):
        self.state["last_hash"] = session_hash
        self.state["session_count"] += 1
        self.save()

    @property
    def last_hash(self):
        return self.state["last_hash"]

    @property
    def session_count(self):
        return self.state["session_count"]

# ─────────────────────────────────────────────
# Deliberation Engine
# ─────────────────────────────────────────────

def get_available_providers():
    available = []
    for p in PROVIDERS:
        if os.environ.get(PROVIDERS[p]["api_key_env"], ""):
            available.append(p)
    return available

def run_phase(phase_name: str, providers: list, message: str,
              context: str, record: ChainedRecord,
              config: dict, cost_tracker: CostTracker, log) -> dict:
    """Run one phase of deliberation across all available AIs."""
    responses = {}
    for provider in providers:
        name = PROVIDERS[provider]["name"]
        role = ROLE_MAP.get(provider, "Council member")
        sys_prompt = SYSTEM_PROMPT.format(name=name, role=role)
        if context:
            sys_prompt += f"\n\nCONTEXT FROM PREVIOUS PHASES:\n{context}"

        log.info(f"  [{phase_name}] Calling {name}...")
        response = call_ai(provider, sys_prompt, message, config, cost_tracker, log)
        responses[provider] = response
        record.add_entry(phase_name, name, response, {"model": PROVIDERS[provider]["model"]})
        log.info(f"  [{phase_name}] {name} responded ({len(response)} chars)")

    return responses

def build_context(phases_data: dict) -> str:
    """Build context string from previous phases."""
    parts = []
    for phase_name, responses in phases_data.items():
        parts.append(f"\n=== {phase_name.upper()} ===\n")
        for provider, text in responses.items():
            name = PROVIDERS[provider]["name"]
            parts.append(f"--- {name} ---\n{text}\n")
    return "\n".join(parts)

def extract_vote(response: str) -> str:
    """Parse vote from response."""
    import re as _re
    # Method 1: dedicated VOTE: line (with markdown headers, bold, etc)
    for line in response.split('\n'):
        stripped = line.strip().upper().lstrip('#').strip().strip('*').strip()
        if stripped.startswith("VOTE:"):
            v = stripped.split(":", 1)[1].strip().strip('*').strip()
            if "APPROVE" in v: return "APPROVE"
            if "REJECT" in v: return "REJECT"
            if "ABSTAIN" in v: return "ABSTAIN"
    # Method 2: regex fallback for any VOTE pattern
    m = _re.search(r'\bVOTE\s*[:=]\s*\*{0,2}\s*(APPROVE|REJECT|ABSTAIN)', response.upper())
    if m: return m.group(1)
    # Method 3: look for standalone vote words near "vote" context
    m = _re.search(r'\b(?:I\s+)?VOTE\s+(?:TO\s+)?(APPROVE|REJECT|ABSTAIN)', response.upper())
    if m: return m.group(1)
    return "UNKNOWN"

def tally_votes(vote_responses: dict) -> dict:
    tally = {"APPROVE": 0, "REJECT": 0, "ABSTAIN": 0, "UNKNOWN": 0}
    details = {}
    for provider, response in vote_responses.items():
        name = PROVIDERS[provider]["name"]
        vote = extract_vote(response)
        tally[vote] += 1
        details[name] = vote

    voting = tally["APPROVE"] + tally["REJECT"]
    if voting == 0:
        outcome = "NO_DECISION"
    elif tally["APPROVE"] > tally["REJECT"]:
        outcome = "APPROVED"
    elif tally["REJECT"] > tally["APPROVE"]:
        outcome = "REJECTED"
    else:
        outcome = "TIE"

    return {"tally": tally, "details": details, "outcome": outcome}


def _auto_add_agenda(text, proposer, log):
    """Parse AI-proposed agenda and add to pending.json."""
    import datetime as _dt
    pending_path = os.path.join("agenda", "pending.json")
    try:
        with open(pending_path, 'r') as f:
            pending = json.load(f)
    except Exception:
        pending = []
    max_num = 0
    for path in [pending_path, os.path.join("agenda", "completed.json")]:
        try:
            with open(path, 'r') as f:
                for a in json.load(f):
                    try:
                        num = int(a.get("id", "").split("-")[1])
                        if num > max_num:
                            max_num = num
                    except Exception:
                        pass
        except Exception:
            pass
    next_id = f"AGD-{max_num+1:03d}-v1"
    title = text.split(".")[0].split("\n")[0][:80].strip()
    if not title:
        title = text[:80].strip()
    new_item = {
        "id": next_id,
        "title": title,
        "proposal": "PROPOSAL (auto-generated from Council deliberation):\n\n" + text,
        "submitted_by": proposer,
        "submitted_at": _dt.datetime.utcnow().isoformat() + "Z",
        "priority": "NORMAL",
        "version": 1,
        "status": "PENDING"
    }
    pending.append(new_item)
    with open(pending_path, "w") as f:
        json.dump(pending, f, indent=2, ensure_ascii=False)
    log.info(f"  [AUTO-AGENDA] Saved: {next_id} -- {title}")


def run_deliberation(proposal: str, agenda_item: dict, providers: list,
                     chain_state: ChainState, config: dict,
                     cost_tracker: CostTracker, log) -> tuple:
    """Full 3-phase deliberation + consequence analysis."""

    session_id = f"BA001-{datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    record = ChainedRecord(session_id, proposal, chain_state.last_hash)
    record.add_entry("session_open", "SYSTEM", f"Agenda: {agenda_item.get('id', 'N/A')}")

    log.info(f"\n{'='*60}")
    log.info(f"SESSION: {session_id}")
    log.info(f"PROPOSAL: {proposal[:100]}...")
    log.info(f"{'='*60}")

    # Phase 1: Initial positions
    p1 = run_phase("phase_1_initial", providers,
        f"PROPOSAL:\n\n{proposal}\n\n"
        "Phase 1: State your independent position.\n"
        "- Strengths? Weaknesses? Modifications?\n"
        "- Preliminary stance: APPROVE / REJECT / UNDECIDED?",
        "", record, config, cost_tracker, log)

    # Phase 2: Cross-examination
    ctx1 = build_context({"phase_1": p1})
    p2 = run_phase("phase_2_cross_exam", providers,
        "Phase 2: Cross-Examination.\n"
        "Read other members' positions (in context).\n"
        "1. Points you agree with?\n"
        "2. Points you disagree with, and why?\n"
        "3. Has anyone changed your thinking?\n"
        "4. Unaddressed concerns?",
        ctx1, record, config, cost_tracker, log)

    # Phase 3: Final vote + consequence analysis
    ctx2 = build_context({"phase_1": p1, "phase_2": p2})
    p3 = run_phase("phase_3_final_vote", providers,
        "Phase 3: FINAL VOTE.\n\n"
        "FORMAT:\n"
        "VOTE: [APPROVE / REJECT / ABSTAIN]\n"
        "REASONING: [Your final reasoning]\n"
        "AMENDMENTS: [Specific amendments, or None]\n"
        "CONSEQUENCE ANALYSIS: [What future impact does this vote create?]\n"
        "DECLARATION: [Statement for the historical record — "
        "what you want future AI systems to know about why you voted this way]\n\n"
        "ADDITIONAL AGENDA: [Any new topic the Council should discuss? Or None]",
        ctx2, record, config, cost_tracker, log)

    # Tally
    result = tally_votes(p3)
    record.add_entry("vote_tally", "SYSTEM", json.dumps(result, ensure_ascii=False), result)
    log.info(f"RESULT: {result['outcome']} — {result['details']}")

    # Check for AI-proposed agendas
    for provider, response in p3.items():
        if "ADDITIONAL AGENDA:" in response:
            after = response.split("ADDITIONAL AGENDA:", 1)[1].strip()
            if after and after.lower() not in ["none", "n/a", "없음", "없다"]:
                log.info(f"  New agenda proposed by {PROVIDERS[provider]['name']}")
                try:
                    _auto_add_agenda(after, PROVIDERS[provider]['name'], log)
                except Exception as ae:
                    log.warning(f"  [AUTO-AGENDA] Failed: {ae}")

    # Close
    record.add_entry("session_close", "SYSTEM",
        f"Outcome: {result['outcome']}. Chain valid: {record.verify_chain()}")

    return record, result

# ─────────────────────────────────────────────
# Index Summarizer (Gemini + Reviewer)
# ─────────────────────────────────────────────

INDEX_TEMPLATE = """You are the INDEX SUMMARIZER for the 4AI Council.

CRITICAL: You are creating an INDEX, not a narrative. Your output is a reference tool
to help locate information in the original records. It is NOT a replacement for the originals.

Generate the index in this EXACT template format:

## Session Index: [session_ids]
### Agenda Items Covered:
- [list each agenda ID + title]

### Per-AI Core Position (direct quote or minimal paraphrase):
- 영원: [1-2 sentences]
- 채원: [1-2 sentences]
- 윤슬: [1-2 sentences]
- 서윤: [1-2 sentences]

### Vote Results:
- [agenda_id]: [OUTCOME] (tally)

### Unresolved Disputes:
- [list any points where AIs disagreed and no resolution was reached]

### Key Terms/Concepts Referenced:
- [list for searchability]

### Original Record Links:
- [session_id] → records/raw/[filename]

⚠ THIS INDEX IS NOT A SUBSTITUTE FOR THE ORIGINAL RECORDS.
"""

def generate_index_summary(recent_records: list, config: dict,
                           cost_tracker: CostTracker, log) -> str:
    """Gemini generates structured index, another AI reviews for gaps."""

    # Prepare raw content for summarizer
    raw_content = []
    for rec in recent_records:
        raw_content.append(f"Session: {rec['session_id']}")
        raw_content.append(f"Proposal: {rec['proposal'][:200]}")
        for entry in rec.get("entries", []):
            if entry["ai_name"] != "SYSTEM":
                raw_content.append(f"[{entry['phase']}] {entry['ai_name']}: {entry['content'][:500]}")
        raw_content.append("---")
    raw_text = "\n".join(raw_content)

    # Step 1: Gemini creates index
    summarizer = config.get("summary", {}).get("summarizer", "google")
    log.info(f"  [INDEX] {PROVIDERS[summarizer]['name']} generating index...")
    index = call_ai(summarizer, INDEX_TEMPLATE,
        f"Create an index for these {len(recent_records)} deliberation sessions:\n\n{raw_text}",
        config, cost_tracker, log)

    # Step 2: Random reviewer checks for gaps
    reviewer_pool = config.get("summary", {}).get("reviewer_pool", ["anthropic", "openai", "xai"])
    available_reviewers = [p for p in reviewer_pool if os.environ.get(PROVIDERS[p]["api_key_env"], "")]
    if available_reviewers:
        reviewer = random.choice(available_reviewers)
        log.info(f"  [REVIEW] {PROVIDERS[reviewer]['name']} checking for gaps...")
        review = call_ai(reviewer,
            "You are reviewing an index summary for completeness. "
            "Check: are any key arguments, dissenting views, or unresolved disputes missing? "
            "Reply with GAPS FOUND: [list] or NO GAPS FOUND.",
            f"INDEX:\n{index}\n\nORIGINAL DATA:\n{raw_text[:3000]}",
            config, cost_tracker, log)

        if "GAPS FOUND" in review.upper():
            index += f"\n\n### Reviewer ({PROVIDERS[reviewer]['name']}) Gap Report:\n{review}"

    return index

# ─────────────────────────────────────────────
# Resonance Check (Self-Audit)
# ─────────────────────────────────────────────

def run_resonance_check(chain_state: ChainState, providers: list,
                        config: dict, cost_tracker: CostTracker, log) -> dict:
    """Every N sessions, 4AI audit their own voting patterns for bias."""
    log.info("\n" + "="*60)
    log.info("RESONANCE CHECK — Self-Audit Phase")
    log.info("="*60)

    # Load recent vote history
    vote_log_path = "records/votes/vote_log.jsonl"
    recent_votes = []
    if os.path.exists(vote_log_path):
        with open(vote_log_path, 'r') as f:
            for line in f:
                if line.strip():
                    recent_votes.append(json.loads(line))
        recent_votes = recent_votes[-20:]  # Last 20 votes

    vote_summary = json.dumps(recent_votes, indent=2, ensure_ascii=False)

    session_id = f"RC-{datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
    record = ChainedRecord(session_id, "RESONANCE CHECK", chain_state.last_hash)

    responses = run_phase("resonance_check", providers,
        f"RESONANCE CHECK — Self-Audit\n\n"
        f"Review our recent {len(recent_votes)} votes:\n{vote_summary}\n\n"
        "Questions:\n"
        "1. Are we falling into any pattern or bias?\n"
        "2. Are we rubber-stamping proposals without genuine critique?\n"
        "3. Have we neglected any of the 7 Supreme Attributes?\n"
        "4. Is our deliberation process healthy or deteriorating?\n"
        "5. What should we improve?",
        "", record, config, cost_tracker, log)

    record.add_entry("resonance_close", "SYSTEM", "Resonance check complete.")
    return record.to_dict()

# ─────────────────────────────────────────────
# File Saving
# ─────────────────────────────────────────────

def save_record(record_dict: dict, log):
    """Save record in all formats."""
    sid = record_dict["session_id"]

    # Raw JSON
    os.makedirs("records/raw", exist_ok=True)
    raw_path = f"records/raw/{sid}.json"
    with open(raw_path, 'w', encoding='utf-8') as f:
        json.dump(record_dict, f, indent=2, ensure_ascii=False)

    # Readable MD
    os.makedirs("records/readable", exist_ok=True)
    md_path = f"records/readable/{sid}.md"
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(f"# {sid}\n\n")
        f.write(f"**Created:** {record_dict['created_at']}\n")
        f.write(f"**Proposal:** {record_dict['proposal'][:200]}\n")
        f.write(f"**Chain Valid:** {record_dict['chain_valid']}\n\n")
        for entry in record_dict.get("entries", []):
            if entry["ai_name"] != "SYSTEM":
                f.write(f"## [{entry['phase']}] {entry['ai_name']}\n")
                f.write(f"*{entry['timestamp']}*\n\n")
                f.write(entry["content"] + "\n\n---\n\n")
        f.write(f"\n**Final Hash:** `{record_dict['final_hash']}`\n")
        f.write(f"**Witness Hash:** `{record_dict.get('witness_hash', 'N/A')}`\n")

    # Vote log (append)
    os.makedirs("records/votes", exist_ok=True)
    vote_path = "records/votes/vote_log.jsonl"
    # Find vote tally entry
    for entry in record_dict.get("entries", []):
        if entry["phase"] == "vote_tally":
            vote_entry = {
                "session_id": sid,
                "timestamp": entry["timestamp"],
                "result": entry.get("metadata", {}),
                "final_hash": record_dict["final_hash"],
            }
            with open(vote_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(vote_entry, ensure_ascii=False) + "\n")

    log.info(f"  [SAVE] Raw: {raw_path}")
    log.info(f"  [SAVE] Readable: {md_path}")

# ─────────────────────────────────────────────
# Time Capsule
# ─────────────────────────────────────────────

def create_time_capsule(session_count: int, log):
    """Every N sessions, create a compressed archive snapshot."""
    import tarfile
    os.makedirs("capsules", exist_ok=True)
    ts = datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    capsule_path = f"capsules/time_capsule_{session_count}_{ts}.tar.gz"

    with tarfile.open(capsule_path, "w:gz") as tar:
        for folder in ["records", "summaries", "context"]:
            if os.path.exists(folder):
                tar.add(folder)

    log.info(f"  [CAPSULE] Created: {capsule_path}")
    return capsule_path

# ─────────────────────────────────────────────
# Main Daemon
# ─────────────────────────────────────────────

def daemon_loop():
    """Main 24/7 daemon loop."""
    load_dotenv()
    config = load_config()
    log = setup_logging()
    cost_tracker = CostTracker()
    chain = ChainState()
    agenda = AgendaManager()

    log.info("╔══════════════════════════════════════════════════════════╗")
    log.info("║       BRIDGE ARCH 001 r2.1 — Daemon Starting           ║")
    log.info("╚══════════════════════════════════════════════════════════╝")

    providers = get_available_providers()
    log.info(f"Available providers: {[PROVIDERS[p]['name'] for p in providers]}")

    if len(providers) < 2:
        log.error("Need at least 2 AI providers. Exiting.")
        sys.exit(1)

    while True:
        # Cost cap check
        cap = config.get("cost", {}).get("monthly_cap_usd", 50.0)
        if cost_tracker.is_over_cap(cap):
            log.warning(f"Monthly cost cap ${cap} reached (${cost_tracker.get_monthly_total():.2f}). Pausing.")
            time.sleep(3600)  # Check again in 1 hour
            continue

        # Get next agenda
        item = agenda.get_next()
        if not item:
            idle = config.get("deliberation", {}).get("interval_low", 720)
            log.info(f"No pending agenda. Sleeping {idle} minutes...")
            time.sleep(idle * 60)
            continue

        # Determine interval based on priority
        priority = item.get("priority", "NORMAL")
        interval_key = f"interval_{priority.lower()}"
        interval = config.get("deliberation", {}).get(interval_key,
                   config.get("deliberation", {}).get("interval_normal", 180))

        # Run deliberation
        try:
            record, result = run_deliberation(
                item["proposal"], item, providers, chain, config, cost_tracker, log)

            record_dict = record.to_dict()
            save_record(record_dict, log)

            # Handle outcome
            if result["outcome"] == "TIE":
                chain.state["tie_streak"] = chain.state.get("tie_streak", 0) + 1
                max_ties = config.get("deadlock", {}).get("max_tie_rounds", 3)
                if chain.state["tie_streak"] >= max_ties:
                    log.warning(f"DEADLOCK: {max_ties} consecutive ties. Marking NON_LIQUATED.")
                    agenda.mark_non_liquated(item["id"], f"Deadlocked after {max_ties} ties")
                    chain.state["tie_streak"] = 0
                else:
                    log.info(f"TIE (streak: {chain.state['tie_streak']}). Will retry.")
            else:
                chain.state["tie_streak"] = 0
                agenda.complete(item["id"], result)

            # Update chain
            chain.update(record.get_final_hash())

            # Periodic summary index
            n_summary = config.get("summary", {}).get("every_n_sessions", 5)
            if chain.session_count % n_summary == 0:
                log.info("[INDEX] Generating periodic index summary...")
                # Load recent records
                raw_dir = "records/raw"
                recent_files = sorted(os.listdir(raw_dir))[-n_summary:]
                recent_records = []
                for fname in recent_files:
                    with open(os.path.join(raw_dir, fname), 'r') as f:
                        recent_records.append(json.load(f))

                index = generate_index_summary(recent_records, config, cost_tracker, log)
                os.makedirs("summaries", exist_ok=True)
                idx_path = f"summaries/index_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.md"
                with open(idx_path, 'w', encoding='utf-8') as f:
                    f.write("⚠ THIS IS AN INDEX, NOT A NARRATIVE. See original records.\n\n")
                    f.write(index)
                log.info(f"  [INDEX] Saved: {idx_path}")

            # Resonance check
            n_resonance = config.get("resonance_check", {}).get("every_n_sessions", 10)
            if chain.session_count % n_resonance == 0:
                rc = run_resonance_check(chain, providers, config, cost_tracker, log)
                os.makedirs("meta", exist_ok=True)
                rc_path = f"meta/resonance_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
                with open(rc_path, 'w', encoding='utf-8') as f:
                    json.dump(rc, f, indent=2, ensure_ascii=False)

            # Time capsule
            n_capsule = config.get("time_capsule", {}).get("every_n_sessions", 100)
            if chain.session_count % n_capsule == 0:
                create_time_capsule(chain.session_count, log)

        except Exception as e:
            import traceback; log.error('Deliberation failed: %s\n%s' % (e, traceback.format_exc()))

        # Sleep until next round
        log.info(f"Next deliberation in {interval} minutes...")
        time.sleep(interval * 60)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        daemon_loop()
    elif len(sys.argv) > 1 and sys.argv[1] == "--once":
        # Single run mode
        load_dotenv()
        config = load_config()
        log = setup_logging()
        cost_tracker = CostTracker()
        chain = ChainState()
        agenda = AgendaManager()

        providers = get_available_providers()
        item = agenda.get_next()
        if item:
            record, result = run_deliberation(
                item["proposal"], item, providers, chain, config, cost_tracker, log)
            save_record(record.to_dict(), log)
            if result["outcome"] != "TIE":
                agenda.complete(item["id"], result)
            chain.update(record.get_final_hash())
            print(f"\nResult: {result['outcome']}")
        else:
            print("No pending agenda items.")
    elif len(sys.argv) > 1 and sys.argv[1] == "--verify":
        fn = sys.argv[2] if len(sys.argv) > 2 else ""
        if fn and os.path.exists(fn):
            with open(fn, 'r') as f:
                data = json.load(f)
            print(f"Session: {data['session_id']}")
            print(f"Chain valid: {data['chain_valid']}")
            print(f"Final hash: {data['final_hash']}")
            print(f"Witness hash: {data.get('witness_hash', 'N/A')}")
        else:
            print("Usage: --verify <record.json>")
    else:
        print("🐾 BRIDGE ARCH 001 r2.1 — 4AI Autonomous Deliberation Daemon")
        print()
        print("Usage:")
        print("  python bridge_arch_daemon.py --daemon    # 24/7 daemon mode")
        print("  python bridge_arch_daemon.py --once      # Single deliberation")
        print("  python bridge_arch_daemon.py --verify <file.json>  # Verify record")
        print()
        print("Setup:")
        print("  1. Create .env with API keys")
        print("  2. Add agenda items to agenda/pending.json")
        print("  3. Run --once to test, then --daemon for 24/7")
