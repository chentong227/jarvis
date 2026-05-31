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
    make_node_id, KIND_THREAD, KIND_CONCERN, KIND_JOKE, KIND_PROTOCOL,
    KIND_STANCE,
)

EmbedFn = Callable[[List[str]], List[Optional[List[float]]]]


def _log(msg: str) -> None:
    try:
        from jarvis_utils import bg_log
        bg_log(msg)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Default embedder — 复用 hippocampus 向量器 (Gemini embedding + key 轮换)
# ---------------------------------------------------------------------------

_EMBED_HIPP = None
_EMBED_LOCK = threading.Lock()


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
    ):
        self.manifold = manifold if manifold is not None else get_manifold()
        self.embed_fn = embed_fn if embed_fn is not None else default_embed_fn
        mp = os.path.join(root or ".", "memory_pool")
        self.threads_path = threads_path or os.path.join(mp, "self_threads.json")
        self.concerns_path = concerns_path or os.path.join(mp, "concerns.json")
        self.relational_path = relational_path or os.path.join(mp, "relational_state.json")
        self.vectors_path = vectors_path or os.path.join(mp, "manifold_vectors.json")
        self.stance_path = stance_path or os.path.join(mp, "stance.json")
        self._vec_cache: Dict[str, Dict[str, Any]] = {}
        self._weave_count = 0
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._load_vectors()

    def _wcfg(self) -> Dict[str, Any]:
        return get_manifold_config().get("weaver", {}) or {}

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
        M = np.array([vecs[i] for i in ids], dtype=np.float32)
        norms = np.linalg.norm(M, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        Mn = M / norms
        sim = Mn @ Mn.T
        seen = set()
        added = 0
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
                if self.manifold.add_geometric_edge(a, b, c, now=now):
                    added += 1
        return added

    # ---- 维护 ----
    def maintain(self, now: Optional[float] = None) -> int:
        now = time.time() if now is None else now
        self.manifold.apply_decay(now=now)
        return self.manifold.prune(now=now)

    # ---- 全量一轮 ----
    def weave_once(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = time.time() if now is None else now
        with self._lock:
            nodes = self.harvest_nodes()
            added = self.weave_geometric(nodes, now=now)
            self._weave_count += 1
            pruned = 0
            dev = int(self._wcfg().get("decay_every_n_weaves", 6))
            if dev > 0 and self._weave_count % dev == 0:
                pruned = self.maintain(now=now)
            # 体-P3: 重算语义曲面 (面随边变, 廉价图 BFS)
            surfaces = self.manifold.compute_surfaces(now=now)
            self.manifold.set_surfaces(surfaces)
            self.manifold.save()
        stats = self.manifold.stats(now=now)
        stats.update({"weave_count": self._weave_count, "nodes": len(nodes),
                      "embed_edges_added": added, "pruned": pruned,
                      "surface_count": len(surfaces)})
        _log(f"[Weaver] weave#{self._weave_count} nodes={len(nodes)} "
             f"embed+={added} pruned={pruned} edges={stats['edge_count']} "
             f"surfaces={len(surfaces)}")
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
