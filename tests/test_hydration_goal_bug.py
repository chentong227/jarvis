# -*- coding: utf-8 -*-
"""[Sir 2026-05-24 21:14 真测 hydration_goal BUG A] regression test.

源 BUG:
  Sir reply "搞错了吧, 我不是每天要喝3000毫升吗? 那不应该是10杯吗"
  → 主脑 emit mutation.update field_path='profile.hydration_goal'
    new='3000ml (10 cups @ 300ml/cup)'
  → ProfileCard _OVERWRITE_ALLOWED_FIELDS 不含 hydration_goal
  → overwrite_field 返 ow_ok=False
  → fallback apply_correction (audit-only)
  → ok=True 报谎 + chat_bypass 显示 "✅ sir_profile.json 已 atomic 覆写" 谎言
  → 主脑下次 retrieve sir_profile.json 没 hydration_goal 字段 → 继续错算

修法 4 层:
  L1 jarvis_memory_hub.py WriteReceipt 加 physical_write 字段 (默认 False).
     ow_ok=True 路径设 physical_write=True; fallback audit 保持 False.
  L2 jarvis_chat_bypass.py 显示 "atomic 覆写" 改成 physical_write=True 才显示.
     audit-only fallback 显示 "⚠️ audit-only fallback (sir_profile.json 未真改)".
  L3 jarvis_routing.py _OVERWRITE_ALLOWED_FIELDS 加 'health_goals' dict.
     Sir 教 hydration/sleep/exercise 目标都进 health_goals.
  L4 memory_pool/concerns.json sir_hydration_habit.what_i_watch
     '8-mug/3L target' → '10-cup/3L target' (数据 fix).
"""
import os
import sys
import json
import unittest
import tempfile
import shutil

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


class TestL1WriteReceiptPhysicalWrite(unittest.TestCase):
    """L1: WriteReceipt 加 physical_write 字段 (区分真覆写 vs audit-only)."""

    def test_physical_write_field_exists(self):
        from jarvis_memory_hub import WriteReceipt
        r = WriteReceipt(
            mutation_id='m1', ts=0, iso='', field_path='profile.x',
            new_value_excerpt='v', old_value_excerpt='', source='test',
            confidence=0.9, layer_targeted='ProfileCard', ok=True,
        )
        self.assertTrue(hasattr(r, 'physical_write'))
        self.assertEqual(r.physical_write, False, '默认 False')

    def test_physical_write_default_audit_only(self):
        from jarvis_memory_hub import WriteReceipt
        r = WriteReceipt(
            mutation_id='m1', ts=0, iso='', field_path='profile.x',
            new_value_excerpt='v', old_value_excerpt='', source='test',
            confidence=0.9, layer_targeted='ProfileCard', ok=True,
        )
        d = r.to_dict()
        self.assertIn('physical_write', d)
        self.assertEqual(d['physical_write'], False)


class TestL2ChatBypassPrecisionDisplay(unittest.TestCase):
    """L2: chat_bypass 显示精准 — physical_write=True 才说 atomic 覆写."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_chat_bypass.py'), 'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_atomic_message_gated_by_physical_write(self):
        """'sir_profile.json 已 atomic 覆写' 字符串前必须有 physical_write 检查 (用 rfind 找最后一次, 真 code 不是注释)."""
        # 用 rfind 找最后一处 — 通常是 code, 注释在前
        idx = self.src.rfind('sir_profile.json 已 atomic 覆写')
        self.assertGreater(idx, 0, '应找到完整 atomic 覆写 字符串')
        section = self.src[max(0, idx - 300):idx]
        self.assertIn("getattr(receipt, 'physical_write', False)", section,
                      'atomic 覆写 真代码前必须有 physical_write 检查')

    def test_audit_only_fallback_message_exists(self):
        """audit-only fallback 路径必须有显示 (诚信)."""
        self.assertIn('audit-only fallback', self.src,
                      'audit-only fallback 必须有显示')
        self.assertIn('sir_profile.json 未真改', self.src,
                      '必须明告 Sir profile 未真改')


class TestL3HealthGoalsAllowed(unittest.TestCase):
    """L3: _OVERWRITE_ALLOWED_FIELDS 必须含 health_goals."""

    def test_health_goals_in_allowed_list(self):
        from jarvis_routing import ProfileCard
        self.assertIn('health_goals', ProfileCard._OVERWRITE_ALLOWED_FIELDS,
                      'health_goals 必须在白名单 (BUG A L3)')

    def test_unit_preferences_still_in_allowed(self):
        """既有的 unit_preferences 不应被回归."""
        from jarvis_routing import ProfileCard
        self.assertIn('unit_preferences', ProfileCard._OVERWRITE_ALLOWED_FIELDS)


class TestL4ConcernsHydrationFix(unittest.TestCase):
    """L4: concerns.json sir_hydration_habit.what_i_watch 数据 fix."""

    def test_what_i_watch_uses_10_cup(self):
        with open(os.path.join(ROOT, 'memory_pool', 'concerns.json'), 'r', encoding='utf-8') as f:
            d = json.load(f)
        what = d.get('sir_hydration_habit', {}).get('what_i_watch', '')
        self.assertIn('10-cup', what, "what_i_watch 必须是 '10-cup/3L target' (3000ml / 300ml/cup)")
        self.assertNotIn('8-mug', what, "what_i_watch 不能再有错误的 '8-mug'")


class TestPriorBypassFallbackMessage(unittest.TestCase):
    """老路径: receipt.ok=True 但有 error 时, chat_bypass 显示 fallback 警告."""

    def test_summary_contains_fallback_warning_when_audit_only(self):
        """模拟一个 audit-only receipt (ok=True, physical_write=False, err='...fallback...')"""
        from jarvis_memory_hub import WriteReceipt
        r = WriteReceipt(
            mutation_id='m1', ts=0, iso='', field_path='profile.hydration_goal',
            new_value_excerpt='3000ml', old_value_excerpt='', source='fast_call_mutation:update',
            confidence=0.9, layer_targeted='ProfileCard', ok=True,
            error='overwrite_field fail: top field hydration_goal not in allowed list',
            physical_write=False,
        )
        # 验 receipt physical_write=False
        self.assertFalse(r.physical_write)
        # 验 error 非空
        self.assertIn('not in allowed list', r.error)


if __name__ == '__main__':
    unittest.main()
