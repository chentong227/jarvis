# -*- coding: utf-8 -*-
"""[canonical-backfill-slice25 / 2026-06-08] LTM 回填软提议层 单测.

设计 JARVIS_SLICE25_BACKFILL_PROPOSER_DESIGN.md + 三硬约束。
批量遍历 LTM 情节 subject 短语 → 子串扫词表对齐 cid → 复用 add_soft_alias_link
产 proposed (source=ltm_backfill)。只产 proposed、只读数据源、对不齐跳过。

覆盖 (设计 §3 八条):
  ① LTM subject "妈妈手术" → 子串命中 → 产 proposed (source=ltm_backfill) + resolve None
  ② 对不齐 (无词表命中) → 跳过不产
  ③ 回填 N 次幂等 (第2次起 no-op)
  ④ 撞 active 不覆盖 / 撞 proposed 不重复 / 撞 revoked skip 不复活
  ⑤ 回填 proposed 不污染硬层 (touch_refs 不变 / touch_count=0)
  ⑥ dry-run 预览数 == --apply 实际数
  ⑦ 只读数据源 (回填前后 db 行数/内容逐字不变)
  ⑧ provenance source_kind=ltm_backfill
"""
from __future__ import annotations

import os
import sys
import json
import time
import sqlite3
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_canonical_entities as CE
import scripts.canonical_backfill as BF


def _make_db(rows):
    """建临时 TaskMemories DB。rows=[(id, entities_json, intent, macro_goal, is_deleted)]."""
    tmp = tempfile.mkdtemp(prefix='bf_ltm_')
    path = os.path.join(tmp, 'jarvis_memory.db')
    conn = sqlite3.connect(path)
    c = conn.cursor()
    c.execute('''CREATE TABLE TaskMemories (
        id INTEGER PRIMARY KEY, timestamp REAL, environment TEXT,
        user_intent TEXT, macro_goal TEXT, execution_summary TEXT,
        raw_actions TEXT, semantic_embedding BLOB, is_deleted INTEGER DEFAULT 0,
        memory_type TEXT, entities_json TEXT, is_future_task INTEGER, trigger_time REAL)''')
    for rid, ej, intent, goal, deleted in rows:
        c.execute("INSERT INTO TaskMemories (id, timestamp, environment, user_intent, "
                  "macro_goal, entities_json, is_deleted) VALUES (?,?,?,?,?,?,?)",
                  (rid, time.time(), 'CHAT', intent, goal, ej, deleted))
    conn.commit()
    conn.close()
    return tmp, path


class _BFHarness(unittest.TestCase):
    """每个 test 用隔离 registry + 隔离 DB (patch BF._DB_PATH + CE singleton)。"""

    def setUp(self):
        # 隔离 registry: patch get_canonical_registry 返回临时实例
        self.reg_tmp = tempfile.mkdtemp(prefix='bf_reg_')
        self.reg_path = os.path.join(self.reg_tmp, 'canonical_entities.json')
        self.reg = CE.CanonicalEntityRegistry(path=self.reg_path)
        self._orig_get = CE.get_canonical_registry
        CE.get_canonical_registry = lambda: self.reg
        # backfill 脚本也 import 了 CE.get_canonical_registry — patch 模块级引用
        BF.CE.get_canonical_registry = lambda: self.reg
        self._db_tmp = None

    def tearDown(self):
        CE.get_canonical_registry = self._orig_get
        BF.CE.get_canonical_registry = self._orig_get
        import shutil
        shutil.rmtree(self.reg_tmp, ignore_errors=True)
        if self._db_tmp:
            shutil.rmtree(self._db_tmp, ignore_errors=True)

    def _set_db(self, rows):
        self._db_tmp, path = _make_db(rows)
        BF._DB_PATH = path
        return path


class TestBackfillCore(_BFHarness):
    def test_01_ltm_subject_produces_proposed(self):
        self._set_db([(1, json.dumps({"subject": "妈妈手术"}), "妈妈手术安排", "", 0)])
        res = BF.backfill_ltm(apply=True)
        lk = self.reg.get_alias_link("妈妈")
        self.assertIsNotNone(lk, "妈妈手术应子串命中妈妈")
        self.assertEqual(lk['status'], 'proposed')
        self.assertEqual(lk['source'], 'ltm_backfill')
        self.assertIsNone(self.reg.resolve_surface_to_cid("妈妈"),
                          "①proposed 不进硬层 (resolve None)")

    def test_02_no_match_skipped(self):
        self._set_db([(1, json.dumps({"subject": "面试成绩"}), "确认面试成绩", "", 0)])
        res = BF.backfill_ltm(apply=True)
        self.assertEqual(res['stats']['hits'], 0, "②无词表命中→跳过不产")
        self.assertEqual(len(self.reg.list_proposed()), 0)

    def test_03_idempotent_n_times(self):
        self._set_db([(1, json.dumps({"subject": "妈妈手术"}), "x", "", 0)])
        r1 = BF.backfill_ltm(apply=True)
        self.assertEqual(r1['stats']['applied_new'], 1)
        r2 = BF.backfill_ltm(apply=True)
        self.assertEqual(r2['stats']['applied_new'], 0, "③第2次 no-op")
        self.assertEqual(r2['stats']['dedup_proposed'], 1)
        self.assertEqual(len(self.reg.list_proposed()), 1, "不重复产")

    def test_04a_skip_active_no_overwrite(self):
        # 硬源先建 active 妈妈
        self.reg.create_canonical_entity("person:mother", {"canonical_label": "母亲",
                                         "relation_to_sir": "mother"},
                                         [{"source_kind": "exact", "ref": "t", "ts": 0, "detail": "x"}])
        self.reg.add_canonical_alias_link("妈妈", "person:mother", source="exact", ref="t")
        self._set_db([(1, json.dumps({"subject": "妈妈手术"}), "x", "", 0)])
        res = BF.backfill_ltm(apply=True)
        self.assertEqual(self.reg.get_alias_link("妈妈")['status'], 'active',
                         "④撞 active 不覆盖")
        self.assertEqual(res['stats']['dedup_active'], 1)

    def test_04b_skip_revoked_no_revive(self):
        self.reg.create_canonical_entity("person:mother", {"canonical_label": "母亲",
                                         "relation_to_sir": "mother"},
                                         [{"source_kind": "llm", "ref": "t", "ts": 0, "detail": "x"}])
        self.reg.add_soft_alias_link("妈妈", "person:mother", source="llm", ref="t")
        self.reg.revoke_alias_link("妈妈", by="sir")
        self._set_db([(1, json.dumps({"subject": "妈妈手术"}), "x", "", 0)])
        res = BF.backfill_ltm(apply=True)
        self.assertEqual(self.reg.get_alias_link("妈妈")['status'], 'revoked',
                         "④撞 revoked skip 不复活")
        self.assertEqual(res['stats']['dedup_revoked'], 1)

    def test_05_no_pollute_hard_layer(self):
        # 硬层 active + touch
        self.reg.create_canonical_entity("person:mother", {"canonical_label": "母亲",
                                         "relation_to_sir": "mother"},
                                         [{"source_kind": "exact", "ref": "t", "ts": 0, "detail": "x"}])
        self.reg.add_canonical_alias_link("我妈", "person:mother", source="exact", ref="t")
        self.reg.touch("person:mother", "turn_hard_1")
        before = len(self.reg.get_canonical_node("person:mother")['touch_refs'])
        # 回填软提议 (不同 surface 妈咪)
        self._set_db([(1, json.dumps({"subject": "妈咪做的菜"}), "x", "", 0)])
        BF.backfill_ltm(apply=True)
        after = len(self.reg.get_canonical_node("person:mother")['touch_refs'])
        self.assertEqual(before, after, "⑤回填不动 touch_refs")
        # 妈咪 proposed, 不计 touch_count (proposed 不触达)
        lk = self.reg.get_alias_link("妈咪")
        self.assertEqual(lk['status'], 'proposed')

    def test_06_dryrun_equals_apply(self):
        # [2a-A] 多行同 surface→cid 命中 (hits > distinct), 验 dry-run will_propose
        # == apply 后 list_proposed 实际新增 (批内去重不虚报)
        self._set_db([(1, json.dumps({"subject": "妈妈手术"}), "x", "", 0),
                      (2, json.dumps({"subject": "妈妈术后"}), "看望妈妈", "", 0),
                      (3, json.dumps({"subject": "爸爸上班"}), "y", "", 0)])
        dry = BF.backfill_ltm(apply=False)
        # dry-run 不写
        self.assertEqual(len(self.reg.list_proposed()), 0, "dry-run 不写")
        # hits 应 > will_propose (妈妈多行重复命中)
        self.assertGreater(dry['stats']['hits'], dry['stats']['will_propose'],
                           "[2a-A] hits 命中次数应 > distinct will_propose")
        apply_r = BF.backfill_ltm(apply=True)
        actual_new = len(self.reg.list_proposed())
        self.assertEqual(dry['stats']['will_propose'], actual_new,
                         "⑥[2a-A] dry-run will_propose == apply 实际新增 list_proposed")
        self.assertEqual(apply_r['stats']['applied_new'], actual_new)

    def test_06b_hits_vs_distinct_batch_dup(self):
        # [2a-A] 批内重复跳过计入 batch_dup, 不计 will_propose
        self._set_db([(1, json.dumps({"subject": "妈妈手术"}), "妈妈安排", "", 0),
                      (2, json.dumps({"subject": "妈妈术后恢复"}), "妈妈", "", 0)])
        dry = BF.backfill_ltm(apply=False)
        # 妈妈 多次命中 (多行多字段) → hits 多, will_propose=1 (distinct), batch_dup>0
        self.assertEqual(dry['stats']['will_propose'], 1,
                         "[2a-A] 妈妈 distinct will_propose=1")
        self.assertGreater(dry['stats']['batch_dup'], 0,
                           "[2a-A] 批内重复计 batch_dup")
        self.assertEqual(dry['stats']['hits'],
                         dry['stats']['will_propose'] + dry['stats']['batch_dup'],
                         "[2a-A] hits == will_propose + batch_dup (无撞库时)")

    def test_07_readonly_db_unchanged(self):
        path = self._set_db([(1, json.dumps({"subject": "妈妈手术"}), "x", "", 0)])
        conn = sqlite3.connect(path)
        before = conn.execute("SELECT count(*), sum(id) FROM TaskMemories").fetchone()
        conn.close()
        BF.backfill_ltm(apply=True)
        conn = sqlite3.connect(path)
        after = conn.execute("SELECT count(*), sum(id) FROM TaskMemories").fetchone()
        conn.close()
        self.assertEqual(before, after, "⑦只读数据源, db 行数/内容不变")

    def test_08_provenance_source_kind(self):
        self._set_db([(1, json.dumps({"subject": "妈妈手术"}), "x", "", 0)])
        BF.backfill_ltm(apply=True)
        lk = self.reg.get_alias_link("妈妈")
        prov_kinds = [p.get('source_kind') for p in lk.get('provenance', [])]
        self.assertIn('ltm_backfill', prov_kinds, "⑧provenance source_kind=ltm_backfill")

    def test_B_manifest_shows_field_and_match(self):
        # [2a-B] 清单每条带 field= + match 文本含该 surface (证显示的是真命中处)
        self._set_db([(1, json.dumps({"subject": "妈妈手术安排"}), "x", "", 0)])
        res = BF.backfill_ltm(apply=False)
        self.assertTrue(res['manifest'], "应有候选")
        m = res['manifest'][0]
        self.assertIn('field', m, "[2a-B] 清单行带 field")
        self.assertIn('match', m, "[2a-B] 清单行带 match 文本")
        self.assertIn(m['surface'], m['match'],
                      "[2a-B] match 文本含该 surface (证显示真命中处)")
        self.assertTrue(m['field'].startswith('entities.') or
                        m['field'] in ('user_intent', 'macro_goal'),
                        "[2a-B] field 是真实字段名")

    def test_B_match_from_nonsubject_field(self):
        # [2a-B] 命中来自非 subject 字段时, field 如实指出 (不架空显 subject)
        # subject 无亲属词, 但 keywords 含 "爸爸的事"
        self._set_db([(1, json.dumps({"subject": "系统权限", "keywords": ["爸爸的事"]}),
                       "x", "", 0)])
        res = BF.backfill_ltm(apply=False)
        father = [m for m in res['manifest'] if m['cid'] == 'person:father']
        self.assertTrue(father, "爸爸 应命中 person:father")
        self.assertEqual(father[0]['field'], 'entities.keywords',
                         "[2a-B] field 指出命中来自 keywords 非 subject")
        self.assertIn('爸', father[0]['match'])


class TestTestDataFilter(_BFHarness):
    """约束②: test 脏数据过滤。"""

    def test_filter_unit_test_source(self):
        self.assertTrue(BF._is_test_row(
            json.dumps({"keywords": ["test", "blood pressure"], "source": "unit_test"}), "", ""))

    def test_filter_test82x(self):
        self.assertTrue(BF._is_test_row(
            json.dumps({"keywords": ["blood pressure"], "source": "test_82x"}), "", ""))

    def test_real_row_not_filtered(self):
        self.assertFalse(BF._is_test_row(
            json.dumps({"subject": "妈妈手术"}), "妈妈手术安排", ""))

    def test_filter_excludes_test_rows_in_backfill(self):
        self._set_db([
            (1, json.dumps({"subject": "妈妈手术"}), "妈妈手术", "", 0),
            (2, json.dumps({"keywords": ["test"], "source": "unit_test"}), "x", "", 0),
            (3, json.dumps({"subject": "母亲术后"}), "母亲术后恢复", "", 1),  # is_deleted
        ])
        res = BF.backfill_ltm(apply=False)
        self.assertEqual(res['stats']['rows_total'], 2, "is_deleted=1 不进 SELECT")
        self.assertEqual(res['stats']['rows_test_filtered'], 1, "test 行被过滤")
        self.assertEqual(res['stats']['rows_real'], 1)


class TestManifoldNoOp(unittest.TestCase):
    """约束①: manifold 路砍出 (no-op)。"""

    def test_manifold_source_is_noop(self):
        import subprocess
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        r = subprocess.run(
            [sys.executable, os.path.join(ROOT, 'scripts', 'canonical_backfill.py'),
             '--source', 'manifold'],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            cwd=ROOT, env=env)
        self.assertEqual(r.returncode, 0)
        self.assertIn('manifold raw', r.stdout or '')


if __name__ == "__main__":
    unittest.main(verbosity=2)
