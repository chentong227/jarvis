# -*- coding: utf-8 -*-
"""[Gap 1 / P5-ToM / 2026-05-21 00:50] Theory of Mind: Sir Mental Model

Sir 22:10 真实 case: "我要去洗澡然后睡, 大概 11 点半"
  surface need (95%): 改 reminder 23:30
  deeper need  (70%): 1.5h buffer + 软抗 sleep nudge  
  unspoken need (30%): 想被陪 / 想再聊一会儿

Jarvis 现在只看到 surface (调 tool 改 reminder). Layer 6 ToM 让主脑读 Sir 言外
之意 — 老友感的真核心.

Design doc: docs/JARVIS_TOM_SIR_MENTAL_MODEL.md

主要组件:
  SirMentalState dataclass: 6 维度 hypothesis (task/emotion/needs 3层/relational)
  SirMentalStateStore: thread-safe persist + revision history
  ToMReflector daemon: 每 turn 后 LLM judge → propose new state
  render_prompt_block: 注 [SIR'S MIND RIGHT NOW] block
  CLI: scripts/sir_mental_state_dump.py
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


_DEFAULT_STORE_PATH = os.path.join('memory_pool', 'sir_mental_state.json')
_MAX_REVISION_HISTORY = 50
_STALE_THRESHOLD_S = 600.0  # 10min — beyond this hypothesis goes stale


# ============================================================
# Data structure
# ============================================================

@dataclass
class SirMentalState:
    """Jarvis's hypothesis about Sir's current mental state. Layer 6."""

    # ===== 当下任务层 =====
    current_task_hypothesis: str = ''      # "Sir is debugging Jarvis apology loop"
    task_confidence: float = 0.0           # 0-1
    task_evidence: List[str] = field(default_factory=list)

    # ===== 当下情绪层 (升级 MoodMirror) =====
    emotional_state: str = 'unknown'       # "engaged_but_tired" / "frustrated" / etc
    emotional_confidence: float = 0.0
    emotion_evidence: List[str] = field(default_factory=list)

    # ===== 当下需求层 (核心 — ToM 真精华) =====
    surface_need: str = ''                 # "改 reminder 时间"
    deeper_need: str = ''                  # "要 buffer + 抗 sleep nudge"
    unspoken_need: str = ''                # "想被陪一会儿" (low conf)
    need_layers_confidence: Dict[str, float] = field(default_factory=lambda: {
        'surface': 0.0, 'deeper': 0.0, 'unspoken': 0.0
    })

    # ===== 与 Jarvis 的关系层 =====
    relational_temp: str = 'neutral'       # warm/cool/playful/serious/tense/intimate
    relational_evidence: List[str] = field(default_factory=list)

    # ===== 演化追踪 =====
    last_updated: float = 0.0
    last_updated_iso: str = ''
    revision_history: List[dict] = field(default_factory=list)
    source_turn_id: str = ''
    proposed_by: str = 'unknown'           # 'tom_reflector' / 'sir_manual' / 'main_brain'

    def to_dict(self) -> dict:
        return asdict(self)

    def is_stale(self, now_ts: Optional[float] = None) -> bool:
        """If hypothesis age > _STALE_THRESHOLD_S, treat as stale."""
        if self.last_updated <= 0:
            return True
        n = now_ts or time.time()
        return (n - self.last_updated) > _STALE_THRESHOLD_S

    def has_meaningful_content(self) -> bool:
        """At least 1 dimension has non-empty hypothesis."""
        return bool(
            self.current_task_hypothesis or self.surface_need or
            self.deeper_need or self.emotional_state != 'unknown'
        )

    def add_revision(self, field_name: str, old_value: Any, new_value: Any,
                     why: str = '', evidence: Optional[List[str]] = None) -> None:
        """Record a hypothesis revision (when LLM updates a field)."""
        self.revision_history.append({
            'ts': time.time(),
            'iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
            'field': field_name,
            'old': str(old_value)[:120],
            'new': str(new_value)[:120],
            'why': why[:200],
            'evidence': (evidence or [])[:3],
        })
        if len(self.revision_history) > _MAX_REVISION_HISTORY:
            self.revision_history = self.revision_history[-_MAX_REVISION_HISTORY:]


# ============================================================
# Store
# ============================================================

class SirMentalStateStore:
    """Thread-safe Sir mental state hypothesis store. Single state object."""

    def __init__(self, persist_path: Optional[str] = None):
        self.persist_path = persist_path or _DEFAULT_STORE_PATH
        self.state = SirMentalState()
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.persist_path):
            return
        try:
            with open(self.persist_path, 'r', encoding='utf-8') as f:
                data = json.load(f) or {}
            # rehydrate dataclass
            _state_d = data.get('state') or {}
            self.state = SirMentalState(
                current_task_hypothesis=_state_d.get('current_task_hypothesis', ''),
                task_confidence=float(_state_d.get('task_confidence', 0.0)),
                task_evidence=list(_state_d.get('task_evidence') or []),
                emotional_state=_state_d.get('emotional_state', 'unknown'),
                emotional_confidence=float(_state_d.get('emotional_confidence', 0.0)),
                emotion_evidence=list(_state_d.get('emotion_evidence') or []),
                surface_need=_state_d.get('surface_need', ''),
                deeper_need=_state_d.get('deeper_need', ''),
                unspoken_need=_state_d.get('unspoken_need', ''),
                need_layers_confidence=dict(_state_d.get('need_layers_confidence') or {
                    'surface': 0.0, 'deeper': 0.0, 'unspoken': 0.0
                }),
                relational_temp=_state_d.get('relational_temp', 'neutral'),
                relational_evidence=list(_state_d.get('relational_evidence') or []),
                last_updated=float(_state_d.get('last_updated', 0.0)),
                last_updated_iso=_state_d.get('last_updated_iso', ''),
                revision_history=list(_state_d.get('revision_history') or []),
                source_turn_id=_state_d.get('source_turn_id', ''),
                proposed_by=_state_d.get('proposed_by', 'unknown'),
            )
        except Exception:
            pass

    def _persist(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
            tmp = self.persist_path + '.tmp'
            snapshot = {
                'state': self.state.to_dict(),
                '_meta': {
                    'persisted_at': time.time(),
                    'persisted_iso': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
                    'schema_version': 1,
                },
            }
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.persist_path)
            # rotation cheap (write counter handles)
            try:
                from jarvis_jsonl_rotator import maybe_rotate as _mr
                _mr(self.persist_path, size_mb_cap=2.0)
            except Exception:
                pass
        except Exception:
            pass

    def get_snapshot(self) -> SirMentalState:
        """Returns shallow copy."""
        with self._lock:
            return SirMentalState(
                current_task_hypothesis=self.state.current_task_hypothesis,
                task_confidence=self.state.task_confidence,
                task_evidence=list(self.state.task_evidence),
                emotional_state=self.state.emotional_state,
                emotional_confidence=self.state.emotional_confidence,
                emotion_evidence=list(self.state.emotion_evidence),
                surface_need=self.state.surface_need,
                deeper_need=self.state.deeper_need,
                unspoken_need=self.state.unspoken_need,
                need_layers_confidence=dict(self.state.need_layers_confidence),
                relational_temp=self.state.relational_temp,
                relational_evidence=list(self.state.relational_evidence),
                last_updated=self.state.last_updated,
                last_updated_iso=self.state.last_updated_iso,
                revision_history=list(self.state.revision_history),
                source_turn_id=self.state.source_turn_id,
                proposed_by=self.state.proposed_by,
            )

    def update(self, new_state_partial: dict, source_turn_id: str = '',
                proposed_by: str = 'tom_reflector') -> List[dict]:
        """Update state with partial dict. Records revision_history per field changed.

        Returns list of revisions made.
        """
        revisions = []
        with self._lock:
            for fld, new_val in new_state_partial.items():
                if not hasattr(self.state, fld):
                    continue
                if fld in ('last_updated', 'last_updated_iso',
                           'revision_history', 'source_turn_id', 'proposed_by'):
                    continue
                old_val = getattr(self.state, fld)
                # only record revision if different
                if old_val != new_val:
                    self.state.add_revision(
                        fld, old_val, new_val,
                        why=f'updated by {proposed_by}',
                        evidence=[],
                    )
                    setattr(self.state, fld, new_val)
                    revisions.append({
                        'field': fld,
                        'old': str(old_val)[:80],
                        'new': str(new_val)[:80],
                    })
            self.state.last_updated = time.time()
            self.state.last_updated_iso = time.strftime(
                '%Y-%m-%dT%H:%M:%S', time.localtime()
            )
            self.state.source_turn_id = source_turn_id
            self.state.proposed_by = proposed_by
            self._persist()
        return revisions

    def correct_field(self, field_name: str, new_value: Any,
                      decided_by: str = 'sir_manual') -> bool:
        """Sir CLI manual correction. Returns success."""
        if not hasattr(self.state, field_name):
            return False
        with self._lock:
            old = getattr(self.state, field_name)
            self.state.add_revision(
                field_name, old, new_value,
                why=f'manual correction by {decided_by}',
                evidence=[],
            )
            setattr(self.state, field_name, new_value)
            self.state.last_updated = time.time()
            self.state.last_updated_iso = time.strftime(
                '%Y-%m-%dT%H:%M:%S', time.localtime()
            )
            self.state.proposed_by = decided_by
            self._persist()
        return True

    def render_prompt_block(self, include_unspoken: bool = True) -> str:
        """Render [SIR'S MIND RIGHT NOW] block for _assemble_prompt.

        Skip if state stale or empty.
        Skip unspoken need if confidence < 0.4 (防止过度推断).
        """
        s = self.get_snapshot()
        if s.is_stale() or not s.has_meaningful_content():
            return ''
        lines = ['[SIR\'S MIND RIGHT NOW (my hypothesis, may be wrong)]']
        # task
        if s.current_task_hypothesis:
            lines.append(
                f"  [TASK] {s.current_task_hypothesis} (conf {s.task_confidence:.2f})"
            )
            if s.task_evidence:
                lines.append(f"      evidence: {', '.join(s.task_evidence[:3])}")
        # emotion
        if s.emotional_state and s.emotional_state != 'unknown':
            lines.append(
                f"  [EMOTION] {s.emotional_state} (conf {s.emotional_confidence:.2f})"
            )
        # needs (3 层)
        if s.surface_need or s.deeper_need or s.unspoken_need:
            lines.append('  [NEEDS]')
            _conf = s.need_layers_confidence or {}
            if s.surface_need:
                lines.append(
                    f"      surface ({_conf.get('surface', 0):.2f}): {s.surface_need[:80]}"
                )
            if s.deeper_need:
                lines.append(
                    f"      deeper  ({_conf.get('deeper', 0):.2f}): {s.deeper_need[:80]}"
                )
            if include_unspoken and s.unspoken_need and _conf.get('unspoken', 0) >= 0.4:
                lines.append(
                    f"      unspoken({_conf.get('unspoken', 0):.2f}): {s.unspoken_need[:80]}"
                )
        # relational
        if s.relational_temp and s.relational_temp != 'neutral':
            lines.append(f"  [RELATIONAL] temp = {s.relational_temp}")
        # how to use
        lines.append(
            '  [usage] Reference these in tone/depth. Surface need = answer literally. '
            'Deeper = consider but do not lecture. Unspoken (low conf) = subtle. '
            'These are MY hypothesis, not facts; if Sir corrects, defer to him.'
        )
        return '\n'.join(lines)

    def stats(self) -> dict:
        with self._lock:
            return {
                'has_state': self.state.has_meaningful_content(),
                'is_stale': self.state.is_stale(),
                'last_updated_iso': self.state.last_updated_iso,
                'proposed_by': self.state.proposed_by,
                'revisions_total': len(self.state.revision_history),
                'task_conf': self.state.task_confidence,
                'emotion': self.state.emotional_state,
                'relational_temp': self.state.relational_temp,
            }


# ============================================================
# Singleton
# ============================================================

_DEFAULT_STORE: Optional[SirMentalStateStore] = None
_LOCK = threading.Lock()


def get_default_store() -> SirMentalStateStore:
    global _DEFAULT_STORE
    with _LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = SirMentalStateStore()
        return _DEFAULT_STORE


def reset_default_store_for_test() -> None:
    global _DEFAULT_STORE
    with _LOCK:
        _DEFAULT_STORE = None


def render_prompt_block(include_unspoken: bool = True) -> str:
    """Public entry for _assemble_prompt."""
    try:
        return get_default_store().render_prompt_block(include_unspoken=include_unspoken)
    except Exception:
        return ''


def update_state(partial: dict, source_turn_id: str = '',
                  proposed_by: str = 'tom_reflector') -> List[dict]:
    """Public update entry for ToMReflector."""
    return get_default_store().update(partial, source_turn_id=source_turn_id,
                                       proposed_by=proposed_by)


# ============================================================
# ToM Reflector — LLM-driven hypothesis updater (post-turn)
# ============================================================

_TOM_REFLECTOR_PROMPT = """[ROLE] You are Jarvis's Theory of Mind reflector.

Sir just had a turn with Jarvis. Your job: update Jarvis's mental hypothesis
about Sir's current state. Read the evidence below, propose hypothesis updates.

[CURRENT TURN]
Sir said: "{sir_utterance}"
Jarvis replied: "{jarvis_reply}"
Turn time: {iso_now}

[CURRENT HYPOTHESIS (may be stale)]
{current_state}

[ADDITIONAL CONTEXT]
{context_summary}

[YOUR JOB]
Decide which fields to update. For each field you change, give the new value
and confidence. SKIP fields you can't confidently update.

Required output JSON ONLY (no markdown):
{{
  "current_task_hypothesis": "..." or null (skip),
  "task_confidence": 0.0-1.0,
  "task_evidence": ["..."],
  "emotional_state": "..." or null,
  "emotional_confidence": 0.0-1.0,
  "surface_need": "..." or null,
  "deeper_need": "..." or null,
  "unspoken_need": "..." or null,
  "need_layers_confidence": {{"surface": 0.95, "deeper": 0.7, "unspoken": 0.3}},
  "relational_temp": "warm" | "cool" | "playful" | "serious" | "tense" | "intimate" | "neutral" or null
}}

Rules:
- Use null (not "") to skip a field.
- task/emotion/needs/relational don't all need updating each turn.
- DEFAULT to NOT updating a field unless current turn provides clear evidence.
- unspoken_need: only set if confidence >= 0.4 AND clear pattern.
- Use [usage]: hypothesis is fallible — if Sir contradicts, the next turn we revise.
"""


class ToMReflector:
    """Async daemon. Per turn, LLM proposes Sir mental state update.

    Usage:
        reflector = ToMReflector(key_router=...)
        # at turn end:
        reflector.reflect_async(sir_utt, jarvis_reply, turn_id)
    """

    def __init__(self, key_router=None, store: Optional[SirMentalStateStore] = None):
        self.key_router = key_router
        self.store = store or get_default_store()
        self._lock = threading.Lock()
        self._stats = {
            'reflections_total': 0,
            'updates_total': 0,
            'llm_fail_count': 0,
        }

    def reflect_async(self, sir_utterance: str, jarvis_reply: str,
                       turn_id: str = '', context_summary: str = '') -> None:
        """Fire-and-forget: spawn thread to propose update."""
        if not sir_utterance or not jarvis_reply:
            return
        threading.Thread(
            target=self._reflect_sync,
            args=(sir_utterance, jarvis_reply, turn_id, context_summary),
            daemon=True,
            name=f'ToMReflector-{turn_id[:12]}',
        ).start()

    def _reflect_sync(self, sir_utterance: str, jarvis_reply: str,
                       turn_id: str = '', context_summary: str = '') -> None:
        try:
            self._reflect_impl(sir_utterance, jarvis_reply, turn_id, context_summary)
        except Exception:
            pass

    def _reflect_impl(self, sir_utterance: str, jarvis_reply: str,
                       turn_id: str, context_summary: str) -> None:
        # short-circuit: no key router → skip
        if self.key_router is None:
            return

        with self._lock:
            self._stats['reflections_total'] += 1

        current = self.store.get_snapshot()
        current_state_text = (
            f"  task: {current.current_task_hypothesis or '(none)'} "
            f"(conf {current.task_confidence:.2f})\n"
            f"  emotion: {current.emotional_state} "
            f"(conf {current.emotional_confidence:.2f})\n"
            f"  needs: surface='{current.surface_need or '(none)'}', "
            f"deeper='{current.deeper_need or '(none)'}', "
            f"unspoken='{current.unspoken_need or '(none)'}'\n"
            f"  relational_temp: {current.relational_temp}\n"
            f"  last_updated: {current.last_updated_iso}"
        )

        prompt = _TOM_REFLECTOR_PROMPT.format(
            sir_utterance=str(sir_utterance or '')[:300],
            jarvis_reply=str(jarvis_reply or '')[:400],
            iso_now=time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime()),
            current_state=current_state_text,
            context_summary=str(context_summary or '(no context)')[:300],
        )

        # LLM call
        try:
            from jarvis_utils import safe_openrouter_call
            okey, _label = self.key_router.get_openrouter_key(caller='tom_reflector')
            response = safe_openrouter_call(
                openrouter_key=okey,
                model='google/gemini-2.5-flash-preview-09-2025',
                prompt=prompt,
                max_tokens=600,
                temperature=0.2,
            )
        except Exception:
            with self._lock:
                self._stats['llm_fail_count'] += 1
            return

        # parse JSON
        try:
            txt = (response or '').strip()
            if txt.startswith('```'):
                lines = txt.split('\n')
                if len(lines) >= 3:
                    txt = '\n'.join(lines[1:-1])
            parsed = json.loads(txt)
            if not isinstance(parsed, dict):
                return
        except Exception:
            return

        # build update dict — drop nulls
        update = {}
        for key in ('current_task_hypothesis', 'emotional_state', 'surface_need',
                    'deeper_need', 'unspoken_need', 'relational_temp'):
            v = parsed.get(key)
            if v is not None and v != '' and v != 'null':
                update[key] = str(v)[:200]
        for key in ('task_confidence', 'emotional_confidence'):
            v = parsed.get(key)
            if v is not None:
                try:
                    update[key] = max(0.0, min(1.0, float(v)))
                except Exception:
                    pass
        if 'task_evidence' in parsed and isinstance(parsed['task_evidence'], list):
            update['task_evidence'] = [str(e)[:80] for e in parsed['task_evidence'][:3]]
        if 'need_layers_confidence' in parsed and isinstance(parsed['need_layers_confidence'], dict):
            _confs = {}
            for layer in ('surface', 'deeper', 'unspoken'):
                _v = parsed['need_layers_confidence'].get(layer)
                if _v is not None:
                    try:
                        _confs[layer] = max(0.0, min(1.0, float(_v)))
                    except Exception:
                        pass
            if _confs:
                update['need_layers_confidence'] = _confs

        if update:
            revisions = self.store.update(update, source_turn_id=turn_id,
                                            proposed_by='tom_reflector')
            with self._lock:
                self._stats['updates_total'] += len(revisions)
            try:
                from jarvis_utils import bg_log
                bg_log(
                    f"🧠 [ToMReflector] turn={turn_id[:16]} updated "
                    f"{len(revisions)} field(s): "
                    f"{', '.join(r['field'] for r in revisions[:4])}"
                )
            except Exception:
                pass

    def stats(self) -> dict:
        with self._lock:
            return dict(self._stats)


_DEFAULT_REFLECTOR: Optional[ToMReflector] = None


def get_default_reflector(key_router=None) -> ToMReflector:
    global _DEFAULT_REFLECTOR
    with _LOCK:
        if _DEFAULT_REFLECTOR is None:
            _DEFAULT_REFLECTOR = ToMReflector(key_router=key_router)
        return _DEFAULT_REFLECTOR


def reset_default_reflector_for_test() -> None:
    global _DEFAULT_REFLECTOR
    with _LOCK:
        _DEFAULT_REFLECTOR = None
