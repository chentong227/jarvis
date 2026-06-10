#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[body-diff-P0c Step1 / Sir 2026-06-06] 历史 about 边背填 镜像 — 只读, 无 LLM, 无写回.

真理源: docs/AGENT_KICKOFF_BODY_DIFFERENTIATION.md §14 (about 边设计) + §15 (终态裁定) +
本轮 Sir Step 1 交接 (链路 thread → evidence_thought_ids → inner_thoughts.jsonl thought →
parse actionable → concern_id; 一次性回放历史; 只连带 id 的; 严禁 cosine/lexical/Tier2 刷孤儿)。

⚠️ 只读诊断工具 / 非生产路径: 复制生产体到 temp, 在沙盒回放背填, 绝不 .save 写回真体。
背填 = 模拟"若 Tier1 前向捕捉从一开始就接着, 历史会建的 about 边"。机械/接地/非 cosine。

链路 (Sir 交接钉死, 与已落地 Tier1 同语义):
  thread (self_threads.json) → evidence_thought_ids → inner_thoughts.jsonl 那条 thought →
  parse actionable (adjust_concern_notes:<cid>:.. / update_concern_severity:<cid>:<val>) → concern_id
  → observe_thought_concern_link(thread_id, concern_id) = observe_shared_entity(
        [thread_node, concern_node], entity_id=concern_id)  (PROV_SHARED, grounded by concern_id)

§14.1 铁律: 只连真有 referent 的 (262 带可解析 concern_id 的 thought 经 evidence 链落到 thread);
~2975 条无 concern_id 的 (玩笑/说话风格 proto/自发) 留作孤儿 = 健康私人生活, 绝不凑接地。

Step 2 量 5 个数 (背填前/后两列):
  1. 面数 (surface_count)        — 期望 1 → 3-6
  2. largest_frac                — 不许暴涨 (暴涨=单面吞并=反向塌方=失败)
  3. 桥数 (bridge_count)         — >0, 多 concern 的 thread 自然成桥
  4. 孤儿数 (orphan: 有边但没进任何面) — 期望稳在 ~90
  5. operator-monitoring 占比     — 机械代理: about 边里指向 jarvis_*(自我/运维监控) concern 的占比
                                    (vs sir_* = Sir 真实生活 concern); 只测不修 (红线B 邻近)

用法: python scripts/manifold_p0c_step1_mirror.py
"""
from __future__ import annotations

import collections
import json
import os
import shutil
import sys
import tempfile
import time
import unittest.mock as mock

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_relational_manifold as rm  # noqa: E402
from jarvis_relational_manifold import (  # noqa: E402
    RelationalManifold, make_node_id, split_node_id, KIND_THREAD, KIND_CONCERN,
)
from jarvis_relational_weaver import (  # noqa: E402
    observe_thought_concern_link, RelationalWeaver,
)

SRC = os.path.join(ROOT, "memory_pool", "relational_manifold.json")
THOUGHTS = os.path.join(ROOT, "memory_pool", "inner_thoughts.jsonl")
ST = os.path.join(ROOT, "memory_pool", "self_threads.json")
VOCAB = os.path.join(ROOT, "memory_pool", "relational_manifold_vocab.json")


def _cfg() -> dict:
    c = json.loads(json.dumps(rm._SEED_MANIFOLD_CONFIG))
    try:
        if os.path.exists(VOCAB):
            ov = json.load(open(VOCAB, encoding="utf-8"))
            c = rm._deep_merge(c, ov.get("config", ov))
    except Exception:
        pass
    return c


def _parse_concern_id(actionable: str):
    """actionable → (concern_id, kind) 或 (None, None). kind ∈ {adjust, severity}. 纯机械."""
    a = (actionable or "").strip()
    if a.startswith("adjust_concern_notes:"):
        p = a.split(":", 2)
        if len(p) >= 3 and p[1].strip():
            return p[1].strip(), "adjust"
    elif a.startswith("update_concern_severity:"):
        p = a.split(":", 2)
        if len(p) >= 3 and p[1].strip():
            return p[1].strip(), "severity"
    return None, None


def _thought_index() -> dict:
    """inner_thoughts.jsonl: thought id -> thought dict."""
    idx = {}
    if not os.path.exists(THOUGHTS):
        return idx
    with open(THOUGHTS, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
            except Exception:
                continue
            tid = (t.get("id") or t.get("thought_id") or "").strip()
            if tid:
                idx[tid] = t
    return idx


def _backfill_pairs():
    """Sir 链路: thread → evidence_thought_ids → thought → actionable → concern_id.
    返 set((thread_id, concern_id))。只含带可解析 concern_id 的 (§14.1 铁律)。"""
    idx = _thought_index()
    st = json.load(open(ST, encoding="utf-8")) if os.path.exists(ST) else {}
    pairs = set()
    for th in st.get("threads", []) or []:
        tid = (th.get("thread_id") or "").strip()
        if not tid:
            continue
        for eid in th.get("evidence_thought_ids") or []:
            t = idx.get(eid)
            if not t:
                continue
            cid, _ = _parse_concern_id(t.get("actionable"))
            if cid:
                pairs.add((tid, cid))
    return pairs


def _strip_to_about_only(m):
    """about-only 配置 (同 manifold_deweld_mirror.py L2): 只留 about-接地 thread↔concern
    (shared/said) 边, 移除 embed mesh + cooccur + concern↔concern, 让 about 骨架显形。
    机械, 不删节点 (孤儿保留, 红线C 不删传记)。只在 temp 沙盒做。"""
    with m._lock:
        for key in list(m._edges.keys()):
            e = m._edges[key]
            ka = split_node_id(e["a"])[0]
            kb = split_node_id(e["b"])[0]
            ks = {p.get("kind") for p in e.get("provenance", [])}
            keep = ({ka, kb} == {"thread", "concern"}) and bool(ks & {"shared", "said"})
            if not keep:
                m._adj[e["a"]].discard(key)
                m._adj[e["b"]].discard(key)
                del m._edges[key]


def _measure(m, cfg, label):
    """量 5 个数 + 面/桥结构。只读。"""
    now = time.time()
    with mock.patch.object(rm, "get_manifold_config", return_value=cfg):
        surfaces = m.compute_surfaces(now=now)
        m.set_surfaces(surfaces)
        rep = m.complexity_report(now=now)
        bridges = m.bridge_nodes(surfaces)
        in_surf = set()
        for s in surfaces:
            in_surf.update(s.get("members", ()))
        all_nodes = {m.resolve(n) for n, ks in m._adj.items() if ks}
        orphans = all_nodes - in_surf
    surface_count = rep["surface_count"]
    largest_frac = rep["largest_surface_frac"]
    bridge_count = rep["bridge_count"]
    orphan_count = len(orphans)
    sizes = sorted((s["size"] for s in surfaces), reverse=True)
    print(f"\n=== {label} ===")
    print(f"  health={rep['health']}  nodes={rep['node_count']}  edges={rep['edge_count']}")
    print(f"  ① 面数={surface_count}   ② largest_frac={largest_frac}   "
          f"③ 桥数={bridge_count}   ④ 孤儿数={orphan_count}")
    print(f"  面 size 分布: {sizes[:12]}{' ...' if len(sizes) > 12 else ''}")
    # 桥里 concern 种类 (看是否多样, 防单一补水)
    bconcerns = sorted({split_node_id(n)[1] for n in bridges
                        if split_node_id(n)[0] == "concern"})
    print(f"  桥含 concern ({len(bconcerns)} 种): {bconcerns}")
    return {
        "surfaces": surface_count, "largest_frac": largest_frac,
        "bridges": bridge_count, "orphans": orphan_count,
        "surfaces_obj": surfaces, "bridge_concerns": bconcerns,
    }


def _operator_monitoring_share(pairs):
    """⑤ operator-monitoring 占比 — 机械代理 (无关键词硬编, 纯 concern_id 命名空间).
    jarvis_* concern = Jarvis 自我/运维监控 (keyrouter/internal_health 等); sir_* = Sir 真实生活。
    只测不修 (Sir trap #2, 红线B 邻近)。"""
    by_ns = collections.Counter()
    concern_hist = collections.Counter()
    for _, cid in pairs:
        concern_hist[cid] += 1
        if cid.startswith("jarvis_"):
            by_ns["jarvis_self/operator"] += 1
        elif cid.startswith("sir_"):
            by_ns["sir_reallife"] += 1
        else:
            by_ns["other"] += 1
    total = sum(by_ns.values())
    jshare = (by_ns["jarvis_self/operator"] / total) if total else 0.0
    return jshare, by_ns, concern_hist


def main() -> int:
    if not os.path.exists(SRC):
        print(f"(无生产体数据 {SRC})")
        return 0
    pairs = _backfill_pairs()
    jshare, by_ns, chist = _operator_monitoring_share(pairs)
    print(f"[P0c Step1 背填镜像] 只读真数据, 无写回")
    print(f"  Sir 链路落到的 (thread,concern) 对: {len(pairs)}  "
          f"(distinct thread={len({t for t,_ in pairs})}, distinct concern={len(chist)})")
    print(f"  concern 分布: {chist.most_common()}")
    print(f"  ⑤ operator-monitoring 代理: jarvis_*(自我/运维)={by_ns['jarvis_self/operator']} "
          f"sir_*(真实生活)={by_ns['sir_reallife']} other={by_ns['other']}  "
          f"→ jarvis 占 about 边 {round(100*jshare,1)}% (只测不修)")

    tmp = tempfile.mkdtemp(prefix="p0c_step1_")
    dst = os.path.join(tmp, "m.json")
    shutil.copy(SRC, dst)  # 只读: 复制到 temp, 绝不写回生产
    try:
        m = RelationalManifold(dst)
        cfg = _cfg()
        try:
            harvested = set(RelationalWeaver(manifold=m).harvest_nodes().keys())
        except Exception:
            harvested = set()

        before = _measure(m, cfg, "BEFORE — 真 manifold (背填前)")

        # 一次性回放历史背填: 只对当前 body 真实存在的 thread+concern 节点连边 (§14.5: 不造幽灵)
        applied = skipped = 0
        for tid, cid in sorted(pairs):
            tnode = make_node_id(KIND_THREAD, tid)
            cnode = make_node_id(KIND_CONCERN, cid)
            if tnode not in harvested or cnode not in harvested:
                skipped += 1
                continue
            if observe_thought_concern_link(tid, cid, manifold=m, save=False):
                applied += 1
        print(f"\n[背填] 应用 {applied} 条 about 边 (现存节点); "
              f"跳过 {skipped} 条 (节点已 aged-out, 避免造幽灵节点 §14.5)")

        after = _measure(m, cfg, "AFTER — +历史 about 边背填 (全存储图)")

        # ---- about-only 配置 (Sir 指定: 同 deweld L2, embed mesh 剥掉让 about 骨架显形) ----
        # 全存储图里 embed mesh 主导, 背填 about 边被 over_dense 掩盖 (§15.1)。Sir 要 about-only
        # 看背填对"接地骨架"这层的真实效果。
        #   before-about-only: 重新 load SRC (未背填) → strip
        #   after-about-only : 复用 m (已在内存背填 32 条, save=False 没落盘) → strip
        dst_b = os.path.join(tmp, "m_before.json")
        shutil.copy(SRC, dst_b)
        mb_before = RelationalManifold(dst_b)
        _strip_to_about_only(mb_before)
        ab_before = _measure(mb_before, cfg, "about-only BEFORE — 仅现存 about 边 (背填前)")
        _strip_to_about_only(m)  # m 已含背填 32 条 about 边
        ab_after = _measure(m, cfg, "about-only AFTER — 现存+背填 about 边")

        # ---- 5 数前后对比表 ----
        print("\n" + "=" * 64)
        print("  Step 2 验收 5 数 (背填前 → 背填后)")
        print("=" * 64)
        print(f"  {'指标':<26}{'全存储图':^26}{'about-only 配置':^26}")
        print(f"  {'':<26}{'前 → 后':^26}{'前 → 后':^26}")
        metrics = [
            ("① 面数 (期望 1→3-6)", "surfaces"),
            ("② largest_frac (不许暴涨)", "largest_frac"),
            ("③ 桥数 (期望 >0)", "bridges"),
            ("④ 孤儿数 (期望稳 ~90)", "orphans"),
        ]
        for name, k in metrics:
            full = f"{before[k]} → {after[k]}"
            abo = f"{ab_before[k]} → {ab_after[k]}"
            print(f"  {name:<26}{full:^26}{abo:^26}")
        print(f"  {'⑤ operator-monitoring 占比':<26}"
              f"{'about 边 jarvis_* 占 '+str(round(100*jshare,1))+'%':^52}")
        print(f"\n  桥 concern 种类 (全图): {before['bridge_concerns']} → {after['bridge_concerns']}")
        print(f"  桥 concern 种类 (about-only): {ab_before['bridge_concerns']} → {ab_after['bridge_concerns']}")
        print("\n  反向塌方守卫: largest_frac 暴涨 = 单面吞并 = 失败; 孤儿应稳不应爆。")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
