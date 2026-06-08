#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[body-diff-P1 设计验证 / Sir 2026-06-06] 接地偏权 spread 镜像 — 只读, 无 LLM, 无写回.

真理源: docs/AGENT_KICKOFF_BODY_DIFFERENTIATION.md §15 (终态) + §15.6/15.7 (P1 三门) +
本轮 Sir P1 设计验证交接 (接地偏权 spread 5 条 + 镜像验证规格)。

⚠️ 只读诊断 / 非生产路径: 复制生产体到 temp, 沙盒跑, 绝不 .save 写回; 不碰任何 flag;
不开/关 lens; 不改存储; 不 commit 行为变更。import 链只触 manifold + weaver (已 verify
不在脏改动集)。

回答唯一问题: 薄+embed-mesh 体上, spread 投影能否只投人读为真的接地关联, 且绝不把人读已
证伪的假焊 (hand_pain<->interview cooccur / 监控-thread cosine mesh) 投进主脑 prompt?

两档对照 (复用生产 lens 投影口径: spread → 取激活 top-N 节点文本):
  OFF (naive 全边权)  = 当前生产真实行为 (lens.project 走 manifold.spread, 全边遍历).
                        量"贾维斯现在正被喂多少假焊"。
  ON  (接地偏权)       = spread 只沿 PROV_SHARED about 边 (带 concern_id) 传播;
                        embed(cosine)/cooccur 边权=0 不走 (两半假焊都排, §15.7);
                        seed 无接地路径 → 诚实返回空 (不变量①, 不回退 embed 填满)。

准则 6.5: edge-class 权重 + 接地阈值走 vocab (memory_pool/manifold_p1_spread_vocab.json)
+ py SEED fallback (本文件 _SEED_P1_SPREAD)。无 vocab 文件 → 用 seed, 不硬编死。

用法: python scripts/manifold_p1_spread_mirror.py
验收: Sir 手标"真关联 vs 假关联"清单, 看 OFF 是否投假焊 (预期 yes=坐实)、ON 是否只投真
接地 + 无路径时沉默 (预期 yes=修法成立)。
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
import time

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
    RelationalManifold, split_node_id, make_node_id, KIND_CONCERN,
    PROV_SHARED, PROV_SAID,
)
from jarvis_relational_weaver import RelationalWeaver  # noqa: E402

SRC = os.path.join(ROOT, "memory_pool", "relational_manifold.json")
P1_VOCAB = os.path.join(ROOT, "memory_pool", "manifold_p1_spread_vocab.json")

# 准则 6.5: py SEED fallback (vocab 文件不存在时用这个, 不硬编死参数)
_SEED_P1_SPREAD = {
    # 接地偏权: 这些 provenance 算"真接地 about 边", spread 只沿它们走 (§15.7 只 PROV_SHARED,
    # cooccur 虽 grounded-type 但虚假 → 不列入; said 是 Sir 显式连接, 真接地 → 列入)。
    "grounded_about_provenance": [PROV_SHARED, PROV_SAID],
    # spread 遍历参数 (与生产 lens.project 默认对齐, 便于同口径对照)
    "hops": 2,
    "decay_per_hop": 0.5,
    "min_activation": 0.08,
    "project_max_nodes": 10,
}


def _p1cfg() -> dict:
    cfg = dict(_SEED_P1_SPREAD)
    try:
        if os.path.exists(P1_VOCAB):
            ov = json.load(open(P1_VOCAB, encoding="utf-8"))
            cfg.update(ov.get("config", ov))
    except Exception:
        pass
    return cfg


def _edge_provs(e) -> set:
    return {p.get("kind") for p in e.get("provenance", [])}


def _grounded_neighbors(m, node, grounded_kinds, now):
    """node 的接地 about 邻居 [(other, eff_w)] — 只含 provenance ∩ grounded_kinds 的边。"""
    out = []
    for key in m._adj.get(node, ()):
        e = m._edges.get(key)
        if not e:
            continue
        if not (_edge_provs(e) & grounded_kinds):
            continue
        w = m.effective_weight(e, now)
        other = e["b"] if e["a"] == node else e["a"]
        out.append((other, w))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def _spread(m, seeds, *, grounded_only, grounded_kinds, hops, decay_per_hop,
            min_activation, now):
    """spreading-activation. grounded_only=False → 复刻生产 manifold.spread (全边, OFF);
    grounded_only=True → 只沿 about 接地边 (ON)。返 {node: activation}。"""
    activation = {}
    frontier = {s: 1.0 for s in seeds if s}
    for s in frontier:
        activation[s] = 1.0
    for _hop in range(max(0, hops)):
        nxt = {}
        for node, act in frontier.items():
            if grounded_only:
                nbrs = _grounded_neighbors(m, node, grounded_kinds, now)
            else:
                nbrs = m.neighbors(node, now=now, limit=None)  # 全边, 同生产
            for other, w in nbrs:
                new_act = act * decay_per_hop * math.tanh(w)
                if new_act < min_activation:
                    continue
                if new_act > nxt.get(other, 0.0):
                    nxt[other] = new_act
        for node, act in nxt.items():
            if act > activation.get(node, 0.0):
                activation[node] = act
        frontier = nxt
        if not frontier:
            break
    return activation


def _project(m, activation, seed_set, text_map, max_nodes):
    """复刻 lens.project 的取节点口径: resolve 去重 + 排 seed/无文本 + top-N。
    返 [(node, score, text)]。"""
    best = {}
    for nid, score in activation.items():
        rep = m.resolve(nid)
        if rep in seed_set or rep not in text_map:
            continue
        if score > best.get(rep, -1.0):
            best[rep] = score
    rows = sorted(best.items(), key=lambda x: x[1], reverse=True)[:max_nodes]
    return [(n, s, (text_map.get(n) or "").strip().replace("\n", " ")) for n, s in rows]


def _path_kind(m, seed_set, target, grounded_kinds, now):
    """target 是否经 ≥1 条 about 接地边可从某 seed 1-hop 到达? 粗判投影来源:
    返 'about' 若 target 与任一 seed 有直接 about 边; 否则 'non-about(假焊/embed/cooccur)'。
    (2-hop 简化: 只标直接边类型, 给 Sir 看"这条投影是不是接地来的"。)"""
    for s in seed_set:
        e = m.get_edge(s, target)
        if e and (_edge_provs(e) & grounded_kinds):
            return "about"
    return "non-about"


def _run_seed(m, seed, text_map, cfg, now):
    grounded_kinds = set(cfg["grounded_about_provenance"])
    seed_set = {seed}
    kw = dict(hops=cfg["hops"], decay_per_hop=cfg["decay_per_hop"],
              min_activation=cfg["min_activation"], now=now)
    off = _spread(m, [seed], grounded_only=False, grounded_kinds=grounded_kinds, **kw)
    on = _spread(m, [seed], grounded_only=True, grounded_kinds=grounded_kinds, **kw)
    off_p = _project(m, off, seed_set, text_map, cfg["project_max_nodes"])
    on_p = _project(m, on, seed_set, text_map, cfg["project_max_nodes"])
    seed_txt = (text_map.get(seed) or "").strip().replace("\n", " ")
    print("\n" + "=" * 72)
    print(f"SEED: {seed}")
    print(f"      {seed_txt[:90]}")
    print("=" * 72)
    print(f"  --- OFF (naive 全边权 = 当前生产真实投影) {len(off_p)} 节点 ---")
    if not off_p:
        print("    (空)")
    for n, s, t in off_p:
        src = _path_kind(m, seed_set, n, grounded_kinds, now)
        flag = "  ⚠️非接地" if src == "non-about" else "  ✓接地"
        print(f"    [{split_node_id(n)[0]:7}] act={s:.3f}{flag}  {t[:62]}")
    n_off = len(off_p)
    n_off_fake = sum(1 for n, _, _ in off_p
                     if _path_kind(m, seed_set, n, grounded_kinds, now) == "non-about")
    print(f"  --- ON (接地偏权 只走 about 边) {len(on_p)} 节点 ---")
    if not on_p:
        print("    (空 — 诚实沉默: 该 seed 无接地路径, 不回退 embed 填满 [不变量①])")
    for n, s, t in on_p:
        print(f"    [{split_node_id(n)[0]:7}] act={s:.3f}  ✓接地  {t[:62]}")
    return n_off, n_off_fake, len(on_p)


def main() -> int:
    if not os.path.exists(SRC):
        print(f"(无生产体数据 {SRC})")
        return 0
    cfg = _p1cfg()
    print(f"[P1 接地偏权 spread 镜像] 只读真数据, 沙盒, 无写回, 不碰 flag")
    print(f"  接地 about provenance (ON 只走这些): {cfg['grounded_about_provenance']}")
    print(f"  vocab 来源: {'磁盘 '+P1_VOCAB if os.path.exists(P1_VOCAB) else 'py SEED fallback (无 vocab 文件)'}")

    tmp = tempfile.mkdtemp(prefix="p1_spread_")
    dst = os.path.join(tmp, "m.json")
    shutil.copy(SRC, dst)
    try:
        m = RelationalManifold(dst)
        now = time.time()
        try:
            text_map = RelationalWeaver(manifold=m).harvest_nodes()
        except Exception:
            text_map = {}

        # 取真 seed: 含接地路径的 (hydration/interview/sleep 这些有 about 边的 concern)
        # + 已证伪假焊的 (hand_pain, interview — 看 OFF 是否互投) + 无接地孤儿。
        grounded_kinds = set(cfg["grounded_about_provenance"])
        # 找有 about 边的 concern 节点 (有接地路径)
        about_concerns = set()
        for e in m.all_edges():
            if _edge_provs(e) & grounded_kinds:
                for nd in (e["a"], e["b"]):
                    if split_node_id(nd)[0] == "concern":
                        about_concerns.add(m.resolve(nd))
        # 找一个无 about 边的孤儿 (joke/proto/thread, 无接地路径)
        all_nodes = {m.resolve(n) for n, ks in m._adj.items() if ks}
        orphan_no_about = []
        for n in sorted(all_nodes):
            has_about = any((_edge_provs(m._edges[k]) & grounded_kinds)
                            for k in m._adj.get(n, ()) if m._edges.get(k))
            if not has_about and split_node_id(n)[0] in ("joke", "proto", "thread"):
                orphan_no_about.append(n)

        print(f"\n  有 about 边的 concern (有接地路径): {sorted(split_node_id(c)[1] for c in about_concerns)}")
        print(f"  无 about 边的自产孤儿 (无接地路径, 取样 3): "
              f"{[split_node_id(n)[1][:30] for n in orphan_no_about[:3]]}")

        # 关键 seed: hand_pain + interview (人读已证伪互焊), hydration (真接地), 1 孤儿
        seeds = []
        for cid in ("sir_hand_pain_recurrence", "sir_interview_prep_balance",
                    "sir_hydration_habit", "sir_sleep_streak"):
            nid = make_node_id(KIND_CONCERN, cid)
            if nid in text_map or m.resolve(nid) in all_nodes:
                seeds.append(nid)
            else:
                print(f"  (skip seed {cid}: 不在当前体)")
        if orphan_no_about:
            seeds.append(orphan_no_about[0])

        tot_off = tot_fake = tot_on = 0
        for seed in seeds:
            n_off, n_fake, n_on = _run_seed(m, seed, text_map, cfg, now)
            tot_off += n_off
            tot_fake += n_fake
            tot_on += n_on

        print("\n" + "#" * 72)
        print("  汇总 (跨所有 seed)")
        print("#" * 72)
        print(f"  OFF 投影节点总数: {tot_off}")
        print(f"  其中经'非接地边'(embed/cooccur 假焊) 投进来的: {tot_fake}  "
              f"→ 假焊占 OFF 投影 {round(100*tot_fake/tot_off,1) if tot_off else 0}%")
        print(f"  ON  投影节点总数: {tot_on}  (只走 about 接地边; 0 = 全程诚实沉默)")
        print(f"\n  → Sir 止血决策依据: 假焊占比 = {round(100*tot_fake/tot_off,1) if tot_off else 0}% "
              f"(高 → 倾向先关 lens 止血; 低 → 可不关快上 ON 修法)")
        print(f"  → 修法成立判据: ON 只投接地 + 无路径沉默, 不靠假焊出内容 (人读上面每 seed 两档对照)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
