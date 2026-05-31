"""jarvis_relational_manifold.py — 体 (Body) 的边层 / Relational Manifold edge store.

体-P1 边接地 (2026-05-31). 详 docs/JARVIS_TRINITY_ARCHITECTURE.md.

这是"体"(三位一体里和口/识同级的第三器官)的最底层地基: **交叉引用的图**。
- **点 (nodes)**: 不在这里重存 (准则 6 #4)。节点是命名空间 id (`kind:raw_id`),
  指回各自的真理源 store (hippocampus / concerns / relational / self_threads / notes)。
- **边 (edges)**: 节点之间的关系, 由几何 (embedding, 体-P2) + 结构 (共现/引用/共享, 本文件)
  造出, Hebbian 反复强化 + 时间衰减。
- **接地红线 (言出必行)**: 每条边必带 provenance (怎么造的 + trace ref),
  无 ref 的边 = 幻觉, 拒绝写入。LLM 推断边 (体-P4) propose-not-trust, 标 inferred + review。

本文件只做边层 (P1)。面 (surfaces) / 立场 (stance) / 织网者 (Weaver) / 透镜 (Lens) 是后续阶段。
"""

from __future__ import annotations

# [体-P1 / 2026-05-31] import safety net (JARVIS_PYTHON_STYLE §1)
import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import re  # noqa: F401
import time
import json
import math
import threading
import collections  # noqa: F401
from typing import Dict, List, Optional, Tuple, Iterable, Any

# ---------------------------------------------------------------------------
# Node id namespace — 体只引用, 不重存 (准则 6 #4)
# ---------------------------------------------------------------------------

KIND_THREAD = "thread"      # self_threads.json: thought_YYYYMMDD_...
KIND_CONCERN = "concern"    # concerns.json: sir_sleep_streak ...
KIND_JOKE = "joke"          # relational_state.json: joke_YYYYMMDD_...
KIND_PROTOCOL = "proto"     # relational_state.json: proto_YYYYMMDD_...
KIND_MEMORY = "mem"         # hippocampus 记忆 id
KIND_ENTITY = "entity"      # 实体 (人/物/项目)
KIND_TOPIC = "topic"        # 话题 tag
KIND_STANCE = "stance"      # 立场 (体-P4): Jarvis 自己对 Sir/关系的接地 view

_KNOWN_KINDS = frozenset({
    KIND_THREAD, KIND_CONCERN, KIND_JOKE, KIND_PROTOCOL,
    KIND_MEMORY, KIND_ENTITY, KIND_TOPIC, KIND_STANCE,
})

# Edge provenance kinds (= 边怎么造出来的)
PROV_COOCCUR = "cooccur"    # 同 turn/session 一起出现
PROV_SAID = "said"          # Sir 一句话显式把两者连起
PROV_SHARED = "shared"      # 共享实体 / concern
PROV_EMBED = "embed"        # embedding cosine (体-P2)
PROV_INFERRED = "inferred"  # LLM 推断 (体-P4, propose-not-trust)

_NODE_SEP = ":"
_KEY_SEP = "\u241f"  # SYMBOL FOR UNIT SEPARATOR — 不会出现在任何 node id 里


def make_node_id(kind: str, raw_id: str) -> str:
    """组命名空间节点 id。kind 必须是已知类型。raw_id 指回真理源 store。"""
    kind = (kind or "").strip()
    raw_id = (raw_id or "").strip()
    if not kind or not raw_id:
        raise ValueError("make_node_id: kind 和 raw_id 都不能为空")
    if _NODE_SEP in kind or _KEY_SEP in raw_id:
        raise ValueError(f"make_node_id: 非法字符 in {kind!r}/{raw_id!r}")
    return f"{kind}{_NODE_SEP}{raw_id}"


def split_node_id(node_id: str) -> Tuple[str, str]:
    """拆命名空间节点 id → (kind, raw_id)。"""
    if _NODE_SEP not in node_id:
        return ("", node_id)
    kind, raw = node_id.split(_NODE_SEP, 1)
    return (kind, raw)


# ---------------------------------------------------------------------------
# Config — 准则 6 持久化 (seed 默认 + json override, mtime cache)
# ---------------------------------------------------------------------------

_SEED_MANIFOLD_CONFIG: Dict[str, Any] = {
    # 每种 provenance 一次 observe 给边加多少 weight (Hebbian 增量)
    "weight_increment": {
        PROV_COOCCUR: 0.30,   # 共现弱关联
        PROV_SAID: 1.00,      # Sir 显式连接 = 强信号
        PROV_SHARED: 0.50,    # 共享实体
        PROV_EMBED: 0.60,     # 几何相似 (实际 = increment * cosine, 体-P2)
        PROV_INFERRED: 0.40,  # LLM 推断 (实际 = increment * confidence)
    },
    "weight_cap": 6.0,                 # 单边 weight 上限 (防无限增长)
    "half_life_days": 14.0,            # 关系边半衰期 (慢衰, 关系比事实持久)
    "prune_floor": 0.05,               # 衰减后低于此 → prune
    "max_provenance_per_edge": 12,     # 每边最多留几条溯源 (留最近的)
    "neighbor_default_limit": 24,      # neighbors() 默认返回上限
    # 几何边 (体-P2, embedding cosine) — 注意: 相似度是"静态属性"非"事件流",
    # 故 weaver 用 accumulate=False (set-to-floor, 不 Hebbian 累加, 防重复 weave 膨胀)
    "embed_threshold": 0.72,           # cosine >= 阈值才连 embed 边
    "embed_top_k_per_node": 8,         # 每节点最多保留 K 条最强 embed 边 (防稠密图)
    "merge_threshold": 0.90,           # cosine >= 此 = 近重复 → 合并 alias (口识体-D2 防 bloat)
    # 面 (体-P3) — 语义曲面 = 图里强连通的节点社区
    "surface_min_weight": 0.45,        # 边有效权重 >= 此值才算"紧"连接 (聚面用)
    "surface_min_size": 3,             # 面最小节点数 (< 此不算一个面)
    # 透镜 (体-P6) — 投影主脑. 默认 0 (Sir 真机验投影质量后再开, 动主脑热路径)
    "lens_inject_enabled": 0,
    # 口识体-E (内敛): 透镜活时替 SOUL Layer2/3 平行表示 (默认 0, 渐进退旧块).
    # Sir 真机 A/B 验投影质量满意后改 vocab 开 → Layer2/3 由体/lens 供, 删平行 (准则6#4)。
    # 逐块退: 先 lens_inject_enabled=1 加投影看质量, 满意再 replaces_layer2/3=1 退旧。
    "lens_replaces_layer2": 0,
    "lens_replaces_layer3": 0,
    # 织网者 Weaver (体-P5) — 后台慢工节奏
    "weaver": {
        "weave_interval_s": 600,       # daemon 两次全量 weave 间隔 (慢工, 不抢 TTFT)
        "initial_delay_s": 90,         # 启动后等多久才第一次 weave (让 boot 先稳定)
        "decay_every_n_weaves": 6,     # 每 N 次 weave 做一次 decay+prune
        "max_text_chars": 400,         # embed 前截断节点文本
        "min_node_text_chars": 4,      # 太短文本不 embed
        "embed_batch_size": 32,        # 批量 embed 上限
    },
    # 体势能 E (口识体-B3) — 自转的坡度. 详 docs/JARVIS_VOICE_AND_MIND_REFACTOR.md §2.
    # 接地无 LLM: novelty(新边) + drift(边权变) + tension(高severity concern 无 stance 覆盖)
    "energy": {
        "w_novelty": 1.0,              # 新颖权重 (新形成的强边)
        "w_drift": 0.6,                # 漂移权重 (边权在变)
        "w_tension": 1.2,              # 张力权重 (未化解 = 最该想)
        "delta_threshold": 0.30,       # 节点能量上升超此 → 派 body_delta (唤醒识)
        "tension_severity_min": 0.40,  # concern severity >= 此且无 stance 覆盖 = 张力
        "drift_min": 0.05,             # 边权变化超此才算 drift
        "max_deltas_per_weave": 12,    # 单次 weave 最多派几个 delta (防洪泛)
        # 口识体-C: nudge/care 警报 → 体张力 (感知环穿体). wellness/proactive 警报
        # 退化为体能量, 不直推 __NUDGE__ → 识经 body_delta attend (而非 nudge 抢话筒).
        "nudge_tension_enabled": 1,
        "nudge_window_s": 600.0,           # 读 SWM 多久内的 nudge 警报
        "nudge_tension_per_event": 0.5,    # 每条警报张力 (× event salience, 接地)
        "nudge_tension_cap": 1.5,          # 单 concern nudge 张力上限 (防 storm 膨胀)
        "nudge_tension_etypes": [          # 带 concern_id / missed_concern_ids 的警报类型
            "proactive_care_advice",       # ProactiveCare 想 nudge 某 concern
            "care_signal_derived",         # sensor 派生的 concern signal
            "soul_alignment_advice",       # missed_concern_ids = Jarvis 漏掉 = 张力
            "proactive_nudge_fired",       # daemon fire (extra_metadata 带 concern_id 才计)
        ],
        # 口识体-F: 张力 dyad — 立场↔Sir关心 的边 (阻力/老师载体, §6). 高置信 active
        # stance about 某 concern → stance 节点与 concern 节点连 dyad 边 (grounded by
        # stance_id), 且贡献一份"立场张力" (Jarvis 在此持有坚定 view = 可能推开 Sir 的
        # 阻力源). 数据驱动: 立场越多/越坚定 → dyad 越多 → 体在那些区有阻力势能。
        # 真冲突 valence (立场逆 Sir 当下意愿) 待 Sir-wish 信号成熟再精算 (现保守计基线)。
        "stance_dyad_enabled": 1,
        "stance_dyad_min_confidence": 0.6,   # 立场置信 >= 此才织 dyad (够坚定才算阻力)
        "stance_dyad_tension": 0.4,          # 每条 dyad 贡献的立场张力基线
    },
}

_MANIFOLD_CONFIG_PATH = os.path.join("memory_pool", "relational_manifold_vocab.json")
_MANIFOLD_CONFIG_CACHE: Optional[Dict[str, Any]] = None
_MANIFOLD_CONFIG_MTIME: float = 0.0


def _deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def get_manifold_config() -> Dict[str, Any]:
    """读 config (seed 默认叠加 json override)。mtime cache 防频繁读盘 (JARVIS_PYTHON_STYLE §6.2)。"""
    global _MANIFOLD_CONFIG_CACHE, _MANIFOLD_CONFIG_MTIME
    try:
        mtime = os.path.getmtime(_MANIFOLD_CONFIG_PATH) if os.path.exists(
            _MANIFOLD_CONFIG_PATH) else 0.0
    except OSError:
        mtime = 0.0
    if _MANIFOLD_CONFIG_CACHE is None or mtime > _MANIFOLD_CONFIG_MTIME:
        cfg = dict(_SEED_MANIFOLD_CONFIG)
        try:
            if os.path.exists(_MANIFOLD_CONFIG_PATH):
                with open(_MANIFOLD_CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    cfg = _deep_merge(cfg, data.get("config", data))
        except Exception:
            cfg = dict(_SEED_MANIFOLD_CONFIG)
        _MANIFOLD_CONFIG_CACHE = cfg
        _MANIFOLD_CONFIG_MTIME = mtime
    return _MANIFOLD_CONFIG_CACHE


def _log(msg: str) -> None:
    try:
        from jarvis_utils import bg_log
        bg_log(msg)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# RelationalManifold — 边 store
# ---------------------------------------------------------------------------

class RelationalManifold:
    """关系流形的边层。无 LLM、纯几何/结构 + Hebbian, 廉价可测。

    存储 (`memory_pool/relational_manifold.json`):
        {"_meta": {...}, "edges": {"<a>\u241f<b>": {edge}, ...}}
    其中 a,b 为排序后的 node id (无向边), edge =
        {"a","b","weight","reinforce_count","created_ts","last_reinforced_ts",
         "provenance":[{"kind","ref","ts","detail","confidence"?,"inferred"?}],
         "review": bool}
    """

    _DEFAULT_PATH = os.path.join("memory_pool", "relational_manifold.json")

    def __init__(self, path: Optional[str] = None):
        self.path = path or self._DEFAULT_PATH
        self._lock = threading.RLock()
        self._edges: Dict[str, Dict[str, Any]] = {}
        self._adj: Dict[str, set] = collections.defaultdict(set)  # node -> {edge_key}
        self._surfaces: List[Dict[str, Any]] = []  # 体-P3 语义曲面 (Weaver 算)
        self._aliases: Dict[str, str] = {}  # 口识体-D2: 近重复节点 → 代表 (合并, 不动源)
        self._load()

    # ---- persistence ----
    def _load(self) -> None:
        with self._lock:
            self._edges = {}
            self._adj = collections.defaultdict(set)
            self._surfaces = []
            if not os.path.exists(self.path):
                return
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                edges = data.get("edges", {}) if isinstance(data, dict) else {}
                for key, e in edges.items():
                    if not isinstance(e, dict) or "a" not in e or "b" not in e:
                        continue
                    self._edges[key] = e
                    self._adj[e["a"]].add(key)
                    self._adj[e["b"]].add(key)
                sf = data.get("surfaces", []) if isinstance(data, dict) else []
                self._surfaces = sf if isinstance(sf, list) else []
                al = data.get("aliases", {}) if isinstance(data, dict) else {}
                self._aliases = al if isinstance(al, dict) else {}
            except Exception as exc:
                _log(f"[Manifold] load failed ({exc!r}) — starting empty")
                self._edges = {}
                self._adj = collections.defaultdict(set)

    def save(self) -> None:
        with self._lock:
            payload = {
                "_meta": {
                    "schema": "relational_manifold",
                    "schema_version": 1,
                    "purpose": "体(Body)边层: 节点间交叉引用图, Hebbian+衰减, 每边接地",
                    "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "edge_count": len(self._edges),
                    "surface_count": len(self._surfaces),
                    "edit_via": "scripts/manifold_dump.py",
                },
                "edges": self._edges,
                "surfaces": self._surfaces,
                "aliases": self._aliases,
            }
            tmp = self.path + ".tmp"
            try:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            except Exception as exc:
                _log(f"[Manifold] save failed ({exc!r})")

    # ---- edge keys ----
    @staticmethod
    def _edge_key(a: str, b: str) -> str:
        lo, hi = (a, b) if a <= b else (b, a)
        return f"{lo}{_KEY_SEP}{hi}"

    @staticmethod
    def _decay_factor(dt_s: float, half_life_s: float) -> float:
        if half_life_s <= 0 or dt_s <= 0:
            return 1.0
        return math.exp(-math.log(2.0) * dt_s / half_life_s)

    def _half_life_s(self) -> float:
        return float(get_manifold_config().get("half_life_days", 14.0)) * 86400.0

    def effective_weight(self, edge: Dict[str, Any], now: Optional[float] = None) -> float:
        """活算的衰减后 weight (不改存储)。"""
        now = time.time() if now is None else now
        base = float(edge.get("weight", 0.0))
        dt = now - float(edge.get("last_reinforced_ts", now))
        return base * self._decay_factor(dt, self._half_life_s())

    # ---- core mutate ----
    def add_edge(
        self,
        a: str,
        b: str,
        kind: str,
        ref: str,
        *,
        detail: str = "",
        weight_scale: float = 1.0,
        confidence: Optional[float] = None,
        inferred: bool = False,
        accumulate: bool = True,
        now: Optional[float] = None,
    ) -> Optional[str]:
        """造/强化一条边。**接地红线**: ref 必填 (trace 来源), 否则拒绝 (返回 None)。

        - kind: PROV_* 之一 (怎么造的)。
        - ref: trace 来源 (turn_id / concern_id / 'cosine' ...)。无 = 幻觉, 拒。
        - inferred=True (LLM 推断): 标 review, propose-not-trust (体-P4)。
        - accumulate=True (默认, 事件边 cooccur/said/shared): Hebbian 累加 (越多次越强)。
          accumulate=False (属性边 embed, 体-P2): set-to-floor (相似度是静态属性,
          重复 weave 不膨胀; weight = max(已衰减值, 本次增量))。
        返回 edge_key, 或 None (被拒)。
        """
        if a == b or not a or not b:
            return None
        if not ref:
            _log(f"[Manifold] REJECT ungrounded edge {a}~{b} kind={kind} (no ref)")
            return None
        now = time.time() if now is None else now
        cfg = get_manifold_config()
        inc = float(cfg.get("weight_increment", {}).get(kind, 0.3)) * float(weight_scale)
        if confidence is not None:
            inc *= max(0.0, min(1.0, float(confidence)))
        cap = float(cfg.get("weight_cap", 6.0))
        key = self._edge_key(a, b)
        with self._lock:
            e = self._edges.get(key)
            if e is None:
                e = {
                    "a": min(a, b), "b": max(a, b),
                    "weight": 0.0, "reinforce_count": 0,
                    "created_ts": now, "last_reinforced_ts": now,
                    "provenance": [], "review": bool(inferred),
                }
                self._edges[key] = e
                self._adj[e["a"]].add(key)
                self._adj[e["b"]].add(key)
            # 先把已有 weight 衰减到 now
            dt = now - float(e.get("last_reinforced_ts", now))
            decayed = float(e.get("weight", 0.0)) * self._decay_factor(dt, self._half_life_s())
            if accumulate:
                # 事件边: Hebbian 累加 (越多次越强)
                e["weight"] = min(cap, decayed + inc)
                e["reinforce_count"] = int(e.get("reinforce_count", 0)) + 1
            else:
                # 属性边 (embed): set-to-floor, 几何相似度提供权重下限, 不累加膨胀
                e["weight"] = min(cap, max(decayed, inc))
            e["last_reinforced_ts"] = now
            if inferred:
                e["review"] = True
            self._append_provenance(e, kind, ref, now, detail, confidence, inferred)
        return key

    def _append_provenance(self, e, kind, ref, now, detail, confidence, inferred) -> None:
        prov = e.setdefault("provenance", [])
        # dedup: 同 (kind, ref) 不重复堆, 刷新 ts/count + 最新 detail/confidence
        for p in prov:
            if p.get("kind") == kind and p.get("ref") == ref:
                p["ts"] = now
                p["count"] = int(p.get("count", 1)) + 1
                if detail:
                    p["detail"] = detail[:200]
                if confidence is not None:
                    p["confidence"] = round(float(confidence), 3)
                return
        rec = {"kind": kind, "ref": ref, "ts": now, "count": 1}
        if detail:
            rec["detail"] = detail[:200]
        if confidence is not None:
            rec["confidence"] = round(float(confidence), 3)
        if inferred:
            rec["inferred"] = True
        prov.append(rec)
        cap = int(get_manifold_config().get("max_provenance_per_edge", 12))
        if len(prov) > cap:
            prov.sort(key=lambda p: p.get("ts", 0.0))
            del prov[: len(prov) - cap]

    # ---- structural observers (识/sensor/对话调这些, 非 LLM) ----
    def observe_cooccurrence(
        self, node_ids: Iterable[str], turn_id: str, *,
        weight_scale: float = 1.0, now: Optional[float] = None,
    ) -> int:
        """一组节点在同一 turn/session 一起出现 → 两两加 cooccur 边。返回新增/强化边数。"""
        nodes = sorted({n for n in node_ids if n})
        if len(nodes) < 2 or not turn_id:
            return 0
        n = 0
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                if self.add_edge(nodes[i], nodes[j], PROV_COOCCUR, turn_id,
                                 weight_scale=weight_scale, now=now):
                    n += 1
        return n

    def observe_explicit_link(
        self, a: str, b: str, turn_id: str, *, detail: str = "", now: Optional[float] = None,
    ) -> Optional[str]:
        """Sir 一句话显式把两节点连起 → said 边 (强信号)。"""
        return self.add_edge(a, b, PROV_SAID, turn_id, detail=detail, now=now)

    def observe_shared_entity(
        self, node_ids: Iterable[str], entity_id: str, *, now: Optional[float] = None,
    ) -> int:
        """一组节点共享同一实体/concern → 两两加 shared 边。"""
        nodes = sorted({n for n in node_ids if n})
        if len(nodes) < 2 or not entity_id:
            return 0
        n = 0
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                if self.add_edge(nodes[i], nodes[j], PROV_SHARED, entity_id, now=now):
                    n += 1
        return n

    def add_inferred_edge(
        self, a: str, b: str, turn_id: str, confidence: float, rationale: str,
        *, now: Optional[float] = None,
    ) -> Optional[str]:
        """LLM 推断边 (体-P4 propose-not-trust): 标 inferred + review, 必带 turn_id + confidence。"""
        if not turn_id:
            return None
        return self.add_edge(a, b, PROV_INFERRED, turn_id, detail=rationale,
                             confidence=confidence, inferred=True, now=now)

    def add_geometric_edge(
        self, a: str, b: str, cosine: float, *, now: Optional[float] = None,
    ) -> Optional[str]:
        """体-P2 几何边: embedding cosine 相似度。

        相似度是**静态属性**非事件 → accumulate=False (set-to-floor, 重复 weave 不膨胀)。
        ref='cosine' (稳定, provenance 去重为一条, 每次刷新最新 cos 值 = 可复现接地)。
        weight ≈ embed_increment * cosine (confidence 缩放)。
        """
        return self.add_edge(
            a, b, PROV_EMBED, "cosine",
            detail=f"cos={cosine:.3f}", confidence=float(cosine),
            accumulate=False, now=now,
        )

    # ---- decay / prune (织网者 Weaver 周期调, 体-P5) ----
    def apply_decay(self, now: Optional[float] = None) -> None:
        """把所有边 weight 衰减到 now (写回存储)。"""
        now = time.time() if now is None else now
        hl = self._half_life_s()
        with self._lock:
            for e in self._edges.values():
                dt = now - float(e.get("last_reinforced_ts", now))
                e["weight"] = float(e.get("weight", 0.0)) * self._decay_factor(dt, hl)
                e["last_reinforced_ts"] = now

    def prune(self, now: Optional[float] = None) -> int:
        """删衰减后低于 prune_floor 的边。返回删除数。"""
        now = time.time() if now is None else now
        floor = float(get_manifold_config().get("prune_floor", 0.05))
        removed = 0
        with self._lock:
            for key in list(self._edges.keys()):
                e = self._edges[key]
                if self.effective_weight(e, now) < floor:
                    self._adj[e["a"]].discard(key)
                    self._adj[e["b"]].discard(key)
                    del self._edges[key]
                    removed += 1
        return removed

    # ---- queries (透镜 Lens 体-P6 / CLI 用) ----
    def get_edge(self, a: str, b: str) -> Optional[Dict[str, Any]]:
        return self._edges.get(self._edge_key(a, b))

    def neighbors(
        self, node_id: str, *, min_weight: float = 0.0,
        limit: Optional[int] = None, now: Optional[float] = None,
    ) -> List[Tuple[str, float]]:
        """返回与 node_id 相连的节点 [(node, effective_weight)], 按权重降序。"""
        now = time.time() if now is None else now
        if limit is None:
            limit = int(get_manifold_config().get("neighbor_default_limit", 24))
        out: List[Tuple[str, float]] = []
        with self._lock:
            for key in self._adj.get(node_id, ()):  # type: ignore[arg-type]
                e = self._edges.get(key)
                if not e:
                    continue
                w = self.effective_weight(e, now)
                if w < min_weight:
                    continue
                other = e["b"] if e["a"] == node_id else e["a"]
                out.append((other, w))
        out.sort(key=lambda x: x[1], reverse=True)
        return out[:limit] if limit else out

    def degree(self, node_id: str) -> int:
        return len(self._adj.get(node_id, ()))

    def spread(
        self, seeds: Iterable[str], *, hops: int = 2, decay_per_hop: float = 0.5,
        min_activation: float = 0.05, now: Optional[float] = None,
    ) -> Dict[str, float]:
        """Spreading-activation: 从 seeds 出发逐跳扩散激活值 (透镜 Lens 体-P6 的核心原语)。

        返回 {node: activation}。seed 激活=1.0, 每跳 *= decay_per_hop * 边相对权重。
        """
        now = time.time() if now is None else now
        activation: Dict[str, float] = {}
        frontier: Dict[str, float] = {s: 1.0 for s in seeds if s}
        for s in frontier:
            activation[s] = 1.0
        for _hop in range(max(0, hops)):
            nxt: Dict[str, float] = {}
            for node, act in frontier.items():
                for other, w in self.neighbors(node, now=now, limit=None):
                    # 边权归一到 (0,1] 用 tanh, 防强边吃掉一切
                    edge_factor = math.tanh(w)
                    new_act = act * decay_per_hop * edge_factor
                    if new_act < min_activation:
                        continue
                    if new_act > nxt.get(other, 0.0):
                        nxt[other] = new_act
            # 累积 (取最大激活)
            for node, act in nxt.items():
                if act > activation.get(node, 0.0):
                    activation[node] = act
            frontier = nxt
            if not frontier:
                break
        return activation

    # ---- 面 / surfaces (体-P3): 强连通节点社区 ----
    def compute_surfaces(
        self, *, min_weight: Optional[float] = None,
        min_size: Optional[int] = None, now: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """图社区检测: 沿"强边"(有效权重 >= min_weight) BFS 连通块 → 语义曲面。

        纯几何, 无 LLM (准则 1/6)。每个面 = {surface_id, members, size, kinds, top_nodes}。
        面是"Sir 的某一片关注/某一簇笑话"这种自然涌现的区域。
        """
        now = time.time() if now is None else now
        cfg = get_manifold_config()
        if min_weight is None:
            min_weight = float(cfg.get("surface_min_weight", 0.45))
        if min_size is None:
            min_size = int(cfg.get("surface_min_size", 3))
        with self._lock:
            strong: Dict[str, set] = collections.defaultdict(set)
            for e in self._edges.values():
                if self.effective_weight(e, now) >= min_weight:
                    strong[e["a"]].add(e["b"])
                    strong[e["b"]].add(e["a"])
            seen: set = set()
            surfaces: List[Dict[str, Any]] = []
            for start in list(strong.keys()):
                if start in seen:
                    continue
                comp: List[str] = []
                stack = [start]
                seen.add(start)
                while stack:
                    n = stack.pop()
                    comp.append(n)
                    for m in strong[n]:
                        if m not in seen:
                            seen.add(m)
                            stack.append(m)
                if len(comp) < min_size:
                    continue
                kinds = collections.Counter(split_node_id(n)[0] for n in comp)
                # top_nodes = 面内强连接度最高的几个 (代表节点)
                deg = sorted(comp, key=lambda n: len(strong[n] & set(comp)), reverse=True)
                surfaces.append({
                    "surface_id": "surf:" + min(comp),
                    "members": sorted(comp),
                    "size": len(comp),
                    "kinds": dict(kinds),
                    "top_nodes": deg[:5],
                })
            surfaces.sort(key=lambda s: s["size"], reverse=True)
            return surfaces

    def set_surfaces(self, surfaces: List[Dict[str, Any]]) -> None:
        with self._lock:
            self._surfaces = list(surfaces or [])

    def get_surfaces(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._surfaces)

    def surface_of(self, node_id: str) -> Optional[Dict[str, Any]]:
        """node 属于哪个面 (没有则 None)。"""
        with self._lock:
            for s in self._surfaces:
                if node_id in s.get("members", ()):
                    return s
        return None

    # ---- 合并 / alias (口识体-D2): 近重复节点 → 代表 (不动源 store) ----
    def add_alias(self, dup: str, rep: str) -> bool:
        """记 dup 是 rep 的近重复 (合并)。**不删源**, 只在体层把 dup 指向 rep。
        防环 + 防自指。投影/复杂度据此把它们当一个。
        """
        if dup == rep or not dup or not rep:
            return False
        with self._lock:
            rep_r = self.resolve(rep)        # rep 自己可能已是别人的 alias
            if rep_r == dup:                 # 防环
                return False
            self._aliases[dup] = rep_r
        return True

    def resolve(self, node_id: str, _depth: int = 0) -> str:
        """跟随 alias 链到代表节点 (深度封顶防坏数据死循环)。"""
        if _depth > 8:
            return node_id
        rep = self._aliases.get(node_id)
        return self.resolve(rep, _depth + 1) if rep else node_id

    def get_aliases(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._aliases)

    # ---- introspection ----
    def stats(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = time.time() if now is None else now
        kind_counts: Dict[str, int] = collections.defaultdict(int)
        review = 0
        total_w = 0.0
        with self._lock:
            for e in self._edges.values():
                total_w += self.effective_weight(e, now)
                if e.get("review"):
                    review += 1
                seen = set()
                for p in e.get("provenance", []):
                    k = p.get("kind")
                    if k and k not in seen:
                        kind_counts[k] += 1
                        seen.add(k)
            node_count = len([n for n, ks in self._adj.items() if ks])
        return {
            "edge_count": len(self._edges),
            "node_count": node_count,
            "review_count": review,
            "total_effective_weight": round(total_w, 3),
            "edges_by_kind": dict(kind_counts),
        }

    def complexity_report(self, now: Optional[float] = None) -> Dict[str, Any]:
        """复杂度 vs 体积度量 (口识体 closure D1) — "保证复杂度而非单纯提高体积"。

        不只数节点/边, 测**结构质量**: 大簇占比(blob 检测) / 密度 / 接地率 / 压缩比。
        详 docs/JARVIS_FULL_CLOSURE_AND_CONVERGENCE.md §6。纯计算无 LLM。
        """
        now = time.time() if now is None else now
        s = self.stats(now=now)
        surfaces = self.get_surfaces()
        nc, ec = s["node_count"], s["edge_count"]
        review = s["review_count"]
        largest = max((sf.get("size", 0) for sf in surfaces), default=0)
        largest_frac = round(largest / nc, 3) if nc else 0.0
        density = round(ec / nc, 2) if nc else 0.0
        grounded_frac = round(1.0 - (review / ec), 3) if ec else 1.0
        surf_count = len(surfaces)
        compression = round(nc / surf_count, 2) if surf_count else float(nc)
        # health 判定 (体积大但低复杂度 = 病)
        if largest_frac >= 0.5:
            health = "blob"            # 一个大簇吃掉过半节点 = 冗余体积, 低复杂度
        elif density >= 6.0:
            health = "over_dense"      # 边/节点过高 = 过连接, 信息稀释
        elif nc >= 3 and density < 0.4:
            health = "sparse"          # 太稀 = 还没织出结构
        else:
            health = "healthy"
        # 复杂度分 (0-1): 奖均衡面+接地, 罚 blob+过密
        score = round(grounded_frac * (1.0 - min(1.0, largest_frac))
                      * (1.0 if density <= 5 else 5.0 / density), 3)
        return {
            "node_count": nc, "edge_count": ec, "surface_count": surf_count,
            "density": density, "largest_surface_frac": largest_frac,
            "grounded_frac": grounded_frac, "compression": compression,
            "health": health, "complexity_score": score,
            "merged_dups": len(self._aliases),  # 口识体-D2: 已合并的近重复数
        }

    def all_edges(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(e, _key=k) for k, e in self._edges.items()]

    def edge_snapshot(self, now: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
        """{edge_key: {a, b, w(effective)}} 快照 (体势能 diff 用, 不暴露内部)。"""
        now = time.time() if now is None else now
        with self._lock:
            return {k: {"a": e["a"], "b": e["b"], "w": self.effective_weight(e, now)}
                    for k, e in self._edges.items()}


# ---------------------------------------------------------------------------
# Module singleton (识 / 织网者 / CLI 共享一个实例)
# ---------------------------------------------------------------------------

_SINGLETON: Optional[RelationalManifold] = None
_SINGLETON_LOCK = threading.Lock()


def get_manifold() -> RelationalManifold:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = RelationalManifold()
    return _SINGLETON
