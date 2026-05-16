"""轴 1.5 单元测试：VISUAL_PULSE 通道接通 BreathingLight

起因：α5 设计了 VISUAL_PULSE 通道（金光呼吸 + 字幕飘一行不出声），
但 BreathingLightUI 之前不读 subtitle_queue，subtitle_queue.put(("visual_pulse", ...)) 直接被丢。
本轮接通：SubtitleOverlay._poll_queue 收到 visual_pulse → 调 orb.flash_pulse(kind) → 1.2s 后回基线。

跑法：
    cd d:\\Jarvis
    python tests/_test_axis1_5_visual_pulse.py
"""
import os
import re
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestVisualPulseSourceContract(unittest.TestCase):
    """源码契约：flash_pulse 方法 + visual_pulse 派发 + pulse 防覆盖。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_flash_pulse_method_exists(self):
        self.assertIn('def flash_pulse(self', self.src,
                      "BreathingLightUI 必须有 flash_pulse 方法")

    def test_pulse_state_fields_in_init(self):
        # __init__ 必须初始化 _pulse_active / _pulse_start_time / _pulse_duration
        self.assertIn('_pulse_active', self.src)
        self.assertIn('_pulse_start_time', self.src)
        self.assertIn('_pulse_duration', self.src)

    def test_subtitle_overlay_dispatches_visual_pulse(self):
        # _poll_queue 的 visual_pulse 分支必须调 orb.flash_pulse
        m = re.search(
            r'elif lang == "visual_pulse":.*?orb\.flash_pulse',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "SubtitleOverlay._poll_queue visual_pulse 分支必须调 orb.flash_pulse")

    def test_update_targets_guards_pulse(self):
        # _update_targets 入口必须检查 _pulse_active，pulse 中不被状态机覆盖
        m = re.search(
            r'def _update_targets.*?_pulse_active.*?return',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "_update_targets 必须在 _pulse_active 时短路 return")

    def test_paintGL_clears_pulse_on_expiry(self):
        # paintGL 必须在 pulse 到期时设置 _pulse_active = False
        m = re.search(
            r'def paintGL.*?_pulse_active.*?_pulse_duration.*?False',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "paintGL 必须检测 pulse 到期 → _pulse_active = False")

    def test_pulse_three_kinds_supported(self):
        # flash_pulse 必须区分至少 3 种 kind：gold/amber/lavender
        self.assertIn("'gold'", self.src)
        self.assertIn("'amber'", self.src)
        self.assertIn("'lavender'", self.src)


class TestFlashPulseBehavior(unittest.TestCase):
    """运行时：flash_pulse 真的会 spike scale/color_mix 并自动回基线。"""

    def _make_orb(self):
        """构造一个最小 orb，不进 OpenGL 真实初始化。"""
        from jarvis_nerve import BreathingLightUI
        orb = BreathingLightUI.__new__(BreathingLightUI)
        # 手动初始化必需字段（绕过 PyQt 全套初始化）
        orb.state = "IDLE"
        orb.is_awake = False
        orb.current_scale = 0.15
        orb.current_speed = 0.4
        orb.current_color_mix = 0.0
        orb.target_scale = 0.15
        orb.target_speed = 0.4
        orb.target_color_mix = 0.0
        orb._debounce_until = 0.0
        orb._pending_state = None
        orb._pending_awake = None
        orb._pulse_active = False
        orb._pulse_start_time = 0.0
        orb._pulse_duration = 1.2
        orb._pulse_target_scale = 0.40
        orb._pulse_target_color_mix = 0.85
        orb._pulse_target_speed = 1.4
        return orb

    def test_flash_pulse_sets_active_flag(self):
        orb = self._make_orb()
        orb.flash_pulse('gold')
        self.assertTrue(orb._pulse_active)

    def test_flash_pulse_spikes_scale(self):
        orb = self._make_orb()
        base = orb.target_scale  # 0.15
        orb.flash_pulse('gold')
        self.assertGreater(orb.target_scale, base + 0.15,
                           "pulse 必须明显抬高 target_scale (>0.30)")

    def test_flash_pulse_spikes_color_mix(self):
        orb = self._make_orb()
        orb.flash_pulse('gold')
        self.assertGreater(orb.target_color_mix, 0.5,
                           "gold pulse 必须让 color_mix > 0.5（偏暖色）")

    def test_flash_pulse_amber_differs_from_gold(self):
        orb1 = self._make_orb()
        orb1.flash_pulse('gold')
        orb2 = self._make_orb()
        orb2.flash_pulse('amber')
        # amber 应该比 gold 更激进（更橙）
        self.assertNotEqual(
            (orb1.target_scale, orb1.target_color_mix),
            (orb2.target_scale, orb2.target_color_mix),
            "amber 和 gold 应该有不同的 target 值",
        )

    def test_flash_pulse_unknown_kind_falls_back(self):
        orb = self._make_orb()
        orb.flash_pulse('totally_made_up_kind')
        self.assertTrue(orb._pulse_active)
        # 应该走默认暖金色（scale > 0.3）
        self.assertGreater(orb.target_scale, 0.3)

    def test_update_targets_blocked_during_pulse(self):
        orb = self._make_orb()
        orb.flash_pulse('gold')
        spike_scale = orb.target_scale
        # 模拟状态机想把 target_scale 拉回 IDLE
        orb.state = "IDLE"
        orb.is_awake = False
        orb._update_targets()
        # pulse 期间应该保持 spike，不被覆盖
        self.assertEqual(orb.target_scale, spike_scale,
                         "pulse 期间 _update_targets 不能覆盖 target_scale")

    def test_pulse_expires_after_duration(self):
        """pulse 到期后调 _update_targets 应回到 IDLE 基线。"""
        orb = self._make_orb()
        orb.flash_pulse('gold')
        # 把 _pulse_start_time 调到过去（模拟 1.5s 前）
        orb._pulse_start_time = time.time() - 2.0
        # 模拟 paintGL 中的过期检查逻辑
        if time.time() - orb._pulse_start_time >= orb._pulse_duration:
            orb._pulse_active = False
            orb._update_targets()
        self.assertFalse(orb._pulse_active)
        # 已回到 IDLE 待机基线
        self.assertAlmostEqual(orb.target_scale, 0.15, places=2)


class TestSubtitleOverlayDispatch(unittest.TestCase):
    """运行时：SubtitleOverlay 收到 visual_pulse 事件 → orb.flash_pulse 被调。"""

    def test_visual_pulse_event_dispatches_to_orb(self):
        """模拟 SubtitleOverlay._poll_queue 处理 ('visual_pulse', 'task_handoff_ready')。"""
        # 检查源码包含正确的调用模式
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        src = _read_corpus()

        # 必须包含 getattr(self, 'orb', None) 模式 → 防 orb 不存在时崩
        self.assertIn("getattr(self, 'orb', None)", src,
                      "visual_pulse 分支必须用 getattr 兜底 orb 存在性")
        # 必须调 flash_pulse
        m = re.search(
            r'elif lang == "visual_pulse":.*?orb\.flash_pulse\(',
            src, re.DOTALL,
        )
        self.assertIsNotNone(m)

    def test_visual_pulse_event_uses_text_as_kind(self):
        """('visual_pulse', 'gold') 中 text 应作为 kind 传给 flash_pulse。"""
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        src = _read_corpus()
        m = re.search(
            r'elif lang == "visual_pulse":.*?orb\.flash_pulse\(str\(text\)',
            src, re.DOTALL,
        )
        self.assertIsNotNone(m,
                             "flash_pulse 调用应把 text 转 str 后作为 kind 传入")


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestVisualPulseSourceContract),
        loader.loadTestsFromTestCase(TestFlashPulseBehavior),
        loader.loadTestsFromTestCase(TestSubtitleOverlayDispatch),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] 轴 1.5 VISUAL_PULSE tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
