# -*- coding: utf-8 -*-
"""[fix44 / Sir 2026-05-28 19:47 P1] sensor thresholds vocab + Sir CLI + inner_thought actionable.

Sir 真意 (准则 6 持久化 + 准则 7 元否决 + 准则 8 优雅):
  原本 30s ghost_dampen / 60s afk_threshold / IDE keywords list 全 hardcode 在
  jarvis_proactive_shield.py / jarvis_env_probe.py source 里. Sir 想调 → 改 .py
  + git commit. 违反准则 6 vocab 持久化范式.

治本:
  1. memory_pool/sensor_thresholds_vocab.json — writable_paths 持久化
  2. jarvis_sensor_thresholds.py — get_threshold / propose / apply / reject / reset API
  3. scripts/sensor_thresholds_dump.py — Sir CLI (list/proposals/approve/reject/apply/reset/dry-run/history/gate)
  4. jarvis_inner_thought_daemon.py — _do_adjust_sensor_threshold handler (sal>=0.75)
  5. sensor 模块 (env_probe / proactive_shield) 读 get_threshold 替代 hardcode

防回退 testcase (12 covers):
  T1: helper public API 都存在 (validate_value / apply_direct etc)
  T2: get_threshold happy + enabled=0 返 default
  T3: validate min/max/max_delta_per_change 拒绝
  T4: propose -> approve -> current 改 + history 记
  T5: propose -> reject -> queue 清 current 不动
  T6: apply_direct (Sir 元否决) 跳过 queue
  T7: reset_to_default 回 default
  T8: env_probe.py 接入 get_threshold (源码 marker)
  T9: proactive_shield.py 接入 get_threshold (源码 marker)
  T10: inner_thought handler _do_adjust_sensor_threshold 存在 + sal gate
  T11: prompt actionable `adjust_sensor_threshold:<path>:<value>` 在
  T12: CLI 9 subcommands 都注册
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(name: str) -> str:
    with open(os.path.join(ROOT, name), 'r', encoding='utf-8') as f:
        return f.read()


def _mk_isolated_vocab(tmpdir: str) -> str:
    """make isolated test vocab JSON, return path. T2-T7 用."""
    path = os.path.join(tmpdir, 'sensor_thresholds_vocab.json')
    data = {
        '_doc': ['testcase isolated vocab'],
        'schema_version': 1,
        'enabled': 1,
        'writable_paths': {
            'test.int_threshold_s': {
                'type': 'int',
                'description': 'test int with min/max/delta',
                'current': 60,
                'default': 60,
                'min': 30,
                'max': 300,
                'max_delta_per_change': 60,
                'owner': 'testcase',
            },
            'test.bool_flag': {
                'type': 'bool',
                'description': 'test bool',
                'current': False,
                'default': False,
                'owner': 'testcase',
            },
            'test.list_keywords': {
                'type': 'list_str',
                'description': 'test list_str',
                'current': ['a', 'b'],
                'default': ['a', 'b'],
                'max_items': 10,
                'owner': 'testcase',
            },
        },
        'review_queue': [],
        'history': [],
        'last_modified_at': 0.0,
        'last_modified_iso': '',
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


# ==========================================================================
# T1: helper public API 完整 (Sir CLI / handler 调的方法都存在)
# ==========================================================================
class TestT1HelperApiSurface(unittest.TestCase):
    def test_helper_public_api_exists(self):
        """jarvis_sensor_thresholds 必须 export 9 个 public API."""
        import jarvis_sensor_thresholds as h
        for name in (
            'get_threshold',
            'get_writable_paths',
            'propose_adjustment',
            'list_review_queue',
            'apply_adjustment',
            'reject_adjustment',
            'get_history',
            'reset_to_default',
            'validate_value',     # 新加 (CLI dry-run)
            'apply_direct',       # 新加 (Sir 元否决)
            'invalidate_cache',
        ):
            self.assertTrue(hasattr(h, name),
                            f'jarvis_sensor_thresholds.{name} 必须存在')


# ==========================================================================
# T2: get_threshold happy + gate off 返 default
# ==========================================================================
class TestT2GetThresholdGateBehavior(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vocab_path = _mk_isolated_vocab(self.tmp.name)
        os.environ['JARVIS_SENSOR_THRESHOLDS_VOCAB_PATH'] = self.vocab_path
        import jarvis_sensor_thresholds as h
        h.invalidate_cache()
        self.h = h

    def tearDown(self):
        os.environ.pop('JARVIS_SENSOR_THRESHOLDS_VOCAB_PATH', None)
        self.h.invalidate_cache()
        self.tmp.cleanup()

    def test_happy_returns_current(self):
        """enabled=1 时 get_threshold 返 current_value."""
        v = self.h.get_threshold('test.int_threshold_s', default=-1)
        self.assertEqual(v, 60, 'happy path: 返 current 60')

    def test_unknown_path_returns_default(self):
        """unknown path 必须返 default (sensor 故障开放)."""
        v = self.h.get_threshold('test.unknown_thing', default=99)
        self.assertEqual(v, 99, 'unknown path: 必须返 caller default')

    def test_gate_off_returns_default(self):
        """enabled=0 时 get_threshold 必须返 caller default (gate off)."""
        with open(self.vocab_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data['enabled'] = 0
        with open(self.vocab_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.h.invalidate_cache()
        v = self.h.get_threshold('test.int_threshold_s', default=999)
        self.assertEqual(v, 999, 'gate off: 必须返 caller default 不读 current')


# ==========================================================================
# T3: validate min/max/max_delta/type 全拒
# ==========================================================================
class TestT3ValidateRejectBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vocab_path = _mk_isolated_vocab(self.tmp.name)
        os.environ['JARVIS_SENSOR_THRESHOLDS_VOCAB_PATH'] = self.vocab_path
        import jarvis_sensor_thresholds as h
        h.invalidate_cache()
        self.h = h

    def tearDown(self):
        os.environ.pop('JARVIS_SENSOR_THRESHOLDS_VOCAB_PATH', None)
        self.h.invalidate_cache()
        self.tmp.cleanup()

    def test_below_min_reject(self):
        ok, why = self.h.validate_value('test.int_threshold_s', 5)
        self.assertFalse(ok, '5 < min 30 必须拒')
        self.assertIn('min=30', why)

    def test_above_max_reject(self):
        ok, why = self.h.validate_value('test.int_threshold_s', 500)
        self.assertFalse(ok, '500 > max 300 必须拒')
        self.assertIn('max=300', why)

    def test_delta_cap_reject(self):
        """current=60, max_delta=60, 200 - 60 = 140 必须拒."""
        ok, why = self.h.validate_value('test.int_threshold_s', 200)
        self.assertFalse(ok, 'delta 140 > max_delta 60 必须拒')
        self.assertIn('max_delta_per_change=60', why)

    def test_within_range_accept(self):
        ok, why = self.h.validate_value('test.int_threshold_s', 90)
        self.assertTrue(ok, f'90 (delta 30, in [30,300]) 必须过: {why}')

    def test_unknown_path_reject(self):
        ok, why = self.h.validate_value('nope.unknown', 1)
        self.assertFalse(ok, 'unknown path 必须拒')

    def test_list_str_max_items_reject(self):
        ok, why = self.h.validate_value(
            'test.list_keywords', ['a'] * 20)
        self.assertFalse(ok, 'list 20 > max_items 10 必须拒')
        self.assertIn('max_items=10', why)

    def test_bool_type_mismatch_reject(self):
        ok, why = self.h.validate_value('test.bool_flag', 'true')
        self.assertFalse(ok, 'str "true" 不是 bool 必须拒 (caller 要先 cast)')


# ==========================================================================
# T4: propose -> approve -> current 改 + history 记
# ==========================================================================
class TestT4ProposeApproveFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vocab_path = _mk_isolated_vocab(self.tmp.name)
        os.environ['JARVIS_SENSOR_THRESHOLDS_VOCAB_PATH'] = self.vocab_path
        import jarvis_sensor_thresholds as h
        h.invalidate_cache()
        self.h = h

    def tearDown(self):
        os.environ.pop('JARVIS_SENSOR_THRESHOLDS_VOCAB_PATH', None)
        self.h.invalidate_cache()
        self.tmp.cleanup()

    def test_propose_approve_mutates_current(self):
        ok, item_id = self.h.propose_adjustment(
            'test.int_threshold_s', 90,
            source='inner_thought:t_xyz', rationale='Sir test')
        self.assertTrue(ok, f'propose 必须过: {item_id}')

        queue = self.h.list_review_queue()
        self.assertEqual(len(queue), 1, 'queue 必须 1 entry')
        self.assertEqual(queue[0]['proposed_value'], 90)
        self.assertEqual(queue[0]['state'], 'review')

        ok2, msg = self.h.apply_adjustment(item_id)
        self.assertTrue(ok2, f'approve 必须过: {msg}')

        v_after = self.h.get_threshold('test.int_threshold_s', -1)
        self.assertEqual(v_after, 90, 'apply 后 current 必须 = 90')

        queue_after = self.h.list_review_queue()
        self.assertEqual(len(queue_after), 0, 'apply 后 queue 必须清')

        hist = self.h.get_history('test.int_threshold_s')
        self.assertEqual(len(hist), 1, 'history 必须 1 entry')
        self.assertEqual(hist[0]['action'], 'applied')
        self.assertEqual(hist[0]['old_value'], 60)
        self.assertEqual(hist[0]['new_value'], 90)


# ==========================================================================
# T5: propose -> reject -> queue 清 current 不动 + history 记 rejected
# ==========================================================================
class TestT5ProposeRejectFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vocab_path = _mk_isolated_vocab(self.tmp.name)
        os.environ['JARVIS_SENSOR_THRESHOLDS_VOCAB_PATH'] = self.vocab_path
        import jarvis_sensor_thresholds as h
        h.invalidate_cache()
        self.h = h

    def tearDown(self):
        os.environ.pop('JARVIS_SENSOR_THRESHOLDS_VOCAB_PATH', None)
        self.h.invalidate_cache()
        self.tmp.cleanup()

    def test_propose_reject_no_mutate(self):
        ok, item_id = self.h.propose_adjustment(
            'test.int_threshold_s', 100,
            source='inner_thought:t_abc', rationale='测试拒')
        self.assertTrue(ok)

        ok2, msg = self.h.reject_adjustment(item_id, reason='too aggressive')
        self.assertTrue(ok2, f'reject 必须过: {msg}')

        v_after = self.h.get_threshold('test.int_threshold_s', -1)
        self.assertEqual(v_after, 60, 'reject 后 current 必须不动 (=60)')

        queue_after = self.h.list_review_queue()
        self.assertEqual(len(queue_after), 0, 'reject 后 queue 必须清')

        hist = self.h.get_history('test.int_threshold_s')
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]['action'], 'rejected')
        self.assertIn('too aggressive', hist[0].get('reject_reason', ''))


# ==========================================================================
# T6: apply_direct (Sir 元否决) 跳过 review queue
# ==========================================================================
class TestT6ApplyDirectMetaOverride(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vocab_path = _mk_isolated_vocab(self.tmp.name)
        os.environ['JARVIS_SENSOR_THRESHOLDS_VOCAB_PATH'] = self.vocab_path
        import jarvis_sensor_thresholds as h
        h.invalidate_cache()
        self.h = h

    def tearDown(self):
        os.environ.pop('JARVIS_SENSOR_THRESHOLDS_VOCAB_PATH', None)
        self.h.invalidate_cache()
        self.tmp.cleanup()

    def test_apply_direct_bypasses_queue(self):
        ok, msg = self.h.apply_direct(
            'test.int_threshold_s', 75,
            source='sir_cli', rationale='Sir 元否决直改')
        self.assertTrue(ok, f'apply_direct 必须过: {msg}')

        v = self.h.get_threshold('test.int_threshold_s', -1)
        self.assertEqual(v, 75, 'apply_direct 直改 current')

        queue = self.h.list_review_queue()
        self.assertEqual(len(queue), 0,
                          'apply_direct 跳过 queue, queue 必须空')

        hist = self.h.get_history('test.int_threshold_s')
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]['action'], 'applied_direct')

    def test_apply_direct_still_validates(self):
        ok, msg = self.h.apply_direct(
            'test.int_threshold_s', 1000,
            source='sir_cli', rationale='超 max')
        self.assertFalse(ok, '1000 > max 300 必须拒 (Sir 元否决也走 validate)')


# ==========================================================================
# T7: reset_to_default 回 default + history
# ==========================================================================
class TestT7ResetToDefault(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vocab_path = _mk_isolated_vocab(self.tmp.name)
        os.environ['JARVIS_SENSOR_THRESHOLDS_VOCAB_PATH'] = self.vocab_path
        import jarvis_sensor_thresholds as h
        h.invalidate_cache()
        self.h = h

    def tearDown(self):
        os.environ.pop('JARVIS_SENSOR_THRESHOLDS_VOCAB_PATH', None)
        self.h.invalidate_cache()
        self.tmp.cleanup()

    def test_reset_restores_default(self):
        self.h.apply_direct(
            'test.int_threshold_s', 90, source='sir_cli', rationale='test')
        self.assertEqual(self.h.get_threshold('test.int_threshold_s', -1), 90)

        ok, msg = self.h.reset_to_default('test.int_threshold_s')
        self.assertTrue(ok)
        self.assertEqual(self.h.get_threshold('test.int_threshold_s', -1), 60,
                          'reset 后 current 必须 = default 60')

        hist = self.h.get_history('test.int_threshold_s')
        actions = [h.get('action') for h in hist]
        self.assertIn('reset_to_default', actions)


# ==========================================================================
# T8: jarvis_env_probe.py 接入 get_threshold (源码 marker, 防回退到 hardcode)
# ==========================================================================
class TestT8EnvProbeIntegration(unittest.TestCase):
    def test_env_probe_reads_get_threshold(self):
        """env_probe.py 必须 import + call get_threshold, 不再 hardcode 60s."""
        src = _read('jarvis_env_probe.py')
        self.assertIn('from jarvis_sensor_thresholds import get_threshold',
                      src,
                      'env_probe 必须 import get_threshold')
        # 必须读 3 个 path
        for path in (
            'afk.idle_threshold_s',
            'ghost_activity.idle_threshold_s',
            'ghost_activity.publish_cooldown_s',
        ):
            self.assertIn(path, src,
                          f'env_probe 必须读 vocab path: {path}')


# ==========================================================================
# T9: jarvis_proactive_shield.py 接入 get_threshold
# ==========================================================================
class TestT9ProactiveShieldIntegration(unittest.TestCase):
    def test_proactive_shield_reads_get_threshold(self):
        src = _read('jarvis_proactive_shield.py')
        self.assertIn('from jarvis_sensor_thresholds import get_threshold',
                      src,
                      'proactive_shield 必须 import get_threshold')
        self.assertIn('proactive_shield.ghost_dampen_idle_real_s', src,
                      'proactive_shield 必须读 vocab path '
                      'proactive_shield.ghost_dampen_idle_real_s')


# ==========================================================================
# T10: inner_thought handler 存在 + sal gate
# ==========================================================================
class TestT10InnerThoughtHandler(unittest.TestCase):
    def test_handler_method_exists(self):
        src = _read('jarvis_inner_thought_daemon.py')
        self.assertIn('def _do_adjust_sensor_threshold(self', src,
                      'inner_thought 必须有 _do_adjust_sensor_threshold handler')
        self.assertIn('ADJUST_SENSOR_THRESHOLD_MIN_SAL', src,
                      'handler 必须有 sal gate const')
        # propose_adjustment 调用必须在 (而不是直接 mutate current)
        self.assertIn('propose_adjustment', src,
                      'handler 必须走 propose_adjustment (不直 mutate)')


# ==========================================================================
# T11: prompt actionable 列表含 adjust_sensor_threshold
# ==========================================================================
class TestT11PromptActionableListed(unittest.TestCase):
    def test_adjust_sensor_threshold_in_actionable_prompt(self):
        src = _read('jarvis_inner_thought_daemon.py')
        # 必须在 ACTIONABLE prompt 列表里
        self.assertIn('adjust_sensor_threshold:<path>:<value>', src,
                      'prompt ACTIONABLE 列表必须列 '
                      'adjust_sensor_threshold:<path>:<value>')


# ==========================================================================
# T12: CLI 9 subcommands 都注册
# ==========================================================================
class TestT12CliSubcommandsRegistered(unittest.TestCase):
    def test_cli_subcommands(self):
        src = _read('scripts/sensor_thresholds_dump.py')
        for sub in (
            "'list'",
            "'proposals'",
            "'approve'",
            "'reject'",
            "'apply'",
            "'reset'",
            "'dry-run'",
            "'history'",
            "'gate'",
        ):
            self.assertIn(sub, src,
                          f'CLI 必须注册 subcommand {sub}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
