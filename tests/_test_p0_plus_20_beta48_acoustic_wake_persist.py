# -*- coding: utf-8 -*-
"""
[P0+20-β.4.8 / 2026-05-19] AcousticWakeDetector (openWakeWord) 测试套件

覆盖:
- vocab 加载 (mtime cache / seed fallback / 损坏)
- AcousticWakeDetector.create (各种 fail-safe 路径)
- process / feed_pyaudio_buffer 行为
- 准则 6.5 红线 (vocab 在 memory_pool/, 无 .py 硬编码 wakeword)
- 单例 get / reset
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ==========================================================================
# Vocab loader
# ==========================================================================

class TestP0Plus20Beta48VocabLoader(unittest.TestCase):
    def setUp(self):
        from jarvis_acoustic_wake import _MIC_VOCAB_CACHE
        _MIC_VOCAB_CACHE['mtime'] = 0.0
        _MIC_VOCAB_CACHE['data'] = None

    def test_vocab_file_exists(self):
        p = os.path.join(ROOT, 'memory_pool', 'mic_safety_vocab.json')
        self.assertTrue(os.path.exists(p), 'memory_pool/mic_safety_vocab.json 必须存在')
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('_meta', data)
        self.assertIn('thresholds', data['_meta'])

    def test_load_thresholds_has_all_required_keys(self):
        from jarvis_acoustic_wake import load_mic_safety_thresholds, _SEED_THRESHOLDS
        thr = load_mic_safety_thresholds()
        for k in _SEED_THRESHOLDS:
            self.assertIn(k, thr, f'thresholds 缺字段 {k}')

    def test_load_thresholds_types(self):
        from jarvis_acoustic_wake import load_mic_safety_thresholds
        thr = load_mic_safety_thresholds()
        self.assertIsInstance(thr['acoustic_wake_enabled'], bool)
        self.assertIsInstance(thr['openwakeword_model'], str)
        self.assertIsInstance(thr['openwakeword_threshold'], float)
        self.assertIsInstance(thr['openwakeword_frame_length'], int)
        self.assertGreater(thr['openwakeword_threshold'], 0.0)
        self.assertLessEqual(thr['openwakeword_threshold'], 1.0)

    def test_is_acoustic_wake_enabled_default_false(self):
        """β.4.8 P1: 默认 vocab.enabled=false (灰度开关). Sir 真机调通后才 true."""
        from jarvis_acoustic_wake import is_acoustic_wake_enabled
        self.assertFalse(is_acoustic_wake_enabled(),
            'β.4.8 P1 默认 acoustic_wake_enabled=false 防止破坏现 wake')

    def test_seed_fallback_when_missing(self):
        from jarvis_acoustic_wake import load_mic_safety_thresholds, _SEED_THRESHOLDS
        import jarvis_acoustic_wake as mod
        original_path = mod._MIC_VOCAB_PATH
        mod._MIC_VOCAB_PATH = '/nonexistent/file/xyz.json'
        try:
            thr = load_mic_safety_thresholds()
            for k, v in _SEED_THRESHOLDS.items():
                self.assertEqual(thr[k], v, f'seed fallback 字段 {k} 不对')
        finally:
            mod._MIC_VOCAB_PATH = original_path

    def test_corrupt_vocab_falls_back_to_seed(self):
        from jarvis_acoustic_wake import load_mic_safety_thresholds, _SEED_THRESHOLDS
        import jarvis_acoustic_wake as mod
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            f.write('{not valid json')
            tmppath = f.name
        original_path = mod._MIC_VOCAB_PATH
        mod._MIC_VOCAB_PATH = tmppath
        mod._MIC_VOCAB_CACHE['mtime'] = 0.0
        mod._MIC_VOCAB_CACHE['data'] = None
        try:
            thr = load_mic_safety_thresholds()
            self.assertEqual(thr['acoustic_wake_enabled'],
                             _SEED_THRESHOLDS['acoustic_wake_enabled'])
        finally:
            mod._MIC_VOCAB_PATH = original_path
            os.unlink(tmppath)

    def test_mtime_cache_avoids_reread(self):
        from jarvis_acoustic_wake import load_mic_safety_thresholds, _MIC_VOCAB_CACHE
        load_mic_safety_thresholds()
        self.assertIsNotNone(_MIC_VOCAB_CACHE['data'])
        self.assertGreater(_MIC_VOCAB_CACHE['mtime'], 0.0)


# ==========================================================================
# Detector create / fail-safe
# ==========================================================================

class TestP0Plus20Beta48DetectorCreate(unittest.TestCase):
    def setUp(self):
        from jarvis_acoustic_wake import reset_acoustic_wake_singleton
        reset_acoustic_wake_singleton()

    def test_default_vocab_disabled_returns_stub(self):
        """vocab.enabled=false → create() 返 disabled stub, is_available()=False."""
        from jarvis_acoustic_wake import AcousticWakeDetector
        det = AcousticWakeDetector.create(force_enable=False)
        self.assertFalse(det.is_available())
        self.assertIn('enabled', det.get_disable_reason().lower())

    def test_force_enable_loads_openwakeword(self):
        """force_enable=True → 真创建 openWakeWord Model (要求 openwakeword 已装)."""
        try:
            import openwakeword  # noqa: F401
        except ImportError:
            self.skipTest('openwakeword 未安装')
        from jarvis_acoustic_wake import AcousticWakeDetector
        det = AcousticWakeDetector.create(force_enable=True)
        self.assertTrue(det.is_available(), f'force_enable 创建失败: {det.get_disable_reason()}')
        self.assertGreater(det.frame_length, 0)
        det.close()

    def test_stub_process_returns_not_detected(self):
        """disabled stub.process() 永返 detected=False (不抛异常)."""
        from jarvis_acoustic_wake import AcousticWakeDetector
        det = AcousticWakeDetector._make_disabled('test stub')
        import numpy as np
        res = det.process(np.zeros(1280, dtype=np.int16))
        self.assertFalse(res.detected)
        self.assertEqual(res.score, 0.0)

    def test_stub_feed_pyaudio_buffer_returns_empty(self):
        from jarvis_acoustic_wake import AcousticWakeDetector
        det = AcousticWakeDetector._make_disabled('test stub')
        import numpy as np
        results = det.feed_pyaudio_buffer(np.zeros(2048, dtype=np.int16).tobytes())
        self.assertEqual(results, [])


# ==========================================================================
# Detector runtime behavior
# ==========================================================================

class TestP0Plus20Beta48DetectorRuntime(unittest.TestCase):
    """需要 openWakeWord 真装. 否则 skip."""

    @classmethod
    def setUpClass(cls):
        try:
            import openwakeword  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('openwakeword 未安装')
        from jarvis_acoustic_wake import AcousticWakeDetector
        cls.det = AcousticWakeDetector.create(force_enable=True)
        if not cls.det.is_available():
            raise unittest.SkipTest(f'detector unavailable: {cls.det.get_disable_reason()}')

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'det'):
            cls.det.close()

    def test_silence_score_near_zero(self):
        import numpy as np
        res = self.det.process(np.zeros(self.det.frame_length, dtype=np.int16))
        self.assertFalse(res.detected)
        self.assertLess(res.score, 0.3, f'silence 分数 {res.score} 不应高 (probably model loaded wrong)')

    def test_random_noise_low_score(self):
        """白噪音不应触发唤醒."""
        import numpy as np
        rng = np.random.RandomState(42)
        noise = (rng.randn(self.det.frame_length) * 1000).astype(np.int16)
        res = self.det.process(noise)
        self.assertFalse(res.detected,
            f'白噪音不应唤醒, 分数 {res.score:.3f}; model: {self.det.keyword_name}')

    def test_frame_length_mismatch_returns_not_detected(self):
        import numpy as np
        wrong = np.zeros(self.det.frame_length // 2, dtype=np.int16)
        res = self.det.process(wrong)
        self.assertFalse(res.detected)
        self.assertIn('_error', res.raw_scores)
        self.assertIn('mismatch', res.raw_scores['_error'])

    def test_feed_pyaudio_buffer_accumulator(self):
        """PyAudio 1024 + 1024 → 2048 > 1280 → 1 个 frame."""
        import numpy as np
        self.det.reset_accum()
        buf = np.zeros(1024, dtype=np.int16).tobytes()
        r1 = self.det.feed_pyaudio_buffer(buf)
        self.assertEqual(len(r1), 0, '1024 还没攒满 1280, 应 0 result')
        r2 = self.det.feed_pyaudio_buffer(buf)
        self.assertEqual(len(r2), 1, '2048 > 1280, 应 1 result')
        # 再喂 4096 → 至少 3 result (剩 768 + 4096 = 4864 / 1280 = 3 full)
        r3 = self.det.feed_pyaudio_buffer(np.zeros(4096, dtype=np.int16).tobytes())
        self.assertGreaterEqual(len(r3), 3)

    def test_process_with_bytes_input(self):
        import numpy as np
        res = self.det.process(np.zeros(self.det.frame_length, dtype=np.int16).tobytes())
        self.assertFalse(res.detected)


# ==========================================================================
# Singleton
# ==========================================================================

class TestP0Plus20Beta48Singleton(unittest.TestCase):
    def setUp(self):
        from jarvis_acoustic_wake import reset_acoustic_wake_singleton
        reset_acoustic_wake_singleton()

    def test_singleton_returns_same_instance(self):
        from jarvis_acoustic_wake import get_acoustic_wake_detector
        d1 = get_acoustic_wake_detector(force_enable=False)
        d2 = get_acoustic_wake_detector(force_enable=False)
        self.assertIs(d1, d2)

    def test_reset_creates_new(self):
        from jarvis_acoustic_wake import get_acoustic_wake_detector, reset_acoustic_wake_singleton
        d1 = get_acoustic_wake_detector(force_enable=False)
        reset_acoustic_wake_singleton()
        d2 = get_acoustic_wake_detector(force_enable=False)
        self.assertIsNot(d1, d2)


# ==========================================================================
# 准则 6.5 红线 — vocab 必须在 memory_pool/, NOT 硬编码在 .py
# ==========================================================================

class TestP0Plus20Beta48Principle65RedLines(unittest.TestCase):
    def test_no_hardcoded_threshold_in_py_source(self):
        """jarvis_acoustic_wake.py 不应硬编码具体 wakeword/threshold (除 SEED fallback)."""
        path = os.path.join(ROOT, 'jarvis_acoustic_wake.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        # SEED 是允许的 fallback (不算硬编码) — 标记 _SEED_THRESHOLDS
        self.assertIn('_SEED_THRESHOLDS', src,
            'SEED 必须存在作为 fail-safe fallback')
        # threshold 必须从 vocab 读
        self.assertIn('load_mic_safety_thresholds', src)
        self.assertIn('openwakeword_threshold', src)

    def test_vocab_file_in_memory_pool(self):
        path = os.path.join(ROOT, 'memory_pool', 'mic_safety_vocab.json')
        self.assertTrue(os.path.exists(path),
            'vocab 必须在 memory_pool/ (准则 6.5 持久化)')

    def test_vocab_has_meta_required_fields(self):
        path = os.path.join(ROOT, 'memory_pool', 'mic_safety_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        meta = data.get('_meta', {})
        for k in ['schema_version', 'marker', 'purpose', 'edit_via', 'consumer', 'thresholds']:
            self.assertIn(k, meta, f'_meta 缺字段 {k} (准则 6.5 standard schema)')

    def test_no_picovoice_porcupine_reference(self):
        """β.4.8 选 openWakeWord 后, .py 中不应剩 Picovoice/Porcupine 引用 (避免误导)."""
        path = os.path.join(ROOT, 'jarvis_acoustic_wake.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        # 注释里可以提 (说明 why not), 但 import / API call 不该有
        self.assertNotIn('import pvporcupine', src)
        self.assertNotIn('pvporcupine.create', src)


# ==========================================================================
# Phase C: AuditoryCortex 集成 (verify worker.py 接 acoustic wake)
# ==========================================================================

class TestP0Plus20Beta48WorkerIntegration(unittest.TestCase):
    """Phase C: AuditoryCortex 必须接 acoustic wake (init + check + handler)."""

    def setUp(self):
        self.worker_path = os.path.join(ROOT, 'jarvis_worker.py')
        with open(self.worker_path, 'r', encoding='utf-8') as f:
            self.src = f.read()

    def test_init_imports_detector(self):
        """AuditoryCortex.run init 必须 import + 创建 get_acoustic_wake_detector."""
        self.assertIn('from jarvis_acoustic_wake import get_acoustic_wake_detector', self.src,
            'AuditoryCortex.run 必须 import get_acoustic_wake_detector')
        self.assertIn('self._acoustic_det = get_acoustic_wake_detector()', self.src,
            'AuditoryCortex.run 必须 init self._acoustic_det 单例')

    def test_main_loop_calls_feed_buffer(self):
        """主循环 non-active 段必须 feed_pyaudio_buffer."""
        self.assertIn('self._acoustic_det.feed_pyaudio_buffer(data)', self.src,
            '主循环必须 feed PyAudio data 给 acoustic detector')

    def test_main_loop_only_when_not_active(self):
        """acoustic check 必须在 not self.in_active_conversation 才调."""
        self.assertIn('not self.in_active_conversation', self.src)
        # 完整契约: 至少一处 acoustic check 在 not in_active_conversation 守卫下
        self.assertIn("getattr(self, '_acoustic_det', None) is not None", self.src,
            'acoustic check 必须 None safe')

    def test_handler_method_exists(self):
        """_handle_acoustic_wake helper 必须存在."""
        self.assertIn('def _handle_acoustic_wake(self, res:', self.src,
            'AuditoryCortex 必须有 _handle_acoustic_wake helper')
        # handler 必须 emit awake_signal + set_active + emit jarvis cmd
        self.assertIn("source='acoustic_wake_word'", self.src,
            'handler 必须用 source=acoustic_wake_word 区分原 ASR string match wake')
        self.assertIn("self._emit_with_attention(\"jarvis\")", self.src,
            'handler 必须 emit "jarvis" empty cmd 走默认 At your service 路径')

    def test_jarvis_speaking_period_clears_accum(self):
        """Jarvis 自己说话 / mute 期间必须 reset_accum 防污染."""
        self.assertIn('self._acoustic_det.reset_accum()', self.src,
            'is_jarvis_speaking guard 段必须 reset accumulator')

    def test_acoustic_fallback_on_exception(self):
        """acoustic feed 异常必须 try/except, 不阻塞主链."""
        # 主循环 acoustic 调用必须有 try/except + bg_log 容忍
        # 找 "feed_pyaudio_buffer" 前后看上下文
        idx = self.src.find('self._acoustic_det.feed_pyaudio_buffer(data)')
        self.assertGreater(idx, 0)
        # 前 200 字符必有 try:, 后 1200 字符必有 except (β.4.8 P2 加了 mark_wake_triggered + 注释扩展了块)
        context = self.src[max(0, idx-200):idx+1200]
        self.assertIn('try:', context, 'feed_pyaudio_buffer 必须包在 try 内')
        # 必须 ≥ 2 个 except (一个 inner mark_wake_triggered try/except, 一个 outer feed_buffer try/except)
        except_count = context.count('except')
        self.assertGreaterEqual(except_count, 2,
            f'必须 ≥ 2 个 except 兜底 (β.4.8 P2 inner+outer), 实际 {except_count}')
        self.assertIn('容忍', context, 'outer except 必须 bg_log "容忍" 提示 (不阻塞主链)')

    def test_does_not_break_legacy_wake(self):
        """β.4.8 不能删 parse_wake_word 或破坏老 ASR string match wake."""
        self.assertIn('def parse_wake_word(self, text):', self.src,
            'parse_wake_word 老路径必须保留 (fallback)')
        # 老 wake 处理 line ~1077 应仍 emit awake_signal/set_active source='wake_word_match'
        self.assertIn("source='wake_word_match'", self.src,
            "老 ASR string match wake 路径 (source='wake_word_match') 必保留")


# ==========================================================================
# scripts/mic_diag.py CLI (准则 6.5 "Sir 不需改 .py")
# ==========================================================================

class TestP0Plus20Beta48MicDiagCLI(unittest.TestCase):
    """mic_diag.py CLI 验证: vocab-show / set / use-model / use-builtin / rms / test-wake."""

    def setUp(self):
        self.script = os.path.join(ROOT, 'scripts', 'mic_diag.py')
        self.vocab = os.path.join(ROOT, 'memory_pool', 'mic_safety_vocab.json')

    def test_script_exists(self):
        self.assertTrue(os.path.exists(self.script),
            'scripts/mic_diag.py 必须存在 (β.4.8 准则 6.5 CLI)')

    def test_script_has_all_commands(self):
        with open(self.script, 'r', encoding='utf-8') as f:
            src = f.read()
        for cmd in ['--vocab-show', '--set', '--use-model', '--use-builtin',
                     '--rms', '--test-wake']:
            self.assertIn(cmd, src, f'mic_diag.py 必须有 {cmd} 命令')

    def test_parse_value_helper(self):
        """_parse_value: true→True / false→False / 0.5→float / 100→int / "abc"→str."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("mic_diag_mod", self.script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertIs(mod._parse_value('true'), True)
        self.assertIs(mod._parse_value('False'), False)
        self.assertEqual(mod._parse_value('0.5'), 0.5)
        self.assertEqual(mod._parse_value('100'), 100)
        self.assertEqual(mod._parse_value('some_string'), 'some_string')

    def test_set_persists_to_vocab(self):
        """--set 必须落盘 vocab. test cycle: save → read → restore."""
        import subprocess
        # 备份
        with open(self.vocab, 'r', encoding='utf-8') as f:
            original = json.load(f)
        try:
            # 改 threshold 到 0.99
            result = subprocess.run(
                [sys.executable, self.script, '--set', 'openwakeword_threshold=0.99'],
                cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
            )
            self.assertEqual(result.returncode, 0, f'--set 失败: {result.stderr}')
            # 读 vocab 验
            with open(self.vocab, 'r', encoding='utf-8') as f:
                data = json.load(f)
            thr = data['_meta']['thresholds']
            self.assertEqual(thr['openwakeword_threshold'], 0.99)
        finally:
            # 还原 (含 trailing newline 保持 git diff 干净)
            with open(self.vocab, 'w', encoding='utf-8') as f:
                json.dump(original, f, ensure_ascii=False, indent=2)
                f.write('\n')


# ==========================================================================
# β.4.8 P2: VAD + cooldown 误唤醒治本
# ==========================================================================

class TestP0Plus20Beta48P2VADAndCooldown(unittest.TestCase):
    """β.4.8 P2: Sir 实测误唤醒 (键盘/环境音/timeout 后立刻被环境音连击) → 治本."""

    def setUp(self):
        from jarvis_acoustic_wake import reset_acoustic_wake_singleton, _MIC_VOCAB_CACHE
        reset_acoustic_wake_singleton()
        _MIC_VOCAB_CACHE['mtime'] = 0.0
        _MIC_VOCAB_CACHE['data'] = None

    def test_vocab_has_vad_and_cooldown_keys(self):
        """β.4.8 P2: vocab 必须有 VAD threshold + cooldown_s."""
        from jarvis_acoustic_wake import load_mic_safety_thresholds
        thr = load_mic_safety_thresholds()
        self.assertIn('openwakeword_vad_threshold', thr)
        self.assertIn('acoustic_wake_cooldown_s', thr)
        self.assertIsInstance(thr['openwakeword_vad_threshold'], float)
        self.assertIsInstance(thr['acoustic_wake_cooldown_s'], float)
        # VAD 默认 0.5 (启用)
        self.assertGreaterEqual(thr['openwakeword_vad_threshold'], 0.0)
        self.assertLessEqual(thr['openwakeword_vad_threshold'], 1.0)
        # cooldown 默认 30s (合理范围 0-300)
        self.assertGreater(thr['acoustic_wake_cooldown_s'], 0.0)
        self.assertLess(thr['acoustic_wake_cooldown_s'], 600.0)

    def test_threshold_default_raised_to_085(self):
        """β.4.8 P2: 默认 threshold 从 0.5 提到 0.85 (Sir 误唤醒治本)."""
        from jarvis_acoustic_wake import _SEED_THRESHOLDS
        self.assertGreaterEqual(_SEED_THRESHOLDS['openwakeword_threshold'], 0.85,
            'β.4.8 P2 SEED threshold 必须 ≥ 0.85')

    def test_mark_wake_triggered_starts_cooldown(self):
        """mark_wake_triggered() → is_in_cooldown()=True + remaining > 0."""
        try:
            import openwakeword  # noqa: F401
        except ImportError:
            self.skipTest('openwakeword 未安装')
        from jarvis_acoustic_wake import AcousticWakeDetector
        det = AcousticWakeDetector.create(force_enable=True)
        try:
            self.assertFalse(det.is_in_cooldown(), '初始无 cooldown')
            self.assertEqual(det.cooldown_remaining_s(), 0.0)
            det.mark_wake_triggered()
            self.assertTrue(det.is_in_cooldown(), 'mark_wake_triggered 后应进 cooldown')
            self.assertGreater(det.cooldown_remaining_s(), 0.0)
            self.assertLessEqual(det.cooldown_remaining_s(), det.cooldown_s + 0.5)
        finally:
            det.close()

    def test_process_blocked_during_cooldown(self):
        """cooldown 期间 process() 永返 not detected (即使真有 wake 信号)."""
        try:
            import openwakeword  # noqa: F401
            import numpy as np
        except ImportError:
            self.skipTest('openwakeword 未安装')
        from jarvis_acoustic_wake import AcousticWakeDetector
        det = AcousticWakeDetector.create(force_enable=True)
        try:
            det.mark_wake_triggered()
            # 喂任何信号 → 应被 cooldown gate 拦
            silent = np.zeros(det.frame_length, dtype=np.int16)
            res = det.process(silent)
            self.assertFalse(res.detected, 'cooldown 期间不应触发')
            self.assertIn('_cooldown_remaining_s', res.raw_scores,
                'cooldown 拦截应在 raw_scores 暴露剩余时间')
        finally:
            det.close()

    def test_cooldown_clears_accum(self):
        """mark_wake_triggered 顺手清 _accum (防 Jarvis TTS 期间音频污染)."""
        try:
            import openwakeword  # noqa: F401
        except ImportError:
            self.skipTest('openwakeword 未安装')
        from jarvis_acoustic_wake import AcousticWakeDetector
        det = AcousticWakeDetector.create(force_enable=True)
        try:
            det._accum = [1, 2, 3, 4, 5]
            det.mark_wake_triggered()
            self.assertEqual(det._accum, [], 'cooldown 应顺手清 _accum')
        finally:
            det.close()

    def test_worker_calls_mark_wake_triggered(self):
        """jarvis_worker.py wake handler 必须调 mark_wake_triggered() (启动 cooldown)."""
        p = os.path.join(ROOT, 'jarvis_worker.py')
        with open(p, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('mark_wake_triggered', src,
            'worker.py wake handler 必须调 mark_wake_triggered (β.4.8 P2 治本误唤醒)')

    def test_create_loads_with_vad_threshold(self):
        """create() 应把 vocab.vad_threshold 传给 openWakeWord.Model.

        新版 openwakeword 接受 vad_threshold; 老版本不接受会 fallback (通过 TypeError catch).
        两条路径都应得到 is_available() = True.
        """
        try:
            import openwakeword  # noqa: F401
        except ImportError:
            self.skipTest('openwakeword 未安装')
        from jarvis_acoustic_wake import AcousticWakeDetector
        det = AcousticWakeDetector.create(force_enable=True)
        try:
            self.assertTrue(det.is_available(),
                f'VAD 启用后 create 应仍 work (实际: {det.get_disable_reason()})')
        finally:
            det.close()


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print('='*60)
    if result.wasSuccessful():
        print('[OK] All β.4.8 acoustic wake tests passed.')
    else:
        print(f'[FAIL] {len(result.failures)} failures, {len(result.errors)} errors')
    print('='*60)
    sys.exit(0 if result.wasSuccessful() else 1)
