"""jarvis_relational_weaver.py — 织网者 (Weaver), 体(Body)的维护器官.

体-P5 / 体-P2 (2026-05-31). 详 docs/JARVIS_TRINITY_ARCHITECTURE.md §4.

织网者 = 和"识"(思考脑)同级的后台 peer。它不"活"(那是识的事), 不"投影"(那是透镜的事),
它只做一件慢工: **维护关系流形**。
- **harvest**: 从各真理源 store (self_threads / concerns / relational_state) 取节点 + 文本。
- **几何织网 (体-P2)**: embed 节点文本 (复用 hippocampus 向量器, 带缓存), 算两两 cosine,
  相似度 >= 阈值 → 连 embed 边。**相似度是静态属性** → set-to-floor (不 Hebbian 累加)。
- **维护**: 周期 decay (关系慢衰) + prune (删枯边)。
- **接地红线**: embed 边 ref='cosine' + detail=cos值 (可复现), 不是幻觉。

准则 1 (TTFT): 全程后台慢工 (默认 600s 一轮), 不在主脑热路径。
准则 6 #1/#3: 数据进 manifold (持久化), 织网逻辑非 LLM (纯几何), 配置 CLI 可改。
"""

from __future__ import annotations

# [体-P5 / 2026-05-31] import safety net (JARVIS_PYTHON_STYLE §1)
import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import re  # noqa: F401
import time
import json
import math  # noqa: F401
import threading
import hashlib
import collections  # noqa: F401
from typing import Dict, List, Optional, Callable, Any

import numpy as np

from jarvis_relational_manifold import (
    RelationalManifold, get_manifold, get_manifold_config,
    make_node_id, split_node_id, KIND_THREAD, KIND_CONCERN, KIND_JOKE,
    KIND_PROTOCOL, KIND_STANCE, PROV_SHARED,
)

EmbedFn = Callable[[List[str]], List[Optional[List[float]]]]


def _log(msg: str) -> None:
    try:
        from jarvis_utils import bg_log
        bg_log(msg)
    except Exception:
        pass


def _default_event_bus():
    """口识体-C: 默认读全局 SWM (生产). 注入便于 test 隔离。失败返 None。"""
    try:
        from jarvis_utils import get_event_bus
        return get_event_bus()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Default embedder — 复用 hippocampus 向量器 (Gemini embedding + key 轮换)
# ---------------------------------------------------------------------------

_EMBED_HIPP = None
_EMBED_LOCK = threading.Lock()

# ---- 口写体 (口识体-B2): 对话 turn → 显著共现边 ----
# node 文本 TTL 缓存 (per-turn 调, 不每次 harvest 4 文件)
_TURN_TEXT_CACHE: Dict[str, str] = {}
_TURN_TEXT_TS = 0.0
_TURN_TEXT_TTL = 120.0
_TERM_CJK = re.compile(r"[\u4e00-\u9fff]{2,6}")
_TERM_EN = re.compile(r"[A-Za-z]{4,}")
# 太常见 → 不算 distinctive (每个节点都含, 匹配无意义)
_TERM_STOP = frozenset({
    "sir", "jarvis", "your", "this", "that", "with", "have", "will", "would",
    "should", "could", "贾维斯", "先生", "应该", "可能", "需要", "我们", "他的", "自己",
})


def _cached_node_texts() -> Dict[str, str]:
    global _TURN_TEXT_CACHE, _TURN_TEXT_TS
    now = time.time()
    if _TURN_TEXT_CACHE and (now - _TURN_TEXT_TS) < _TURN_TEXT_TTL:
        return _TURN_TEXT_CACHE
    try:
        _TURN_TEXT_CACHE = RelationalWeaver(manifold=get_manifold()).harvest_nodes()
    except Exception:
        _TURN_TEXT_CACHE = _TURN_TEXT_CACHE or {}
    _TURN_TEXT_TS = now
    return _TURN_TEXT_CACHE


def _distinctive_terms(text: str, k: int = 12) -> List[str]:
    """抽节点文本里的 distinctive 词: CJK run 滑窗 2/3-gram + 英文 ≥4 字母, 去停用词。

    (滑窗 gram 是为了让长 CJK run 如 '连续熬夜风险' 产出 '熬夜' 以匹配对话, 牺牲少量精度换召回。)
    """
    english = [w.lower() for w in _TERM_EN.findall(text or "")
               if w.lower() not in _TERM_STOP]
    grams3, grams2 = [], []
    for run in _TERM_CJK.findall(text or ""):
        for i in range(len(run) - 2):
            g = run[i:i + 3]
            if g not in _TERM_STOP:
                grams3.append(g)
        for i in range(len(run) - 1):
            g = run[i:i + 2]
            if g not in _TERM_STOP:
                grams2.append(g)
    # 优先序: 英文词(最 distinctive) + CJK 2-gram(中文词多为双字) + 3-gram
    seen: set = set()
    uniq = [t for t in (english + grams2 + grams3) if not (t in seen or seen.add(t))]
    return uniq[:k]


def observe_turn_cooccurrence(
    turn_text: str, turn_id: str, *,
    text_map: Optional[Dict[str, str]] = None, manifold=None,
    max_nodes: int = 6, min_match_nodes: int = 2, save: bool = True,
) -> int:
    """口写体 (B2): 一轮对话提到的体节点 (lexical 匹配) → 两两共现边。

    **选择性 (准则 8 防 bloat)**: 平凡闲聊 → 0-1 节点匹配 → 不写。只有真激活 >=2 个已知
    体节点的 turn 才回写共现边 (turn_id 接地)。词消化进体走现有 STM→thread 管线, 这里只补边。
    返回新增/强化边数。失败非致命。
    """
    if not turn_text:
        return 0
    # turn_id 缺失 (mirror 文本注入 / 某些路径 turn_id 未及设) → 退回时间戳 ref:
    # 共现仍是真实事件 (接地到 time T), 精度降到"何时"而非"哪轮", 不丢接地 (准则 5)。
    if not turn_id:
        turn_id = f"turn@{int(time.time())}"
    try:
        m = manifold if manifold is not None else get_manifold()
        tmap = text_map if text_map is not None else _cached_node_texts()
        tl = turn_text.lower()
        scored: List[tuple] = []
        for nid, ntext in tmap.items():
            terms = _distinctive_terms(ntext)
            hits = sum(1 for t in terms if (t in tl if t.isascii() else t in turn_text))
            if hits >= 1:
                scored.append((nid, hits))
        scored.sort(key=lambda x: x[1], reverse=True)
        nodes = [n for n, _ in scored[:max_nodes]]
        if len(nodes) < min_match_nodes:
            return 0  # 平凡闲聊 / 没激活已知结构 → 不写
        n = m.observe_cooccurrence(nodes, turn_id)
        if save and n:
            m.save()
        return n
    except Exception as exc:
        _log(f"[Weaver] observe_turn_cooccurrence failed ({exc!r})")
        return 0


def default_embed_fn(texts: List[str]) -> List[Optional[List[float]]]:
    """批量 embed (复用 Hippocampus._embed_with_rotation)。

    故障开放: 无 key / 网络挂 / 任何异常 → 返回 [None]*len (Weaver 跳过几何织网,
    不崩)。这是后台慢工, 失败下一轮再试。
    """
    global _EMBED_HIPP
    texts = list(texts)
    if not texts:
        return []
    try:
        with _EMBED_LOCK:
            if _EMBED_HIPP is None:
                # 标准方式建 key_router (load_keys + 三池) 再给 Hippocampus,
                # 否则 embed_content 无 api_key (standalone CLI 场景)。
                from jarvis_hippocampus import Hippocampus
                kr = None
                try:
                    from jarvis_config.keys import load_keys
                    from jarvis_key_router import KeyRouter
                    _keys = load_keys()
                    kr = KeyRouter(
                        main_brain_key=_keys.OPENROUTER_MAIN,
                        google_keys=_keys.GOOGLE_LIST,
                        openrouter_keys=_keys.OPENROUTER_LIST,
                    )
                except Exception as ke:
                    _log(f"[Weaver] key_router 构建失败 ({ke!r}) — embed 将无 key")
                # 海马体永不动红线 (口识体-G0): 体唯一碰 Hippocampus 的地方, 且**只读** —
                # 仅调 _embed_with_rotation (embed 向量), 绝不写/改 hippocampus 永久记忆。
                # tests/_test_body_g0_hippo_immutable.py 静态守护此红线。
                _EMBED_HIPP = Hippocampus(
                    db_path=os.path.join("memory_pool", "jarvis_memory.db"),
                    key_router=kr)
        resp, _key = _EMBED_HIPP._embed_with_rotation(contents=texts)
        out: List[Optional[List[float]]] = []
        embs = list(getattr(resp, "embeddings", []) or [])
        for i in range(len(texts)):
            if i < len(embs):
                out.append(list(embs[i].values))
            else:
                out.append(None)
        return out
    except Exception as exc:
        _log(f"[Weaver] embed failed ({exc!r}) — 本轮跳过几何织网")
        return [None] * len(texts)


# ---------------------------------------------------------------------------
# RelationalWeaver
# ---------------------------------------------------------------------------

class RelationalWeaver:
    """织网者: 维护体的边。harvest → embed(cached) → 几何边 → decay/prune。"""

    def __init__(
        self,
        manifold: Optional[RelationalManifold] = None,
        embed_fn: Optional[EmbedFn] = None,
        *,
        root: str = "",
        threads_path: Optional[str] = None,
        concerns_path: Optional[str] = None,
        relational_path: Optional[str] = None,
        vectors_path: Optional[str] = None,
        stance_path: Optional[str] = None,
        energy_path: Optional[str] = None,
        delta_publisher: Optional[Callable[[Dict[str, Any]], None]] = None,
        event_bus: Optional[Any] = None,
    ):
        self.manifold = manifold if manifold is not None else get_manifold()
        # 口识体-C: 读 SWM nudge/care 警报算体张力 (感知环). None → 生产 lazy 全局 bus。
        self._event_bus = event_bus
        self.embed_fn = embed_fn if embed_fn is not None else default_embed_fn
        mp = os.path.join(root or ".", "memory_pool")
        self.threads_path = threads_path or os.path.join(mp, "self_threads.json")
        self.concerns_path = concerns_path or os.path.join(mp, "concerns.json")
        self.relational_path = relational_path or os.path.join(mp, "relational_state.json")
        self.vectors_path = vectors_path or os.path.join(mp, "manifold_vectors.json")
        self.stance_path = stance_path or os.path.join(mp, "stance.json")
        self.energy_path = energy_path or os.path.join(mp, "body_energy.json")
        # 体势能 (口识体-B3): delta 发布 (默认进 SWM, 注入便于 test) + 跨 weave 状态
        self.delta_publisher = delta_publisher
        self._prev_energy: Dict[str, Dict[str, float]] = {}
        self._recent_deltas: List[Dict[str, Any]] = []
        self._vec_cache: Dict[str, Dict[str, Any]] = {}
        self._weave_count = 0
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._load_vectors()

    def _wcfg(self) -> Dict[str, Any]:
        return get_manifold_config().get("weaver", {}) or {}

    def _ecfg(self) -> Dict[str, Any]:
        return get_manifold_config().get("energy", {}) or {}

    # ---- json read helpers (robust) ----
    @staticmethod
    def _read_json(path: str) -> Any:
        try:
            if not os.path.exists(path):
                return {}
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    # ---- harvest nodes (体只引用真理源, 不重存) ----
    def harvest_nodes(self) -> Dict[str, str]:
        cfg = self._wcfg()
        maxc = int(cfg.get("max_text_chars", 400))
        minc = int(cfg.get("min_node_text_chars", 4))
        out: Dict[str, str] = {}

        def _add(nid: str, *parts: Optional[str]) -> None:
            text = " ".join(p.strip() for p in parts if p and p.strip()).strip()
            if len(text) >= minc:
                out[nid] = text[:maxc]

        # threads (self_threads.json)
        tdata = self._read_json(self.threads_path)
        if isinstance(tdata, dict):
            for t in tdata.get("threads", []) or []:
                if not isinstance(t, dict):
                    continue
                tid = t.get("thread_id")
                if tid and t.get("status") != "let_go":
                    _add(make_node_id(KIND_THREAD, tid), t.get("summary"))

        # concerns (concerns.json: top-level id -> obj)
        cdata = self._read_json(self.concerns_path)
        if isinstance(cdata, dict):
            for cid, c in cdata.items():
                if not isinstance(c, dict) or cid.startswith("_"):
                    continue
                if c.get("state") == "archived":
                    continue
                _add(make_node_id(KIND_CONCERN, c.get("id", cid)),
                     c.get("what_i_watch"), c.get("why_i_care"))

        # relational_state.json: inside_jokes + unspoken_protocols
        rdata = self._read_json(self.relational_path)
        if isinstance(rdata, dict):
            for jid, j in (rdata.get("inside_jokes") or {}).items():
                if isinstance(j, dict) and j.get("state") == "active":
                    _add(make_node_id(KIND_JOKE, j.get("id", jid)),
                         j.get("phrase"), j.get("birth_context"))
            for pid, p in (rdata.get("unspoken_protocols") or {}).items():
                if isinstance(p, dict) and p.get("state") == "active":
                    _add(make_node_id(KIND_PROTOCOL, p.get("id", pid)), p.get("rule"))

        # 立场 (体-P4): active 立场进体, 让 Jarvis 自己的 view 也长边
        sdata = self._read_json(self.stance_path)
        if isinstance(sdata, dict):
            for sid, s in (sdata.get("stances") or {}).items():
                if isinstance(s, dict) and s.get("state") == "active":
                    _add(make_node_id(KIND_STANCE, s.get("stance_id", sid)), s.get("claim"))
        return out

    # ---- vector cache (embed 一次, 文本不变就复用) ----
    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]

    def _load_vectors(self) -> None:
        data = self._read_json(self.vectors_path)
        if isinstance(data, dict):
            self._vec_cache = data.get("vectors", {}) or {}

    def _save_vectors(self) -> None:
        payload = {"_meta": {"schema": "manifold_vectors",
                             "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                             "count": len(self._vec_cache)},
                   "vectors": self._vec_cache}
        tmp = self.vectors_path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.vectors_path) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, self.vectors_path)
        except Exception as exc:
            _log(f"[Weaver] save vectors failed ({exc!r})")

    def _ensure_vectors(self, nodes: Dict[str, str]) -> Dict[str, List[float]]:
        """保证 nodes 都有最新向量 (文本变了才重 embed)。返回 {node: vec}。"""
        # 清掉已消失节点的缓存
        for nid in list(self._vec_cache.keys()):
            if nid not in nodes:
                del self._vec_cache[nid]
        # 找需要 (重)embed 的
        need = [nid for nid, txt in nodes.items()
                if self._vec_cache.get(nid, {}).get("hash") != self._hash(txt)]
        if need:
            bs = max(1, int(self._wcfg().get("embed_batch_size", 32)))
            for i in range(0, len(need), bs):
                chunk = need[i:i + bs]
                vecs = self.embed_fn([nodes[n] for n in chunk])
                for n, v in zip(chunk, vecs):
                    if v:
                        self._vec_cache[n] = {"hash": self._hash(nodes[n]),
                                              "vec": list(v), "ts": time.time()}
            self._save_vectors()
        return {nid: self._vec_cache[nid]["vec"]
                for nid in nodes if nid in self._vec_cache}

    # ---- 几何织网 (体-P2) ----
    def weave_geometric(self, nodes: Optional[Dict[str, str]] = None,
                        now: Optional[float] = None) -> int:
        now = time.time() if now is None else now
        if nodes is None:
            nodes = self.harvest_nodes()
        vecs = self._ensure_vectors(nodes)
        ids = list(vecs.keys())
        if len(ids) < 2:
            return 0
        cfg = get_manifold_config()
        thr = float(cfg.get("embed_threshold", 0.72))
        topk = int(cfg.get("embed_top_k_per_node", 8))
        # 🆕 [body-diff-P0a] 接地不对称折扣 (不变量②): 两端都自产 → embed 边权打折.
        sp_kinds = set(cfg.get("self_produced_kinds", ["thread", "joke", "proto"]))
        sp_discount = float(cfg.get("self_produced_edge_discount", 0.5))
        M = np.array([vecs[i] for i in ids], dtype=np.float32)
        norms = np.linalg.norm(M, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        Mn = M / norms
        sim = Mn @ Mn.T
        merge_thr = float(cfg.get("merge_threshold", 0.90))
        seen = set()
        added = 0
        dup_pairs: List[tuple] = []
        for i in range(len(ids)):
            row = sim[i].copy()
            row[i] = -1.0
            order = np.argsort(row)[::-1][:topk]
            for j in order:
                c = float(row[j])
                if c < thr:
                    break
                a, b = ids[i], ids[int(j)]
                key = (a, b) if a <= b else (b, a)
                if key in seen:
                    continue
                seen.add(key)
                # 接地不对称: 两端都自产 (thread/joke/proto) → 边权折扣 (不删节点, 只降权)
                _ws = 1.0
                if (split_node_id(a)[0] in sp_kinds
                        and split_node_id(b)[0] in sp_kinds):
                    _ws = sp_discount
                if self.manifold.add_geometric_edge(a, b, c, weight_scale=_ws, now=now):
                    added += 1
                if c >= merge_thr:           # 近重复 → 候选合并
                    dup_pairs.append((a, b))
        # 口识体-D2: 近重复 → 合并 alias (代表=度数高/更 established; 不删源)
        merged = 0
        for a, b in dup_pairs:
            ra, rb = self.manifold.resolve(a), self.manifold.resolve(b)
            if ra == rb:
                continue
            if self.manifold.degree(ra) >= self.manifold.degree(rb):
                rep, dup = ra, rb
            else:
                rep, dup = rb, ra
            if self.manifold.add_alias(dup, rep):
                merged += 1
        if merged:
            _log(f"[Weaver/D2] 合并近重复 {merged} 对 (cosine>={merge_thr}) — 防 bloat, 不动源")
        return added

    # ---- 维护 ----
    def maintain(self, now: Optional[float] = None) -> int:
        now = time.time() if now is None else now
        self.manifold.apply_decay(now=now)
        return self.manifold.prune(now=now)

    # 🆕 [体 P4 / Sir 2026-06-01] 内容中性算法健康: 自动合并近重复节点 (收 blob 体积) ===
    # charter JARVIS_ANCHOR_DESIGN.md §6 + 理念源 §6/0601 决议: 体复杂度走**内容中性算法
    # 健康**(模块度/去重), **非锚**(衡碰体仅护定点)。本法复用 D2(manifold_dump cmd_merge_dups)
    # 纯几何去重: 缓存向量 cosine >= threshold → add_alias(dup→rep, rep=度数高)。
    # **不删源、可逆、内容中性**(纯 embedding 相似, 不做任何内容/价值/锚判断)。
    def auto_merge_near_dups(self, threshold: float = 0.93,
                             max_merges: int = 10) -> int:
        """blob 时合并近重复节点收体积。返回合并对数。失败非致命 (返 0)。"""
        try:
            import numpy as np
            data = self._read_json(self.vectors_path) or {}
            vec = (data.get("vectors") or {}) if isinstance(data, dict) else {}
            ids = [k for k in vec
                   if isinstance(vec.get(k), dict) and vec[k].get("vec")]
            if len(ids) < 2:
                return 0
            M = np.array([vec[i]["vec"] for i in ids], dtype=np.float32)
            nrm = np.linalg.norm(M, axis=1, keepdims=True)
            nrm[nrm == 0] = 1.0
            Mn = M / nrm
            sim = Mn @ Mn.T
            pairs = []
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    c = float(sim[i, j])
                    if c >= threshold:
                        pairs.append((c, ids[i], ids[j]))
            pairs.sort(reverse=True)
            merged = 0
            for c, a, b in pairs:
                if merged >= max_merges:
                    break
                ra, rb = self.manifold.resolve(a), self.manifold.resolve(b)
                if ra == rb:
                    continue
                if self.manifold.degree(ra) >= self.manifold.degree(rb):
                    rep, dup = ra, rb
                else:
                    rep, dup = rb, ra
                if self.manifold.add_alias(dup, rep):
                    merged += 1
            if merged:
                self.manifold.save()
            return merged
        except Exception as exc:
            _log(f"[Weaver] auto_merge_near_dups 异常: {exc!r}")
            return 0

    # ---- 体势能 E (口识体-B3): 自转的坡度 ----
    def _concern_severity_map(self) -> Dict[str, float]:
        """{concern node_id: severity} for active concerns (张力源料)。

        🆕 [反刍治本-Fix3 / Sir 2026-06-02] 只计真 active + triggers_proactive 的 concern。
        snoozed (Sir 暂压) / archived / dismiss 软关闭 (triggers_proactive=False) 的不喂
        体张力 — 否则 snooze/dismiss 等于没用 (真机: keyrouter snooze 到 7/2 仍 tension=1.0)。
        """
        out: Dict[str, float] = {}
        cdata = self._read_json(self.concerns_path)
        if isinstance(cdata, dict):
            for cid, c in cdata.items():
                if not isinstance(c, dict) or cid.startswith("_"):
                    continue
                # Fix3: 只 active 状态喂张力 (snoozed/review/archived 不喂)
                if c.get("state") != "active":
                    continue
                # Fix3: dismiss 软关闭 (triggers_proactive=False) 也不喂体张力
                if not c.get("triggers_proactive", True):
                    continue
                try:
                    sev = float(c.get("severity", 0.0) or 0.0)
                except (TypeError, ValueError):
                    sev = 0.0
                out[make_node_id(KIND_CONCERN, c.get("id", cid))] = sev
        return out

    def _nudge_tension_map(self, valid_concerns: set,
                           now: Optional[float] = None) -> Dict[str, float]:
        """口识体-C: 读 SWM 近期 nudge/care 警报 → concern node 张力 (感知环穿体)。

        "一个 wellness/proactive 警报 = 体的张力" (grounded by event salience): nudge 不
        再直推 __NUDGE__, 退化为体能量, 识经 body_delta attend。**只计真实存在的 active
        concern node (valid_concerns), 不造幻影能量** (准则 5 全接地)。
        soul_alignment_advice 取 missed_concern_ids (Jarvis 漏掉的 = 张力)。失败返 {}。
        """
        cfg = self._ecfg()
        try:
            if not int(cfg.get("nudge_tension_enabled", 1)):
                return {}
        except (TypeError, ValueError):
            pass
        bus = self._event_bus if self._event_bus is not None else _default_event_bus()
        if bus is None:
            return {}
        etypes = set(cfg.get("nudge_tension_etypes", []) or [])
        if not etypes:
            return {}
        window = float(cfg.get("nudge_window_s", 600.0))
        per_w = float(cfg.get("nudge_tension_per_event", 0.5))
        cap = float(cfg.get("nudge_tension_cap", 1.5))
        try:
            events = bus.recent_events(within_seconds=window, types=etypes)
        except Exception as exc:
            _log(f"[Weaver/口识体-C] nudge tension read failed ({exc!r})")
            return {}
        out: Dict[str, float] = collections.defaultdict(float)
        for e in events or []:
            meta = e.get("metadata") or {}
            try:
                sal = float(e.get("salience", 0.5) or 0.5)
            except (TypeError, ValueError):
                sal = 0.5
            cids: List[str] = []
            cid = meta.get("concern_id")
            if cid:
                cids.append(str(cid))
            missed = meta.get("missed_concern_ids")
            if isinstance(missed, (list, tuple)):
                cids.extend(str(m) for m in missed if m)
            for c in cids:
                nid = make_node_id(KIND_CONCERN, c)
                if nid in valid_concerns:
                    out[nid] += per_w * max(0.0, min(1.0, sal))
        return {nid: min(v, cap) for nid, v in out.items()}

    def _habituation_map(self, now: Optional[float] = None) -> Dict[str, float]:
        """习惯化因子 {node_id: factor∈[floor,1.0]} — 接地的"放电反馈缺口"补全。

        Sir 2026-06-02 反刍治本: 设计 §3 承诺 "识放电→该区 E 降→不再醒", 但唯一 wired
        放电通道是 stance-coverage。低 agency concern (hydration) 识反复 attend 却只
        adjust_notes (不改 severity 不立 stance) → 永不放电 → tension=severity 每 weave
        重算 → 反复被召唤 ("认识到自己反刍却停不下" = 结构缺口, 早于衡/锚)。

        机制 (纯物理, 无 LLM, 准则 5 接地): 消费识每 tick publish 的 body_attention_outcome
        event (metadata: node, discharged)。某 node 被反复 attend 却 discharged=False →
        非放电 attend 累积 → 超 free_attends 后该 node tension ×= decay_base^excess (graded,
        到 floor 止)。真放电 (discharged=True) → 该 node 习惯化重置 (1.0)。久不 attend (>
        recovery_s) → 恢复 (1.0, spontaneous recovery)。

        只乘到 tension 源 1 (concern severity standing): novelty/drift/nudge/dyad 不受习惯
        化 → 真新进展 (novelty↑/drift↑) 或新外部警报 (nudge) 自然 dishabituate 突破。
        """
        now = time.time() if now is None else now
        cfg = self._ecfg()
        try:
            if not int(cfg.get("habituation_enabled", 1)):
                return {}
        except (TypeError, ValueError):
            return {}
        bus = self._event_bus if self._event_bus is not None else _default_event_bus()
        if bus is None:
            return {}
        etype = str(cfg.get("habituation_outcome_etype", "body_attention_outcome"))
        window = float(cfg.get("habituation_window_s", 1800.0))
        free = int(cfg.get("habituation_free_attends", 2))
        base = float(cfg.get("habituation_decay_base", 0.6))
        floor = float(cfg.get("habituation_floor", 0.15))
        recovery = float(cfg.get("habituation_recovery_s", 3600.0))
        base = max(0.0, min(0.999, base))
        floor = max(0.0, min(1.0, floor))
        try:
            events = bus.recent_events(within_seconds=window, types={etype})
        except Exception as exc:
            _log(f"[Weaver/habituation] outcome read failed ({exc!r})")
            return {}
        # 按 node 聚: 时间序列 [(ts, discharged)]
        per_node: Dict[str, List[tuple]] = collections.defaultdict(list)
        for e in events or []:
            meta = e.get("metadata") or {}
            nid = self.manifold.resolve(str(meta.get("node") or ""))  # alias→代表
            if not nid:
                continue
            try:
                ts = float(e.get("timestamp", now) or now)
            except (TypeError, ValueError):
                ts = now
            per_node[nid].append((ts, bool(meta.get("discharged", False))))
        out: Dict[str, float] = {}
        for nid, seq in per_node.items():
            seq.sort(key=lambda x: x[0])
            last_ts = seq[-1][0]
            # spontaneous recovery: 久不 attend → 恢复
            if now - last_ts > recovery:
                continue  # factor 1.0 (不衰)
            # 从最近一次放电之后起算非放电 attend 数 (放电 = 重置点)
            non_discharge = 0
            for _ts, discharged in seq:
                if discharged:
                    non_discharge = 0   # 放电重置
                else:
                    non_discharge += 1
            excess = max(0, non_discharge - free)
            if excess <= 0:
                continue  # 仍在免费窗内 → 不衰
            factor = max(floor, base ** excess)
            out[nid] = factor
        return out

    def _stance_covered_concerns(self) -> set:
        """有 active stance 覆盖的 concern node_id 集合 (张力已化解 = 不计能量)。"""
        covered: set = set()
        sdata = self._read_json(self.stance_path)
        if isinstance(sdata, dict):
            for s in (sdata.get("stances") or {}).values():
                if isinstance(s, dict) and s.get("state") == "active":
                    about = (s.get("about") or "").strip()
                    if about:
                        # about 可能是 concern id 原值 或 已命名空间化
                        covered.add(about)
                        covered.add(make_node_id(KIND_CONCERN, about))
        return covered

    # ---- 口识体-F: 张力 dyad (立场↔Sir关心 边, 阻力/老师载体) ----
    def _active_stance_dyads(self) -> List[tuple]:
        """返回 [(stance_node, concern_node, stance_id, confidence)] for 高置信 active
        stance whose about 指向一个 concern。grounded by stance_id (准则 5)。

        这是阻力的结构载体 (§6): 立场 = Jarvis 对某 concern 的坚定 view。当置信够高,
        体在那个区有"立场张力"(可能推开 Sir). 真冲突 valence (逆 Sir 当下意愿) 待
        Sir-wish 信号成熟再精算, 现保守: 高置信 active stance about concern = 基线阻力。
        """
        cfg = self._ecfg()
        try:
            if not int(cfg.get("stance_dyad_enabled", 1)):
                return []
        except (TypeError, ValueError):
            pass
        min_conf = float(cfg.get("stance_dyad_min_confidence", 0.6))
        out: List[tuple] = []
        sdata = self._read_json(self.stance_path)
        if not isinstance(sdata, dict):
            return out
        for sid, s in (sdata.get("stances") or {}).items():
            if not isinstance(s, dict) or s.get("state") != "active":
                continue
            try:
                conf = float(s.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            if conf < min_conf:
                continue
            about = (s.get("about") or "").strip()
            if not about:
                continue
            stance_node = make_node_id(KIND_STANCE, s.get("stance_id", sid))
            concern_node = make_node_id(KIND_CONCERN, about)
            out.append((stance_node, concern_node, str(s.get("stance_id", sid)), conf))
        return out

    def weave_stance_dyads(self, now: Optional[float] = None) -> int:
        """织 立场↔concern dyad 边 (grounded by stance_id). 返新增/强化边数。

        准则 5: ref=stance_id (接地, 非幻觉)。inferred=False (这是真实结构关系, 非 LLM
        猜的因果)。stance node 必须真存在于体 (harvest_nodes 含 active stance) 才连。
        """
        now = time.time() if now is None else now
        dyads = self._active_stance_dyads()
        if not dyads:
            return 0
        added = 0
        for stance_node, concern_node, sid, conf in dyads:
            # PROV_SHARED: 立场与 concern 共享同一关注对象 (结构边, 非几何). 接地 stance_id。
            if self.manifold.add_edge(
                    stance_node, concern_node, PROV_SHARED, ref=sid,
                    detail=f"stance-dyad conf={conf:.2f}", weight_scale=conf,
                    accumulate=False, now=now):
                added += 1
        return added

    def _stance_dyad_tension_map(self) -> Dict[str, float]:
        """{stance_node: 立场张力} — 高置信 active stance about concern 的基线阻力势能。"""
        cfg = self._ecfg()
        try:
            if not int(cfg.get("stance_dyad_enabled", 1)):
                return {}
        except (TypeError, ValueError):
            return {}
        per = float(cfg.get("stance_dyad_tension", 0.4))
        out: Dict[str, float] = {}
        for stance_node, _concern_node, _sid, conf in self._active_stance_dyads():
            out[stance_node] = per * conf   # 越坚定 → 阻力势能越高
        return out

    def compute_energy(
        self, new_edge_keys: set, pre_snapshot: Dict[str, Dict[str, Any]],
        post_snapshot: Dict[str, Dict[str, Any]], now: Optional[float] = None,
    ) -> Dict[str, Dict[str, float]]:
        """算每节点的势能 E = w_nov·新颖 + w_drift·漂移 + w_tension·张力 (接地, 无 LLM)。"""
        now = time.time() if now is None else now
        cfg = self._ecfg()
        drift_min = float(cfg.get("drift_min", 0.05))
        energy: Dict[str, Dict[str, float]] = collections.defaultdict(
            lambda: {"novelty": 0.0, "drift": 0.0, "tension": 0.0, "total": 0.0})
        # 新颖: 本轮新边的权重计给两端
        for key in new_edge_keys:
            e = post_snapshot.get(key)
            if e:
                energy[e["a"]]["novelty"] += e["w"]
                energy[e["b"]]["novelty"] += e["w"]
        # 漂移: 非新边里权重变动超 drift_min 的
        for key, e in post_snapshot.items():
            if key in new_edge_keys or key not in pre_snapshot:
                continue
            d = abs(e["w"] - pre_snapshot[key]["w"])
            if d >= drift_min:
                energy[e["a"]]["drift"] += d
                energy[e["b"]]["drift"] += d
        # 张力源 1: 高 severity concern 且无 active stance 覆盖
        # 习惯化补全 (Sir 2026-06-02): 识反复 attend 某 concern 却不放电 (只 adjust_notes,
        # 不改 severity 不立 stance) → 该 concern tension ×= habituation factor (graded 衰
        # 到 floor). 补全设计 §3 "放电→E降→不再醒" 的缺口 (唯一 wired 放电是 stance-coverage,
        # 低 agency concern 永不放电 → 反复召唤). 真放电/真新进展 (novelty/drift) → 突破。
        sev_min = float(cfg.get("tension_severity_min", 0.40))
        sev = self._concern_severity_map()
        covered = self._stance_covered_concerns()
        habit = self._habituation_map(now=now)
        for nid, s in sev.items():
            if s >= sev_min and nid not in covered:
                energy[nid]["tension"] += s * habit.get(nid, 1.0)
        # 张力源 2 (口识体-C): 近期 nudge/care 警报 → 体张力 (感知环穿体).
        # 新外部警报是新扰动 → 不受 stance 覆盖压制 (放电靠 event 老化出窗 + 识 attend);
        # delta-on-rise 机制保证 tension 平台期不重复派 delta (杜绝 churn)。
        for nid, t in self._nudge_tension_map(set(sev.keys()), now=now).items():
            energy[nid]["tension"] += t
        # 张力源 3 (口识体-F): 立场 dyad — 高置信 active stance 在 stance 节点上的阻力
        # 势能 (Jarvis 持有坚定 view = 老师/阻力载体). 计在 stance 节点, 让识 attend 自己
        # 的立场区 (反思/巩固/或被 Sir outcome 削弱后放电)。grounded by stance_id。
        for nid, t in self._stance_dyad_tension_map().items():
            energy[nid]["tension"] += t
        # total
        wn, wd, wt = (float(cfg.get("w_novelty", 1.0)),
                      float(cfg.get("w_drift", 0.6)), float(cfg.get("w_tension", 1.2)))
        out: Dict[str, Dict[str, float]] = {}
        for nid, comp in energy.items():
            comp["total"] = wn * comp["novelty"] + wd * comp["drift"] + wt * comp["tension"]
            out[nid] = dict(comp)
        return out

    def _diff_and_emit_deltas(
        self, curr_energy: Dict[str, Dict[str, float]], now: float,
    ) -> List[Dict[str, Any]]:
        """对比上轮势能 → 能量上升超阈的节点 → 派 body_delta (唤醒识)。"""
        cfg = self._ecfg()
        thr = float(cfg.get("delta_threshold", 0.30))
        wn, wd, wt = (float(cfg.get("w_novelty", 1.0)),
                      float(cfg.get("w_drift", 0.6)), float(cfg.get("w_tension", 1.2)))
        deltas: List[Dict[str, Any]] = []
        for nid, comp in curr_energy.items():
            prev_total = self._prev_energy.get(nid, {}).get("total", 0.0)
            rise = comp["total"] - prev_total
            if rise >= thr:
                kind = max((("novelty", comp["novelty"] * wn),
                            ("drift", comp["drift"] * wd),
                            ("tension", comp["tension"] * wt)), key=lambda x: x[1])[0]
                deltas.append({
                    "node": nid, "kind": kind, "magnitude": round(rise, 3),
                    "energy": round(comp["total"], 3),
                    "ts": now, "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
                })
        deltas.sort(key=lambda d: d["magnitude"], reverse=True)
        deltas = deltas[: int(cfg.get("max_deltas_per_weave", 12))]
        for d in deltas:
            if self.delta_publisher:
                try:
                    self.delta_publisher(d)
                except Exception:
                    pass
        self._recent_deltas = deltas
        self._prev_energy = curr_energy
        return deltas

    def _save_energy(self, curr_energy: Dict[str, Dict[str, float]],
                     deltas: List[Dict[str, Any]]) -> None:
        top = sorted(curr_energy.items(), key=lambda x: x[1]["total"], reverse=True)[:30]
        payload = {
            "_meta": {"schema": "body_energy",
                      "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                      "node_count": len(curr_energy)},
            "top_energy": [{"node": n, **c} for n, c in top],
            "recent_deltas": deltas,
        }
        tmp = self.energy_path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.energy_path) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.energy_path)
        except Exception as exc:
            _log(f"[Weaver] save energy failed ({exc!r})")

    def recent_deltas(self) -> List[Dict[str, Any]]:
        return list(self._recent_deltas)

    # ---- 全量一轮 ----
    def weave_once(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = time.time() if now is None else now
        with self._lock:
            # 体势能: weave 前快照边权 (算 novelty/drift)
            pre_snapshot = self.manifold.edge_snapshot(now=now)
            nodes = self.harvest_nodes()
            added = self.weave_geometric(nodes, now=now)
            # 口识体-F: 织立场 dyad 边 (立场↔concern, grounded by stance_id, 阻力载体)
            dyad_added = self.weave_stance_dyads(now=now)
            if dyad_added:
                added += dyad_added
                _log(f"[Weaver/F] 织 {dyad_added} 条立场 dyad 边 (阻力/老师载体)")
            self._weave_count += 1
            pruned = 0
            dev = int(self._wcfg().get("decay_every_n_weaves", 6))
            if dev > 0 and self._weave_count % dev == 0:
                pruned = self.maintain(now=now)
            # 体-P3: 重算语义曲面 (面随边变, 廉价图 BFS)
            surfaces = self.manifold.compute_surfaces(now=now)
            self.manifold.set_surfaces(surfaces)
            self.manifold.save()
            # 体势能 E (口识体-B3): 算势能 + diff → 派 body_delta 唤醒识
            post_snapshot = self.manifold.edge_snapshot(now=now)
            new_keys = set(post_snapshot.keys()) - set(pre_snapshot.keys())
            curr_energy = self.compute_energy(new_keys, pre_snapshot, post_snapshot, now=now)
            deltas = self._diff_and_emit_deltas(curr_energy, now)
            self._save_energy(curr_energy, deltas)
        stats = self.manifold.stats(now=now)
        # 复杂度度量 (closure D1): 测结构质量, 不只数体积
        cx = self.manifold.complexity_report(now=now)
        stats.update({"weave_count": self._weave_count, "nodes": len(nodes),
                      "embed_edges_added": added, "pruned": pruned,
                      "surface_count": len(surfaces), "deltas": len(deltas),
                      "energy_nodes": len(curr_energy), "complexity": cx})
        _log(f"[Weaver] weave#{self._weave_count} nodes={len(nodes)} "
             f"embed+={added} pruned={pruned} edges={stats['edge_count']} "
             f"surfaces={len(surfaces)} Δ={len(deltas)} "
             f"cx={cx['health']}/{cx['complexity_score']}")
        if cx["health"] in ("blob", "over_dense"):
            _log(f"⚠️ [Weaver/complexity] {cx['health']}: largest_surface_frac="
                 f"{cx['largest_surface_frac']} density={cx['density']} "
                 f"→ 体积大复杂度低, 待 merge (closure D2)")
            # 🆕 [体 P4 / Sir 2026-06-01] blob → 自动内容中性去重 (收体积), gated vocab.
            try:
                from jarvis_relational_manifold import get_manifold_config as _gmc
                _am = (_gmc().get("auto_merge_dups") or {})
                if _am.get("enabled", True):
                    _n = self.auto_merge_near_dups(
                        threshold=float(_am.get("threshold", 0.93)),
                        max_merges=int(_am.get("max_merges_per_weave", 10)))
                    if _n:
                        cx = self.manifold.complexity_report(now=now)
                        stats["complexity"] = cx
                        _log(f"🧹 [Weaver/P4] blob → 自动合并近重复 {_n} 对 (内容中性去重,"
                             f" 可逆 alias); 后 frac={cx['largest_surface_frac']}")
            except Exception as _e:
                _log(f"[Weaver/P4] auto_merge skip: {_e!r}")
        return stats

    # ---- daemon ----
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self.run_forever,
                                        name="RelationalWeaver", daemon=True)
        self._thread.start()
        _log("[Weaver] 织网者启动 (后台慢工)")

    def run_forever(self) -> None:
        cfg = self._wcfg()
        interval = float(cfg.get("weave_interval_s", 600))
        initial = float(cfg.get("initial_delay_s", 90))
        # 启动后先等 boot 稳定再第一次 weave (不和启动抢资源)
        if self._stop.wait(initial):
            return
        while not self._stop.is_set():
            try:
                self.weave_once()
            except Exception as exc:
                import traceback
                _log(f"[Weaver] weave_once 异常: {exc!r}\n{traceback.format_exc()}")
            if self._stop.wait(interval):
                break

    def stop(self) -> None:
        self._stop.set()
