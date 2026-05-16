"""轴 1.6 单元测试：Unicode 安全 print + _detect_help_refusal 不再被 emoji 炸

[Sir-2026-05-15] 修 pre-existing P0 bug：
v3 起 `_detect_help_refusal` 内部有 `print(f"🚫 ...")` 在外层 try/except 里。
Windows GBK 终端无法编码 emoji \U0001f6ab，抛 UnicodeEncodeError → outer except 静默吞 →
后续的 `freeze_for(90.0)` 永远不调用 → 用户拒绝信号失效 → Conductor 仍然催。

修法三层：
1. jarvis_utils 启动时 sys.stdout.reconfigure(encoding='utf-8', errors='replace') —— 根本修
2. _BgLogBuffer._emit_locked / _flush_locked GBK fallback 到 ASCII —— 二级保护
3. _detect_help_refusal 关键 print 改 bg_log —— 业务层兜底

跑法：
    cd d:\\Jarvis
    python tests/_test_axis1_6_unicode_safe_print.py
"""
import os
import re
import sys
import io
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestSourceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.utils_src = open(
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'jarvis_utils.py')),
            'r', encoding='utf-8',
        ).read()
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _source_corpus import read_nerve_corpus
        cls.nerve_src = read_nerve_corpus()

    def test_stdout_reconfigure_present(self):
        # 必须在模块层尝试 sys.stdout.reconfigure(encoding='utf-8')
        self.assertIn("sys.stdout.reconfigure(encoding='utf-8'", self.utils_src,
                      "jarvis_utils.py 顶部必须 reconfigure stdout 为 utf-8")
        self.assertIn("sys.stderr.reconfigure(encoding='utf-8'", self.utils_src,
                      "jarvis_utils.py 顶部必须 reconfigure stderr 为 utf-8")

    def test_emit_locked_has_gbk_fallback(self):
        # _emit_locked 必须有 UnicodeEncodeError 分支降级 ASCII
        m = re.search(
            r"def _emit_locked.*?UnicodeEncodeError.*?ascii.*?errors=['\"]replace['\"]",
            self.utils_src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "_emit_locked 必须有 UnicodeEncodeError → ASCII fallback 分支")

    def test_flush_locked_has_gbk_fallback(self):
        # _flush_locked 也必须有 ASCII fallback
        m = re.search(
            r"def _flush_locked.*?UnicodeEncodeError.*?ascii.*?errors=['\"]replace['\"]",
            self.utils_src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "_flush_locked 必须有 UnicodeEncodeError → ASCII fallback 分支")

    def test_detect_help_refusal_uses_bg_log(self):
        # _detect_help_refusal 必须用 bg_log 而非 print 输出 emoji 行
        m = re.search(
            r"def _detect_help_refusal.*?bg_log\(f.{0,5}Help Refusal",
            self.nerve_src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "_detect_help_refusal 必须改 bg_log 输出 [Help Refusal] 行")

    def test_detect_help_refusal_no_emoji_print(self):
        # _detect_help_refusal 函数体内不应再有 print(f"...emoji...")
        # 提取 _detect_help_refusal 函数体
        m = re.search(
            r"def _detect_help_refusal\(self, cmd: str\):.*?(?=\n    def )",
            self.nerve_src, re.DOTALL,
        )
        self.assertIsNotNone(m, "找不到 _detect_help_refusal 函数体")
        body = m.group(0)
        # 函数体内不应再有 emoji print 调用（emoji 在 print 字符串里）
        emoji_print = re.search(r'print\(f["\'][^"\']*[\U0001f300-\U0001fbff]', body)
        self.assertIsNone(emoji_print,
            "_detect_help_refusal 不应再有 print 带 emoji（应已全部改 bg_log）")


class TestStdoutReconfigured(unittest.TestCase):
    """运行时验证：import jarvis_utils 后 sys.stdout 编码确为 utf-8。"""

    def test_stdout_encoding_is_utf8_after_import(self):
        import jarvis_utils  # noqa: F401
        if sys.platform == 'win32':
            # reconfigure 后应是 utf-8
            self.assertIn('utf-8', sys.stdout.encoding.lower(),
                          f"reconfigure 后 stdout.encoding 应为 utf-8，实际：{sys.stdout.encoding}")
            self.assertIn('utf-8', sys.stderr.encoding.lower(),
                          f"reconfigure 后 stderr.encoding 应为 utf-8，实际：{sys.stderr.encoding}")
        # 非 Windows 平台默认就是 utf-8，跳过严格检查
        else:
            self.skipTest("非 Windows 平台默认即 utf-8")


class TestDetectHelpRefusalRuntime(unittest.TestCase):
    """运行时：模拟在 GBK 风格 stdout 下，_detect_help_refusal('算了') 真的能冻结。
    
    注意：这个测试 pre-axis1.6 是失败的（fail in v4 / v5 era）。修复后必绿。
    """

    def test_pipeline_with_generic_refusal_freezes_gate(self):
        from jarvis_nerve import NudgeGate, JarvisWorkerThread

        class _SN:
            _refused_help_until = 0.0
            _help_refusal_history = []
            _last_help_fingerprint = ''
            _last_help_fingerprint_time = 0.0
            def _calc_help_cooldown(self, fp):
                return 600.0
            def _gen_help_fingerprint(self, ctx):
                return 'generic'

        class _CC:
            smart_nudge = _SN()

        class _Dummy:
            short_term_memory = []
            nudge_gate = NudgeGate(cooldown_seconds=90)
            event_bus = None
            companion_center = _CC()

        dummy = _Dummy()
        worker = JarvisWorkerThread.__new__(JarvisWorkerThread)
        worker.jarvis = dummy
        worker.humor_memory = None

        worker._detect_help_refusal('\u7b97\u4e86')  # '算了'

        # 修复后必绿：90s 硬冻结生效
        self.assertTrue(dummy.nudge_gate.is_hard_frozen(),
                        "_detect_help_refusal('算了') 必须把 nudge_gate 硬冻结")
        # _hard_freeze_until 应当在 80-100s 之间（90s 但允许 10s 容差）
        delta = dummy.nudge_gate._hard_freeze_until - time.time()
        self.assertGreater(delta, 80)
        self.assertLess(delta, 100)

    def test_strong_refusal_freezes_300s(self):
        """强拒绝词 → 300s 硬冻结。"""
        from jarvis_nerve import NudgeGate, JarvisWorkerThread

        class _SN:
            _refused_help_until = 0.0
            _help_refusal_history = []
            _last_help_fingerprint = ''
            _last_help_fingerprint_time = 0.0
            def _calc_help_cooldown(self, fp):
                return 600.0
            def _gen_help_fingerprint(self, ctx):
                return 'generic'

        class _CC:
            smart_nudge = _SN()

        class _Dummy:
            short_term_memory = []
            nudge_gate = NudgeGate(cooldown_seconds=90)
            event_bus = None
            companion_center = _CC()

        dummy = _Dummy()
        worker = JarvisWorkerThread.__new__(JarvisWorkerThread)
        worker.jarvis = dummy
        worker.humor_memory = None

        worker._detect_help_refusal('\u4e0d\u9700\u8981\u4f60\u7684\u5e2e\u52a9')  # '不需要你的帮助'

        self.assertTrue(dummy.nudge_gate.is_hard_frozen())
        delta = dummy.nudge_gate._hard_freeze_until - time.time()
        self.assertGreater(delta, 290)
        self.assertLess(delta, 310)


class TestEmojiPrintWithMockGbkStdout(unittest.TestCase):
    """模拟 GBK stdout 不抛异常时 print emoji，验证 bg_log fallback 工作。"""

    def test_bg_log_emoji_does_not_raise(self):
        """直接 bg_log 一条带 emoji 的消息不该抛任何异常。"""
        from jarvis_utils import bg_log
        # 临时切到 cp936 backing 的 buffer 模拟 Windows GBK 行为
        import io
        old_stderr = sys.stderr
        try:
            # 用 io.TextIOWrapper 包一个真正只能 cp936 的 buffer
            buf = io.BytesIO()
            wrapper = io.TextIOWrapper(buf, encoding='cp936', errors='strict', write_through=True)
            sys.stderr = wrapper
            # 调 bg_log 不该抛
            try:
                bg_log("\U0001f6ab [Test] emoji message")
                bg_log("\U0001f9ca [Test] another emoji")
            except UnicodeEncodeError:
                self.fail("bg_log 在 cp936 stderr 下不该抛 UnicodeEncodeError")
            wrapper.flush()
            output = buf.getvalue().decode('cp936', errors='replace')
            # ASCII fallback 应该把 emoji 替换成 '?'
            self.assertIn('?', output, "ASCII fallback 应该把 emoji 替换为 ?")
            self.assertIn('Test', output, "ASCII fallback 应保留可编码部分")
        finally:
            sys.stderr = old_stderr


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestSourceContract),
        loader.loadTestsFromTestCase(TestStdoutReconfigured),
        loader.loadTestsFromTestCase(TestDetectHelpRefusalRuntime),
        loader.loadTestsFromTestCase(TestEmojiPrintWithMockGbkStdout),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] 轴 1.6 Unicode safe print tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
