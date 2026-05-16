# -*- coding: utf-8 -*-
"""[轴3-L0.1 / 2026-05-15] SkillManifest dataclass + SkillRegistry 单例骨架 — 测试套件

覆盖：
  TestSkillManifestDataclass    — dataclass 校验 + 序列化 + render
  TestSkillRegistrySingleton    — 单例 + reset
  TestSkillRegistryRegister     — 注册去重 + 保留 KPI / overwrite 语义
  TestSkillRegistryQuery        — get / has / all / all_healthy / all_by_danger
  TestSkillRegistryInvocation   — record_invocation 滚动统计 + 错误流水
  TestSkillRegistryPromptBlock  — to_prompt_block 三种过滤
  TestSkillRegistryPersistence  — save/load jsonl 往返 + 损坏行容错

跑法：
    cd d:\\Jarvis
    python tests/_test_r8_axis3_l0_1_skill_registry.py
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_skill_registry import (
    SkillManifest,
    SkillRegistry,
    DANGER_SAFE,
    DANGER_RISKY,
    DANGER_DANGEROUS,
    SOURCE_MANUAL,
    SOURCE_MODULE_MANIFEST,
    get_registry,
)


def _make_safe_skill(command='audio_hands.list_devices', **overrides):
    """工厂：生成一个最小合法 SkillManifest。"""
    base = dict(
        command=command,
        module='l4_hands_pool.l4_audio_hands',
        callable_name='list_devices',
        description='列举音频输出设备',
        dangerous_flag=DANGER_SAFE,
    )
    base.update(overrides)
    return SkillManifest(**base)


# ==========================================================================
# TestSkillManifestDataclass
# ==========================================================================

class TestSkillManifestDataclass(unittest.TestCase):
    """SkillManifest dataclass 字段校验 + 序列化"""

    def test_minimal_required_fields(self):
        sk = _make_safe_skill()
        self.assertEqual(sk.command, 'audio_hands.list_devices')
        self.assertEqual(sk.dangerous_flag, DANGER_SAFE)
        self.assertEqual(sk.last_30d_success_rate, 1.0)
        self.assertEqual(sk.call_count_30d, 0)

    def test_invalid_dangerous_flag_raises(self):
        with self.assertRaises(ValueError):
            _make_safe_skill(dangerous_flag='bogus')

    def test_command_must_contain_dot(self):
        with self.assertRaises(ValueError):
            _make_safe_skill(command='no_dot_here')

    def test_empty_command_raises(self):
        with self.assertRaises(ValueError):
            _make_safe_skill(command='')

    def test_description_truncation(self):
        long_desc = 'x' * 300
        sk = _make_safe_skill(description=long_desc)
        self.assertEqual(len(sk.description), 200)
        self.assertTrue(sk.description.endswith('...'))

    def test_is_healthy_new_skill(self):
        """新工具调用次数 < 3 → 不歧视，默认 healthy"""
        sk = _make_safe_skill()
        self.assertTrue(sk.is_healthy())

    def test_is_healthy_below_threshold_after_calls(self):
        sk = _make_safe_skill()
        sk.call_count_30d = 10
        sk.last_30d_success_rate = 0.5
        self.assertFalse(sk.is_healthy(min_success_rate=0.7))

    def test_is_healthy_above_threshold(self):
        sk = _make_safe_skill()
        sk.call_count_30d = 10
        sk.last_30d_success_rate = 0.85
        self.assertTrue(sk.is_healthy(min_success_rate=0.7))

    def test_danger_flag_predicates(self):
        safe_sk = _make_safe_skill(dangerous_flag=DANGER_SAFE)
        risky_sk = _make_safe_skill(command='x.y', dangerous_flag=DANGER_RISKY)
        dang_sk = _make_safe_skill(command='x.z', dangerous_flag=DANGER_DANGEROUS)
        self.assertTrue(safe_sk.is_safe())
        self.assertFalse(safe_sk.is_dangerous())
        self.assertTrue(risky_sk.is_risky())
        self.assertTrue(dang_sk.is_dangerous())

    def test_to_dict_from_dict_roundtrip(self):
        sk = _make_safe_skill(
            command='audio_hands.set_volume',
            callable_name='set_volume',
            args_schema={'level': {'type': 'int', 'range': [0, 100], 'required': True}},
            preconditions=['audio_device_available'],
            typical_latency_ms=180,
            failure_modes=['device_not_found'],
            test_path='tests/_test_audio.py',
            dangerous_flag=DANGER_RISKY,
        )
        d = sk.to_dict()
        sk2 = SkillManifest.from_dict(d)
        self.assertEqual(sk.command, sk2.command)
        self.assertEqual(sk.args_schema, sk2.args_schema)
        self.assertEqual(sk.dangerous_flag, sk2.dangerous_flag)
        self.assertEqual(sk.test_path, sk2.test_path)

    def test_from_dict_ignores_unknown_keys(self):
        """老 jsonl 含未知字段 → 跳过不抛"""
        d = _make_safe_skill().to_dict()
        d['__future_extra_field__'] = 'whatever'
        sk = SkillManifest.from_dict(d)
        self.assertIsNotNone(sk)

    def test_render_one_line_with_args(self):
        sk = _make_safe_skill(
            command='audio_hands.set_volume',
            description='设置媒体音量',
            args_schema={'level': {'type': 'int', 'range': [0, 100]}},
            dangerous_flag=DANGER_RISKY,
            typical_latency_ms=180,
        )
        line = sk.render_one_line()
        self.assertIn('audio_hands.set_volume', line)
        self.assertIn('level: int 0-100', line)
        self.assertIn('设置媒体音量', line)
        self.assertIn('risky', line)
        self.assertIn('~180ms', line)

    def test_render_one_line_no_args(self):
        sk = _make_safe_skill(args_schema={})
        line = sk.render_one_line()
        self.assertIn('()', line)


# ==========================================================================
# TestSkillRegistrySingleton
# ==========================================================================

class TestSkillRegistrySingleton(unittest.TestCase):

    def setUp(self):
        SkillRegistry.reset_instance_for_test()

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def test_singleton_identity(self):
        a = SkillRegistry.get_instance()
        b = SkillRegistry.get_instance()
        self.assertIs(a, b)

    def test_get_registry_is_same_singleton(self):
        a = SkillRegistry.get_instance()
        b = get_registry()
        self.assertIs(a, b)

    def test_reset_creates_new_instance(self):
        a = SkillRegistry.get_instance()
        SkillRegistry.reset_instance_for_test()
        b = SkillRegistry.get_instance()
        self.assertIsNot(a, b)


# ==========================================================================
# TestSkillRegistryRegister
# ==========================================================================

class TestSkillRegistryRegister(unittest.TestCase):

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.reg = SkillRegistry.get_instance()

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def test_register_new_returns_true(self):
        self.assertTrue(self.reg.register(_make_safe_skill()))
        self.assertEqual(self.reg.count(), 1)

    def test_register_duplicate_returns_false_preserves_kpi(self):
        sk = _make_safe_skill()
        self.reg.register(sk)
        # 模拟运行时积累的 KPI
        self.reg.record_invocation(sk.command, success=True, latency_ms=100)
        self.reg.record_invocation(sk.command, success=False, latency_ms=200, error='boom')
        before = self.reg.get(sk.command)
        before_calls = before.call_count_30d
        before_rate = before.last_30d_success_rate
        before_error = before.last_error
        # 重新注册（更新 description）
        sk_new = _make_safe_skill(description='新描述', typical_latency_ms=300)
        result = self.reg.register(sk_new)
        self.assertFalse(result, "重复 register 应返回 False（更新现有）")
        after = self.reg.get(sk.command)
        # KPI 必须保留
        self.assertEqual(after.call_count_30d, before_calls)
        self.assertEqual(after.last_30d_success_rate, before_rate)
        self.assertEqual(after.last_error, before_error)
        # 元数据必须更新
        self.assertEqual(after.description, '新描述')
        self.assertEqual(after.typical_latency_ms, 300)

    def test_register_overwrite_true_replaces_kpi(self):
        sk = _make_safe_skill()
        self.reg.register(sk)
        self.reg.record_invocation(sk.command, success=False, latency_ms=200)
        self.assertEqual(self.reg.get(sk.command).call_count_30d, 1)
        # overwrite
        self.reg.register(_make_safe_skill(), overwrite=True)
        # KPI 被重置
        self.assertEqual(self.reg.get(sk.command).call_count_30d, 0)
        self.assertEqual(self.reg.get(sk.command).last_30d_success_rate, 1.0)

    def test_unregister(self):
        sk = _make_safe_skill()
        self.reg.register(sk)
        self.assertTrue(self.reg.unregister(sk.command))
        self.assertEqual(self.reg.count(), 0)
        self.assertFalse(self.reg.unregister('not_exists.x'))


# ==========================================================================
# TestSkillRegistryQuery
# ==========================================================================

class TestSkillRegistryQuery(unittest.TestCase):

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.reg = SkillRegistry.get_instance()
        self.reg.register(_make_safe_skill('audio.list', dangerous_flag=DANGER_SAFE))
        self.reg.register(_make_safe_skill('audio.set_vol', dangerous_flag=DANGER_RISKY))
        self.reg.register(_make_safe_skill('file.delete', dangerous_flag=DANGER_DANGEROUS))

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def test_get_existing(self):
        sk = self.reg.get('audio.list')
        self.assertIsNotNone(sk)
        self.assertEqual(sk.command, 'audio.list')

    def test_get_nonexistent_returns_none(self):
        self.assertIsNone(self.reg.get('not_exists.x'))

    def test_has(self):
        self.assertTrue(self.reg.has('audio.list'))
        self.assertFalse(self.reg.has('not_exists.x'))

    def test_all(self):
        self.assertEqual(len(self.reg.all()), 3)

    def test_count(self):
        self.assertEqual(self.reg.count(), 3)

    def test_all_healthy_default(self):
        # 全是新工具 → 全 healthy
        self.assertEqual(len(self.reg.all_healthy()), 3)

    def test_all_healthy_excludes_degraded(self):
        # 让 audio.set_vol 失败几次
        for _ in range(10):
            self.reg.record_invocation('audio.set_vol', success=False, latency_ms=100)
        healthy = self.reg.all_healthy(min_success_rate=0.7)
        cmds = [sk.command for sk in healthy]
        self.assertIn('audio.list', cmds)
        self.assertNotIn('audio.set_vol', cmds)

    def test_all_healthy_exclude_dangerous(self):
        healthy_no_danger = self.reg.all_healthy(exclude_dangerous=True)
        cmds = [sk.command for sk in healthy_no_danger]
        self.assertIn('audio.list', cmds)
        self.assertIn('audio.set_vol', cmds)
        self.assertNotIn('file.delete', cmds)

    def test_all_by_danger(self):
        self.assertEqual(len(self.reg.all_by_danger(DANGER_SAFE)), 1)
        self.assertEqual(len(self.reg.all_by_danger(DANGER_RISKY)), 1)
        self.assertEqual(len(self.reg.all_by_danger(DANGER_DANGEROUS)), 1)

    def test_all_by_danger_invalid(self):
        with self.assertRaises(ValueError):
            self.reg.all_by_danger('whatever')


# ==========================================================================
# TestSkillRegistryInvocation
# ==========================================================================

class TestSkillRegistryInvocation(unittest.TestCase):

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.reg = SkillRegistry.get_instance()
        self.reg.register(_make_safe_skill('audio.list'))

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def test_record_unknown_command_returns_false(self):
        ok = self.reg.record_invocation('not_exists.x', success=True)
        self.assertFalse(ok)

    def test_record_success_updates_kpi(self):
        self.reg.record_invocation('audio.list', success=True, latency_ms=120)
        sk = self.reg.get('audio.list')
        self.assertEqual(sk.call_count_30d, 1)
        self.assertEqual(sk.last_30d_success_rate, 1.0)
        self.assertGreater(sk.last_called_ts, 0)
        self.assertIsNone(sk.last_error)

    def test_record_failure_updates_error(self):
        self.reg.record_invocation('audio.list', success=False, latency_ms=200, error='boom')
        sk = self.reg.get('audio.list')
        self.assertEqual(sk.last_30d_success_rate, 0.0)
        self.assertEqual(sk.last_error, 'boom')

    def test_rolling_average_after_mixed_calls(self):
        # 3 success + 1 fail → avg = 0.75
        for _ in range(3):
            self.reg.record_invocation('audio.list', success=True, latency_ms=100)
        self.reg.record_invocation('audio.list', success=False, latency_ms=100)
        sk = self.reg.get('audio.list')
        self.assertEqual(sk.call_count_30d, 4)
        self.assertAlmostEqual(sk.last_30d_success_rate, 0.75, places=2)

    def test_get_recent_errors(self):
        self.reg.record_invocation('audio.list', success=True, latency_ms=100)
        self.reg.record_invocation('audio.list', success=False, error='err1')
        self.reg.record_invocation('audio.list', success=False, error='err2')
        errs = self.reg.get_recent_errors('audio.list', limit=5)
        self.assertEqual(len(errs), 2)
        self.assertEqual(errs[-1]['error'], 'err2')

    def test_invocation_log_capped_at_5000(self):
        for i in range(5100):
            self.reg.record_invocation('audio.list', success=True)
        self.assertLessEqual(len(self.reg._invocation_log), 5000)


# ==========================================================================
# TestSkillRegistryPromptBlock
# ==========================================================================

class TestSkillRegistryPromptBlock(unittest.TestCase):

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.reg = SkillRegistry.get_instance()
        self.reg.register(_make_safe_skill('audio.list', dangerous_flag=DANGER_SAFE))
        self.reg.register(_make_safe_skill('audio.set_vol', dangerous_flag=DANGER_RISKY))
        self.reg.register(_make_safe_skill('file.delete', dangerous_flag=DANGER_DANGEROUS))

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def test_prompt_block_header_and_footer(self):
        block = self.reg.to_prompt_block()
        self.assertIn('=== AVAILABLE SKILLS ===', block)
        self.assertIn('========================', block)

    def test_prompt_block_contains_all_healthy(self):
        block = self.reg.to_prompt_block()
        self.assertIn('audio.list', block)
        self.assertIn('audio.set_vol', block)
        self.assertIn('file.delete', block)

    def test_prompt_block_filter_safe_only(self):
        block = self.reg.to_prompt_block(filter_safe_only=True)
        self.assertIn('audio.list', block)
        self.assertNotIn('audio.set_vol', block)
        self.assertNotIn('file.delete', block)

    def test_prompt_block_excludes_unhealthy(self):
        for _ in range(10):
            self.reg.record_invocation('audio.set_vol', success=False)
        block = self.reg.to_prompt_block(only_healthy=True, min_success_rate=0.7)
        self.assertIn('audio.list', block)
        self.assertNotIn('audio.set_vol', block)

    def test_prompt_block_includes_directive(self):
        block = self.reg.to_prompt_block()
        self.assertIn('FORBIDDEN', block, "prompt 块必须含禁止 generic offer 的 directive")

    def test_prompt_block_empty_when_all_unhealthy(self):
        # 全部失败到 unhealthy
        for cmd in ['audio.list', 'audio.set_vol', 'file.delete']:
            for _ in range(10):
                self.reg.record_invocation(cmd, success=False)
        block = self.reg.to_prompt_block(only_healthy=True)
        self.assertIn('no healthy skills registered', block)


# ==========================================================================
# TestSkillRegistryPersistence
# ==========================================================================

class TestSkillRegistryPersistence(unittest.TestCase):

    def setUp(self):
        SkillRegistry.reset_instance_for_test()
        self.reg = SkillRegistry.get_instance()

    def tearDown(self):
        SkillRegistry.reset_instance_for_test()

    def test_save_load_roundtrip(self):
        self.reg.register(_make_safe_skill('audio.list', source=SOURCE_MODULE_MANIFEST))
        self.reg.register(_make_safe_skill('audio.set_vol', dangerous_flag=DANGER_RISKY))
        self.reg.record_invocation('audio.list', success=True, latency_ms=100)
        self.reg.record_invocation('audio.set_vol', success=False, error='err')

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'reg.jsonl')
            n_saved = self.reg.save(path)
            self.assertEqual(n_saved, 2)
            self.assertTrue(os.path.exists(path))

            # 新单例加载
            SkillRegistry.reset_instance_for_test()
            new_reg = SkillRegistry.get_instance()
            n_loaded = new_reg.load(path)
            self.assertEqual(n_loaded, 2)
            self.assertEqual(new_reg.count(), 2)
            sk = new_reg.get('audio.set_vol')
            self.assertEqual(sk.last_error, 'err')
            self.assertEqual(sk.dangerous_flag, DANGER_RISKY)

    def test_load_nonexistent_returns_zero(self):
        n = self.reg.load('/path/that/does/not/exist.jsonl')
        self.assertEqual(n, 0)

    def test_load_skips_corrupt_lines(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'reg.jsonl')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(json.dumps(_make_safe_skill('audio.list').to_dict()) + '\n')
                f.write('THIS IS NOT JSON\n')  # 损坏行
                f.write(json.dumps(_make_safe_skill('audio.set_vol').to_dict()) + '\n')
            n = self.reg.load(path)
            self.assertEqual(n, 2, "损坏行应跳过，保留好的两行")

    def test_dirty_flag_lifecycle(self):
        self.assertFalse(self.reg.is_dirty())
        self.reg.register(_make_safe_skill('audio.list'))
        self.assertTrue(self.reg.is_dirty())
        with tempfile.TemporaryDirectory() as td:
            self.reg.save(os.path.join(td, 'reg.jsonl'))
        self.assertFalse(self.reg.is_dirty())

    def test_save_atomic_via_tmp(self):
        """save 必须通过 .tmp + os.replace，避免写到一半 crash 损坏 jsonl"""
        self.reg.register(_make_safe_skill('audio.list'))
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'reg.jsonl')
            self.reg.save(path)
            tmp = path + '.tmp'
            self.assertFalse(os.path.exists(tmp), "save 后 .tmp 应已 rename 掉")


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("[OK] All R8 axis3 L0.1 SkillRegistry tests passed.")
    else:
        print(f"[FAIL] {len(result.failures)} failures, {len(result.errors)} errors")
    print("=" * 60)
    sys.exit(0 if result.wasSuccessful() else 1)
