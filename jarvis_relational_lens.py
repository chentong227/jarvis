"""jarvis_relational_lens.py — 透镜 (Lens), 体(Body)→口(Voice) 的忠实投影.

体-P6 (2026-05-31). 详 docs/JARVIS_TRINITY_ARCHITECTURE.md §5/§6.

透镜 = 把高维关系流形(体)**忠实投影**成主脑(口)此刻需要的一小片 prompt。两重忠实:
- **相关性忠实**: 从当前语境节点做 spreading-activation → 选最相关连通子图 (不是固定 dump)。
- **形状忠实 (阻力)**: 显式保留高置信 active 立场 (stance) → Jarvis 自己的形状 survive,
  即使和 Sir 当下意愿分叉 (镜子 vs 老师)。

**准则 1 (TTFT)**: 纯 embedding 图遍历 + dict 查表, **无 LLM**, per-turn 廉价。
node 文本走 TTL 缓存 (默认 120s), 不每 turn 读 4 个 store。

集成 (体-P6 末步): main-brain `_assemble_prompt` 里 flag-gated 注入本 block
(`lens_inject_enabled`, 默认 0), Sir 真机 A/B 验证投影质量后再开。
"""

from __future__ import annotations

# [体-P6 / 2026-05-31] import safety net (JARVIS_PYTHON_STYLE §1)
import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import re  # noqa: F401
import time
import json  # noqa: F401
import threading
from typing import Dict, List, Optional, Callable, Any, Iterable

from jarvis_relational_manifold import (
    get_manifold, get_manifold_config, split_node_id,
    KIND_CONCERN, KIND_STANCE,
)

# node kind → 主脑可读的人话标签
_KIND_LABEL = {
    "thread": "open thread",
    "concern": "concern",
    "joke": "inside joke",
    "proto": "protocol",
    "mem": "memory",
    "stance": "my read",
    "entity": "entity",
    "topic": "topic",
}


def _log(msg: str) -> None:
    try:
        from jarvis_utils import bg_log
        bg_log(msg)
    except Exception:
        pass


class RelationalLens:
    """把体投影成主脑 prompt 的一小片 (相关性 + 形状 两重忠实)。"""

    def __init__(
        self,
        manifold=None,
        stance_store=None,
        text_provider: Optional[Callable[[], Dict[str, str]]] = None,
        *,
        text_ttl_s: float = 120.0,
    ):
        self.manifold = manifold if manifold is not None else get_manifold()
        self._stance_store = stance_store  # lazy
        self._text_provider = text_provider
        self._text_cache: Dict[str, str] = {}
        self._text_cache_ts = 0.0
        self._text_ttl = float(text_ttl_s)
        self._lock = threading.RLock()

    @property
    def stance(self):
        if self._stance_store is None:
            try:
                from jarvis_stance import get_stance_store
                self._stance_store = get_stance_store()
            except Exception:
                self._stance_store = False  # 标记不可用
        return self._stance_store or None

    # ---- node 文本 (TTL 缓存, 不每 turn 读盘) ----
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
                _log(f"[Lens] node text harvest failed ({exc!r})")
                self._text_cache = self._text_cache or {}
            self._text_cache_ts = now
            return self._text_cache

    # ---- 默认 seeds: 体此刻势能焦点 (③ 体→口) → 退回 concern + 高度数 hub ----
    def default_seeds(self, *, limit: int = 6) -> List[str]:
        # 优先: 体势能焦点 (口投影体此刻被激活的区, 非固定 dump)。
        # 仅 prod 模式 (无注入 text_provider) 用全局体焦点; 注入模式(测试)走下方 fallback 保隔离。
        if self._text_provider is None:
            try:
                from jarvis_body_focus import get_body_focus
                seeds = get_body_focus().focus_seeds(limit=limit)
                if seeds:
                    return seeds
            except Exception:
                pass
        # 退回: concern + 高度数 hub
        text_map = self._node_text_map()
        concerns = [n for n in text_map if split_node_id(n)[0] == KIND_CONCERN]
        ranked = sorted(text_map.keys(), key=lambda n: self.manifold.degree(n), reverse=True)
        seeds = []
        for n in concerns + ranked:
            if n not in seeds:
                seeds.append(n)
            if len(seeds) >= limit:
                break
        return seeds

    # ---- 核心: 投影 ----
    def project(
        self, seeds: Optional[Iterable[str]] = None, *,
        max_nodes: int = 10, max_chars: int = 900, hops: int = 2,
        min_activation: float = 0.08, stance_min_conf: float = 0.5,
        now: Optional[float] = None,
    ) -> str:
        """投影成 prompt block (无内容则返 "")。

        relevance: spreading-activation 选相关子图; shape: 显式保留高置信立场。
        """
        now = time.time() if now is None else now
        seeds = list(seeds) if seeds else self.default_seeds()
        seed_set = set(seeds)
        text_map = self._node_text_map()

        # 相关性: 激活扩散 (排除 seed 本身, 主脑已有当前语境)
        relevant: List[tuple] = []
        if seeds:
            activation = self.manifold.spread(
                seeds, hops=hops, min_activation=min_activation, now=now)
            for nid, score in activation.items():
                if nid in seed_set or nid not in text_map:
                    continue
                if split_node_id(nid)[0] == KIND_STANCE:
                    continue  # 立场走形状段, 不混进相关段
                relevant.append((nid, score))
            relevant.sort(key=lambda x: x[1], reverse=True)

        # 形状 (阻力): 高置信 active 立场, 永远尝试保留
        stances = []
        if self.stance is not None:
            try:
                stances = self.stance.list_for_lens(min_confidence=stance_min_conf)
            except Exception:
                stances = []

        if not relevant and not stances:
            return ""

        lines: List[str] = ["=== RELATIONAL CONTEXT (体/Lens, grounded) ==="]
        budget = max_chars - len(lines[0])

        if relevant:
            lines.append("What connects to the present:")
            for nid, score in relevant[:max_nodes]:
                kind = split_node_id(nid)[0]
                label = _KIND_LABEL.get(kind, kind)
                txt = (text_map.get(nid) or "").strip().replace("\n", " ")
                if not txt:
                    continue
                row = f"  - [{label}] {txt[:120]}"
                if budget - len(row) < 0:
                    break
                lines.append(row)
                budget -= len(row)

        if stances:
            lines.append("My read (stance — hold unless Sir overrides):")
            for s in stances:
                claim = (s.get("claim") or "").strip().replace("\n", " ")
                row = f"  - {claim[:140]}"
                if budget - len(row) < 0:
                    break
                lines.append(row)
                budget -= len(row)

        lines.append("=== END RELATIONAL CONTEXT ===")
        if len(lines) <= 2:  # 只有头尾, 没实质内容
            return ""
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 模块单例 + 便捷入口 (main-brain 集成调这个)
# ---------------------------------------------------------------------------

_SINGLETON: Optional[RelationalLens] = None
_SINGLETON_LOCK = threading.Lock()


def get_lens() -> RelationalLens:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = RelationalLens()
    return _SINGLETON


def lens_inject_enabled() -> bool:
    """flag-gated: 默认 0 (Sir 真机验投影质量后, 改 vocab 开)。"""
    try:
        return bool(int(get_manifold_config().get("lens_inject_enabled", 0)))
    except Exception:
        return False


def build_lens_block(seeds: Optional[Iterable[str]] = None, **kw) -> str:
    """main-brain `_assemble_prompt` 调: 返回投影 block (gate 关 → "")。故障静默。"""
    if not lens_inject_enabled():
        return ""
    try:
        return get_lens().project(seeds, **kw)
    except Exception as exc:
        _log(f"[Lens] project failed ({exc!r})")
        return ""
