"""jarvis_body_focus.py — current_focus 桥: 体此刻"哪里有势能" (口/识 共读).

口识体-B (2026-05-31). 详 docs/JARVIS_VOICE_AND_MIND_REFACTOR.md §1/§5.

势能自转的"注意力指针": 读体势能 (Weaver 写的 body_energy.json: recent_deltas + top_energy)
+ 流形邻居 → 给出"体此刻最该被注意的几个节点" + 上下文。
- **识** 用它 attend (想体的高势能区, 非凭空)。
- **口** 用它当透镜 seeds (投影体此刻被激活的区)。
单一真相源, 避免识/口 各算一套 (DRY)。无 LLM, 纯读 + 图遍历 (准则 1)。
"""

from __future__ import annotations

import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import time
import json
import threading
from typing import Dict, List, Optional, Callable, Any

from jarvis_relational_manifold import get_manifold, split_node_id

_KIND_LABEL = {
    "thread": "open thread", "concern": "concern", "joke": "inside joke",
    "proto": "protocol", "mem": "memory", "stance": "my read",
    "entity": "entity", "topic": "topic",
}
_DELTA_VERB = {"tension": "unresolved tension", "novelty": "new connection",
               "drift": "shifting"}


def _log(msg: str) -> None:
    try:
        from jarvis_utils import bg_log
        bg_log(msg)
    except Exception:
        pass


class BodyFocus:
    """体注意力指针: 合并"刚升起的 delta" + "标高能量" → 当前焦点。"""

    def __init__(
        self, manifold=None, energy_path: Optional[str] = None,
        text_provider: Optional[Callable[[], Dict[str, str]]] = None,
        *, text_ttl_s: float = 120.0,
    ):
        self.manifold = manifold if manifold is not None else get_manifold()
        self.energy_path = energy_path or os.path.join("memory_pool", "body_energy.json")
        self._text_provider = text_provider
        self._text_cache: Dict[str, str] = {}
        self._text_cache_ts = 0.0
        self._text_ttl = float(text_ttl_s)
        self._lock = threading.RLock()

    # ---- node 文本 (TTL 缓存, 复用 Weaver harvest) ----
    def _node_text_map(self) -> Dict[str, str]:
        if self._text_provider is not None:
            return self._text_provider()
        now = time.time()
        with self._lock:
            if self._text_cache and (now - self._text_cache_ts) < self._text_ttl:
                return self._text_cache
            try:
                from jarvis_relational_weaver import RelationalWeaver
                self._text_cache = RelationalWeaver(manifold=self.manifold).harvest_nodes()
            except Exception as exc:
                _log(f"[BodyFocus] harvest failed ({exc!r})")
                self._text_cache = self._text_cache or {}
            self._text_cache_ts = now
            return self._text_cache

    def _read_energy(self) -> Dict[str, Any]:
        try:
            if os.path.exists(self.energy_path):
                with open(self.energy_path, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
        except Exception:
            pass
        return {}

    # ---- 当前焦点 ----
    def current_focus(self, *, limit: int = 6) -> List[Dict[str, Any]]:
        """返回体此刻最该注意的节点 [{node, kind, why, score, text}]。

        合并: recent_deltas (刚升起, 高优先) + top_energy (标高能量)。
        """
        data = self._read_energy()
        text_map = self._node_text_map()
        seen: set = set()
        items: List[Dict[str, Any]] = []

        # 1) 刚升起的 delta (最该立刻 attend)
        for d in (data.get("recent_deltas") or []):
            nid = d.get("node")
            if not nid or nid in seen:
                continue
            seen.add(nid)
            items.append({
                "node": nid, "kind": d.get("kind", ""),
                "why": _DELTA_VERB.get(d.get("kind", ""), d.get("kind", "")),
                "score": float(d.get("magnitude", 0.0)) + 1.0,  # delta 优先于 standing
                "fresh": True, "text": (text_map.get(nid) or "").strip(),
            })

        # 2) standing 高能量 (持续值得关注但没新 delta)
        for e in (data.get("top_energy") or []):
            nid = e.get("node")
            if not nid or nid in seen:
                continue
            seen.add(nid)
            comp = max((("tension", e.get("tension", 0.0)),
                        ("novelty", e.get("novelty", 0.0)),
                        ("drift", e.get("drift", 0.0))), key=lambda x: x[1])
            items.append({
                "node": nid, "kind": comp[0], "why": _DELTA_VERB.get(comp[0], comp[0]),
                "score": float(e.get("total", 0.0)), "fresh": False,
                "text": (text_map.get(nid) or "").strip(),
            })

        items.sort(key=lambda x: x["score"], reverse=True)
        return items[:limit]

    def focus_seeds(self, *, limit: int = 6) -> List[str]:
        """焦点节点 id (透镜 seeds / 识 attend 用)。"""
        return [it["node"] for it in self.current_focus(limit=limit)]

    def has_fresh_delta(self, *, min_magnitude: float = 0.0) -> bool:
        """是否有刚升起的 delta (识"该不该醒"的信号)。"""
        data = self._read_energy()
        for d in (data.get("recent_deltas") or []):
            if float(d.get("magnitude", 0.0)) >= min_magnitude:
                return True
        return False

    def render_attention_block(self, *, limit: int = 5, max_chars: int = 600) -> str:
        """给识的"体注意力"prompt 块: 体此刻哪里有势能 (grounded, 让识 attend 非凭空)。"""
        focus = self.current_focus(limit=limit)
        if not focus:
            return ""
        lines = ["=== BODY SIGNALS (体势能, attend these — not free association) ==="]
        budget = max_chars - len(lines[0])
        for it in focus:
            kind, raw = split_node_id(it["node"])
            label = _KIND_LABEL.get(kind, kind)
            txt = (it["text"] or "").replace("\n", " ")[:90]
            tag = "↑NEW" if it.get("fresh") else "·"
            row = f"  {tag} [{label}/{it['why']}] {txt}" if txt else f"  {tag} [{label}/{it['why']}]"
            if budget - len(row) < 0:
                break
            lines.append(row)
            budget -= len(row)
        lines.append("=== END BODY SIGNALS ===")
        if len(lines) <= 2:
            return ""
        return "\n".join(lines)


_SINGLETON: Optional[BodyFocus] = None
_SINGLETON_LOCK = threading.Lock()


def get_body_focus() -> BodyFocus:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = BodyFocus()
    return _SINGLETON
