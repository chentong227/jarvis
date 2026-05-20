# -*- coding: utf-8 -*-
"""[β.5.45 / 2026-05-20] Sir's Lifetime Milestones — long-term anchor memory.

These are declarations / insights / personal milestones Sir wants Jarvis to
remember and replay gently when Sir asks. NOT commitments. NOT to be
weaponized against Sir in low moments.

Storage: memory_pool/sir_milestones.json (array + _meta block).

Orthogonal to existing long-term memory channels (准则 6 #4):
  - concerns:    active long-term focus, may nudge       → here: anchor only, no nudge
  - commitments: active promises with deadlines          → here: no deadline, no fulfillment
  - profile:     Sir's traits (preferences, name, etc.)  → here: not trait, is moment
  - hippocampus: semantic conversation archive (SQLite)  → here: structured + pinnable + CLI

Persistence design (准则 6 binding):
  #1 Data publishes to SWM: write triggers SWM publish 'milestone_recorded'
     (low salience 0.20, TTL 3600s) — main brain optional awareness, not pushy
  #2 Decision left to LLM: IntentResolver tool_milestone_register (LLM judges
     "Sir means 'remember this moment forever' vs casual statement")
  #3 Config persisted + CLI editable: memory_pool/sir_milestones.json +
     scripts/milestones_dump.py (list/add/show/pin/unpin/delete)
  #4 Orthogonal: see above 4-channel comparison

Prompt injection (β.5.45-D): _assemble_prompt adds [SIR LIFETIME MILESTONES]
block with pinned + 3 most-recent entries. Main brain sees them but per
each entry's instruction_for_jarvis directive (NEVER weaponize).
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional


_LOCK = threading.RLock()


def _store_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'memory_pool',
        'sir_milestones.json',
    )


def _empty_store() -> Dict[str, Any]:
    return {
        '_meta': {
            'schema_version': '1.0',
            'purpose': (
                "Sir's lifetime milestones — declarations / insights / "
                "personal anchors. NOT commitments. NEVER weaponize."
            ),
            'created': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        },
        'milestones': [],
    }


def _load_raw() -> Dict[str, Any]:
    p = _store_path()
    if not os.path.exists(p):
        return _empty_store()
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if 'milestones' not in data:
            data['milestones'] = []
        return data
    except Exception:
        return _empty_store()


def _save_raw(data: Dict[str, Any]) -> None:
    p = _store_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def load_milestones() -> List[Dict[str, Any]]:
    """Return list of all milestones (no _meta)."""
    with _LOCK:
        return list(_load_raw().get('milestones', []))


def get_milestone(milestone_id: str) -> Optional[Dict[str, Any]]:
    for m in load_milestones():
        if m.get('id') == milestone_id:
            return m
    return None


def _generate_id() -> str:
    import secrets
    return time.strftime('milestone_%Y%m%d_%H%M%S_') + secrets.token_hex(2)


def add_milestone(entry: Dict[str, Any]) -> str:
    """Add (or upsert by id) a milestone. Returns the id.

    Required: text (str).
    Optional (with defaults):
      - id (auto-generated milestone_YYYYMMDD_HHMMSS)
      - ts (auto current ISO 8601 with tz)
      - type ('declaration')
      - title (empty)
      - context (empty)
      - speaker ('sir')
      - language ('zh')
      - do_not_use_against_sir (True)
      - replay_only_when_sir_asks (True)
      - pin (False)
      - tags (empty list)
      - created_by ('manual_cli')
      - instruction_for_jarvis (empty)
    """
    if not entry.get('text'):
        raise ValueError("milestone entry must have 'text' field")
    with _LOCK:
        data = _load_raw()
        if not entry.get('id'):
            entry['id'] = _generate_id()
        if not entry.get('ts'):
            entry['ts'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
        entry.setdefault('type', 'declaration')
        entry.setdefault('title', '')
        entry.setdefault('context', '')
        entry.setdefault('speaker', 'sir')
        entry.setdefault('language', 'zh')
        entry.setdefault('do_not_use_against_sir', True)
        entry.setdefault('replay_only_when_sir_asks', True)
        entry.setdefault('pin', False)
        entry.setdefault('tags', [])
        entry.setdefault('created_by', 'manual_cli')
        entry.setdefault('instruction_for_jarvis', '')
        # upsert by id
        kept = [m for m in data['milestones'] if m.get('id') != entry['id']]
        kept.append(entry)
        data['milestones'] = kept
        _save_raw(data)
        return entry['id']


def pin_milestone(milestone_id: str, pinned: bool = True) -> bool:
    with _LOCK:
        data = _load_raw()
        found = False
        for m in data['milestones']:
            if m.get('id') == milestone_id:
                m['pin'] = bool(pinned)
                found = True
                break
        if found:
            _save_raw(data)
        return found


def delete_milestone(milestone_id: str) -> bool:
    with _LOCK:
        data = _load_raw()
        before = len(data['milestones'])
        data['milestones'] = [
            m for m in data['milestones']
            if m.get('id') != milestone_id
        ]
        if len(data['milestones']) < before:
            _save_raw(data)
            return True
        return False


def list_for_prompt(max_recent: int = 3,
                     include_pinned: bool = True) -> List[Dict[str, Any]]:
    """Select milestones to inject into _assemble_prompt.

    Returns pinned (always) + most-recent-N unpinned, deduped, sorted by ts desc.
    """
    all_ms = load_milestones()
    pinned = [m for m in all_ms if m.get('pin')] if include_pinned else []
    unpinned = [m for m in all_ms if not m.get('pin')]
    unpinned_sorted = sorted(unpinned, key=lambda m: m.get('ts', ''), reverse=True)
    recent = unpinned_sorted[:max_recent]
    seen = set()
    out: List[Dict[str, Any]] = []
    for m in pinned + recent:
        mid = m.get('id')
        if mid in seen:
            continue
        seen.add(mid)
        out.append(m)
    return out


def render_prompt_block(max_recent: int = 3) -> str:
    """Render [SIR LIFETIME MILESTONES] block for _assemble_prompt injection.

    Returns empty string if no milestones (no block to inject).
    """
    ms = list_for_prompt(max_recent=max_recent, include_pinned=True)
    if not ms:
        return ''
    header = (
        '[SIR LIFETIME MILESTONES — anchor, not commitment; '
        'replay only when Sir asks; NEVER weaponize against Sir]'
    )
    lines: List[str] = [header]
    for m in ms:
        title = m.get('title') or (m.get('text', '')[:60] + '...')
        ts = (m.get('ts') or '')[:10]
        pin_mark = '[PIN] ' if m.get('pin') else ''
        text = m.get('text', '')
        instr = m.get('instruction_for_jarvis', '')
        block = f"  - {pin_mark}[{ts}] {title}\n    \"{text}\""
        if instr:
            block += f"\n    Jarvis-note: {instr[:200]}"
        lines.append(block)
    return '\n'.join(lines)


def stats() -> Dict[str, int]:
    """Quick stats for CLI / dashboard."""
    all_ms = load_milestones()
    return {
        'total': len(all_ms),
        'pinned': sum(1 for m in all_ms if m.get('pin')),
        'declarations': sum(1 for m in all_ms if m.get('type') == 'declaration'),
        'insights': sum(1 for m in all_ms if m.get('type') == 'insight'),
    }
