#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""[canonical-backfill-slice25 / 2026-06-08] LTM 情节 → canonical 软提议批量回填 CLI.

设计真理源: docs/process/JARVIS_SLICE25_BACKFILL_PROPOSER_DESIGN.md (顾问签收 + 三硬约束)。

做什么: 只读遍历 TaskMemories 历史情节 → 取 subject/keywords/intent 短语 → 子串扫
  kinship+soft 词表对齐 canonical cid → 复用 Slice2 add_soft_alias_link 产 **proposed**
  AliasLink (source='ltm_backfill')。绝不自动 active、绝不改数据源、对不齐跳过不硬凑。

三硬约束 (顾问覆盖设计原文):
  ① 范围收窄: 本片只 --source ltm。manifold raw 路砍出 (现网仅 2 垃圾 entity 节点,
     产出恒 0) → --source manifold = 显式 no-op + 提示, 留后续片。
  ② test 脏数据过滤: 见 _is_test_row (entities_json.source ∈ {unit_test,test_82x,test*}
     / intent 含 [测试]/test_ / macro_goal 含 test)。报过滤行数。
  ③ dry-run 出可读清单: 逐条 surface→cid + LTM subject 原文 (截断) + 当前状态
     (将产 proposed / 已 active 跳 / 已 proposed 跳 / revoked 跳)。

复用 (0 改产品判定): lookup_kinship_surfaces + lookup_soft_surfaces (cid 对齐) /
  add_soft_alias_link (产 proposed, 三硬条件守) / create_canonical_entity (实体)。
只读: 对 jarvis_memory.db 只开只读 SELECT (WHERE is_deleted=0), 绝不 UPDATE/写回。
不进热路径: 纯独立 CLI, --dry-run 默认, --apply 才写, 幂等可重入。

用法:
  python scripts/canonical_backfill.py --source ltm                # dry-run (默认)
  python scripts/canonical_backfill.py --source ltm --apply        # 真跑 (幂等)
  python scripts/canonical_backfill.py --source ltm --limit 20     # 小批验
  python scripts/canonical_backfill.py --source manifold           # no-op (本片砍)
"""
from __future__ import annotations

import os
import sys
import json
import argparse
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

if sys.platform == 'win32':
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass

import jarvis_canonical_entities as CE

_DB_PATH = os.path.join(ROOT, 'memory_pool', 'jarvis_memory.db')

# 约束②: test 脏数据特征 (按勘察实测: source=unit_test/test_82x, 大量 keywords=[test])
_TEST_SOURCE_MARKERS = ('unit_test', 'test_82x', 'test_', 'pytest', '_test')


def _is_test_row(entities_json: str, intent: str, macro_goal: str) -> bool:
    """约束②: 判定 test 脏数据行 (显式规则, 写在代码里)。

    规则 (任一命中即 test):
      - entities_json.source ∈ test markers (unit_test / test_82x / test_* / pytest)
      - entities_json.keywords 含 'test' 且全部是 test/blood pressure 占位
      - intent / macro_goal 含 '[测试]' / 'unit_test' / 'test_82x'
    """
    blob = f"{entities_json or ''} {intent or ''} {macro_goal or ''}".lower()
    try:
        ej = json.loads(entities_json) if entities_json else {}
    except Exception:
        ej = {}
    if isinstance(ej, dict):
        src = str(ej.get('source', '')).lower()
        if any(m in src for m in _TEST_SOURCE_MARKERS):
            return True
        kws = [str(k).lower() for k in (ej.get('keywords') or [])]
        # 纯占位 keywords (test / blood pressure 这类单测残留)
        if kws and all(k in ('test', 'blood pressure', 'consultation') for k in kws):
            return True
    for m in ('unit_test', 'test_82x', '[测试]', '[test]'):
        if m in blob:
            return True
    return False


def _extract_surfaces_from_row(entities_json: str, intent: str,
                               macro_goal: str) -> list:
    """从一行 LTM 取候选 (field_name, text) 对 (subject/keywords/intent/macro_goal)。

    [2a-B] 返回带字段名, 让清单显"命中来自哪个字段" (不固定显 subject)。
    """
    out = []  # [(field_name, text)]
    try:
        ej = json.loads(entities_json) if entities_json else {}
    except Exception:
        ej = {}
    if isinstance(ej, dict):
        for key in ('subject', 'location', 'context', 'action'):
            v = ej.get(key)
            if v and isinstance(v, str) and v.lower() != 'none':
                out.append((f"entities.{key}", v))
        for k in ej.get('keywords') or []:
            if isinstance(k, str) and k.strip():
                out.append(("entities.keywords", k))
    if intent:
        out.append(("user_intent", intent))
    if macro_goal:
        out.append(("macro_goal", macro_goal))
    return out


def _match_snippet(text: str, surface: str, ctx: int = 8) -> str:
    """[2a-B] 截取 surface 在 text 中命中位置的上下文片段 (便于一眼判真假亲属)。"""
    idx = text.find(surface)
    if idx < 0:
        return text[:30]
    start = max(0, idx - ctx)
    end = min(len(text), idx + len(surface) + ctx)
    pre = '...' if start > 0 else ''
    post = '...' if end < len(text) else ''
    return f"{pre}{text[start:end]}{post}"




def _align_cid(text: str) -> list:
    """约束: cid 对齐复用词表子串扫 (kinship + soft), 不烧 LLM。

    返回命中列表 [(surface, cid, label, relation)]。无命中 → []。
    """
    out = []
    seen = set()
    for surface, (cid, label, rel) in (
            CE.lookup_kinship_surfaces(text) + CE.lookup_soft_surfaces(text)):
        if (surface, cid) in seen:
            continue
        seen.add((surface, cid))
        out.append((surface, cid, label, rel))
    return out


def _read_ltm_rows(limit: int = 0) -> list:
    """只读 SELECT TaskMemories (WHERE is_deleted=0)。绝不 UPDATE/写回。"""
    # 只读连接 (uri mode=ro)
    uri = f"file:{_DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        c = conn.cursor()
        sql = ("SELECT id, entities_json, user_intent, macro_goal "
               "FROM TaskMemories WHERE is_deleted=0 ORDER BY id")
        if limit and limit > 0:
            sql += f" LIMIT {int(limit)}"
        c.execute(sql)
        return [{'id': r[0], 'entities_json': r[1], 'intent': r[2],
                 'macro_goal': r[3]} for r in c.fetchall()]
    finally:
        conn.close()


def backfill_ltm(apply: bool = False, limit: int = 0) -> dict:
    """LTM 回填主流程。apply=False → dry-run (只统计+清单, 不写)。

    [2a-A] 报表口径分离: hits(命中次数) ≠ will_propose(会真新建 distinct surface→cid)。
      批内同 (surface,cid) 第 2 次起计 batch_dup (不再计 will_propose), 让
      dry-run 报的 will_propose == apply 后 list_proposed 实际新增。
    """
    rows = _read_ltm_rows(limit=limit)
    stats = {'rows_total': len(rows), 'rows_test_filtered': 0,
             'rows_real': 0, 'hits': 0,
             'will_propose': 0, 'batch_dup': 0,
             'dedup_active': 0, 'dedup_proposed': 0, 'dedup_revoked': 0,
             'applied_new': 0, 'applied_noop': 0}
    manifest = []
    reg = CE.get_canonical_registry()
    seen_cand = set()  # (surface, cid) 批内去重: 第 2 次起 batch_dup, 不重复计/不重复入清单

    for row in rows:
        if _is_test_row(row['entities_json'], row['intent'], row['macro_goal']):
            stats['rows_test_filtered'] += 1
            continue
        stats['rows_real'] += 1

        for field, text in _extract_surfaces_from_row(
                row['entities_json'], row['intent'], row['macro_goal']):
            for surface, cid, label, rel in _align_cid(text):
                stats['hits'] += 1
                key = (surface, cid)
                # [2a-A] 批内去重: 同 (surface,cid) 已在本次 run 见过 → batch_dup
                if key in seen_cand:
                    stats['batch_dup'] += 1
                    continue
                seen_cand.add(key)

                # 当前 registry 状态 (查 get_alias_link, 只读)
                lk = reg.get_alias_link(surface)
                status = lk.get('status') if lk else None
                if status == CE.STATUS_ACTIVE and lk.get('cid') == cid:
                    state = 'skip:active'
                    stats['dedup_active'] += 1
                elif status == CE.STATUS_PROPOSED and lk.get('cid') == cid:
                    state = 'skip:proposed'
                    stats['dedup_proposed'] += 1
                elif status == CE.STATUS_REVOKED:
                    state = 'skip:revoked'
                    stats['dedup_revoked'] += 1
                else:
                    state = 'will_propose'
                    stats['will_propose'] += 1

                # [2a-B] 清单显命中字段 + 命中文本片段 (证显示的是真命中处)
                manifest.append({
                    'surface': surface, 'cid': cid,
                    'field': field, 'match': _match_snippet(text, surface),
                    'ltm_row': row['id'], 'state': state,
                })

                if apply and state == 'will_propose':
                    gref = {"source_kind": "ltm_backfill",
                            "ref": f"ltm:{row['id']}",
                            "ts": __import__('time').time(),
                            "detail": f"ltm_backfill:{surface}->{cid}"}
                    reg.create_canonical_entity(
                        cid, {"canonical_label": label,
                              "relation_to_sir": rel}, [gref])
                    ok = reg.add_soft_alias_link(
                        surface, cid, source="ltm_backfill",
                        ref=f"ltm:{row['id']}")
                    if ok:
                        stats['applied_new'] += 1
                    else:
                        stats['applied_noop'] += 1
    if apply and stats['applied_new'] > 0:
        reg.save()
    return {'stats': stats, 'manifest': manifest}


def _print_report(result: dict, apply: bool) -> None:
    s = result['stats']
    mode = 'APPLY' if apply else 'DRY-RUN'
    print(f"\n=== canonical_backfill LTM [{mode}] ===")
    print(f"LTM rows: total={s['rows_total']} test_filtered={s['rows_test_filtered']} "
          f"real={s['rows_real']}")
    # [2a-A] 口径分离: 命中次数 ≠ 会真新建
    print(f"hits (命中次数): {s['hits']}")
    print(f"  会真新建 will_propose (distinct surface→cid)={s['will_propose']}")
    print(f"  批内重复跳过 batch_dup={s['batch_dup']}")
    print(f"  撞 active={s['dedup_active']} 撞 proposed={s['dedup_proposed']} "
          f"撞 revoked={s['dedup_revoked']}")
    if apply:
        print(f"  applied_new={s['applied_new']} applied_noop={s['applied_noop']}")
    print(f"\n--- 候选清单 ({len(result['manifest'])} 条 distinct surface→cid) ---")
    for m in result['manifest']:
        print(f"  [{m['state']:<14}] {m['surface']} -> {m['cid']}  "
              f"| LTM#{m['ltm_row']} field={m['field']} match='{m['match']}'")


def main() -> int:
    ap = argparse.ArgumentParser(description="canonical 软提议批量回填 (Slice2.5)")
    ap.add_argument('--source', choices=['ltm', 'manifold'], default='ltm',
                    help="ltm (本片) / manifold (本片砍, no-op)")
    ap.add_argument('--apply', action='store_true',
                    help="真跑写 proposed (默认 dry-run 只预览)")
    ap.add_argument('--limit', type=int, default=0, help="只看前 N 行 (小批验)")
    args = ap.parse_args()

    if args.source == 'manifold':
        # 约束①: manifold raw 路砍出 (现网仅 2 垃圾 entity 节点, 产出恒 0)
        print("[canonical_backfill] manifold raw 暂不回填,留后续片 "
              "(现网仅 2 个垃圾 entity 节点, 产出恒 0)。本片只 --source ltm。")
        return 0

    result = backfill_ltm(apply=args.apply, limit=args.limit)
    _print_report(result, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
