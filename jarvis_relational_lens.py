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
import collections
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
        # 口识体-A: 本轮投影过哪些 stance (turn_id → {ts, stance_ids}). 闭学习环后半
        # 的接线点 — Sir 反应回来时据 turn_id 取回投影过的 stance reinforce/weaken。
        # 有界 + TTL 对齐 meta_feedback reaction 窗口 (30 min), 纯 in-memory (准则 1)。
        self._projected: "collections.OrderedDict[str, Dict[str, Any]]" = (
            collections.OrderedDict())
        self._projected_cap = 128
        self._projected_ttl = 1800.0

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
        turn_id: Optional[str] = None,
        max_nodes: int = 10, max_chars: int = 900, hops: int = 2,
        min_activation: float = 0.08, stance_min_conf: float = 0.5,
        now: Optional[float] = None,
    ) -> str:
        """投影成 prompt block (无内容则返 "")。

        relevance: spreading-activation 选相关子图; shape: 显式保留高置信立场。

        turn_id (口识体-A): 给定则记录本轮投影过的 stance_id → Sir 反应回来时
        apply_reaction_outcome(turn_id, ...) 据此 reinforce/weaken (闭学习环后半)。
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

        projected_sids: List[str] = []
        if stances:
            lines.append("My read (stance — hold unless Sir overrides):")
            for s in stances:
                claim = (s.get("claim") or "").strip().replace("\n", " ")
                row = f"  - {claim[:140]}"
                if budget - len(row) < 0:
                    break
                lines.append(row)
                budget -= len(row)
                sid = s.get("stance_id")
                if sid:
                    projected_sids.append(sid)

        lines.append("=== END RELATIONAL CONTEXT ===")
        if len(lines) <= 2:  # 只有头尾, 没实质内容
            return ""
        # 口识体-A: 记录本轮真正投影进 prompt 的 stance (只记进了的, 没进的不算
        # "被投影" → 不归因 outcome)。无 turn_id 不记 (mirror/某些路径 turn 缺失)。
        if turn_id and projected_sids:
            self.record_projected_stances(turn_id, projected_sids, now=now)
        return "\n".join(lines)

    # ---- 口识体-A: outcome→stance (闭学习环后半) ----
    def record_projected_stances(
        self, turn_id: str, stance_ids: Iterable[str], *,
        now: Optional[float] = None,
    ) -> None:
        """记本轮投影过的 stance_id (turn_id → ids), 有界 + LRU 淘汰。"""
        ids = [s for s in dict.fromkeys(stance_ids) if s]
        if not turn_id or not ids:
            return
        now = time.time() if now is None else now
        with self._lock:
            self._projected[turn_id] = {"ts": now, "stance_ids": ids}
            self._projected.move_to_end(turn_id)
            while len(self._projected) > self._projected_cap:
                self._projected.popitem(last=False)

    def projected_stances_for(
        self, turn_id: str, *, now: Optional[float] = None,
    ) -> List[str]:
        """取回某 turn 投影过的 stance_id (超 TTL 视为过期返 [])。"""
        if not turn_id:
            return []
        now = time.time() if now is None else now
        with self._lock:
            rec = self._projected.get(turn_id)
            if not rec or (now - rec["ts"]) > self._projected_ttl:
                return []
            return list(rec["stance_ids"])

    def apply_reaction_outcome(
        self, turn_id: str, reaction: str, *, stance_store=None,
        engaged_delta: float = 0.1, rejected_delta: float = 0.15,
        now: Optional[float] = None,
    ) -> int:
        """Sir 对回复的反应 → reinforce/weaken 当轮投影过的 stance (闭学习环后半)。

        engaged → reinforce(+engaged_delta, evidence_kind='outcome', ref=turn_id);
        rejected → weaken(rejected_delta, 跌破 0.15 自动转 review);
        其它 (ignored/未知) → no-op (太弱/歧义不动 stance, 同 inner_voice ignored 语义)。

        幂等: apply 后 consume 该 turn 记录, 同 turn 被 mark 两次不二次改。
        返回更新的 stance 数。失败非致命。
        """
        reaction = (reaction or "").strip().lower()
        if reaction not in ("engaged", "rejected"):
            return 0
        sids = self.projected_stances_for(turn_id, now=now)
        if not sids:
            return 0
        store = stance_store if stance_store is not None else self.stance
        if store is None:
            return 0
        updated = 0
        for sid in sids:
            try:
                if reaction == "engaged":
                    ok = store.reinforce(
                        sid, evidence_kind="outcome", evidence_ref=turn_id,
                        detail="sir engaged with reply", delta=engaged_delta,
                        now=now)
                else:
                    ok = store.weaken(
                        sid, delta=rejected_delta,
                        reason=f"sir rejected (turn={turn_id})", now=now)
                if ok:
                    updated += 1
            except Exception as exc:
                _log(f"[Lens] apply_reaction_outcome failed sid={sid} ({exc!r})")
        with self._lock:  # consume → 幂等
            self._projected.pop(turn_id, None)
        if updated:
            verb = "reinforced" if reaction == "engaged" else "weakened"
            _log(f"[Lens/口识体-A] outcome={reaction} → {updated} stance {verb} "
                 f"(turn={turn_id})")
        return updated


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


def reset_lens_for_test(lens: Optional[RelationalLens] = None) -> None:
    """test 隔离: 替换/清空 lens 单例 (同 reset_stance_store_for_test 风格)。"""
    global _SINGLETON
    _SINGLETON = lens


def lens_inject_enabled() -> bool:
    """flag-gated: 默认 0 (Sir 真机验投影质量后, 改 vocab 开)。"""
    try:
        return bool(int(get_manifold_config().get("lens_inject_enabled", 0)))
    except Exception:
        return False


def body_claim_evidence(query: str, *, max_items: int = 8,
                        stance_min_conf: float = 0.4) -> List[Dict[str, str]]:
    """口识体-B: 体作 evidence 源 — 返回可能支持 query(claim) 的体证据 (验证环穿体)。

    给 ClaimTracer `body_evidence_provider` 用: 关系类 claim 对体审一致。证据来自:
      - active stance (Jarvis 接地的关系判断, conf>=阈值)
      - 体节点文本 (concern/thread/joke/protocol — 关系结构里的接地事实, 词重叠预筛)
    返回 list[{source, content}]; 失败返 [] (故障开放, 老行为零变化)。准则 5: 每条全接地。

    注: 不受 lens_inject_enabled gate (那只管投影进 prompt; 本函数是只读验证, 仅
    unverified claim 罕触发, 不碰 TTFT)。
    """
    out: List[Dict[str, str]] = []
    try:
        from jarvis_stance import get_stance_store, STATE_ACTIVE
        for s in get_stance_store().list(STATE_ACTIVE):
            try:
                if float(s.get("confidence", 0.0)) >= stance_min_conf:
                    out.append({"source": f"stance:{s.get('stance_id', '')}",
                                "content": str(s.get("claim", ""))})
            except Exception:
                continue
    except Exception:
        pass
    try:
        qwords = {w for w in re.findall(r"\w+", (query or "").lower()) if len(w) >= 2}
        if qwords:
            texts = get_lens()._node_text_map()
            scored: List[tuple] = []
            for nid, txt in texts.items():
                tw = set(re.findall(r"\w+", (txt or "").lower()))
                ov = len(qwords & tw)
                if ov >= 1:
                    scored.append((ov, nid, txt))
            scored.sort(key=lambda x: x[0], reverse=True)
            for _, nid, txt in scored[:max_items]:
                out.append({"source": nid, "content": str(txt)})
    except Exception:
        pass
    return out[: max_items * 2]


def build_lens_block(seeds: Optional[Iterable[str]] = None, *,
                     turn_id: Optional[str] = None, **kw) -> str:
    """main-brain `_assemble_prompt` 调: 返回投影 block (gate 关 → "")。故障静默。

    turn_id 透传给 project → 记录本轮投影 stance (口识体-A 闭学习环后半接线点)。
    """
    if not lens_inject_enabled():
        return ""
    try:
        return get_lens().project(seeds, turn_id=turn_id, **kw)
    except Exception as exc:
        _log(f"[Lens] project failed ({exc!r})")
        return ""
