# -*- coding: utf-8 -*-
"""[Reshape M4.1 / 2026-05-24] PromiseLog schema 扩 (4 kind + who_promised + trigger_pattern + bound_to_concern_id)

覆盖:
  - 新 field default 值 (老数据 0 这 3 字段加载不破)
  - _backfill_who_promised 老数据 author → who_promised migration
  - 老 register API (kind=soft/hard) backward compat
  - 新 caller 可用 4 kind (commitment/cyclic/watch/self_promise)
  - trigger_pattern + bound_to_concern_id 字段可读可写
"""
import os
import sys
import json
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from jarvis_promise_log import Promise, PromiseExecutionLog, STATE_PENDING


class TestSchemaExpansion(unittest.TestCase):
    """新 field 默认值 + 可读写."""

    def test_new_fields_default(self):
        p = Promise(id='p_test1', description='test')
        # 新 field 默认值
        self.assertEqual(p.who_promised, '')
        self.assertEqual(p.trigger_pattern, {})
        self.assertEqual(p.bound_to_concern_id, '')
        # 老 field 不动
        self.assertEqual(p.kind, 'soft')
        self.assertEqual(p.author, 'jarvis')

    def test_new_fields_explicit_set(self):
        p = Promise(
            id='p_test2',
            description='check progress every 30min',
            kind='cyclic',
            who_promised='jarvis',
            trigger_pattern={'kind': 'cycle_minutes', 'value': 30},
            bound_to_concern_id='sir_focus_streak',
        )
        self.assertEqual(p.kind, 'cyclic')
        self.assertEqual(p.who_promised, 'jarvis')
        self.assertEqual(p.trigger_pattern, {'kind': 'cycle_minutes', 'value': 30})
        self.assertEqual(p.bound_to_concern_id, 'sir_focus_streak')

    def test_to_dict_includes_new_fields(self):
        p = Promise(
            id='p_test3', description='x',
            who_promised='sir', bound_to_concern_id='c1',
            trigger_pattern={'kind': 'cycle_minutes', 'value': 60},
        )
        d = p.to_dict()
        self.assertIn('who_promised', d)
        self.assertIn('trigger_pattern', d)
        self.assertIn('bound_to_concern_id', d)
        self.assertEqual(d['who_promised'], 'sir')


class TestBackwardCompatLoad(unittest.TestCase):
    """老 JSON 无新 field 加载不破 + backfill_who_promised 自动填充."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='m4_1_')
        self.path = os.path.join(self.tmpdir, 'promise_log.json')
        # 模拟 β.5.30 时代老 JSON: 含 author, 无 who_promised/trigger_pattern/bound_to_concern_id
        old_data = {
            'p_old1': {
                'id': 'p_old1',
                'description': 'Sir will sleep at 11pm',
                'kind': 'hard',
                'deadline_str': '23:00',
                'jarvis_reply': '',
                'turn_id': 'turn_old',
                'lang': 'en',
                'state': STATE_PENDING,
                'registered_at': 1779000000.0,
                'fulfilled_at': 0.0,
                'evidence': [],
                'author': 'sir',
            },
            'p_old2': {
                'id': 'p_old2',
                'description': 'I shall remind Sir to drink water',
                'kind': 'soft',
                'deadline_str': '',
                'jarvis_reply': 'Yes Sir, I shall remind.',
                'turn_id': 'turn_old2',
                'lang': 'en',
                'state': STATE_PENDING,
                'registered_at': 1779000010.0,
                'fulfilled_at': 0.0,
                'evidence': [],
                'author': 'jarvis',
            },
        }
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(old_data, f, ensure_ascii=False, indent=2)

    def tearDown(self):
        try:
            for f in os.listdir(self.tmpdir):
                os.remove(os.path.join(self.tmpdir, f))
            os.rmdir(self.tmpdir)
        except Exception:
            pass

    def test_old_data_loads_without_error(self):
        log = PromiseExecutionLog(persist_path=self.path)
        self.assertEqual(len(log.promises), 2)
        self.assertIn('p_old1', log.promises)
        self.assertIn('p_old2', log.promises)

    def test_old_data_new_fields_have_default(self):
        log = PromiseExecutionLog(persist_path=self.path)
        p1 = log.promises['p_old1']
        # 老 JSON 无 trigger_pattern → 默认 {}
        self.assertEqual(p1.trigger_pattern, {})
        # 老 JSON 无 bound_to_concern_id → 默认 ''
        self.assertEqual(p1.bound_to_concern_id, '')

    def test_who_promised_backfilled_from_author(self):
        log = PromiseExecutionLog(persist_path=self.path)
        p1 = log.promises['p_old1']  # author=sir
        p2 = log.promises['p_old2']  # author=jarvis
        # 自动从 author 拷贝
        self.assertEqual(p1.who_promised, 'sir',
                          'M4.1: 老数据 author=sir → who_promised=sir')
        self.assertEqual(p2.who_promised, 'jarvis',
                          'M4.1: 老数据 author=jarvis → who_promised=jarvis')

    def test_who_promised_backfill_no_double(self):
        """已有 who_promised 的不重写 (新数据 author/who_promised 可能不同时)."""
        log = PromiseExecutionLog(persist_path=self.path)
        # 手动设, 再 backfill 应该不破
        log.promises['p_old1'].who_promised = 'system'
        n = log._backfill_who_promised()
        self.assertEqual(n, 0)
        self.assertEqual(log.promises['p_old1'].who_promised, 'system')


class TestBackwardCompatRegister(unittest.TestCase):
    """老 register API 不破."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='m4_1_reg_')
        self.path = os.path.join(self.tmpdir, 'p.json')
        self.log = PromiseExecutionLog(persist_path=self.path)

    def tearDown(self):
        try:
            for f in os.listdir(self.tmpdir):
                os.remove(os.path.join(self.tmpdir, f))
            os.rmdir(self.tmpdir)
        except Exception:
            pass

    def test_old_register_kind_soft(self):
        pid = self.log.register(description='I shall drink water', kind='soft',
                                 jarvis_reply='Yes Sir.')
        self.assertTrue(pid.startswith('p_'))
        p = self.log.promises[pid]
        self.assertEqual(p.kind, 'soft')
        self.assertEqual(p.author, 'jarvis')

    def test_old_register_kind_hard(self):
        pid = self.log.register(description='Sir will sleep at 11',
                                 kind='hard', deadline_str='23:00',
                                 author='sir')
        p = self.log.promises[pid]
        self.assertEqual(p.kind, 'hard')
        self.assertEqual(p.author, 'sir')


if __name__ == '__main__':
    unittest.main()
