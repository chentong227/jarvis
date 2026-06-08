# -*- coding: utf-8 -*-
"""[bugB(c) Part 2 / Sir 2026-06-08] ProfileReflector.activate → 真写回 sir_profile.json.

闭合 bugB 后半环: corrections 读不回 → Sir activate proposal 后经安全契约真写 profile。
复用 ProfileCard.overwrite_field 原子写 + 保守白名单 + .bak + 幂等 + 审计。

覆盖:
  T1 白名单过: activate 白名单 proposal → profile 该字段 = new_value, state=applied
  T2 非白名单拒: activate 核心身份锚 field → profile 逐字不变, state=rejected_non_whitelist
  T3 .bak: 写前生成备份, 备份内容 == 写前原值
  T4 写后读到 (fixC 教训): activate 后 _load_profile/snapshot 读到新值 (缓存失效生效)
  T5 幂等: 已 applied 再 activate → no-op (不二次写/不新增 .bak)
  T6 behavior-preserving: 未 activate 时 profile 不动; daemon 仍只 propose
"""
from __future__ import annotations

import os
import sys
import json
import glob
import time
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _FakeNerve:
    habit_clock = None
    causal_chain = None
    project_timeline = None


def _seed_profile(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class _Harness(unittest.TestCase):
    def setUp(self):
        from jarvis_routing import ProfileCard
        from jarvis_profile_reflector import ProfileReflector
        self.tmp = tempfile.mkdtemp(prefix='bugB_wb_')
        self.profile_path = os.path.join(self.tmp, 'sir_profile.json')
        self.review_path = os.path.join(self.tmp, 'profile_review.json')
        _seed_profile(self.profile_path, {
            'preferred_tools': 'Cursor',
            'core_philosophy': 'DO NOT TOUCH — IP anchor',
        })
        # ProfileCard 指向 temp profile (overwrite_field 写死 jarvis_config/sir_profile.json,
        # 故 monkeypatch 其路径常量不可行 → 用 _patch_overwrite_path)
        self.nerve = _FakeNerve()
        self.pc = ProfileCard(self.nerve)
        self.nerve.profile_card = self.pc
        # patch overwrite_field + _load_profile 的 profile 路径到 temp
        self._patch_profile_path()
        self.reflector = ProfileReflector(
            review_path=self.review_path,
            corrections_path=os.path.join(self.tmp, 'corrections.jsonl'),
            profile_path=self.profile_path,
            nerve=self.nerve,
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch_profile_path(self):
        # overwrite_field / _load_profile 用 os.path.join('jarvis_config','sir_profile.json').
        # 测试隔离: monkeypatch ProfileCard.overwrite_field + _load_profile 内的路径。
        # 最干净做法: 包装 overwrite_field 让它写 temp。这里用 os.path.join patch 风险大,
        # 改为直接替换两方法的 profile 文件定位 — 用闭包重绑。
        import jarvis_routing as R
        _orig_join = os.path.join
        tmp_profile = self.profile_path

        def _patched_load(_self):
            try:
                with open(tmp_profile, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        self.pc._load_profile = _patched_load.__get__(self.pc, type(self.pc))

        # overwrite_field: 重绑一个写 temp 的版本 (复用真逻辑结构, 仅改路径)
        _real_overwrite = self.pc.overwrite_field

        def _patched_overwrite(field, new_value, source='fast_call_mutation',
                               turn_id='', reason=''):
            # 临时把 cwd-based 路径替换: 直接内联 temp 版 (复用白名单 + 原子写语义)
            allowed = type(self.pc)._OVERWRITE_ALLOWED_FIELDS
            if not field:
                return False, 'empty field', None
            f = field
            if f.startswith('preferences.'):
                f = 'unit_preferences.' + f[len('preferences.'):]
            if '.' in f:
                top, sub = f.split('.', 1)
            else:
                top, sub = f, None
            if top not in allowed:
                return False, f"top field '{top}' not in allowed list", None
            with open(tmp_profile, 'r', encoding='utf-8') as fh:
                prof = json.load(fh)
            if sub:
                tv = prof.get(top)
                if not isinstance(tv, dict):
                    tv = {}
                    prof[top] = tv
                old = tv.get(sub)
                if old == new_value:
                    return True, 'no-op', old
                tv[sub] = new_value
            else:
                old = prof.get(top)
                if old == new_value:
                    return True, 'no-op', old
                prof[top] = new_value
            tmpf = tmp_profile + '.tmp'
            with open(tmpf, 'w', encoding='utf-8') as fh:
                json.dump(prof, fh, ensure_ascii=False, indent=2)
            os.replace(tmpf, tmp_profile)
            self.pc._cache_time = 0
            return True, f'profile.{field} overwritten', old
        self.pc.overwrite_field = _patched_overwrite

    def _mk_proposal(self, field_path, new_value, action='modify', state='review'):
        from jarvis_profile_reflector import ProfileProposal
        p = ProfileProposal(
            proposal_id=f'prop_test_{field_path.replace(".", "_")}',
            field_path=field_path, action=action, new_value=new_value,
            proposed_at=time.time(), state=state)
        self.reflector._proposals.append(p)
        return p


class TestActivateWriteback(_Harness):
    def test_t1_whitelist_writes(self):
        self._mk_proposal('preferred_tools', 'Kiro')
        ok = self.reflector.activate('prop_test_preferred_tools')
        self.assertTrue(ok)
        prof = json.load(open(self.profile_path, encoding='utf-8'))
        self.assertEqual(prof['preferred_tools'], 'Kiro')
        p = [x for x in self.reflector._proposals if x.proposal_id == 'prop_test_preferred_tools'][0]
        self.assertEqual(p.state, 'applied')

    def test_t2_non_whitelist_rejected(self):
        before = json.load(open(self.profile_path, encoding='utf-8'))
        self._mk_proposal('core_philosophy', 'HACKED')
        ok = self.reflector.activate('prop_test_core_philosophy')
        self.assertFalse(ok)
        after = json.load(open(self.profile_path, encoding='utf-8'))
        self.assertEqual(before, after, "非白名单 → profile 逐字不变")
        p = [x for x in self.reflector._proposals if x.proposal_id == 'prop_test_core_philosophy'][0]
        self.assertEqual(p.state, 'rejected_non_whitelist')

    def test_t3_bak_backup(self):
        self._mk_proposal('preferred_tools', 'Kiro')
        self.reflector.activate('prop_test_preferred_tools')
        baks = glob.glob(self.profile_path + '.bak.*')
        self.assertEqual(len(baks), 1, "应生成 1 个 .bak")
        bak_data = json.load(open(baks[0], encoding='utf-8'))
        self.assertEqual(bak_data['preferred_tools'], 'Cursor',
                         "备份内容应 == 写前原值")

    def test_t4_read_after_write(self):
        # fixC 教训: 写后 retrieve 立读新值 (缓存失效生效)
        self._mk_proposal('preferred_tools', 'Kiro')
        # 先 snapshot 一次建缓存
        _ = self.pc.snapshot()
        self.reflector.activate('prop_test_preferred_tools')
        # _load_profile 直读
        self.assertEqual(self.pc._load_profile()['preferred_tools'], 'Kiro')
        # 缓存失效 → snapshot 重建读新值
        self.assertEqual(self.pc._cache_time, 0, "写后缓存应失效")

    def test_t5_idempotent(self):
        self._mk_proposal('preferred_tools', 'Kiro')
        ok1 = self.reflector.activate('prop_test_preferred_tools')
        self.assertTrue(ok1)
        baks1 = glob.glob(self.profile_path + '.bak.*')
        # 改文件外部值, 再 activate 已 applied → 不应二次写
        _seed_profile(self.profile_path, {'preferred_tools': 'EXTERNAL', 'core_philosophy': 'x'})
        ok2 = self.reflector.activate('prop_test_preferred_tools')
        self.assertTrue(ok2, "已 applied 再 activate → no-op 返 True")
        after = json.load(open(self.profile_path, encoding='utf-8'))
        self.assertEqual(after['preferred_tools'], 'EXTERNAL',
                         "幂等: 不二次写 (外部值保留)")
        baks2 = glob.glob(self.profile_path + '.bak.*')
        self.assertEqual(len(baks1), len(baks2), "幂等: 不新增 .bak")

    def test_t6_no_activate_no_change(self):
        # behavior-preserving: 未 activate → profile 不动
        before = json.load(open(self.profile_path, encoding='utf-8'))
        self._mk_proposal('preferred_tools', 'Kiro')
        # 不调 activate
        after = json.load(open(self.profile_path, encoding='utf-8'))
        self.assertEqual(before, after)

    def test_t7_unsupported_action_rejected(self):
        self._mk_proposal('preferred_tools', 'X', action='remove')
        ok = self.reflector.activate('prop_test_preferred_tools')
        self.assertFalse(ok)
        p = [x for x in self.reflector._proposals if x.proposal_id == 'prop_test_preferred_tools'][0]
        self.assertEqual(p.state, 'rejected_unsupported_action')

    def test_t8_writeback_fail_never_applied(self):
        # 🔴 关键: 过 activate 白名单但 overwrite_field 返 ok=False →
        # profile 不变 + state=writeback_failed (绝不 applied) + 无孤儿 .bak
        before = json.load(open(self.profile_path, encoding='utf-8'))
        self._mk_proposal('preferred_tools', 'Kiro')
        # mock overwrite_field → ok=False (模拟 overwrite 白名单拒/写盘失败)
        self.pc.overwrite_field = lambda *a, **k: (False, 'simulated overwrite reject', None)
        ok = self.reflector.activate('prop_test_preferred_tools')
        self.assertFalse(ok)
        after = json.load(open(self.profile_path, encoding='utf-8'))
        self.assertEqual(before, after, "写失败 → profile 逐字不变")
        p = [x for x in self.reflector._proposals if x.proposal_id == 'prop_test_preferred_tools'][0]
        self.assertNotEqual(p.state, 'applied', "写失败绝不标 applied")
        self.assertEqual(p.state, 'writeback_failed')
        baks = glob.glob(self.profile_path + '.bak.*')
        self.assertEqual(len(baks), 0, "写失败 → 孤儿 .bak 应清理")


class TestWhitelistSubsetInvariant(unittest.TestCase):
    def test_subset_of_overwrite_whitelist(self):
        # 不变式: activate 白名单 ⊆ overwrite_field 白名单 (否则"过本白名单→overwrite拒→谎称applied")
        from jarvis_routing import ProfileCard
        from jarvis_profile_reflector import ProfileReflector
        ow = ProfileCard._OVERWRITE_ALLOWED_FIELDS
        wl = ProfileReflector._ACTIVATE_WRITEBACK_WHITELIST
        not_subset = wl - ow
        self.assertEqual(not_subset, set(),
                         f"activate 白名单必须 ⊆ overwrite 白名单, 越界字段: {sorted(not_subset)}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
