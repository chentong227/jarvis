"""R7 单元测试：
1. <AWAIT_GATEKEEPER> 后走 Fast Path 风格的单确认收尾（不再 round-trip 二轮大模型）
2. 截图策略：除 WAKE_ONLY 外一律实时截屏，60s 缓存已删除

跑法：
    cd d:\\Jarvis
    python tests/_test_r7_oneshot_and_screenshot.py
"""
import io
import os
import re
import sys
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestGatekeeperOneShotSourceContract(unittest.TestCase):
    """直接读 jarvis_nerve.py 源码，确保 <AWAIT_GATEKEEPER> 分支:
       1. 不再 append continuation_prompt 到 chat_history
       2. 不再 `continue` 进入第二轮 LLM；改为 `break`
       3. _circuit_broken_reason = "gatekeeper_one_shot" 或 "_fail"
    """

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def _slice_await_branch(self):
        # 截取从 `if gatekeeper_triggered:` 到下一个独立 `if fast_call_triggered:` 之间的代码
        m = re.search(r"if gatekeeper_triggered:(.+?)# 👇 当触发盲操拦截器时", self.src, re.DOTALL)
        self.assertIsNotNone(m, "未在源码中定位到 <AWAIT_GATEKEEPER> 分支")
        return m.group(1)

    def test_no_second_round_continuation_prompt(self):
        branch = self._slice_await_branch()
        # 旧实现里通向第二轮 LLM 的特征：把 "[SYSTEM GATEKEEPER RESULT]" 拼进 continuation_prompt
        self.assertNotIn(
            "[SYSTEM GATEKEEPER RESULT]",
            branch,
            "<AWAIT_GATEKEEPER> 分支不应再构造 continuation_prompt（这会回到大模型第二轮）",
        )

    def test_branch_breaks_instead_of_continue(self):
        branch = self._slice_await_branch()
        # 分支末尾应当 break 而非 continue
        # 注意：分支体内部可能仍有其他 continue，但末尾的控制流必须是 break
        tail = branch.strip().splitlines()[-15:]  # 末尾 15 行足够覆盖收尾逻辑
        tail_text = "\n".join(tail)
        self.assertIn("break", tail_text, "<AWAIT_GATEKEEPER> 分支末尾必须 break，停止流式循环")

    def test_circuit_broken_reason_marker_present(self):
        branch = self._slice_await_branch()
        self.assertRegex(
            branch,
            r"_circuit_broken_reason\s*=\s*['\"]gatekeeper_one_shot",
            "必须设置 _circuit_broken_reason = 'gatekeeper_one_shot[_fail]' 让收尾合成识别",
        )

    def test_local_fallback_audio_emit(self):
        branch = self._slice_await_branch()
        # 当 spoken_so_far 为空时本地兜底必须直接调 _put_audio，不依赖大模型
        self.assertIn("_put_audio(_en)", branch, "spoken_so_far 为空时必须本地 _put_audio 兜底")

    def test_branch_handles_success_and_failure(self):
        branch = self._slice_await_branch()
        # 必须区分 SUCCESS / FAILURE 两条路径
        self.assertIn("Gatekeeper SUCCESS", branch)
        self.assertIn("Gatekeeper TIMEOUT", branch)


class TestScreenshotStrategySourceContract(unittest.TestCase):
    """直接读 jarvis_nerve.py 源码，确保截图策略:
       1. 没有写入 self._screenshot_cache（删掉 60s 缓存）
       2. 仅 WAKE_ONLY 跳过；其他档实时截屏
    """

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_no_cache_write(self):
        # 找到 stream_chat 截图段（标志：R7/Screenshot 注释或 ImageGrab.grab() 调用）
        # 关键断言：没有 self._screenshot_cache = (img_bytes, ...) 这种写入
        self.assertNotRegex(
            self.src,
            r"self\._screenshot_cache\s*=\s*\(",
            "60s 截图缓存写入已删除，不应再有 self._screenshot_cache = (..., ...) 形态",
        )

    def test_no_cache_ttl_attribute(self):
        # screenshot_cache_ttl 应当不再存在（或仅作为注释/历史标记）
        # 排除注释行后再检查活跃赋值
        active_lines = [
            ln for ln in self.src.splitlines()
            if "screenshot_cache_ttl" in ln and not ln.lstrip().startswith('#')
        ]
        self.assertEqual(
            active_lines, [],
            f"screenshot_cache_ttl 活跃赋值已废弃，发现残留：{active_lines}",
        )

    def test_wake_only_still_skips(self):
        # WAKE_ONLY 跳过逻辑必须保留（省 ~50ms 唤醒延时）
        # R7-β1 加入 FACTUAL_RECALL 后判定改成 `prompt_tier in ('WAKE_ONLY', 'FACTUAL_RECALL')`
        # 老的 `prompt_tier == 'WAKE_ONLY'` 字面也可能仍然存在（其他位置如 _classify_prompt_tier）
        self.assertTrue(
            ("prompt_tier == 'WAKE_ONLY'" in self.src)
            or ("'WAKE_ONLY'" in self.src and "FACTUAL_RECALL" in self.src),
            "WAKE_ONLY 跳过截图的判断必须保留（独立判定或 in 集合判定均可）",
        )

    def test_image_grab_is_inline_after_wake_check(self):
        # 实时截屏：ImageGrab.grab() 应在 WAKE_ONLY 跳过判断的 else 分支里直接调用
        # R7-β1 改成 `prompt_tier in ('WAKE_ONLY', 'FACTUAL_RECALL')` 之后正则要兼容
        m = re.search(
            r"if prompt_tier (?:==|in)[^:]+(?:'WAKE_ONLY'|\"WAKE_ONLY\")[^:]*:(.+?)_t_ss_done\s*=\s*time\.time\(\)",
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(m, "截图窗口未定位到")
        window = m.group(1)
        self.assertIn("ImageGrab.grab()", window, "WAKE_ONLY else 分支必须实时截屏")
        # 缓存复用代码（cached_bytes 读取）应当被删掉
        self.assertNotIn("_cached_bytes", window, "缓存复用分支已删除")
        self.assertNotIn("_cached_ts", window, "缓存复用分支已删除")


class TestChatBypassScreenshotCacheRuntime(unittest.TestCase):
    """运行时验证：ChatBypass.__init__ 不再创建带 TTL 的缓存元组。"""

    def test_screenshot_cache_attr_is_none_by_default(self):
        # 不实例化整个 ChatBypass（依赖太多），直接静态读默认值
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        src = _read_corpus()
        # 找到 ChatBypass.__init__ 中的 _screenshot_cache 赋值行
        m = re.search(r"self\._screenshot_cache\s*=\s*([^\n#]+)", src)
        self.assertIsNotNone(m, "ChatBypass 应当仍声明 _screenshot_cache 属性占位")
        self.assertEqual(m.group(1).strip(), "None", "_screenshot_cache 默认值应为 None（不再写入）")


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestGatekeeperOneShotSourceContract),
        loader.loadTestsFromTestCase(TestScreenshotStrategySourceContract),
        loader.loadTestsFromTestCase(TestChatBypassScreenshotCacheRuntime),
    ])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("\n[OK] All R7 one-shot + screenshot tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
