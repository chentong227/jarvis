"""jarvis_stance.py — 立场 (Stance), 体(Body)里 Jarvis 自己的接地 view.

体-P4 (2026-05-31). 详 docs/JARVIS_TRINITY_ARCHITECTURE.md §3 (立场) + §6 (两重忠实).

**立场 = Jarvis 自己对 Sir / 关系 / 什么对 Sir 好 的累积观点**, 独立于 profile:
- profile.json = **Sir 的** (Sir 是谁 / Sir 的事实)。
- stance.json = **Jarvis 的** (Jarvis 怎么看 Sir / Jarvis 学到了什么 / Jarvis 的判断)。

立场是"阻力 / 老师感"的载体 (§6 形状忠实): 透镜 (体-P6) 投影时**显式保留**高置信 active
立场 → 即使和 Sir 当下意愿分叉, Jarvis 的形状也 survive (镜子 vs 老师)。

**接地红线 (言出必行)**: 每条立场必带 evidence (thought/outcome/turn trace), 无 evidence =
幻觉, 拒。识 (思考脑) propose 立场默认 state='review' (propose-not-trust); outcome 闭环
reinforce/weaken; **Sir 元否决权 (准则 7)**: Sir CLI 可 confirm / retire / revert 任何立场。
"""

from __future__ import annotations

# [体-P4 / 2026-05-31] import safety net (JARVIS_PYTHON_STYLE §1)
import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import re  # noqa: F401
import time
import json
import secrets
import threading
import collections  # noqa: F401
from typing import Dict, List, Optional, Any

STATE_ACTIVE = "active"
STATE_REVIEW = "review"
STATE_RETIRED = "retired"

_MAX_EVIDENCE = 16


def _log(msg: str) -> None:
    try:
        from jarvis_utils import bg_log
        bg_log(msg)
    except Exception:
        pass


class StanceStore:
    """Jarvis 立场 store。接地 (每条带 evidence) + 三态 (active/review/retired) + Sir 可否决。"""

    _DEFAULT_PATH = os.path.join("memory_pool", "stance.json")

    def __init__(self, path: Optional[str] = None):
        self.path = path or self._DEFAULT_PATH
        self._lock = threading.RLock()
        self._stances: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ---- persistence ----
    def _load(self) -> None:
        with self._lock:
            self._stances = {}
            if not os.path.exists(self.path):
                return
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                st = data.get("stances", {}) if isinstance(data, dict) else {}
                if isinstance(st, dict):
                    self._stances = {k: v for k, v in st.items() if isinstance(v, dict)}
            except Exception as exc:
                _log(f"[Stance] load failed ({exc!r}) — starting empty")
                self._stances = {}

    def save(self) -> None:
        with self._lock:
            payload = {
                "_meta": {
                    "schema": "stance",
                    "schema_version": 1,
                    "purpose": "Jarvis 自己对 Sir/关系的接地 view (体-P4); 阻力/老师感载体",
                    "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "count": len(self._stances),
                    "edit_via": "scripts/stance_dump.py",
                },
                "stances": self._stances,
            }
            tmp = self.path + ".tmp"
            try:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            except Exception as exc:
                _log(f"[Stance] save failed ({exc!r})")

    # ---- mutate ----
    def add_stance(
        self, claim: str, about: str, *,
        evidence_kind: str, evidence_ref: str, detail: str = "",
        confidence: float = 0.5, source: str = "inner_thought",
        state: str = STATE_REVIEW, now: Optional[float] = None,
    ) -> Optional[str]:
        """新增一条立场。**接地红线**: evidence_ref 必填, 否则拒 (返回 None)。

        识 propose 默认 state='review' (propose-not-trust); Sir confirm 后转 active。
        """
        claim = (claim or "").strip()
        if not claim or not evidence_ref:
            if not evidence_ref:
                _log(f"[Stance] REJECT ungrounded stance ({claim[:40]!r}) — no evidence_ref")
            return None
        now = time.time() if now is None else now
        sid = f"stance_{time.strftime('%Y%m%d_%H%M%S', time.localtime(now))}_{secrets.token_hex(2)}"
        with self._lock:
            self._stances[sid] = {
                "stance_id": sid,
                "claim": claim[:400],
                "about": (about or "").strip()[:80],
                "confidence": max(0.0, min(1.0, float(confidence))),
                "state": state if state in (STATE_ACTIVE, STATE_REVIEW) else STATE_REVIEW,
                "source": source,
                "evidence": [{"kind": evidence_kind, "ref": evidence_ref,
                              "detail": detail[:200], "ts": now}],
                "created_ts": now,
                "created_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
                "last_reinforced_ts": now,
                "reinforce_count": 1,
                "sir_reverted": False,
            }
            self.save()
        return sid

    def _find(self, stance_id: str) -> Optional[str]:
        if stance_id in self._stances:
            return stance_id
        for sid in self._stances:
            if sid.startswith(stance_id):
                return sid
        return None

    def reinforce(
        self, stance_id: str, *, evidence_kind: str, evidence_ref: str,
        detail: str = "", delta: float = 0.1, now: Optional[float] = None,
    ) -> bool:
        """outcome 闭环强化立场 (置信上调 + 加 evidence)。接地: evidence_ref 必填。"""
        if not evidence_ref:
            return False
        now = time.time() if now is None else now
        with self._lock:
            sid = self._find(stance_id)
            if not sid:
                return False
            s = self._stances[sid]
            s["confidence"] = max(0.0, min(1.0, float(s.get("confidence", 0.5)) + delta))
            s["last_reinforced_ts"] = now
            s["reinforce_count"] = int(s.get("reinforce_count", 0)) + 1
            ev = s.setdefault("evidence", [])
            ev.append({"kind": evidence_kind, "ref": evidence_ref,
                       "detail": detail[:200], "ts": now})
            if len(ev) > _MAX_EVIDENCE:
                del ev[: len(ev) - _MAX_EVIDENCE]
            self.save()
        return True

    def weaken(self, stance_id: str, *, delta: float = 0.15, reason: str = "",
               now: Optional[float] = None) -> bool:
        """outcome 反例削弱立场; 置信跌破 0.15 自动转 review。"""
        now = time.time() if now is None else now
        with self._lock:
            sid = self._find(stance_id)
            if not sid:
                return False
            s = self._stances[sid]
            s["confidence"] = max(0.0, float(s.get("confidence", 0.5)) - delta)
            if reason:
                s["last_weaken_reason"] = reason[:200]
            if s["confidence"] < 0.15 and s.get("state") == STATE_ACTIVE:
                s["state"] = STATE_REVIEW
            self.save()
        return True

    def set_state(self, stance_id: str, state: str, *, source: str = "sir") -> bool:
        if state not in (STATE_ACTIVE, STATE_REVIEW, STATE_RETIRED):
            return False
        with self._lock:
            sid = self._find(stance_id)
            if not sid:
                return False
            s = self._stances[sid]
            s["state"] = state
            s["last_state_source"] = source
            if source.startswith("sir"):
                s["sir_reverted"] = (state == STATE_RETIRED)
            self.save()
        return True

    def confirm(self, stance_id: str, *, confidence: float = 0.85) -> bool:
        """Sir 拍板确认 (准则 7): → active + 高置信 + source=sir_confirmed。"""
        with self._lock:
            sid = self._find(stance_id)
            if not sid:
                return False
            s = self._stances[sid]
            s["state"] = STATE_ACTIVE
            s["source"] = "sir_confirmed"
            s["confidence"] = max(float(s.get("confidence", 0.5)), confidence)
            self.save()
        return True

    def retire(self, stance_id: str, *, reason: str = "") -> bool:
        return self.set_state(stance_id, STATE_RETIRED, source="sir") and \
            self._tag_reason(stance_id, reason)

    def _tag_reason(self, stance_id: str, reason: str) -> bool:
        if not reason:
            return True
        with self._lock:
            sid = self._find(stance_id)
            if sid:
                self._stances[sid]["retire_reason"] = reason[:200]
                self.save()
        return True

    # ---- query ----
    def get(self, stance_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            sid = self._find(stance_id)
            return dict(self._stances[sid]) if sid else None

    def list(self, state: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            out = [dict(s) for s in self._stances.values()
                   if state is None or s.get("state") == state]
        out.sort(key=lambda s: float(s.get("confidence", 0)), reverse=True)
        return out

    def list_for_lens(self, *, min_confidence: float = 0.5,
                      limit: int = 8) -> List[Dict[str, Any]]:
        """透镜 (体-P6) 用: 高置信 active 立场 (Jarvis 形状, 投影时保留)。"""
        rows = [s for s in self.list(STATE_ACTIVE)
                if float(s.get("confidence", 0)) >= min_confidence]
        return rows[:limit]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            by_state = collections.Counter(s.get("state") for s in self._stances.values())
        return {"total": len(self._stances), "by_state": dict(by_state)}


_SINGLETON: Optional[StanceStore] = None
_SINGLETON_LOCK = threading.Lock()


def get_stance_store() -> StanceStore:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = StanceStore()
    return _SINGLETON


def reset_stance_store_for_test(store: Optional[StanceStore] = None) -> None:
    global _SINGLETON
    _SINGLETON = store
