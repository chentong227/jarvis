# -*- coding: utf-8 -*-
"""jarvis_canonical_entities.py — corrigible canonical 实体层 (外挂轻量 registry).

[canonical-entity-slice1 / 2026-06-08] §9 A 接地栈. 详
docs/process/JARVIS_SLICE1_CANONICAL_ENTITY_DESIGN.md.

把"母亲/妈妈/我妈"这类**同指表面**, 在一个**与 manifold 物理分离的外挂 registry** 里折叠成
一个 canonical 实体 (person:mother), 每条折叠挂 ≥1 接地出处 (GroundingRef), 读取时把分散
raw 表面**触达计数**折到 canonical。

红线 (逐条守, 静态可扫):
  - manifold 核心 (edges/_adj/_aliases/resolve/add_edge) **零改动** — 本模块不 import 不调它。
  - AliasLink store 与 cosine manifold._aliases **物理分离**: 不同文件 (canonical_entities.json
    vs relational_manifold.json) / 不同对象 / 不同 key 空间 (surface→cid vs node→node)。
  - **禁相似度**: 全程 exact dict + 整词子串命中, 无 cosine/embed/np./similarity import。
  - **无接地不入图**: create_canonical_entity / add_canonical_alias_link 空 provenance/ref 一律拒。
  - revoke 是终态: revoked AliasLink 不被 exact 写入路径自动复活, 只 Sir re-relate/add-surface 显式翻。

Slice 1 范围: 硬源 exact 种子 (kinship 表) → canonical 实体 → 触达计数。
OUT (后续片): LLM 收割 entities_json (Slice2) / cosine proposer (Slice3) / 结晶 facet (Slice4)。
"""

from __future__ import annotations

# [canonical-entity-slice1 / 2026-06-08] import safety net (JARVIS_PYTHON_STYLE §1)
import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import re  # noqa: F401
import time
import json
import threading
import collections  # noqa: F401
from typing import Dict, List, Optional, Any, Tuple

# 注意: 本模块**绝不** import jarvis_relational_manifold / numpy / 任何 embedding —
# 守"manifold 核心零改动" + "禁相似度" 红线 (tests T7 静态扫)。

# ---------------------------------------------------------------------------
# Status / source 常量
# ---------------------------------------------------------------------------

STATUS_ACTIVE = "active"
STATUS_PROPOSED = "proposed"   # 软源 (cosine/llm) 预留, 本片不产
STATUS_REVOKED = "revoked"     # 终态: 不被 exact 写入路径自动复活

SOURCE_EXACT = "exact"         # 硬源 (kinship 表命中)
SOURCE_COSINE = "cosine"       # 软源预留
SOURCE_LLM = "llm"             # 软源预留

# 接地层: 硬源可 active; 软源只能 proposed
_HARD_SOURCES = frozenset({SOURCE_EXACT})


def _log(msg: str) -> None:
    try:
        from jarvis_utils import bg_log
        bg_log(msg)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# kinship 别名表 (准则6 三件套: JSON + CLI + py seed fallback)
# ---------------------------------------------------------------------------

# py seed fallback — json 缺失/损坏时兜底 (与 kinship_alias_vocab.json 同内容)。
# 🆕 [canonical-entity-slice1 取舍裁定] 已删单字 surface ("妈"/"爸"): 子串命中下单字假阳性
# 高 (妈呀/干爸)。多字形 (妈妈/我妈/老妈/母亲) 已覆盖真实指称。日后漏接走 CLI --add-surface 补。
_SEED_KINSHIP: Dict[str, Dict[str, Any]] = {
    "person:mother": {"label": "母亲", "relation": "mother",
                      "surfaces": ["母亲", "妈妈", "我妈", "老妈"]},
    "person:father": {"label": "父亲", "relation": "father",
                      "surfaces": ["父亲", "爸爸", "我爸", "老爸"]},
    "person:elder_brother": {"label": "哥哥", "relation": "elder_brother",
                             "surfaces": ["哥哥", "大哥", "我哥"]},
    "person:elder_sister": {"label": "姐姐", "relation": "elder_sister",
                            "surfaces": ["姐姐", "我姐"]},
    "person:younger_brother": {"label": "弟弟", "relation": "younger_brother",
                               "surfaces": ["弟弟", "我弟"]},
    "person:younger_sister": {"label": "妹妹", "relation": "younger_sister",
                              "surfaces": ["妹妹", "我妹"]},
    "person:paternal_grandfather": {"label": "爷爷", "relation": "paternal_grandfather",
                                    "surfaces": ["爷爷"]},
    "person:paternal_grandmother": {"label": "奶奶", "relation": "paternal_grandmother",
                                    "surfaces": ["奶奶"]},
    "person:maternal_grandfather": {"label": "外公", "relation": "maternal_grandfather",
                                    "surfaces": ["外公", "姥爷"]},
    "person:maternal_grandmother": {"label": "外婆", "relation": "maternal_grandmother",
                                    "surfaces": ["外婆", "姥姥"]},
}

_KINSHIP_PATH = os.path.join("memory_pool", "kinship_alias_vocab.json")
_KINSHIP_CACHE: Optional[Dict[str, Dict[str, Any]]] = None
_KINSHIP_REVERSE: Optional[Dict[str, Tuple[str, str, str]]] = None
_KINSHIP_MTIME: float = -1.0
_KINSHIP_LOCK = threading.Lock()


def _load_kinship() -> Dict[str, Dict[str, Any]]:
    """读 kinship 表 (json override seed, mtime cache)。返回 {cid: {label, relation, surfaces}}。"""
    global _KINSHIP_CACHE, _KINSHIP_REVERSE, _KINSHIP_MTIME
    try:
        mtime = os.path.getmtime(_KINSHIP_PATH) if os.path.exists(_KINSHIP_PATH) else 0.0
    except OSError:
        mtime = 0.0
    with _KINSHIP_LOCK:
        if _KINSHIP_CACHE is None or mtime != _KINSHIP_MTIME:
            data = dict(_SEED_KINSHIP)
            try:
                if os.path.exists(_KINSHIP_PATH):
                    with open(_KINSHIP_PATH, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    k = raw.get("kinship", raw) if isinstance(raw, dict) else {}
                    if isinstance(k, dict) and k:
                        data = k
            except Exception as exc:
                _log(f"[canonical-entity-slice1] kinship load failed ({exc!r}) — seed fallback")
                data = dict(_SEED_KINSHIP)
            # 构建反向索引 surface → (cid, label, relation), exact, 不做相似度。
            rev: Dict[str, Tuple[str, str, str]] = {}
            for cid, meta in data.items():
                if not isinstance(meta, dict):
                    continue
                label = str(meta.get("label", ""))
                relation = str(meta.get("relation", ""))
                for s in meta.get("surfaces", []) or []:
                    s = str(s).strip()
                    if s:
                        rev[s] = (cid, label, relation)
            _KINSHIP_CACHE = data
            _KINSHIP_REVERSE = rev
            _KINSHIP_MTIME = mtime
        return _KINSHIP_CACHE


def get_kinship_table() -> Dict[str, Dict[str, Any]]:
    """公开: 当前 kinship 表 (cid → meta)。"""
    return dict(_load_kinship())


def lookup_kinship_surfaces(text: str) -> List[Tuple[str, Tuple[str, str, str]]]:
    """对 kinship 表所有 surfaces 做**整词子串命中** (exact, 禁相似度, 不切词)。

    取舍裁定: 采 surface-in-text 整词子串命中 (零误切、最小侵入)。命中即产出
    (surface, (cid, label, relation))。同一 cid 多 surface 命中 → 各产一条
    (writeback 侧用 resolve 门控 + touch 去重防重复触达)。

    返回命中列表 (插入序稳定); 无命中 → []。失败非致命 (返 [])。
    """
    if not text:
        return []
    try:
        _load_kinship()
        rev = _KINSHIP_REVERSE or {}
        out: List[Tuple[str, Tuple[str, str, str]]] = []
        for surface, meta in rev.items():
            if surface and surface in text:
                out.append((surface, meta))
        return out
    except Exception as exc:
        _log(f"[canonical-entity-slice1] lookup_kinship_surfaces failed ({exc!r})")
        return []


# ---------------------------------------------------------------------------
# [canonical-soft-proposer-slice2] 软源词表 (路线A: 离散整词命中, 不烧 LLM)
# ---------------------------------------------------------------------------
# 软词表 = 扩展指称表面 (口语别称等), 命中 → 产 proposed (绝不 active)。与 kinship
# 硬种子表物理分离 (不同 json), 防"软词混进硬源自动 active"。准则6 三件套同款。
# py seed 兜底; json override; mtime cache。
_SEED_SOFT_ENTITY: Dict[str, Dict[str, Any]] = {
    # 软指称 (口语/昵称) — 命中只产 proposed, 待硬接地或 Sir 确认才升 active。
    "person:mother": {"label": "母亲", "relation": "mother",
                      "surfaces": ["妈咪", "娘"]},
    "person:father": {"label": "父亲", "relation": "father",
                      "surfaces": ["爹", "老爷子"]},
}

_SOFT_ENTITY_PATH = os.path.join("memory_pool", "soft_entity_vocab.json")
_SOFT_ENTITY_REVERSE: Optional[Dict[str, Tuple[str, str, str]]] = None
_SOFT_ENTITY_MTIME: float = -1.0
_SOFT_ENTITY_LOCK = threading.Lock()


def _load_soft_entity() -> Dict[str, Tuple[str, str, str]]:
    """读软词表 (json override seed, mtime cache)。返回反向索引 surface→(cid,label,relation)。"""
    global _SOFT_ENTITY_REVERSE, _SOFT_ENTITY_MTIME
    try:
        mtime = os.path.getmtime(_SOFT_ENTITY_PATH) if os.path.exists(_SOFT_ENTITY_PATH) else 0.0
    except OSError:
        mtime = 0.0
    with _SOFT_ENTITY_LOCK:
        if _SOFT_ENTITY_REVERSE is None or mtime != _SOFT_ENTITY_MTIME:
            data = dict(_SEED_SOFT_ENTITY)
            try:
                if os.path.exists(_SOFT_ENTITY_PATH):
                    with open(_SOFT_ENTITY_PATH, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    k = raw.get("soft_entity", raw) if isinstance(raw, dict) else {}
                    if isinstance(k, dict) and k:
                        data = k
            except Exception as exc:
                _log(f"[canonical-soft-proposer-slice2] soft vocab load failed ({exc!r}) — seed")
                data = dict(_SEED_SOFT_ENTITY)
            rev: Dict[str, Tuple[str, str, str]] = {}
            for cid, meta in data.items():
                if not isinstance(meta, dict):
                    continue
                label = str(meta.get("label", ""))
                relation = str(meta.get("relation", ""))
                for s in meta.get("surfaces", []) or []:
                    s = str(s).strip()
                    if s:
                        rev[s] = (cid, label, relation)
            _SOFT_ENTITY_REVERSE = rev
            _SOFT_ENTITY_MTIME = mtime
        return _SOFT_ENTITY_REVERSE


def lookup_soft_surfaces(text: str) -> List[Tuple[str, Tuple[str, str, str]]]:
    """[canonical-soft-proposer-slice2] 软词表整词子串命中 (离散, 禁相似度, 不烧 LLM)。

    命中 → (surface, (cid, label, relation))。供软提议产 proposed。无命中 → []。
    """
    if not text:
        return []
    try:
        rev = _load_soft_entity() or {}
        return [(surface, meta) for surface, meta in rev.items()
                if surface and surface in text]
    except Exception as exc:
        _log(f"[canonical-soft-proposer-slice2] lookup_soft_surfaces failed ({exc!r})")
        return []


# ---------------------------------------------------------------------------
# CanonicalEntityRegistry — 外挂 registry (与 manifold 物理分离)
# ---------------------------------------------------------------------------

class CanonicalEntityRegistry:
    """corrigible canonical 实体 registry。无 LLM、无相似度、纯 exact dict。

    存储 (memory_pool/canonical_entities.json):
        {"_meta": {...},
         "entities": {"<cid>": {CanonicalEntity}, ...},
         "alias_links": {"<surface>": {AliasLink}, ...}}

    与 manifold (relational_manifold.json 的 _aliases) **物理分离**: 不同文件/对象/key 空间。
    """

    _DEFAULT_PATH = os.path.join("memory_pool", "canonical_entities.json")

    def __init__(self, path: Optional[str] = None):
        self.path = path or self._DEFAULT_PATH
        self._lock = threading.RLock()
        self._entities: Dict[str, Dict[str, Any]] = {}
        self._alias_links: Dict[str, Dict[str, Any]] = {}
        self._load()

    # ---- persistence ----
    def _load(self) -> None:
        with self._lock:
            self._entities = {}
            self._alias_links = {}
            if not os.path.exists(self.path):
                return
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    ent = data.get("entities", {})
                    al = data.get("alias_links", {})
                    self._entities = ent if isinstance(ent, dict) else {}
                    self._alias_links = al if isinstance(al, dict) else {}
            except Exception as exc:
                _log(f"[canonical-entity-slice1] registry load failed ({exc!r}) — empty")
                self._entities = {}
                self._alias_links = {}

    def save(self) -> None:
        with self._lock:
            payload = {
                "_meta": {
                    "schema": "canonical_entities",
                    "schema_version": 1,
                    "purpose": "corrigible canonical 实体层 (外挂, 与 manifold 物理分离)",
                    "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "entity_count": len(self._entities),
                    "alias_count": len(self._alias_links),
                    "edit_via": "scripts/kinship_alias_dump.py (种子) / corrigible ops (纠正)",
                },
                "entities": self._entities,
                "alias_links": self._alias_links,
            }
            tmp = self.path + ".tmp"
            try:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            except Exception as exc:
                _log(f"[canonical-entity-slice1] registry save failed ({exc!r})")

    # ---- grounding 闸 helper ----
    @staticmethod
    def _valid_provenance(provenance: Any) -> List[Dict[str, Any]]:
        """过滤合法 GroundingRef (须有非空 ref)。无接地不入图。"""
        out: List[Dict[str, Any]] = []
        if not isinstance(provenance, (list, tuple)):
            return out
        for g in provenance:
            if isinstance(g, dict) and str(g.get("ref", "")).strip():
                out.append({
                    "source_kind": str(g.get("source_kind", "")),
                    "ref": str(g.get("ref")),
                    "ts": float(g.get("ts", time.time())),
                    "detail": str(g.get("detail", ""))[:200],
                })
        return out

    @staticmethod
    def _merge_provenance(existing: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> None:
        """合并 provenance (按 (source_kind, ref) 去重, 命中刷新 ts + count)。in-place。"""
        for g in new:
            hit = None
            for p in existing:
                if p.get("source_kind") == g.get("source_kind") and p.get("ref") == g.get("ref"):
                    hit = p
                    break
            if hit is not None:
                hit["ts"] = g.get("ts", hit.get("ts"))
                hit["count"] = int(hit.get("count", 1)) + 1
                if g.get("detail"):
                    hit["detail"] = g["detail"]
            else:
                rec = dict(g)
                rec["count"] = 1
                existing.append(rec)

    # ---- API 1: resolve_surface_to_cid ----
    def resolve_surface_to_cid(self, surface: str) -> Optional[str]:
        """exact 查 surface → cid。**只认 active AliasLink** (revoked/proposed 不返)。

        纯 dict 精确查, 零相似度。必修门控核心: revoked 链不命中 → writeback 不再 touch。
        """
        if not surface:
            return None
        with self._lock:
            link = self._alias_links.get(surface)
            if link and link.get("status") == STATUS_ACTIVE:
                return link.get("cid")
        return None

    # ---- API 2: create_canonical_entity ----
    def create_canonical_entity(
        self, cid: str, attrs: Optional[Dict[str, Any]], provenance: List[Dict[str, Any]],
    ) -> bool:
        """建/合并 canonical 实体。空 provenance → 拒 (无接地不入图)。幂等 (已存在则合并)。"""
        if not cid:
            return False
        gprov = self._valid_provenance(provenance)
        if not gprov:
            _log(f"[canonical-entity-slice1] REJECT entity {cid} (no grounding provenance)")
            return False
        now = time.time()
        attrs = attrs or {}
        with self._lock:
            e = self._entities.get(cid)
            if e is None:
                self._entities[cid] = {
                    "cid": cid,
                    "kind": cid.split(":", 1)[0] if ":" in cid else "entity",
                    "canonical_label": str(attrs.get("canonical_label", "")),
                    "relation_to_sir": attrs.get("relation_to_sir"),
                    "attributes": {k: v for k, v in attrs.items()
                                   if k not in ("canonical_label", "relation_to_sir")},
                    "provenance": gprov,
                    "touch_refs": [],
                    "first_seen": now,
                    "last_seen": now,
                    "status": STATUS_ACTIVE,
                }
            else:
                # 幂等: 不重建, 合并 provenance + 刷新 last_seen
                self._merge_provenance(e.setdefault("provenance", []), gprov)
                e["last_seen"] = now
                if not e.get("canonical_label") and attrs.get("canonical_label"):
                    e["canonical_label"] = str(attrs["canonical_label"])
                if e.get("relation_to_sir") is None and attrs.get("relation_to_sir") is not None:
                    e["relation_to_sir"] = attrs["relation_to_sir"]
        return True

    # ---- API 3: add_canonical_alias_link ----
    def add_canonical_alias_link(
        self, surface: str, cid: str, *, source: str, ref: str,
        decided_by: str = "system_exact",
    ) -> bool:
        """建/刷新 surface→cid AliasLink。空 ref → 拒。

        来源信任: 硬源 (exact) → active; 软源 (cosine/llm) → proposed。
        幂等 (重复 surface→同 cid active): 不新建, append provenance 去重 + 刷新 ts。
        冲突 (surface 已 active 指别的 cid): 不静默改写, 拒 (留 Sir re-relate)。
        **revoked 终态**: 已 revoked 的链, exact 写入路径**不自动复活** (返 False);
          只 Sir 显式 re-relate / add-surface 翻 (必修裁定)。
        """
        if not surface or not cid:
            return False
        if not str(ref).strip():
            _log(f"[canonical-entity-slice1] REJECT alias {surface}->{cid} (no ref)")
            return False
        now = time.time()
        status = STATUS_ACTIVE if source in _HARD_SOURCES else STATUS_PROPOSED
        confidence = 1.0 if source in _HARD_SOURCES else 0.5
        gref = {"source_kind": source, "ref": str(ref), "ts": now,
                "detail": f"{source}:{surface}->{cid}"}
        with self._lock:
            link = self._alias_links.get(surface)
            if link is not None:
                # revoked 终态: exact 写入路径不复活 (必修)
                if link.get("status") == STATUS_REVOKED:
                    return False
                # 冲突: 已指别的 cid → 不静默改写
                if link.get("cid") != cid:
                    _log(f"[canonical-entity-slice1] CONFLICT alias {surface}: "
                         f"{link.get('cid')} != {cid} (拒自动改写, 留 Sir re-relate)")
                    return False
                # 幂等: 同 cid → 合并 provenance, 刷新 ts
                self._merge_provenance(link.setdefault("provenance", []), [gref])
                link["ts"] = now
                return True
            self._alias_links[surface] = {
                "surface": surface, "cid": cid, "source": source,
                "confidence": confidence, "status": status,
                "provenance": [dict(gref, count=1)],
                "ts": now, "decided_by": decided_by, "audit": [],
            }
        return True

    # ---- API 4: get_canonical_node ----
    def get_canonical_node(self, cid: str) -> Optional[Dict[str, Any]]:
        """只读快照 (含 touch_count = len(touch_refs))。不存在返 None。"""
        with self._lock:
            e = self._entities.get(cid)
            if e is None:
                return None
            snap = dict(e)
            snap["touch_count"] = len(e.get("touch_refs", []))
            return snap

    # ---- 触达 (同 turn 去重) ----
    def touch(self, cid: str, turn_id: Optional[str]) -> bool:
        """记一次触达 (同一 turn 对同一 cid 只记一次 = read-time fold 写入侧归并)。

        返回 True = 真记了一次新触达; False = 同 turn 重复/实体不存在/空 turn 跳过。
        """
        if not cid or not turn_id:
            return False
        with self._lock:
            e = self._entities.get(cid)
            if e is None:
                return False
            refs = e.setdefault("touch_refs", [])
            if turn_id in refs:
                return False
            refs.append(turn_id)
            e["last_seen"] = time.time()
        return True

    # ---- Slice2 软源提议 ops ----
    def get_alias_link(self, surface: str) -> Optional[Dict[str, Any]]:
        """[canonical-soft-proposer-slice2] 只读返回 surface 的 AliasLink 原始记录 (含 status)。
        不存在返 None。供软提议幂等去重 / 升级钩子查 status 用。"""
        if not surface:
            return None
        with self._lock:
            link = self._alias_links.get(surface)
            return dict(link) if link is not None else None

    def add_soft_alias_link(
        self, surface: str, cid: str, *, source: str = SOURCE_LLM, ref: str,
    ) -> bool:
        """[canonical-soft-proposer-slice2] 软源 (llm/cosine) → 产 **proposed** AliasLink。

        硬条件①(幂等去重, 防双建): 产 proposed 前查 surface→cid 当前状态:
          - 已 active 同 cid  → no-op (硬源已建真, 软源不重复产 proposed, 返 False)
          - 已 proposed 同 cid → no-op (已提议过, 不重复, 返 False)
          - revoked          → no-op (Sir 撤过, 软源不复活, 返 False)
          - active/proposed 指别 cid → 冲突, 不静默改写 (返 False)
          - 不存在            → 建 proposed (返 True)
        软源**绝不** active (source 不在 _HARD_SOURCES → add_canonical_alias_link
        本会自动 proposed, 但这里先做去重/边界守, 再委派)。
        """
        if not surface or not cid:
            return False
        if source in _HARD_SOURCES:
            # 软提议入口拒硬源 (硬源走 add_canonical_alias_link), 防绕过 status 分流。
            _log(f"[canonical-soft-proposer-slice2] REJECT soft alias {surface}->{cid} "
                 f"(source={source} 是硬源, 软入口不接)")
            return False
        if not str(ref).strip():
            return False
        with self._lock:
            link = self._alias_links.get(surface)
            if link is not None:
                st = link.get("status")
                lcid = link.get("cid")
                # 硬条件③同款: revoked 软源不复活
                if st == STATUS_REVOKED:
                    return False
                # 硬条件①: 已 active/proposed 同 cid → no-op (不重复产)
                if lcid == cid and st in (STATUS_ACTIVE, STATUS_PROPOSED):
                    return False
                # 冲突: 指别的 cid → 不静默改写
                if lcid != cid:
                    _log(f"[canonical-soft-proposer-slice2] CONFLICT soft alias {surface}: "
                         f"{lcid} != {cid} (拒, 留 Sir re-relate)")
                    return False
        # 委派 add_canonical_alias_link (source=llm → 自动 status=proposed)
        ok = self.add_canonical_alias_link(
            surface, cid, source=source, ref=ref, decided_by="soft_proposer")
        if ok:
            _log(f"[canonical-soft-proposer-slice2] propose alias surface={surface} "
                 f"-> {cid} source={source} (status=proposed)")
        return ok

    def activate_alias_link(self, surface: str, *, by: str = "sir",
                            reason: str = "", expect_cid: Optional[str] = None) -> bool:
        """[canonical-soft-proposer-slice2] 升级 proposed → active (+ audit 留痕)。

        与 re_relate_surface (改 relation) **不同**: 本 op 只升级 status, 不改 cid/relation。
        硬条件②(严格内容匹配): expect_cid 非空时, 必须 surface 当前指向 == expect_cid 才升,
          否则拒 (防"硬源来了把任意 proposed 都升")。
        硬条件③(不复活 revoked): 自动升级路径 (by='auto_hard_grounding') 遇 revoked → 拒;
          只有 Sir 显式 (by='sir') 才能把 revoked 翻回 active (corrigibility: Sir 元否决)。
        非 proposed 状态:
          - active  → no-op 返 True (已是目标态, 幂等)
          - revoked → 见硬条件③ (auto 拒 / sir 复活)
          - 不存在  → False
        """
        with self._lock:
            link = self._alias_links.get(surface)
            if link is None:
                return False
            st = link.get("status")
            lcid = link.get("cid")
            # 硬条件②: 严格内容匹配 (同 surface 同 cid)
            if expect_cid is not None and lcid != expect_cid:
                _log(f"[canonical-soft-proposer-slice2] activate SKIP {surface}: "
                     f"cid {lcid} != expect {expect_cid} (内容不匹配, 不误升)")
                return False
            if st == STATUS_ACTIVE:
                return True  # 幂等
            # 硬条件③: revoked 不被自动升级复活
            if st == STATUS_REVOKED:
                if by == "sir":
                    link["status"] = STATUS_ACTIVE
                    link.setdefault("audit", []).append({
                        "op": "activate_from_revoked", "by": by,
                        "reason": reason, "ts": time.time(),
                    })
                    _log(f"[canonical-soft-proposer-slice2] Sir 显式 activate "
                         f"(revoked→active) surface={surface}")
                    return True
                _log(f"[canonical-soft-proposer-slice2] activate REFUSE {surface}: "
                     f"revoked, 非 Sir 不复活 (by={by}, 守撤销意志)")
                return False
            if st == STATUS_PROPOSED:
                link["status"] = STATUS_ACTIVE
                link["confidence"] = 1.0
                link.setdefault("audit", []).append({
                    "op": "activate", "by": by, "reason": reason, "ts": time.time(),
                })
                _log(f"[canonical-soft-proposer-slice2] activate proposed→active "
                     f"surface={surface} cid={lcid} by={by}")
                return True
            return False

    def list_proposed(self) -> List[Dict[str, Any]]:
        """[canonical-soft-proposer-slice2] 列所有 proposed AliasLink (Sir 待确认队列)。"""
        with self._lock:
            return [dict(l) for l in self._alias_links.values()
                    if l.get("status") == STATUS_PROPOSED]

    # ---- corrigible ops: revoke + rename (本片实现) ----
    def revoke_alias_link(self, surface: str, *, by: str = "sir", reason: str = "") -> bool:
        """撤一条 AliasLink (status→revoked, 终态 + audit 留痕)。撤后 resolve 不再命中。"""
        with self._lock:
            link = self._alias_links.get(surface)
            if link is None:
                return False
            link["status"] = STATUS_REVOKED
            link.setdefault("audit", []).append({
                "op": "revoke", "by": by, "reason": reason, "ts": time.time(),
            })
        _log(f"[canonical-entity-slice1] revoke alias surface={surface} by={by}")
        return True

    def rename_canonical(self, cid: str, new_label: str, *, by: str = "sir") -> bool:
        """改 canonical_label (不动 cid / 不动 alias 链 + audit 留痕)。"""
        if not new_label:
            return False
        with self._lock:
            e = self._entities.get(cid)
            if e is None:
                return False
            old = e.get("canonical_label", "")
            e["canonical_label"] = str(new_label)
            e.setdefault("audit", []).append({
                "op": "rename", "by": by, "old": old, "new": str(new_label),
                "ts": time.time(),
            })
        _log(f"[canonical-entity-slice1] rename {cid}: {old!r}->{new_label!r} by={by}")
        return True

    # ---- 接口预留 (本片不实现, 标记) ----
    def merge_canonical(self, cid_from: str, cid_to: str, **kw) -> bool:  # noqa: D401
        """接口预留 (Slice 后续): 两 cid 合一 (记录式)。本片 NotImplemented。"""
        raise NotImplementedError("merge_canonical 接口预留, Slice 1 不实现")

    def split_canonical(self, cid: str, **kw) -> bool:
        """接口预留 (Slice 后续): 一 cid 拆二 (记录式)。本片 NotImplemented。"""
        raise NotImplementedError("split_canonical 接口预留, Slice 1 不实现")

    def re_relate_surface(self, surface: str, cid: str, **kw) -> bool:
        """接口预留 (Slice 后续): surface 改指 cid (旧 revoke + 新 active)。本片 NotImplemented。"""
        raise NotImplementedError("re_relate_surface 接口预留, Slice 1 不实现")


# ---------------------------------------------------------------------------
# 单例 (仿 get_manifold)
# ---------------------------------------------------------------------------

_REGISTRY_SINGLETON: Optional[CanonicalEntityRegistry] = None
_REGISTRY_LOCK = threading.Lock()


def get_canonical_registry() -> CanonicalEntityRegistry:
    """全局单例 (生产路径用)。test 用 CanonicalEntityRegistry(path) 直接构造隔离。"""
    global _REGISTRY_SINGLETON
    if _REGISTRY_SINGLETON is None:
        with _REGISTRY_LOCK:
            if _REGISTRY_SINGLETON is None:
                _REGISTRY_SINGLETON = CanonicalEntityRegistry()
    return _REGISTRY_SINGLETON
