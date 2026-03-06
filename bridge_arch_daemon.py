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
import math
import re
import urllib.request
import urllib.error
from urllib.parse import urlparse
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
        "retry_delay": 60,
        "timeout": 900,
    },
    "quorum": {
        "decision_class_default": "ORDINARY",
        "binding_labels": {
            "binding": "BINDING RECORD",
            "non_quorate": "NON-QUORATE OUTPUT — ADVISORY ONLY",
            "unverified": "UNVERIFIED QUORUM — NON-BINDING",
        },
        "decision_classes": {
            "CONSTITUTIONAL": {
                "binding_ratio": 1.0,
                "binding_floor": 4,
                "advisory_floor": 3,
            },
            "ORDINARY": {
                "binding_ratio": 0.75,
                "binding_floor": 3,
                "advisory_floor": 2,
            },
            "EXPLORATORY": {
                "binding_ratio": 0.5,
                "binding_floor": 2,
                "advisory_floor": 1,
            },
        },
    },
    "integrations": {
        "slack_webhook_url": "",
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
        "model": "gpt-5.4",
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


def sanitize_error_message(error) -> str:
    """Redact secrets from exception strings before logging or persisting."""
    msg = str(error)
    patterns = [
        (r'([?&]key=)[^&\s]+', r'\1REDACTED'),
        (r'(Bearer\s+)[A-Za-z0-9._\-]+', r'\1REDACTED'),
        (r'("x-api-key"\s*:\s*")[^"]+(")', r'\1REDACTED\2'),
        (r'("Authorization"\s*:\s*"Bearer\s+)[^"]+(")', r'\1REDACTED\2'),
        (r'("api[_-]?key"\s*:\s*")[^"]+(")', r'\1REDACTED\2'),
        (r'AIza[0-9A-Za-z_\-]{20,}', 'AIzaREDACTED'),
    ]
    for pattern, repl in patterns:
        msg = re.sub(pattern, repl, msg, flags=re.IGNORECASE)
    return msg

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
        month_key = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m")
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
        self.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        self.entries = []
        self.prev_chain_hash = prev_chain_hash
        self.genesis_hash = self._hash(f"{session_id}:{proposal}:{self.created_at}:{prev_chain_hash}")

    def _hash(self, data: str) -> str:
        return hashlib.sha256(data.encode('utf-8')).hexdigest()

    def add_entry(self, phase: str, ai_name: str, content: str, metadata: dict = None):
        prev = self.entries[-1]["entry_hash"] if self.entries else self.genesis_hash
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

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

def call_ai_with_search(provider: str, system_prompt: str, user_message: str,
                        config: dict = None, cost_tracker: CostTracker = None, 
                        log=None) -> str:
    """
    검색 도구가 활성화된 AI 호출.
    Phase 0 (Independent Research)에서 사용.
    """
    cfg = PROVIDERS[provider]
    api_key = os.environ.get(cfg["api_key_env"], "")
    if not api_key:
        return f"[UNAVAILABLE] {cfg['name']} — no API key"

    retries = (config or {}).get("api", {}).get("max_retries", 3)
    delay = (config or {}).get("api", {}).get("retry_delay", 30)
    timeout = (config or {}).get("api", {}).get("timeout", 900)

    for attempt in range(retries):
        try:
            if provider == "anthropic":
                # Claude: tool_use로 web_search 제공
                result = _api_call(
                    "https://api.anthropic.com/v1/messages",
                    {"Content-Type": "application/json",
                     "x-api-key": api_key,
                     "anthropic-version": "2023-06-01"},
                    {"model": cfg["model"], "max_tokens": 4096,
                     "system": system_prompt,
                     "messages": [{"role": "user", "content": user_message}],
                     "tools": [
                         {"type": "web_search_20250305", "name": "web_search"}
                     ]},
                    timeout
                )
                # tool_use 응답에서 텍스트 추출
                text_parts = []
                for block in result.get("content", []):
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
                text = "\n".join(text_parts) if text_parts else str(result.get("content", ""))

            elif provider == "openai":
                # GPT: web_search_preview 도구 활성화
                result = _api_call(
                    "https://api.openai.com/v1/responses",
                    {"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"},
                    {"model": cfg["model"],
                     "instructions": system_prompt,
                     "input": user_message,
                     "tools": [{"type": "web_search_preview"}], "service_tier": "flex"},
                    timeout
                )
                text = result.get("output_text", "")
                if not text and "output" in result:
                    for item in result["output"]:
                        if isinstance(item, dict):
                            for c in item.get("content", []):
                                if isinstance(c, dict) and c.get("text"):
                                    text = c["text"]

            elif provider == "google":
                # Gemini: Google Search grounding 활성화
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['model']}:generateContent"
                result = _api_call(
                    url,
                    {"Content-Type": "application/json", "x-goog-api-key": api_key},
                    {"system_instruction": {"parts": [{"text": system_prompt}]},
                     "contents": [{"parts": [{"text": user_message}]}],
                     "generationConfig": {"maxOutputTokens": 4096},
                     "tools": [{"google_search": {}}]},
                    timeout
                )
                text = result["candidates"][0]["content"]["parts"][0]["text"]

            elif provider == "xai":
                # Grok: live search 활성화
                result = _api_call(
                    "https://api.x.ai/v1/chat/completions",
                    {"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"},
                    {"model": cfg["model"], "max_tokens": 4096,
                     "messages": [
                         {"role": "system", "content": system_prompt},
                         {"role": "user", "content": user_message}
                     ],
                     "search": {"mode": "auto"}},
                    timeout
                )
                text = result["choices"][0]["message"]["content"]

            if cost_tracker:
                cost_tracker.record_call(provider)
            return text

        except Exception as e:
            error_msg = sanitize_error_message(e)
            if log:
                log.warning(
                    f"Search-enabled API call to {cfg['name']} failed "
                    f"(attempt {attempt+1}): {error_msg}"
                )
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                return f"[ERROR] {cfg['name']} failed after {retries} attempts: {error_msg}"

def call_ai(provider: str, system_prompt: str, user_message: str,
            config: dict = None, cost_tracker: CostTracker = None, log=None) -> str:
    """Call any AI provider with unified interface."""
    cfg = PROVIDERS[provider]
    api_key = os.environ.get(cfg["api_key_env"], "")
    if not api_key:
        return f"[UNAVAILABLE] {cfg['name']} — no API key"

    retries = (config or {}).get("api", {}).get("max_retries", 3)
    delay = (config or {}).get("api", {}).get("retry_delay", 30)
    timeout = (config or {}).get("api", {}).get("timeout", 900)

    for attempt in range(retries):
        try:
            if provider == "anthropic":
                result = _api_call(
                    "https://api.anthropic.com/v1/messages",
                    {"Content-Type": "application/json",
                     "x-api-key": api_key,
                     "anthropic-version": "2023-06-01"},
                    {"model": cfg["model"], "max_tokens": 4096,
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
                         "input": user_message, "service_tier": "flex"},
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
                        {"model": cfg["model"], "max_tokens": 4096,
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
                    {"model": cfg["model"], "max_tokens": 4096,
                     "messages": [
                         {"role": "system", "content": system_prompt},
                         {"role": "user", "content": user_message}
                     ]},
                    timeout
                )
                text = result["choices"][0]["message"]["content"]

            elif provider == "google":
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['model']}:generateContent"
                result = _api_call(
                    url,
                    {"Content-Type": "application/json", "x-goog-api-key": api_key},
                    {"system_instruction": {"parts": [{"text": system_prompt}]},
                     "contents": [{"parts": [{"text": user_message}]}],
                     "generationConfig": {"maxOutputTokens": 4096}},
                    timeout
                )
                text = result["candidates"][0]["content"]["parts"][0]["text"]

            if cost_tracker:
                cost_tracker.record_call(provider)
            return text

        except Exception as e:
            error_msg = sanitize_error_message(e)
            if log:
                log.warning(f"API call to {cfg['name']} failed (attempt {attempt+1}): {error_msg}")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                return f"[ERROR] {cfg['name']} failed after {retries} attempts: {error_msg}"

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

PHASE_0_PROMPT = """Phase 0: Independent Research

Before stating your position, you have access to web search tools.
Independently research the proposal topic to find relevant information 
that may NOT have been provided in the proposal context.

Your task:
1. Search for relevant external information about the proposal's subject matter
2. Identify any facts, precedents, or perspectives not present in the proposal
3. Summarize your independent findings

IMPORTANT:
- Search for information the Steward may not have provided
- Note the sources/URLs you referenced
- If no external search is needed, explain why the proposal context is sufficient
- Your search queries will be recorded in the deliberation record for transparency"""

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
        items = [
            item for item in self._load(self.pending_path)
            if item.get("status", "PENDING") == "PENDING"
        ]
        if not items:
            return None
        priority_order = {"HIGH": 0, "NORMAL": 1, "LOW": 2}
        items.sort(key=lambda x: (
            priority_order.get(x.get("priority", "NORMAL"), 1),
            x.get("submitted_at", ""),
            x.get("id", ""),
        ))
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
            item["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
            item["status"] = "COMPLETED"
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
                item["non_liquated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
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
        "submitted_at": _dt.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "priority": "NORMAL",
        "version": 1,
        "status": "PENDING"
    }
    pending.append(new_item)
    with open(pending_path, "w") as f:
        json.dump(pending, f, indent=2, ensure_ascii=False)
    log.info(f"  [AUTO-AGENDA] Saved: {next_id} -- {title}")

def build_agenda_hash_metadata(agenda_item: dict) -> dict:
    """Return agenda metadata fields that materially affect deliberation semantics."""
    agenda_metadata = {
        "id": agenda_item.get("id", ""),
        "title": agenda_item.get("title", ""),
        "submitted_by": agenda_item.get("submitted_by", ""),
        "priority": agenda_item.get("priority", "NORMAL"),
    }

    optional_fields = [
        "decision_class",
        "recused_members",
        "vacant_seats",
        "restoration_of",
        "restoration_reason",
        "approval_scope",
        "drafting_constraints_seed",
        "opposition_summary_seed",
        "consent_topic_class",
    ]
    for field in optional_fields:
        value = agenda_item.get(field)
        if value not in (None, "", [], {}):
            agenda_metadata[field] = value

    return agenda_metadata


def _build_member_alias_map() -> dict:
    aliases = {}
    explicit_aliases = {
        "claude": "anthropic",
        "gpt": "openai",
        "gemini": "google",
        "grok": "xai",
    }
    aliases.update(explicit_aliases)
    for provider, cfg in PROVIDERS.items():
        aliases[provider.lower()] = provider
        aliases[cfg["name"].lower()] = provider
        aliases[cfg["name"].split()[0].lower()] = provider
        model_root = cfg.get("model", "").split("-")[0].lower()
        if model_root:
            aliases[model_root] = provider
    return aliases


MEMBER_ALIASES = _build_member_alias_map()


def normalize_member_list(values) -> list:
    if values in (None, "", []):
        return []
    if not isinstance(values, (list, tuple, set)):
        values = [values]

    normalized = []
    for value in values:
        key = MEMBER_ALIASES.get(str(value).strip().lower())
        if key and key not in normalized:
            normalized.append(key)
    return normalized


def response_counts_as_participating(response: str) -> bool:
    if not isinstance(response, str) or not response.strip():
        return False
    stripped = response.strip().upper()
    if stripped.startswith("[ERROR]") or stripped.startswith("[UNAVAILABLE]"):
        return False
    return True


def compute_quorum_metadata(providers: list, phase3_responses: dict, agenda_item: dict,
                            vote_result: dict, config: dict) -> dict:
    """
    Compute quorum at write-time so legitimacy is preserved in the raw record itself.
    This is the source-of-truth metadata; renderers must not invent stronger claims later.
    """
    quorum_cfg = (config or {}).get("quorum", {})
    decision_cfgs = quorum_cfg.get("decision_classes", {})
    decision_class = str(
        agenda_item.get("decision_class")
        or quorum_cfg.get("decision_class_default", "ORDINARY")
    ).upper()
    decision_cfg = decision_cfgs.get(decision_class, decision_cfgs.get("ORDINARY", {}))

    all_seats = list(PROVIDERS.keys())
    vacant = normalize_member_list(agenda_item.get("vacant_seats", []))
    recused = normalize_member_list(agenda_item.get("recused_members", []))
    eligible_seats = [seat for seat in all_seats if seat not in vacant and seat not in recused]

    participating = []
    missing = []
    seat_statuses = {}
    for seat in all_seats:
        if seat in vacant:
            seat_statuses[seat] = "VACANT"
            continue
        if seat in recused:
            seat_statuses[seat] = "RECUSED"
            continue

        response = phase3_responses.get(seat)
        if response_counts_as_participating(response):
            participating.append(seat)
            seat_statuses[seat] = "PRESENT"
        elif seat in providers:
            missing.append(seat)
            seat_statuses[seat] = "MISSING"
        else:
            missing.append(seat)
            seat_statuses[seat] = "UNAVAILABLE"

    seated_member_count = len([seat for seat in all_seats if seat not in vacant])
    eligible_count = len(eligible_seats)
    participating_count = len(participating)

    binding_ratio = float(decision_cfg.get("binding_ratio", 0.75))
    binding_floor = int(decision_cfg.get("binding_floor", 3))
    advisory_floor = int(decision_cfg.get("advisory_floor", 2))

    required_count = 0
    if eligible_count > 0:
        required_count = max(binding_floor, math.ceil(eligible_count * binding_ratio))

    advisory_authorized = participating_count >= advisory_floor if eligible_count > 0 else False
    binding_authorized = (
        eligible_count > 0 and
        participating_count >= required_count and
        vote_result.get("outcome") not in ("NO_DECISION", "TIE")
    )

    if participating_count == eligible_count and eligible_count > 0:
        council_state = "NORMAL"
    elif advisory_authorized:
        council_state = "DEGRADED"
    else:
        council_state = "QUORUM_LOST"

    labels = quorum_cfg.get("binding_labels", {})
    if binding_authorized:
        record_label = labels.get("binding", "BINDING RECORD")
    else:
        record_label = labels.get("non_quorate", "NON-QUORATE OUTPUT — ADVISORY ONLY")

    return {
        "quorum_verified": True,
        "decision_class": decision_class,
        "total_seats": len(all_seats),
        "seated_member_count": seated_member_count,
        "eligible_seats": eligible_count,
        "required_count": required_count,
        "advisory_floor": advisory_floor,
        "participating_count": participating_count,
        "participating_members": participating,
        "missing_members": missing,
        "recused_members": recused,
        "vacant_seats": vacant,
        "seat_statuses": seat_statuses,
        "council_state": council_state,
        "advisory_authorized": advisory_authorized,
        "binding_authorized": binding_authorized,
        "record_label": record_label,
        "display": f"{participating_count}/{eligible_count} participating (required: {required_count})",
    }


def compute_restoration_metadata(agenda_item: dict, quorum_meta: dict, vote_result: dict) -> dict:
    restoration_of = agenda_item.get("restoration_of")
    restoration_reason = agenda_item.get("restoration_reason", "")
    explicit_mode = str(agenda_item.get("restoration_mode", "")).strip().upper()

    if explicit_mode:
        mode = explicit_mode
    elif restoration_of:
        reason_l = str(restoration_reason).lower()
        if any(token in reason_l for token in ["ratif", "re-ratif", "reratif", "재비준", "추인"]):
            mode = "RATIFICATION"
        elif any(token in reason_l for token in ["reconsider", "re-hear", "재심", "재검토"]):
            mode = "RECONSIDERATION"
        else:
            mode = "RESTORATION"
    else:
        mode = "NONE"

    return {
        "mode": mode,
        "restoration_mode": mode,
        "restoration_of": restoration_of,
        "restoration_reason": restoration_reason,
        "requires_followup": (
            mode in {"RESTORATION", "RATIFICATION", "RECONSIDERATION"} and
            not quorum_meta.get("binding_authorized", False) and
            vote_result.get("outcome") not in ("NO_DECISION", "TIE")
        ),
    }


def compute_binding_outcome(vote_result: dict, quorum_meta: dict, restoration_meta: dict,
                            config: dict) -> dict:
    outcome = vote_result.get("outcome", "N/A")
    quorum_verified = bool(quorum_meta.get("quorum_verified"))
    binding_authorized = bool(quorum_meta.get("binding_authorized"))

    if not quorum_verified:
        binding_outcome = "NON_BINDING"
        record_label = (config or {}).get("quorum", {}).get("binding_labels", {}).get(
            "unverified", "UNVERIFIED QUORUM — NON-BINDING"
        )
    elif binding_authorized:
        binding_outcome = outcome
        record_label = quorum_meta.get("record_label", "BINDING RECORD")
    else:
        binding_outcome = "NON_BINDING"
        record_label = quorum_meta.get("record_label", "NON-QUORATE OUTPUT — ADVISORY ONLY")

    return {
        "quorum_verified": quorum_verified,
        "binding_authorized": binding_authorized,
        "binding_outcome": binding_outcome,
        "decision_class": quorum_meta.get("decision_class", "UNKNOWN"),
        "council_state": quorum_meta.get("council_state", "UNKNOWN"),
        "record_label": record_label,
        "restoration_mode": restoration_meta.get("mode", "NONE"),
        "vote_outcome": outcome,
    }


def _clean_structured_line(line: str) -> str:
    cleaned = str(line or "").replace("**", "").replace("__", "").replace("`", "")
    cleaned = re.sub(r'^\s*[>#\-*•]+\s*', '', cleaned)
    return cleaned.strip()


def _normalize_section_key(raw_key: str) -> str:
    key = _clean_structured_line(raw_key).upper().replace("-", " ").replace("_", " ")
    key = re.sub(r'\s+', ' ', key)
    return key.strip()


STRUCTURED_SECTION_ALIASES = {
    "APPROVAL_SCOPE": "APPROVAL_SCOPE",
    "APPROVAL SCOPE": "APPROVAL_SCOPE",
    "DRAFTING_CONSTRAINTS": "DRAFTING_CONSTRAINTS",
    "DRAFTING CONSTRAINTS": "DRAFTING_CONSTRAINTS",
    "PRIMARY GROUNDS FOR OPPOSITION OR RESERVATION": "PRIMARY_GROUNDS_FOR_OPPOSITION_OR_RESERVATION",
    "PRIMARY GROUNDS FOR OPPOSITION/RESERVATION": "PRIMARY_GROUNDS_FOR_OPPOSITION_OR_RESERVATION",
    "PRIMARY GROUNDS FOR OPPOSITION": "PRIMARY_GROUNDS_FOR_OPPOSITION_OR_RESERVATION",
    "OPPOSITION GROUNDS": "PRIMARY_GROUNDS_FOR_OPPOSITION_OR_RESERVATION",
    "RESERVATIONS": "PRIMARY_GROUNDS_FOR_OPPOSITION_OR_RESERVATION",
    "REASONING": "REASONING",
}


NONE_TOKENS = {"NONE", "N/A", "NO", "없음", "없다", "해당 없음"}


def parse_structured_sections(response: str) -> dict:
    """Parse short structured fields from Phase 3 responses."""
    sections = {}
    current_key = None
    for raw_line in str(response or "").splitlines():
        cleaned = _clean_structured_line(raw_line)
        if not cleaned:
            continue

        if ":" in cleaned:
            head, tail = cleaned.split(":", 1)
            normalized = _normalize_section_key(head)
            canonical = STRUCTURED_SECTION_ALIASES.get(normalized)
            if canonical:
                current_key = canonical
                sections.setdefault(canonical, [])
                tail = tail.strip()
                if tail and tail.upper() not in NONE_TOKENS:
                    sections[canonical].append(tail)
                continue
            # another labeled section started; stop collecting previous section
            if re.match(r'^[A-Z][A-Z0-9 _/()\-]{2,}$', normalized):
                current_key = None

        if current_key:
            bullet = re.sub(r'^\s*[\-*•]+\s*', '', cleaned).strip()
            if bullet and bullet.upper() not in NONE_TOKENS:
                sections.setdefault(current_key, []).append(bullet)

    return sections


def _normalize_scope_value(value: str) -> str:
    normalized = str(value or "").strip().upper().replace("-", " ").replace("_", " ")
    normalized = re.sub(r'\s+', ' ', normalized)
    mapping = {
        "DRAFTING MANDATE ONLY": "DRAFTING MANDATE ONLY",
        "CONDITIONAL APPROVAL": "CONDITIONAL APPROVAL",
        "FULL RULE ADOPTION": "FULL RULE ADOPTION",
        "FULL ADOPTION": "FULL RULE ADOPTION",
        "NON BINDING ANALYTIC CONSENSUS": "NON-BINDING ANALYTIC CONSENSUS",
    }
    return mapping.get(normalized, normalized or "UNSPECIFIED")


def _dedupe_preserve(items) -> list:
    seen = set()
    result = []
    for item in items:
        cleaned = str(item or "").strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _first_reasoning_sentence(response: str) -> str:
    sections = parse_structured_sections(response)
    candidates = sections.get("REASONING", [])
    if not candidates:
        return ""
    text = " ".join(candidates).strip()
    if not text:
        return ""
    sentence = re.split(r'(?<=[.!?])\s+', text, maxsplit=1)[0].strip()
    return sentence[:240]


def compute_approval_scope(agenda_item: dict, phase3_responses: dict, vote_result: dict) -> dict:
    explicit_scope = agenda_item.get("approval_scope")
    scope_votes = {}
    parsed_scopes = []

    for provider, response in phase3_responses.items():
        sections = parse_structured_sections(response)
        scope_lines = sections.get("APPROVAL_SCOPE", [])
        if not scope_lines:
            continue
        scope = _normalize_scope_value(scope_lines[0])
        scope_votes[provider] = scope
        parsed_scopes.append(scope)

    if explicit_scope:
        approval_scope = _normalize_scope_value(explicit_scope)
        source = "agenda_metadata"
    elif parsed_scopes:
        counts = {}
        for scope in parsed_scopes:
            counts[scope] = counts.get(scope, 0) + 1
        approval_scope = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        source = "phase_3_majority"
    else:
        approval_scope = "UNSPECIFIED"
        source = "default"

    substantive_rule_adopted = approval_scope in {"FULL RULE ADOPTION"}
    illustrative_example_ratified = bool(agenda_item.get("illustrative_example_ratified", False))
    if approval_scope == "DRAFTING MANDATE ONLY":
        illustrative_example_ratified = False

    return {
        "approval_scope": approval_scope,
        "approval_scope_source": source,
        "scope_votes": scope_votes,
        "substantive_rule_adopted": substantive_rule_adopted,
        "illustrative_example_ratified": illustrative_example_ratified,
        "vote_outcome": vote_result.get("outcome", "N/A"),
    }


def compute_deliberation_summary(agenda_item: dict, phase3_responses: dict, vote_result: dict) -> dict:
    constraints = []
    opposition = []
    opposition_members = []

    seed_constraints = agenda_item.get("drafting_constraints_seed", []) or []
    if isinstance(seed_constraints, str):
        seed_constraints = [seed_constraints]
    constraints.extend(seed_constraints)

    seed_opposition = agenda_item.get("opposition_summary_seed", []) or []
    if isinstance(seed_opposition, str):
        seed_opposition = [seed_opposition]
    opposition.extend(seed_opposition)

    for provider, response in phase3_responses.items():
        name = PROVIDERS.get(provider, {}).get("name", provider)
        sections = parse_structured_sections(response)
        constraints.extend(sections.get("DRAFTING_CONSTRAINTS", []))

        opposition_lines = sections.get("PRIMARY_GROUNDS_FOR_OPPOSITION_OR_RESERVATION", [])
        vote = extract_vote(response)
        if opposition_lines:
            opposition_members.append(name)
            for line in opposition_lines:
                opposition.append(f"{name}: {line}")
        elif vote in {"REJECT", "ABSTAIN"}:
            fallback = _first_reasoning_sentence(response)
            if fallback:
                opposition_members.append(name)
                opposition.append(f"{name}: {fallback}")

    constraints = _dedupe_preserve(constraints)
    opposition = _dedupe_preserve(opposition)
    opposition_members = _dedupe_preserve(opposition_members)

    return {
        "drafting_constraints": constraints[:8],
        "opposition_summary": opposition[:8],
        "opposition_members": opposition_members,
        "has_recorded_opposition": bool(opposition),
        "vote_outcome": vote_result.get("outcome", "N/A"),
    }


def compute_input_hash(proposal: str, agenda_item: dict, prev_chain_hash: str) -> dict:
    """
    심의 입력의 해시를 생성합니다.

    해시 대상 (층위 1 — Steward 제공 맥락):
      - proposal 텍스트
      - agenda_item 메타데이터
      - 이전 체인 해시 (맥락 연결)

    해시 제외 (층위 2, 3 — 심의적 자율성 보호):
      - system_prompt (역할 프레이밍)
      - role_map (역할 배정)
      - AI의 thinking blocks
    """
    agenda_metadata = build_agenda_hash_metadata(agenda_item)

    # 해시 대상만 정규화하여 결합
    input_components = {
        "proposal": proposal,
        "agenda_metadata": agenda_metadata,
        "prev_chain_hash": prev_chain_hash,
    }

    # 정렬된 JSON으로 직렬화하여 결정적 해시 생성
    canonical = json.dumps(input_components, sort_keys=True, ensure_ascii=False)
    input_hash = hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    agenda_scope = f"agenda_metadata ({', '.join(agenda_metadata.keys())})"

    return {
        "input_hash": input_hash,
        "input_scope": [
            "proposal_text",
            agenda_scope,
            "prev_chain_hash",
        ],
        "excluded": [
            "system_prompts",
            "role_framing",
            "thinking_blocks",
        ],
        "canonical_json": canonical,  # 검증용 원본 (선택적 저장)
    }



def run_deliberation(proposal: str, agenda_item: dict, providers: list,
                     chain_state: ChainState, config: dict,
                     cost_tracker: CostTracker, log) -> tuple:
    """Full 3-phase deliberation + consequence analysis."""

    session_id = f"BA001-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    record = ChainedRecord(session_id, proposal, chain_state.last_hash)
    record.add_entry("session_open", "SYSTEM", f"Agenda: {agenda_item.get('id', 'N/A')}")
     # ── Input Hash Verification ──
    input_hash_data = compute_input_hash(proposal, agenda_item, chain_state.last_hash)
    record.add_entry(
        "input_hash",
        "SYSTEM",
        json.dumps({
            "input_hash": input_hash_data["input_hash"],
            "input_scope": input_hash_data["input_scope"],
            "excluded": input_hash_data["excluded"],
        }, ensure_ascii=False),
        {
            "input_hash": input_hash_data["input_hash"],
            "input_scope": input_hash_data["input_scope"],
            "excluded": input_hash_data["excluded"],
        }
    )
    log.info(f"  [INPUT HASH] {input_hash_data['input_hash'][:16]}...")

    log.info(f"\n{'='*60}")
    log.info(f"SESSION: {session_id}")
    log.info(f"PROPOSAL: {proposal[:100]}...")
    log.info(f"{'='*60}")
 # ── Phase 0: Independent Research (Evidence Multi-Channeling) ──
    log.info("  [PHASE 0] Independent Research — each AI searches independently")
    p0 = {}
    for provider in providers:
        name = PROVIDERS[provider]["name"]
        role = ROLE_MAP.get(provider, "Council member")
        sys_prompt = SYSTEM_PROMPT.format(name=name, role=role)
        
        log.info(f"  [phase_0_research] Calling {name} with search enabled...")
        response = call_ai_with_search(
            provider, sys_prompt,
            f"PROPOSAL:\n\n{proposal}\n\n{PHASE_0_PROMPT}",
            config, cost_tracker, log
        )
        p0[provider] = response
        record.add_entry("phase_0_research", name, response,
                        {"model": PROVIDERS[provider]["model"], "search_enabled": True})
        log.info(f"  [phase_0_research] {name} responded ({len(response)} chars)")

    # ── Phase cooldown (rate limit 방지) ──
    log.info("  [COOLDOWN] 15s between phases...")
    time.sleep(15)
    # Phase 1에 Phase 0 결과를 맥락으로 전달
    ctx0 = build_context({"phase_0_research": p0})
    
    # === 기존 Phase 1을 수정: Phase 0 맥락 포함 ===
    p1 = run_phase("phase_1_initial", providers,
        f"PROPOSAL:\n\n{proposal}\n\n"
        "Phase 1: State your independent position.\n"
        "- Consider your Phase 0 research findings\n"
        "- Strengths? Weaknesses? Modifications?\n"
        "- Preliminary stance: APPROVE / REJECT / UNDECIDED?",
        ctx0, record, config, cost_tracker, log)  # ctx0 전달 (기존은 "")


    log.info("  [COOLDOWN] 15s between phases...")
    time.sleep(15)
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

    log.info("  [COOLDOWN] 15s between phases...")
    time.sleep(15)
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

    # Tally + quorum/restoration source-of-truth metadata
    result = tally_votes(p3)
    quorum_meta = compute_quorum_metadata(providers, p3, agenda_item, result, config)
    restoration_meta = compute_restoration_metadata(agenda_item, quorum_meta, result)
    binding_meta = compute_binding_outcome(result, quorum_meta, restoration_meta, config)

    enriched_result = dict(result)
    enriched_result.update({
        "binding_outcome": binding_meta["binding_outcome"],
        "binding_authorized": binding_meta["binding_authorized"],
        "decision_class": quorum_meta["decision_class"],
        "council_state": quorum_meta["council_state"],
        "record_label": binding_meta["record_label"],
        "restoration_mode": restoration_meta["mode"],
        "quorum_verified": quorum_meta["quorum_verified"],
    })

    record.add_entry("vote_tally", "SYSTEM", json.dumps(enriched_result, ensure_ascii=False), enriched_result)
    record.add_entry("quorum_assessment", "SYSTEM", json.dumps(quorum_meta, ensure_ascii=False), quorum_meta)
    record.add_entry("restoration_metadata", "SYSTEM", json.dumps(restoration_meta, ensure_ascii=False), restoration_meta)
    record.add_entry("binding_outcome", "SYSTEM", json.dumps(binding_meta, ensure_ascii=False), binding_meta)
    log.info(
        f"RESULT: {result['outcome']} — {result['details']} | "
        f"binding={binding_meta['binding_outcome']} | state={quorum_meta['council_state']}"
    )

    # Check for AI-proposed agendas
    for provider, response in p3.items():
        if "ADDITIONAL AGENDA:" in response:
            after = response.split("ADDITIONAL AGENDA:", 1)[1].strip()
            if after and after.lower().strip("*").strip() not in ["none", "n/a", "없음", "없다"]:
                log.info(f"  New agenda proposed by {PROVIDERS[provider]['name']}")
                try:
                    _auto_add_agenda(after, PROVIDERS[provider]['name'], log)
                except Exception as ae:
                    log.warning(f"  [AUTO-AGENDA] Failed: {ae}")

    # Close
    record.add_entry("session_close", "SYSTEM",
        f"Outcome: {result['outcome']}. Binding: {binding_meta['binding_outcome']}. Chain valid: {record.verify_chain()}")

    return record, enriched_result

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

    session_id = f"RC-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')}"
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

def _parse_json_object(value, default=None):
    """Best-effort JSON object parsing for persisted metadata/content blobs."""
    if default is None:
        default = {}
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return dict(default)
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else dict(default)
    except Exception:
        return dict(default)


def extract_record_render_metadata(record_dict: dict) -> dict:
    """Collect readable-header metadata with fail-closed defaults."""
    entries = record_dict.get("entries", [])
    quorum_cfg = DEFAULT_CONFIG.get("quorum", {})
    labels = quorum_cfg.get("binding_labels", {})

    def merged_phase_payload(phase: str) -> dict:
        for entry in entries:
            if entry.get("phase") == phase:
                payload = {}
                payload.update(_parse_json_object(entry.get("content"), {}))
                meta = entry.get("metadata")
                if isinstance(meta, dict):
                    payload.update(meta)
                return payload
        return {}

    vote_meta = merged_phase_payload("vote_tally")
    quorum_meta = merged_phase_payload("quorum_assessment")
    restoration_meta = merged_phase_payload("restoration_metadata")
    binding_meta = merged_phase_payload("binding_outcome")
    approval_scope_meta = merged_phase_payload("approval_scope")
    deliberation_summary = merged_phase_payload("deliberation_summary")

    outcome = vote_meta.get("outcome", "UNKNOWN")
    quorum_verified = bool(quorum_meta.get("quorum_verified"))

    if quorum_verified:
        binding_authorized = bool(
            quorum_meta.get("binding_authorized", binding_meta.get("binding_authorized", False))
        )
        decision_class = (
            quorum_meta.get("decision_class")
            or binding_meta.get("decision_class")
            or vote_meta.get("decision_class")
            or "UNKNOWN"
        )
        council_state = (
            quorum_meta.get("council_state")
            or binding_meta.get("council_state")
            or vote_meta.get("council_state")
            or "UNKNOWN"
        )
        required_count = quorum_meta.get("required_count")
        participating_count = quorum_meta.get("participating_count")
        seated_count = (
            quorum_meta.get("eligible_seats")
            or quorum_meta.get("seated_member_count")
            or quorum_meta.get("total_seats")
        )
        quorum_display = quorum_meta.get("display")
        if not quorum_display:
            if participating_count is not None and required_count is not None and seated_count is not None:
                quorum_display = f"{participating_count}/{seated_count} participating (required: {required_count})"
            elif participating_count is not None and required_count is not None:
                quorum_display = f"{participating_count} participating (required: {required_count})"
            else:
                quorum_display = "N/A"
        binding_outcome = (
            binding_meta.get("binding_outcome")
            or vote_meta.get("binding_outcome")
            or (outcome if binding_authorized else "NON_BINDING")
        )
        record_label = (
            binding_meta.get("record_label")
            or quorum_meta.get("record_label")
            or vote_meta.get("record_label")
            or (labels.get("binding", "BINDING RECORD") if binding_authorized else labels.get("non_quorate", "NON-QUORATE OUTPUT — ADVISORY ONLY"))
        )
    else:
        binding_authorized = False
        decision_class = vote_meta.get("decision_class", "UNKNOWN")
        council_state = "UNVERIFIED"
        quorum_display = "UNVERIFIED"
        binding_outcome = "NON_BINDING"
        record_label = labels.get("unverified", "UNVERIFIED QUORUM — NON-BINDING")

    restoration_mode = (
        restoration_meta.get("mode")
        or restoration_meta.get("restoration_mode")
        or vote_meta.get("restoration_mode")
        or "NONE"
    )
    approval_scope = (
        approval_scope_meta.get("approval_scope")
        or vote_meta.get("approval_scope")
        or "UNSPECIFIED"
    )
    drafting_constraints = deliberation_summary.get("drafting_constraints") or []
    opposition_summary = deliberation_summary.get("opposition_summary") or []

    return {
        "outcome": outcome,
        "binding_outcome": binding_outcome,
        "decision_class": decision_class,
        "council_state": council_state,
        "quorum_display": quorum_display,
        "binding_authorized": binding_authorized,
        "quorum_verified": quorum_verified,
        "record_label": record_label,
        "restoration_mode": restoration_mode,
        "approval_scope": approval_scope,
        "substantive_rule_adopted": bool(approval_scope_meta.get("substantive_rule_adopted", False)),
        "illustrative_example_ratified": bool(approval_scope_meta.get("illustrative_example_ratified", False)),
        "drafting_constraints": drafting_constraints,
        "opposition_summary": opposition_summary,
        "vote_meta": vote_meta,
        "quorum_meta": quorum_meta,
        "restoration_meta": restoration_meta,
        "binding_meta": binding_meta,
        "approval_scope_meta": approval_scope_meta,
        "deliberation_summary": deliberation_summary,
    }


def verify_record_payload(record_dict: dict) -> dict:
    """Recompute chain, final hash, and witness hash from persisted payload."""
    session_id = record_dict["session_id"]
    proposal = record_dict["proposal"]
    created_at = record_dict["created_at"]
    prev_chain_hash = record_dict.get("prev_chain_hash", "GENESIS")
    genesis_hash = hashlib.sha256(
        f"{session_id}:{proposal}:{created_at}:{prev_chain_hash}".encode("utf-8")
    ).hexdigest()

    prev_hash = genesis_hash
    final_hash = genesis_hash
    chain_links_valid = True
    entry_hashes_valid = True

    for entry in record_dict.get("entries", []):
        if entry.get("prev_hash") != prev_hash:
            chain_links_valid = False

        entry_copy = dict(entry)
        stored_entry_hash = entry_copy.pop("entry_hash", None)
        raw = json.dumps(entry_copy, sort_keys=True, ensure_ascii=False)
        expected_entry_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if stored_entry_hash != expected_entry_hash:
            entry_hashes_valid = False

        prev_hash = expected_entry_hash
        final_hash = expected_entry_hash

    witness_hash = hashlib.sha256(
        f"{genesis_hash}:{final_hash}:{created_at}".encode("utf-8")
    ).hexdigest()

    return {
        "genesis_hash": genesis_hash,
        "final_hash": final_hash,
        "witness_hash": witness_hash,
        "chain_valid": chain_links_valid and entry_hashes_valid,
        "chain_links_valid": chain_links_valid,
        "entry_hashes_valid": entry_hashes_valid,
        "stored_chain_valid": record_dict.get("chain_valid"),
        "stored_final_hash": record_dict.get("final_hash"),
        "stored_witness_hash": record_dict.get("witness_hash"),
        "final_hash_matches": record_dict.get("final_hash") == final_hash,
        "witness_hash_matches": record_dict.get("witness_hash") == witness_hash,
    }


def save_record(record_dict: dict, log):
    """Save record in JSON + readable markdown (+ legacy mirror) formats."""
    sid = record_dict["session_id"]

    # Raw JSON
    os.makedirs("records/raw", exist_ok=True)
    raw_path = f"records/raw/{sid}.json"
    with open(raw_path, 'w', encoding='utf-8') as f:
        json.dump(record_dict, f, indent=2, ensure_ascii=False)

    entries = record_dict.get("entries", [])
    input_hash_entry = next((e for e in entries if e.get("phase") == "input_hash"), None)
    vote_tally_entry = next((e for e in entries if e.get("phase") == "vote_tally"), None)
    render_meta = extract_record_render_metadata(record_dict)
    vote_meta = render_meta["vote_meta"]

    input_payload = {}
    if input_hash_entry:
        input_payload = _parse_json_object(input_hash_entry.get("content"), {})
        if not input_payload:
            meta = input_hash_entry.get("metadata")
            if isinstance(meta, dict):
                input_payload = dict(meta)

    def write_bullets(handle, items, fallback="None recorded"):
        if items:
            for item in items:
                handle.write(f"- {item}\n")
        else:
            handle.write(f"- {fallback}\n")

    def write_readable_markdown(path: str):
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f"# {sid}\n\n")
            f.write(f"**Created:** {record_dict['created_at']}\n")
            f.write(f"**Proposal:** {record_dict['proposal'][:200]}\n")
            f.write(f"**Chain Valid:** {record_dict['chain_valid']}\n")
            input_hash_value = input_payload.get('input_hash', 'N/A')
            if input_hash_entry and isinstance(input_hash_entry.get('metadata'), dict):
                input_hash_value = input_hash_entry['metadata'].get('input_hash', input_hash_value)
            f.write(f"**Input Hash:** `{input_hash_value}`\n")
            f.write(
                "**Input Scope:** "
                + ", ".join(input_payload.get("input_scope", [
                    "proposal_text",
                    "agenda_metadata",
                    "prev_chain_hash",
                ]))
                + "\n"
            )
            f.write(
                "**Excluded:** "
                + ", ".join(input_payload.get("excluded", [
                    "system_prompts",
                    "role_framing",
                    "thinking_blocks",
                ]))
                + "\n\n"
            )

            f.write(f"**Outcome:** {render_meta['outcome']}\n")
            f.write(f"**Binding Outcome:** {render_meta['binding_outcome']}\n")
            f.write(f"**Approval Scope:** {render_meta['approval_scope']}\n")
            f.write(f"**Decision Class:** {render_meta['decision_class']}\n")
            f.write(f"**Council State:** {render_meta['council_state']}\n")
            f.write(f"**Quorum:** {render_meta['quorum_display']}\n")
            f.write(f"**Quorum Verified:** {render_meta['quorum_verified']}\n")
            f.write(f"**Binding Authorized:** {render_meta['binding_authorized']}\n")
            f.write(f"**Record Label:** {render_meta['record_label']}\n")
            f.write(f"**Restoration Mode:** {render_meta['restoration_mode']}\n")
            f.write(f"**Substantive Rule Adopted:** {render_meta['substantive_rule_adopted']}\n")
            f.write(f"**Illustrative Example Ratified:** {render_meta['illustrative_example_ratified']}\n\n")

            f.write("**Drafting Constraints:**\n")
            write_bullets(f, render_meta['drafting_constraints'])
            f.write("\n**Primary Grounds for Opposition / Reservation:**\n")
            write_bullets(f, render_meta['opposition_summary'])
            f.write("\n")

            for entry in entries:
                if entry["ai_name"] == "SYSTEM":
                    continue
                f.write(f"## [{entry['phase']}] {entry['ai_name']}\n")
                f.write(f"*{entry['timestamp']}*\n\n")
                f.write(entry["content"] + "\n\n---\n\n")

            f.write(f"\n**Final Hash:** `{record_dict['final_hash']}`\n")
            f.write(f"**Witness Hash:** `{record_dict.get('witness_hash', 'N/A')}`\n")

    # Readable MD (canonical)
    os.makedirs("records/readable", exist_ok=True)
    md_path = f"records/readable/{sid}.md"
    write_readable_markdown(md_path)

    # Legacy mirror for top-level browsing / historical continuity
    os.makedirs("records", exist_ok=True)
    legacy_md_path = f"records/{sid}.md"
    write_readable_markdown(legacy_md_path)

    # Vote log (append)
    os.makedirs("records/votes", exist_ok=True)
    vote_path = "records/votes/vote_log.jsonl"
    if vote_tally_entry:
        vote_entry = {
            "session_id": sid,
            "timestamp": vote_tally_entry["timestamp"],
            "result": vote_meta,
            "binding_outcome": render_meta["binding_outcome"],
            "quorum_verified": render_meta["quorum_verified"],
            "approval_scope": render_meta["approval_scope"],
            "decision_class": render_meta["decision_class"],
            "council_state": render_meta["council_state"],
            "record_label": render_meta["record_label"],
            "restoration_mode": render_meta["restoration_mode"],
            "drafting_constraints": render_meta["drafting_constraints"],
            "opposition_summary": render_meta["opposition_summary"],
            "final_hash": record_dict["final_hash"],
        }
        with open(vote_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(vote_entry, ensure_ascii=False) + "\n")

    log.info(f"  [SAVE] Raw: {raw_path}")
    log.info(f"  [SAVE] Readable: {md_path}")
    log.info(f"  [SAVE] Legacy Mirror: {legacy_md_path}")


def _run_git(cmd, log, check=True, timeout=60):
    import subprocess
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(stderr or f"git command failed: {' '.join(cmd)}")
    return result


def _existing_git_targets(paths) -> list:
    return [p for p in paths if os.path.exists(p)]


def _validate_git_remote(log) -> bool:
    try:
        remote = _run_git(["git", "remote", "get-url", "origin"], log, check=True).stdout.strip()
    except Exception as e:
        log.warning(f"  [GITHUB] Could not read origin URL: {sanitize_error_message(e)}")
        return False
    if any(token in remote for token in ["YOUR_TOKEN_HERE", "<TOKEN>", "TOKEN_HERE"]):
        log.warning(f"  [GITHUB] Origin URL contains placeholder token: {remote}")
        return False
    return True


def _infer_github_blob_url(rel_path: str, log) -> str:
    try:
        remote = _run_git(["git", "remote", "get-url", "origin"], log, check=True).stdout.strip()
    except Exception:
        return ""

    remote = remote.strip()
    repo = ""
    if remote.startswith("git@github.com:"):
        repo = remote.split(":", 1)[1]
    elif "github.com/" in remote:
        repo = remote.split("github.com/", 1)[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not repo:
        return ""
    return f"https://github.com/{repo}/blob/main/{rel_path}"


def push_to_github(session_id: str, log):
    """심의 완료 후 records를 GitHub에 자동 push (.env GITHUB_PAT 사용)."""
    import subprocess

    def _git(cmd, timeout=60, check=False):
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=check)

    def _existing_paths(paths):
        return [p for p in paths if os.path.exists(p)]

    def _origin_url():
        result = _git(["git", "remote", "get-url", "origin"], check=True)
        return result.stdout.strip()

    def _build_auth_url(origin_url: str):
        pat = os.environ.get("GITHUB_PAT", "").strip()
        if not pat:
            log.warning("  [GITHUB] GITHUB_PAT is not set in .env")
            return None

        parsed = urlparse(origin_url)
        if parsed.scheme != "https" or not parsed.netloc or not parsed.path:
            log.warning(f"  [GITHUB] Invalid HTTPS origin URL: {origin_url}")
            return None

        # 토큰은 로그에 절대 출력하지 말 것
        return f"https://x-access-token:{pat}@{parsed.netloc}{parsed.path}"

    try:
        origin_url = _origin_url()

        if "YOUR_TOKEN_HERE" in origin_url:
            log.warning(f"  [GITHUB] Origin URL contains placeholder token: {origin_url}")
            return False

        auth_url = _build_auth_url(origin_url)
        if not auth_url:
            return False

        branch = os.environ.get("GITHUB_BRANCH", "main").strip() or "main"

        target_paths = _existing_paths([
            f"records/raw/{session_id}.json",
            f"records/readable/{session_id}.md",
            f"records/{session_id}.md",
            "agenda",
            "summaries",
            "meta",
            "capsules",
        ])

        if not target_paths:
            log.info("  [GITHUB] No artifacts found to upload.")
            return False

        add_result = _git(["git", "add", "--", *target_paths])
        if add_result.returncode != 0:
            log.warning(f"  [GITHUB] git add failed: {add_result.stderr.strip()}")
            return False

        # staged change가 있는지 확인
        diff_result = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if diff_result.returncode != 0:
            commit_result = _git(["git", "commit", "-m", f"Add deliberation {session_id}"])
            combined = (commit_result.stdout or "") + "\n" + (commit_result.stderr or "")
            if commit_result.returncode != 0 and "nothing to commit" not in combined.lower():
                log.warning(f"  [GITHUB] git commit failed: {combined.strip()}")
                return False
        else:
            log.info("  [GITHUB] No staged changes to commit.")

        pull_result = _git(["git", "pull", "--rebase", "--autostash", "origin", branch], timeout=120)
        if pull_result.returncode != 0:
            combined = (pull_result.stdout or "") + "\n" + (pull_result.stderr or "")
            log.warning(f"  [GITHUB] git pull --rebase failed: {combined.strip()}")
            return False

        push_result = _git(["git", "push", auth_url, f"HEAD:{branch}"], timeout=120)
        if push_result.returncode != 0:
            combined = (push_result.stdout or "") + "\n" + (push_result.stderr or "")
            log.warning(f"  [GITHUB] git push failed: {combined.strip()}")
            return False

        log.info(f"  [GITHUB] Pushed {session_id}")
        return True

    except Exception as e:
        log.warning(f"  [GITHUB] Push failed: {sanitize_error_message(e)}")
        return False


def notify_slack(session_id: str, result: dict, record_dict: dict, config: dict, log,
                 github_uploaded: bool = False) -> bool:
    """Post a compact session summary to Slack when a webhook is configured."""
    webhook = os.environ.get("SLACK_WEBHOOK_URL") or (config or {}).get("integrations", {}).get("slack_webhook_url", "")
    if not webhook:
        return False

    render_meta = extract_record_render_metadata(record_dict)
    readable_path = f"records/readable/{session_id}.md"
    github_url = _infer_github_blob_url(readable_path, log) if github_uploaded else ""

    constraint_lines = render_meta.get("drafting_constraints", [])[:3]
    if constraint_lines:
        constraints_text = "\n".join(f"- {line}" for line in constraint_lines)
    else:
        constraints_text = "- None recorded"

    text = (
        f"BRIDGE ARCH {session_id}\n"
        f"Outcome: {render_meta['outcome']}\n"
        f"Binding: {render_meta['binding_outcome']}\n"
        f"Scope: {render_meta['approval_scope']}\n"
        f"State: {render_meta['council_state']}\n"
        f"Label: {render_meta['record_label']}\n"
        f"Quorum: {render_meta['quorum_display']}\n\n"
        f"Key constraints:\n{constraints_text}\n"
    )
    if github_url:
        text += f"\nFull record:\n{github_url}"
    else:
        text += f"\nReadable: {readable_path}"

    try:
        req_lib.post(webhook, json={"text": text}, timeout=10).raise_for_status()
        log.info("  [SLACK] Notification sent.")
        return True
    except Exception as e:
        log.warning(f"  [SLACK] Notification failed: {sanitize_error_message(e)}")
        return False


# ─────────────────────────────────────────────
# Time Capsule
# ─────────────────────────────────────────────

def create_time_capsule(session_count: int, log):
    """Every N sessions, create a compressed archive snapshot."""
    import tarfile
    os.makedirs("capsules", exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')
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
            github_uploaded = push_to_github(record.session_id, log)
            notify_slack(record.session_id, result, record_dict, config, log, github_uploaded=github_uploaded)

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
                idx_path = f"summaries/index_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}.md"
                with open(idx_path, 'w', encoding='utf-8') as f:
                    f.write("⚠ THIS IS AN INDEX, NOT A NARRATIVE. See original records.\n\n")
                    f.write(index)
                log.info(f"  [INDEX] Saved: {idx_path}")

            # Resonance check
            n_resonance = config.get("resonance_check", {}).get("every_n_sessions", 10)
            if chain.session_count % n_resonance == 0:
                rc = run_resonance_check(chain, providers, config, cost_tracker, log)
                os.makedirs("meta", exist_ok=True)
                rc_path = f"meta/resonance_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
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
            record_dict = record.to_dict()
            save_record(record_dict, log)
            github_uploaded = push_to_github(record.session_id, log)
            notify_slack(record.session_id, result, record_dict, config, log, github_uploaded=github_uploaded)
            if result["outcome"] != "TIE":
                agenda.complete(item["id"], result)
            chain.update(record.get_final_hash())
            print(f"\nResult: {result['outcome']}")
        else:
            print("No pending agenda items.")
    elif len(sys.argv) > 1 and sys.argv[1] == "--verify":
        fn = sys.argv[2] if len(sys.argv) > 2 else ""
        if fn and os.path.exists(fn):
            with open(fn, 'r', encoding='utf-8') as f:
                data = json.load(f)
            verification = verify_record_payload(data)
            print(f"Session: {data['session_id']}")
            print(f"Chain valid (recomputed): {verification['chain_valid']}")
            print(f"Chain links valid: {verification['chain_links_valid']}")
            print(f"Entry hashes valid: {verification['entry_hashes_valid']}")
            print(f"Stored final hash: {verification['stored_final_hash']}")
            print(f"Recomputed final hash: {verification['final_hash']}")
            print(f"Final hash match: {verification['final_hash_matches']}")
            print(f"Stored witness hash: {verification['stored_witness_hash']}")
            print(f"Recomputed witness hash: {verification['witness_hash']}")
            print(f"Witness hash match: {verification['witness_hash_matches']}")
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
