# -*- coding: utf-8 -*-
"""[轴3-L0.4 / 2026-05-15] 运行时 KPI 喂回 — 测试套件

覆盖：
  TestWrapInvocationSuccessPath  — ExecutionResult success=True / False / 抛异常
  TestWrapInvocationReturnTypes  — 支持 bool / None / dict / object 各种返回
  TestSafeRecord                 — 直接记录 + 兜底
  TestNerveIntegrationContract   — jarvis_nerve.py:11792 接入点的源码契约

跑法：
    cd d:\\Jarvis
    python tests/_test_r8_axis3_l0_4_kpi_tracking.py
"""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_skill_registry import (
    SkillRegistry,
    SkillManifest,
    DANGER_SAFE,
    DANGER_RISKY,
    get_registry,
    wrap_invocation,
    safe_record,
)


def _make(command, **k):
    base = dict(command=command, module='m', callable_name='c',
                description='d', dangerous_flag=DANGER_SAFE)
    base.update(k)
    return SkillManifest(**base)


class _FakeExecutionResult:
    """Mock ExecutionResult 类（避免依赖 jarvis_blood）"""
    def __init__(self, success, msg='', data=None):
        self.success = success
        self.msg = msg
        self.data = data or {}


class TestWrapInvocationSuccessPath(unittest.TestCase):

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.reg = get_registry()
        self.reg.register(_make('audio.list'))

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def test_success_result_records_success(self):
        def fn():
            return _FakeExecutionResult(True, msg='ok')
        result = wrap_invocation('audio.list', fn)
        self.assertTrue(result.success)
        sk = self.reg.get('audio.list')
        self.assertEqual(sk.call_count_30d, 1)
        self.assertEqual(sk.last_30d_success_rate, 1.0)
        self.assertIsNone(sk.last_error)

    def test_failure_result_records_failure_with_error(self):
        def fn():
            return _FakeExecutionResult(False, msg='device_not_found')
        wrap_invocation('audio.list', fn)
        sk = self.reg.get('audio.list')
        self.assertEqual(sk.last_30d_success_rate, 0.0)
        self.assertEqual(sk.last_error, 'device_not_found')

    def test_exception_records_failure_and_reraises(self):
        def fn():
            raise RuntimeError('boom')
        with self.assertRaises(RuntimeError):
            wrap_invocation('audio.list', fn)
        sk = self.reg.get('audio.list')
        self.assertEqual(sk.last_30d_success_rate, 0.0)
        self.assertIn('boom', sk.last_error)

    def test_latency_recorded(self):
        import time
        def fn():
            time.sleep(0.05)
            return _FakeExecutionResult(True)
        wrap_invocation('audio.list', fn)
        sk = self.reg.get('audio.list')
        # 1 个流水记录，应该 latency >= 50ms
        log = self.reg._invocation_log[-1]
        self.assertGreaterEqual(log['latency_ms'], 40,
            f"latency 应 ≥ 40ms，实际 {log['latency_ms']}ms")

    def test_args_kwargs_passed_through(self):
        captured = {}
        def fn(a, b, kw=None):
            captured['a'] = a
            captured['b'] = b
            captured['kw'] = kw
            return _FakeExecutionResult(True)
        wrap_invocation('audio.list', fn, 1, 2, kw='hello')
        self.assertEqual(captured, {'a': 1, 'b': 2, 'kw': 'hello'})


class TestWrapInvocationReturnTypes(unittest.TestCase):

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.reg = get_registry()
        self.reg.register(_make('audio.list'))

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def test_bool_true_treated_as_success(self):
        wrap_invocation('audio.list', lambda: True)
        self.assertEqual(self.reg.get('audio.list').last_30d_success_rate, 1.0)

    def test_bool_false_treated_as_failure(self):
        wrap_invocation('audio.list', lambda: False)
        self.assertEqual(self.reg.get('audio.list').last_30d_success_rate, 0.0)

    def test_none_treated_as_success(self):
        wrap_invocation('audio.list', lambda: None)
        self.assertEqual(self.reg.get('audio.list').last_30d_success_rate, 1.0)

    def test_dict_treated_as_success(self):
        wrap_invocation('audio.list', lambda: {'data': 'x'})
        self.assertEqual(self.reg.get('audio.list').last_30d_success_rate, 1.0)


class TestSafeRecord(unittest.TestCase):

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.reg = get_registry()
        self.reg.register(_make('audio.list'))

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def test_safe_record_success(self):
        ok = safe_record('audio.list', success=True, latency_ms=120)
        self.assertTrue(ok)
        self.assertEqual(self.reg.get('audio.list').call_count_30d, 1)

    def test_safe_record_unknown_command_returns_false(self):
        ok = safe_record('not_exists.x', success=True)
        self.assertFalse(ok)


class TestNerveIntegrationContract(unittest.TestCase):
    """jarvis_nerve.py:11792 接入点的源码契约 — 防 future 重构丢失 KPI 接入"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_marker_present(self):
        self.assertIn('[轴3-L0.4 / 2026-05-15]', self.src,
            'jarvis_nerve.py 必须有 [轴3-L0.4] marker（KPI 接入点）')

    def test_imports_safe_record(self):
        self.assertIn('from jarvis_skill_registry import safe_record', self.src,
            '必须 from jarvis_skill_registry import safe_record')

    def test_records_around_hands_execute(self):
        """safe_record 必须在 self.hands.execute(action) 之后调用"""
        import re
        m = re.search(
            r'self\.hands\.execute\(action\).*?safe_record\(',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            'safe_record 必须在 self.hands.execute(action) 之后调用')

    def test_uses_correct_command_format(self):
        """global_command 必须是 f"{req_hands}.{action.command}" 格式"""
        self.assertIn(
            'f"{req_hands}.{action.command}"',
            self.src,
            'KPI 接入必须用 f"{req_hands}.{action.command}" 拼出 global_command'
        )

    def test_wrapped_in_try_except(self):
        """KPI 调用必须包在 try/except 里，绝不影响主流程"""
        import re
        # 找 safe_record 周围的 try
        m = re.search(
            r'try:\s*\n\s*from jarvis_skill_registry import safe_record.*?'
            r'safe_record\(.*?\)\s*\n\s*except Exception:',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            'safe_record 调用必须包在 try/except Exception 里（不阻塞主流程）')


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("[OK] All R8 axis3 L0.4 KPI tracking tests passed.")
    else:
        print(f"[FAIL] {len(result.failures)} failures, {len(result.errors)} errors")
    print("=" * 60)
    sys.exit(0 if result.wasSuccessful() else 1)
