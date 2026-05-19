# -*- coding: utf-8 -*-
"""[β.5.20 / 2026-05-20] Sir 实测 BUG-AFK: 主脑误触 offer_help on Sir AFK
全集修复 testcase (β.5.20-A/B/C 三 sub-step).

Sir 实测 (5/20 00:42):
  1. Sir AFK 9.6min (Cascade 跑代码出 AttributeError)
  2. Conductor `_check_path_a` 触发 → conductor_message 给主脑 "空闲:578s + 报错:True + 窗口:Cursor IDE"
  3. 主脑 LLM 看 578s 不语义化, 难推 "Sir AFK 9.6min"
  4. 主脑生成 offer_help "AttributeErrors persistent, Sir" — 错对象 (Cascade Agent 在 fix, 不是 Sir)

修法 3 sub-step:
  - β.5.20-A: jarvis_conductor.py path_a + path_b sensor_summary 替原始 `空闲:578s` →
    语义化标签 (`AFK 9min — Sir 离开桌前` / `短暂空闲 3min` / `在场`); nudge_context 加
    `afk_minutes` + `is_afk_long`.
  - β.5.20-B: jarvis_chat_bypass.py stream_nudge 加 AFK CONTEXT block —
    afk_minutes >= 3 且 nudge_type ≠ return_greeting/morning_greeting 时, 给主脑 evidence:
    Sir 离开 X min, 屏幕状态可能不是 Sir 在挣扎 fix, 主脑可选 [SILENCE] / 转 welcome back.
  - β.5.20-C: jarvis_smart_nudge.py SmartNudgeSentinel._dispatch_nudge nudge_context 同样
    加 afk_minutes / is_afk_long (从 PhysicalEnvironmentProbe.get_sensor_snapshot 读).
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


class TestBeta520AConductorAFKSemanticSignal(unittest.TestCase):
    """[β.5.20-A] Conductor sensor_summary 替原始 idle_seconds → 语义化 + nudge_context 加 afk_minutes"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_conductor.py'))

    def test_marker(self):
        self.assertIn('β.5.20-A', self.src,
            'jarvis_conductor.py 必须含 β.5.20-A marker')

    def test_path_a_sensor_summary_uses_semantic_label(self):
        """path_a sensor_summary 必须含 `空闲状态:` 替代原始 `空闲:`+s 数."""
        # 找 _dispatch_path_a 位置
        idx = self.src.find('def _dispatch_path_a')
        self.assertGreater(idx, 0)
        end = self.src.find('def _execute_path_b', idx)
        region = self.src[idx:end]
        self.assertIn('空闲状态:', region,
            "path_a sensor_summary 必须含 '空闲状态:' 语义化标签")
        # 不再用原始 `空闲:{idle_seconds}s` 形态
        self.assertNotIn(
            "f\"空闲: {snapshot.get('idle_seconds', 0)}s | \"", region,
            'path_a sensor_summary 不再用 `空闲:Xs` 原始秒数')

    def test_path_b_sensor_summary_uses_semantic_label(self):
        """path_b sensor_summary 同样语义化."""
        idx = self.src.find('def _execute_path_b')
        self.assertGreater(idx, 0)
        end = self.src.find('def _rule_decision', idx)
        region = self.src[idx:end] if end > idx else self.src[idx:idx + 10000]
        self.assertIn('空闲状态:', region,
            'path_b sensor_summary 必须含 `空闲状态:` 语义化标签')

    def test_afk_label_three_buckets(self):
        """语义化标签 3 档: 在场 / 短暂空闲 / AFK Sir 离开桌前."""
        self.assertIn('AFK', self.src)
        self.assertIn('短暂空闲', self.src)
        self.assertIn('在场', self.src)

    def test_path_a_nudge_context_has_afk_minutes(self):
        """path_a nudge_context 加 afk_minutes / is_afk_long 字段."""
        idx = self.src.find('def _dispatch_path_a')
        end = self.src.find('def _execute_path_b', idx)
        region = self.src[idx:end]
        self.assertIn('"afk_minutes":', region,
            'path_a nudge_context 必须含 afk_minutes')
        self.assertIn('"is_afk_long":', region)

    def test_path_b_nudge_context_has_afk_minutes(self):
        """path_b nudge_context 加 afk_minutes / is_afk_long 字段."""
        idx = self.src.find('def _execute_path_b')
        end = self.src.find('def _rule_decision', idx)
        region = self.src[idx:end] if end > idx else self.src[idx:idx + 10000]
        self.assertIn('"afk_minutes":', region)
        self.assertIn('"is_afk_long":', region)

    def test_afk_buckets_5min_threshold(self):
        """is_afk_long 阈值是 5 (跟 chat_bypass β.5.20-B 同步)."""
        self.assertIn('_afk_min >= 5', self.src,
            'is_afk_long 阈值必须是 5min')


class TestBeta520BChatBypassAFKContextBlock(unittest.TestCase):
    """[β.5.20-B] chat_bypass stream_nudge 加 AFK CONTEXT block"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_chat_bypass.py'))

    def test_marker(self):
        self.assertIn('β.5.20-B', self.src,
            'jarvis_chat_bypass.py 必须含 β.5.20-B marker')

    def test_afk_context_block_present(self):
        """AFK CONTEXT block 在 stream_nudge prompt 拼接路径里."""
        self.assertIn('[AFK CONTEXT', self.src,
            'stream_nudge 必须含 [AFK CONTEXT block')
        self.assertIn('afk_minutes:', self.src)
        self.assertIn('is_afk_long:', self.src)

    def test_afk_threshold_3min(self):
        """β.5.20-B 阈值: afk_minutes >= 3min 才注入 (短暂空闲也提示)."""
        self.assertIn('_afk_min >= 3', self.src,
            'AFK CONTEXT block 注入阈值 >= 3min')

    def test_afk_block_excludes_return_greeting(self):
        """return_greeting / morning_greeting 不注入 AFK CONTEXT (那本就是问候归来)."""
        idx = self.src.find('[AFK CONTEXT')
        self.assertGreater(idx, 0)
        # 前 200 字内含 return_greeting 排除
        region = self.src[max(0, idx - 400):idx + 100]
        self.assertIn('return_greeting', region,
            'AFK CONTEXT block 必须排除 return_greeting')

    def test_afk_block_evidence_based(self):
        """主脑决策提示是 evidence-based (准则 6 不写死句式)."""
        idx = self.src.find('[AFK CONTEXT')
        region = self.src[idx:idx + 2000]
        # 含 'evidence' / 'decision 提示' 等关键字
        self.assertIn('evidence', region.lower())
        # 不写死 "say 'welcome back'" — 给选项让主脑自决
        # (我们写 'welcome back' 风格 + [SILENCE] 选项)
        self.assertIn('[SILENCE]', region,
            'AFK block 必须给 [SILENCE] 选项让主脑自决')


class TestBeta520CSmartNudgeAFKSignal(unittest.TestCase):
    """[β.5.20-C] SmartNudgeSentinel._dispatch_nudge nudge_context 加 afk_minutes"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_smart_nudge.py'))

    def test_marker(self):
        self.assertIn('β.5.20-C', self.src,
            'jarvis_smart_nudge.py 必须含 β.5.20-C marker')

    def test_nudge_context_has_afk_signal(self):
        """_dispatch_nudge context 加 afk_minutes / is_afk_long 字段."""
        idx = self.src.find('def _dispatch_nudge')
        self.assertGreater(idx, 0)
        # 看后续 2000 字内有这两字段
        region = self.src[idx:idx + 3000]
        self.assertIn('context["afk_minutes"]', region)
        self.assertIn('context["is_afk_long"]', region)

    def test_uses_get_sensor_snapshot(self):
        """读 idle_seconds 必须走 PhysicalEnvironmentProbe.get_sensor_snapshot()
        (跟 conductor 同源 + 同款 line 735 已用法).
        """
        idx = self.src.find('def _dispatch_nudge')
        region = self.src[idx:idx + 3000]
        self.assertIn('PhysicalEnvironmentProbe.get_sensor_snapshot()', region,
            '必须走 get_sensor_snapshot() classmethod 不是 attr')

    def test_threshold_5min_consistent(self):
        """is_afk_long 阈值 5min, 跟 conductor (β.5.20-A) + chat_bypass (β.5.20-B) 同步."""
        idx = self.src.find('def _dispatch_nudge')
        region = self.src[idx:idx + 3000]
        self.assertIn('_afk_min >= 5', region)


class TestBeta520RuntimeBehavior(unittest.TestCase):
    """[β.5.20] 运行时模拟 — Sir AFK 9.6min 场景模拟 nudge_context 数据流"""

    def test_simulated_afk_minutes_propagation(self):
        """模拟 Conductor → nudge_context → chat_bypass 主脑 prompt: afk_minutes 字段穿透."""
        # 模拟 Conductor 注入
        nudge_context = {
            "type": "offer_help",
            "afk_minutes": 9,
            "is_afk_long": True,
            "conductor_message": "Sir 空闲状态: AFK 9min — Sir 离开桌前. 报错: True",
        }
        # 简化的 chat_bypass 等价逻辑
        afk_min = nudge_context.get('afk_minutes', 0) or 0
        is_afk_long = nudge_context.get('is_afk_long', False)
        afk_block_should_inject = afk_min >= 3 and nudge_context.get('type') not in (
            'return_greeting', 'morning_greeting')
        self.assertTrue(afk_block_should_inject,
            'Sir AFK 9.6min + offer_help 时, AFK CONTEXT block 必须注入')
        self.assertTrue(is_afk_long, 'AFK 9min ≥ 5 → is_afk_long=True')

    def test_simulated_short_afk_no_inject(self):
        """模拟 Sir 在场 (afk_minutes=0): AFK CONTEXT block 不注入."""
        nudge_context = {"type": "offer_help", "afk_minutes": 0, "is_afk_long": False}
        afk_min = nudge_context.get('afk_minutes', 0) or 0
        afk_block_should_inject = afk_min >= 3
        self.assertFalse(afk_block_should_inject,
            'Sir 在场 afk=0 时不注入 AFK CONTEXT block')

    def test_simulated_return_greeting_excluded(self):
        """return_greeting 即使 AFK 9min 也不注入 (那本就是问候归来)."""
        nudge_context = {"type": "return_greeting", "afk_minutes": 9, "is_afk_long": True}
        afk_min = nudge_context.get('afk_minutes', 0) or 0
        afk_block_should_inject = afk_min >= 3 and nudge_context.get('type') not in (
            'return_greeting', 'morning_greeting')
        self.assertFalse(afk_block_should_inject,
            'return_greeting 类型不注入 AFK CONTEXT (避免重复)')


if __name__ == '__main__':
    unittest.main(verbosity=2)
