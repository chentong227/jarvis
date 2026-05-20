"""P2 修复测试（继 R7-β post-test v2 / P1 之后）：
NudgeGate 硬冻结 + Conductor 拒绝期尊重 + 强拒绝词典 + TTS 末尾静音 + set_browser_ducking 名单 + 字幕跨轮清空

跑法：
    cd d:\\Jarvis
    python tests/_test_p2_refusal_and_audio.py

覆盖：
1. NudgeGate.freeze_for 现在是"硬冻结" → 即使 is_urgent=True 也被拒绝
2. Conductor._dispatch_path_a / _execute_path_b 对所有 nudge_type 都尊重 _refused_help_until
   （之前只有 offer_help 走这条路）
3. _STRONG_REFUSAL_PATTERNS 词典存在 + 包含核心强拒绝词
4. set_browser_ducking 目标进程名单扩大（含 Edge 全家 / 国内浏览器 / 直播宿主）
5. vocal.render_only 末尾追加 0.25s 静音 padding（修"Done, Sir." 末尾被截）
6. SubtitleOverlay 在 lang="en" 时间隔 > 3s 自动清空旧字幕（修"字是不断累加的"）
"""
import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestNudgeGateHardFreeze(unittest.TestCase):
    """[P2-A] freeze_for 必须连 is_urgent=True 也挡住。"""

    def setUp(self):
        from jarvis_nerve import NudgeGate
        self.gate = NudgeGate(cooldown_seconds=90)

    def test_freeze_blocks_urgent_calls(self):
        self.gate.freeze_for(30.0, source='user_rejection')
        self.assertFalse(self.gate.can_speak('guardian', is_urgent=True),
                         "freeze_for 必须挡住 is_urgent=True 的来电")
        self.assertFalse(self.gate.can_speak('companion', is_urgent=True),
                         "freeze_for 必须挡住所有中心的 is_urgent")

    def test_freeze_blocks_non_urgent_too(self):
        self.gate.freeze_for(30.0, source='user_rejection')
        self.assertFalse(self.gate.can_speak('guardian', is_urgent=False))
        self.assertFalse(self.gate.can_speak('companion', is_urgent=False))

    def test_freeze_expires_after_duration(self):
        self.gate.freeze_for(0.01, source='test')
        time.sleep(0.05)
        self.assertTrue(self.gate.can_speak('guardian', is_urgent=True),
                        "freeze 过期后必须放行")

    def test_freeze_for_zero_seconds_safe(self):
        self.gate.freeze_for(0.0, source='test')
        # 0s freeze should not really block (or only block 1 step)
        self.assertTrue(self.gate.can_speak('guardian', is_urgent=True))

    def test_is_hard_frozen_method_exists(self):
        self.assertTrue(hasattr(self.gate, 'is_hard_frozen'))
        self.gate.freeze_for(5.0, source='test')
        self.assertTrue(self.gate.is_hard_frozen())

    def test_freeze_longer_overrides_shorter(self):
        self.gate.freeze_for(0.5, source='short')
        self.gate.freeze_for(60.0, source='long')
        # 长 freeze 应该胜出
        time.sleep(0.6)
        self.assertFalse(self.gate.can_speak('guardian', is_urgent=True),
                         "60s freeze 必须覆盖 0.5s freeze")


class TestStrongRefusalPatterns(unittest.TestCase):
    """[P2-B] _STRONG_REFUSAL_PATTERNS 词典必须存在且包含核心词。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_strong_refusal_constant_declared(self):
        self.assertIn('_STRONG_REFUSAL_PATTERNS', self.src)

    def test_contains_core_chinese_phrases(self):
        for phrase in ("不需要你的帮助", "别再提", "闭嘴", "不要打扰"):
            self.assertIn(f'"{phrase}"', self.src,
                          f"_STRONG_REFUSAL_PATTERNS 必须包含 '{phrase}'")

    def test_contains_core_english_phrases(self):
        for phrase in ("stop offering", "leave me alone", "shut up"):
            self.assertIn(f'"{phrase}"', self.src,
                          f"_STRONG_REFUSAL_PATTERNS 必须包含 '{phrase}'")

    def test_detect_help_refusal_uses_strong_pattern(self):
        """🩹 [β.5.35 / 2026-05-20] regex 跟上 refusal_vocab 持久化重构.
        老 regex 锁 `is_strong_refusal = any(... _STRONG_REFUSAL_PATTERNS)`,
        β.4.X 已重构: vocab 持久化后用 `_strong` 局部变量 (从 vocab dict 拿).
        允许两种写法 (`_strong` 或直接 `_STRONG_REFUSAL_PATTERNS`).

        regex 注意: `p.lower()` 内含 `)`, 不能用 `[^)]*` (会卡在第一个 `)`).
        用 `.*?` 非贪婪即可 (同一行内匹配, 不跨行)."""
        self.assertIn('_STRONG_REFUSAL_PATTERNS', self.src)
        self.assertRegex(
            self.src,
            r'is_strong_refusal\s*=\s*any\(.*?(_strong|_STRONG_REFUSAL_PATTERNS)',
            "_detect_help_refusal 必须用 _strong / _STRONG_REFUSAL_PATTERNS 判强拒绝"
        )

    def test_strong_refusal_triggers_300s_freeze(self):
        # 强拒绝时 freeze_seconds = 300
        self.assertRegex(
            self.src,
            r'is_strong_refusal[^\n]*\n[^\n]*freeze_seconds\s*=\s*300\.0',
            "强拒绝必须触发 ≥300s 硬冻结"
        )


class TestConductorRefusalRespectAllTypes(unittest.TestCase):
    """[P2-C] Conductor 路径 A/B 对所有 nudge_type 都尊重 _refused_help_until。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_path_b_checks_refused_before_type_branch(self):
        # _execute_path_b 必须在 nudge_type 分支之前先做一次"任何类型"的拒绝期检查
        m = re.search(
            r'def _execute_path_b.*?_refused_help_until.*?nudge_type\s*!=\s*[\'"]return_greeting[\'"]'
            r'.*?if nudge_type == [\'"]offer_help[\'"]',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "_execute_path_b 必须在 nudge_type==offer_help 之前先做一次 _refused_help_until 检查（return_greeting 例外）"
        )

    def test_path_a_checks_refused_before_type_branch(self):
        m = re.search(
            r'def _dispatch_path_a.*?_refused_help_until.*?nudge_type\s*!=\s*[\'"]return_greeting[\'"]'
            r'.*?if nudge_type == [\'"]offer_help[\'"]',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "_dispatch_path_a 必须在 nudge_type==offer_help 之前先做一次 _refused_help_until 检查"
        )

    def test_refusal_respect_emits_bg_log(self):
        self.assertIn('Conductor/RefusalRespect', self.src)


class TestBrowserDuckingExpanded(unittest.TestCase):
    """[P2-D] set_browser_ducking 目标进程名单必须扩大。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_covers_edge_family(self):
        for name in ("msedge.exe", "msedgewebview2.exe"):
            self.assertIn(f'"{name}"', self.src,
                          f"set_browser_ducking 必须覆盖 {name}")

    def test_covers_chinese_browsers(self):
        for name in ("qqbrowser.exe", "sogouexplorer.exe", "360se.exe"):
            self.assertIn(f'"{name}"', self.src,
                          f"set_browser_ducking 必须覆盖国内浏览器 {name}")

    def test_covers_live_stream_hosts(self):
        for name in ("obs64.exe", "potplayer.exe", "vlc.exe"):
            self.assertIn(f'"{name}"', self.src,
                          f"set_browser_ducking 必须覆盖直播宿主 {name}")

    def test_emits_ducking_bg_log(self):
        self.assertIn('BrowserDucking', self.src,
                      "set_browser_ducking 应当 bg_log 实际静音了几个会话")


class TestVocalCordTrailingSilence(unittest.TestCase):
    """[P2-E] vocal.render_only 末尾必须追加静音 padding 避免短句被截。"""

    @classmethod
    def setUpClass(cls):
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'jarvis_vocal_cord.py'))
        with open(path, 'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_trailing_silence_added(self):
        self.assertIn('trailing_silence', self.src,
                      "render_only 必须追加 trailing_silence")
        self.assertIn('leading_silence', self.src)

    def test_trailing_silence_uses_22050(self):
        # 22050 是 vocal.stream 的采样率
        self.assertRegex(
            self.src,
            r'trailing_silence_samples\s*=\s*int\(0\.2\d\s*\*\s*22050\)',
            "trailing_silence 应当用 22050 采样率 + ~0.2s 长度"
        )

    def test_final_audio_includes_both_paddings(self):
        # final_audio_int16 必须是 (leading + audio + trailing) 的拼接
        self.assertRegex(
            self.src,
            r'np\.concatenate\(\(leading_silence,\s*audio_data_int16,\s*trailing_silence\)\)',
            "final_audio 必须按 leading + audio + trailing 顺序拼接"
        )


class TestSubtitleAccumulationFix(unittest.TestCase):
    """[P2-F] SubtitleOverlay 在 lang=='en' 时检测时间间隔自动清空旧字幕。
    
    [v5 Sir-2026-05-14] 阈值从 3.0s → 8.0s（修"英文打印不完整"——慢响应两句间隔可达 4-7s）。
    """

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_en_handler_has_gap_clear(self):
        # v5：阈值改为 8.0s
        m = re.search(
            r'elif lang == "en":(.+?)elif lang ==',
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m, "找不到 lang == 'en' 分支")
        body = m.group(1)
        self.assertIn('self._last_update', body,
                      "lang=='en' 分支必须用 _last_update 检测跨轮")
        self.assertRegex(body, r'time\.time\(\)\s*-\s*self\._last_update\s*>\s*8\.0',
                         "lang=='en' 分支必须用 8.0s 间隔判断新一轮（v5：从 3.0 抬高，修慢响应截断）")
        self.assertRegex(body, r'self\._en_words\s*=\s*\[\]',
                         "跨轮检测命中后必须清空 _en_words")


class TestHelpRefusalCalls(unittest.TestCase):
    """[P2-G] _detect_help_refusal 实测：对 "不需要你的帮助" 触发 ≥300s 硬冻结。"""

    def test_full_pipeline_strong_refusal_hard_freezes(self):
        """模拟 _detect_help_refusal 真实调用，验证 NudgeGate 真的硬冻结。"""
        from jarvis_nerve import NudgeGate, JarvisWorkerThread

        class _DummyJarvis:
            def __init__(self):
                self.short_term_memory = []
                self.nudge_gate = NudgeGate(cooldown_seconds=90)
                self.event_bus = None
                # 模拟 companion_center.smart_nudge
                class _CC:
                    class _SN:
                        _refused_help_until = 0.0
                        _help_refusal_history = []
                        _last_help_fingerprint = ''
                        _last_help_fingerprint_time = 0.0
                        def _calc_help_cooldown(self, fp):
                            return 600.0
                        def _gen_help_fingerprint(self, ctx):
                            return 'generic'
                    smart_nudge = _SN()
                companion_center = _CC()

        dummy = _DummyJarvis()
        # 不通过 super().__init__() 直接拿到 _detect_help_refusal
        worker = JarvisWorkerThread.__new__(JarvisWorkerThread)
        worker.jarvis = dummy
        worker.humor_memory = None  # 不需要 humor 也能跑

        worker._detect_help_refusal("不需要你的帮助")
        # NudgeGate 应当被硬冻结
        self.assertTrue(dummy.nudge_gate.is_hard_frozen(),
                        "强拒绝必须立刻硬冻结 NudgeGate")
        # 即使带 is_urgent=True 也应该被挡
        self.assertFalse(dummy.nudge_gate.can_speak('guardian', is_urgent=True, nudge_type='offer_help'),
                         "强拒绝硬冻结时，Conductor is_urgent=True 也不能说话")

    def test_pipeline_with_generic_refusal(self):
        """模拟一般拒绝（"算了"），90s 硬冻结。"""
        from jarvis_nerve import NudgeGate, JarvisWorkerThread

        class _Dummy:
            short_term_memory = []
            nudge_gate = NudgeGate(cooldown_seconds=90)
            event_bus = None
            class _CC:
                class _SN:
                    _refused_help_until = 0.0
                    _help_refusal_history = []
                    _last_help_fingerprint = ''
                    _last_help_fingerprint_time = 0.0
                    def _calc_help_cooldown(self, fp):
                        return 600.0
                    def _gen_help_fingerprint(self, ctx):
                        return 'generic'
                smart_nudge = _SN()
            companion_center = _CC()

        dummy = _Dummy()
        worker = JarvisWorkerThread.__new__(JarvisWorkerThread)
        worker.jarvis = dummy
        worker.humor_memory = None

        worker._detect_help_refusal("算了")
        # 还是会冻结（至少 90s）
        self.assertTrue(dummy.nudge_gate.is_hard_frozen())


class TestConductorRefusalRespectRuntime(unittest.TestCase):
    """[P2-H] 运行时验证：拒绝期内 Conductor.execute_path_b 真的会 return。"""

    def test_path_b_blocked_by_refusal(self):
        """模拟 _execute_path_b 触发，应该在 _refused_help_until 期内 return 不发命令。"""
        from jarvis_nerve import Conductor, NudgeGate

        class _Worker:
            def __init__(self):
                self.commands = []
                self.jarvis = self
                self.short_term_memory = []
                # 模拟 companion_center.smart_nudge
                class _CC:
                    class _SN:
                        _refused_help_until = time.time() + 600.0  # 还在拒绝期
                        _help_refusal_history = []
                        _last_help_fingerprint = ''
                        _last_help_fingerprint_time = 0.0
                        def _calc_help_cooldown(self, fp):
                            return 0.0
                        def _gen_help_fingerprint(self, ctx):
                            return 'generic'
                    smart_nudge = _SN()
                self.companion_center = _CC()
            def push_command(self, cmd):
                self.commands.append(cmd)

        worker = _Worker()
        gate = NudgeGate(cooldown_seconds=90)
        conductor = Conductor(worker, nudge_gate=gate)

        # 仅"决策完成且 should_speak=True"才会触发
        # 用 monkeypatch 短路 _decision_llm
        def fake_decision(filter_result):
            return {
                'should_speak': True,
                'nudge_type': 'check_in',  # 非 offer_help —— 验证新分支
                'action': 'Check-in',
                'decision_reason': 'test',
                'tone': 'gentle',
                'confidence': 0.8,
            }
        conductor._decision_llm = fake_decision

        # 提供 filter_result
        result = {
            'triggered': True,
            'reason': 'test',
            'snapshot': {},
            'fusion_trend': '',
        }
        conductor._execute_path_b(result)
        self.assertEqual(len(worker.commands), 0,
                         "拒绝期内任何 nudge_type 都不应该 push __NUDGE__")


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestNudgeGateHardFreeze),
        loader.loadTestsFromTestCase(TestStrongRefusalPatterns),
        loader.loadTestsFromTestCase(TestConductorRefusalRespectAllTypes),
        loader.loadTestsFromTestCase(TestBrowserDuckingExpanded),
        loader.loadTestsFromTestCase(TestVocalCordTrailingSilence),
        loader.loadTestsFromTestCase(TestSubtitleAccumulationFix),
        loader.loadTestsFromTestCase(TestHelpRefusalCalls),
        loader.loadTestsFromTestCase(TestConductorRefusalRespectRuntime),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] All P2 fix tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
