"""R7-β1 单元测试：Smart Routing + FACTUAL_RECALL 档 + 熔断后 working_feed fallback。

跑法：
    cd d:\\Jarvis
    python tests/_test_r7_beta1_factual_recall.py

覆盖：
- PROMPT_TIER_FACTUAL_RECALL 常量 + 关键词触发
- _classify_prompt_tier 优先级：FACTUAL_RECALL 必须在 TOOL_REQUEST 之前判定
- "刚复制的内容" 不再被误判为 TOOL_REQUEST（19:21 实战 bug）
- _assemble_prompt FACTUAL_RECALL 分支：禁工具 + 含 working_feed
- 熔断后 working_feed fallback：源码契约
- SMART ROUTING prompt 块存在 + 关键约束
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


# 复用现有的 ClassifyPromptTier 真实类（不实例化整个 JarvisWorkerThread）
class _MockWorker:
    """轻量 mock，只暴露 _classify_prompt_tier 需要的方法。"""

    PROMPT_TIER_WAKE_ONLY = 'WAKE_ONLY'
    PROMPT_TIER_SHORT_CHAT = 'SHORT_CHAT'
    PROMPT_TIER_FACTUAL_RECALL = 'FACTUAL_RECALL'
    PROMPT_TIER_TOOL_REQUEST = 'TOOL_REQUEST'
    PROMPT_TIER_DEEP_QUERY = 'DEEP_QUERY'
    PROMPT_TIER_CRITICAL = 'CRITICAL'

    def _compute_wake_weight(self, cmd_clean, cmd_words):
        # 与真实类无关；FACTUAL_RECALL 测试不需要 wake_weight
        return 0.0


def _bind_real_classifier():
    """绑定当前 JarvisWorkerThread 上的真实 tier classifier。"""
    from jarvis_worker import JarvisWorkerThread

    class RealClassifier:
        PROMPT_TIER_WAKE_ONLY = JarvisWorkerThread.PROMPT_TIER_WAKE_ONLY
        PROMPT_TIER_SHORT_CHAT = JarvisWorkerThread.PROMPT_TIER_SHORT_CHAT
        PROMPT_TIER_FACTUAL_RECALL = JarvisWorkerThread.PROMPT_TIER_FACTUAL_RECALL
        PROMPT_TIER_TOOL_REQUEST = JarvisWorkerThread.PROMPT_TIER_TOOL_REQUEST
        PROMPT_TIER_DEEP_QUERY = JarvisWorkerThread.PROMPT_TIER_DEEP_QUERY
        PROMPT_TIER_CRITICAL = JarvisWorkerThread.PROMPT_TIER_CRITICAL
        _TIER_CRITICAL_KEYWORDS = JarvisWorkerThread._TIER_CRITICAL_KEYWORDS
        _TIER_FACTUAL_RECALL_KEYWORDS = (
            JarvisWorkerThread._TIER_FACTUAL_RECALL_KEYWORDS)
        _TIER_TOOL_KEYWORDS = JarvisWorkerThread._TIER_TOOL_KEYWORDS
        _TIER_DEEP_KEYWORDS = JarvisWorkerThread._TIER_DEEP_KEYWORDS
        _classify_prompt_tier = JarvisWorkerThread._classify_prompt_tier

        def _compute_wake_weight(self, cmd_clean, cmd_words):
            return 0.0

    return RealClassifier


RealClassifier = _bind_real_classifier()


class TestFactualRecallTier(unittest.TestCase):
    """β1 核心：FACTUAL_RECALL 档分类正确性。"""

    def setUp(self):
        self.cls = RealClassifier()

    def _classify(self, cmd: str) -> str:
        cmd_clean = re.sub(r'[^\w\s]', '', cmd.lower()).strip()
        cmd_words = cmd_clean.split()
        return self.cls._classify_prompt_tier(cmd, cmd_clean, cmd_words)

    # ---- 实战 bug：剪贴板查询不能被误判为 TOOL_REQUEST ----
    def test_19_21_bug_clipboard_query_routes_to_factual_recall(self):
        """19:21 实战 bug：'呃，我刚才复制的那段话里面是什么内容'
        被 TOOL_REQUEST 关键词'复制'误吸 → 调了不存在的工具 → 熔断。
        现在必须走 FACTUAL_RECALL。"""
        self.assertEqual(
            self._classify("呃，我刚才复制的那段话里面是什么内容"),
            'FACTUAL_RECALL',
        )

    def test_zh_clipboard_variants(self):
        cases = [
            "我刚复制的是什么",
            "刚复制的内容是啥",
            "刚刚复制的那段",
            "剪贴板里有什么内容",
            "刚才剪贴板的内容是什么",
        ]
        for c in cases:
            with self.subTest(cmd=c):
                self.assertEqual(self._classify(c), 'FACTUAL_RECALL',
                                 f"'{c}' 应走 FACTUAL_RECALL，实际：{self._classify(c)}")

    def test_zh_command_history(self):
        cases = [
            "我刚跑的命令是什么",
            "刚才跑的那个命令",
        ]
        for c in cases:
            with self.subTest(cmd=c):
                self.assertEqual(self._classify(c), 'FACTUAL_RECALL')

    def test_en_clipboard_variants(self):
        cases = [
            "What did I just copy?",
            "What's on the clipboard?",
            "what is in the clipboard right now",
            "the thing I just copied",
        ]
        for c in cases:
            with self.subTest(cmd=c):
                self.assertEqual(self._classify(c), 'FACTUAL_RECALL')

    def test_en_command_history(self):
        cases = [
            "What command did I just run?",
            "what did I just type",
            "recently ran command",
        ]
        for c in cases:
            with self.subTest(cmd=c):
                self.assertEqual(self._classify(c), 'FACTUAL_RECALL')

    # ---- 不应误吸的反例 ----
    def test_pure_copy_action_still_tool_request(self):
        """'复制这段文字到剪贴板' 是新动作，应走 TOOL_REQUEST。"""
        self.assertEqual(self._classify("复制这段文字到剪贴板"), 'TOOL_REQUEST')

    def test_pure_open_still_tool_request(self):
        self.assertEqual(self._classify("打开剪贴板历史"), 'TOOL_REQUEST')

    def test_critical_still_wins(self):
        """CRITICAL 优先级最高 —— 即便有'刚 X'也应走 CRITICAL。"""
        # 这种边界用户很少说，但优先级必须正确
        self.assertEqual(
            self._classify("提醒我看看刚刚复制的内容"),
            'CRITICAL',
        )

    def test_short_chat_still_works(self):
        self.assertEqual(self._classify("好的"), 'SHORT_CHAT')


class TestSourceContractFactualRecallPromptBranch(unittest.TestCase):
    """_assemble_prompt 必须有 FACTUAL_RECALL 短路分支，禁工具 + 含 working_feed。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_factual_recall_branch_exists(self):
        self.assertIn("PROMPT_TIER_FACTUAL_RECALL", self.src)
        # _assemble_prompt 必须有 FACTUAL_RECALL 分支
        m = re.search(
            r"if prompt_tier == self\.PROMPT_TIER_FACTUAL_RECALL:.+?return ",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "_assemble_prompt 必须有 FACTUAL_RECALL 短路分支")

    def test_factual_recall_branch_includes_working_feed(self):
        m = re.search(
            r"def _assemble_factual_recall_prompt\(.+?"
            r"(?=^    def\s+\w+|\Z)",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m)
        body = m.group(0)
        self.assertIn('working_feed', body, "FACTUAL_RECALL 分支必须含 working_feed")
        self.assertIn('event_bus', body, "FACTUAL_RECALL 分支必须含 event_bus")

    def test_factual_recall_branch_forbids_tools(self):
        # FACTUAL_RECALL 必须明确禁止 FAST_CALL —— "DO NOT call any tool" 是给 LLM 的指令
        # 必须出现在 FACTUAL_RECALL 分支 return 出的 f-string 里
        m = re.search(
            r"def _assemble_factual_recall_prompt\(.+?"
            r"(?=^    def\s+\w+|\Z)",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "未定位到完整的 FACTUAL_RECALL 分支（含 return f-string）")
        body = m.group(0)
        self.assertIn('DO NOT call', body)
        self.assertIn('tool', body.lower())

    def test_skip_heavy_includes_factual_recall(self):
        # _skip_heavy / _allow_full 必须包括 FACTUAL_RECALL
        self.assertIn(
            "PROMPT_TIER_FACTUAL_RECALL",
            self.src,
        )

    def test_screenshot_skipped_for_factual_recall(self):
        # FACTUAL_RECALL 必须跟 WAKE_ONLY 一样跳过截图
        m = re.search(
            r"prompt_tier in \(['\"]WAKE_ONLY['\"]\s*,\s*['\"]FACTUAL_RECALL['\"]\)",
            self.src
        )
        self.assertIsNotNone(m, "截图判定必须把 FACTUAL_RECALL 加进跳过列表")


class TestSourceContractSmartRouting(unittest.TestCase):
    """how_to_respond 必须含 SMART ROUTING 块。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_smart_routing_block_exists(self):
        self.assertIn('[SMART ROUTING', self.src,
                      "how_to_respond 必须含 [SMART ROUTING ...] 块")

    def test_smart_routing_warns_about_clipboard(self):
        self.assertIn('CLIPBOARD CONTENTS', self.src)
        self.assertIn('DO NOT call any clipboard tool', self.src)

    def test_smart_routing_warns_about_terminal(self):
        self.assertIn('RECENT TERMINAL COMMANDS', self.src)


class TestCircuitBrokenWorkingFeedFallback(unittest.TestCase):
    """熔断后 working_feed fallback：duplicate_call + 未知指令 → 试 working_feed。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_fallback_block_exists(self):
        # 必须有 D 方向：检测 last_bad 含"未知指令/unknown command" + 从 working_feed 取
        self.assertIn('_bad_unknown', self.src)
        # 必须明确检测"未知指令"或"unknown command"
        self.assertTrue(
            '未知指令' in self.src and 'unknown command' in self.src,
            "fallback 必须识别中英文 unknown command"
        )

    def test_fallback_quotes_clipboard_preview(self):
        # 当用户问剪贴板内容时，fallback 必须从 working_feed 取 clipboard_copy preview
        m = re.search(
            r"_ask_clipboard\s*=.+?clipboard_copy.+?preview",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "fallback 必须在用户问 clipboard 时取 clipboard_copy preview")

    def test_fallback_supports_terminal_cmd(self):
        m = re.search(
            r"_ask_cmd\s*=.+?terminal_cmd",
            self.src, re.DOTALL
        )
        self.assertIsNotNone(m, "fallback 必须支持 terminal_cmd 查询")

    def test_fallback_does_not_break_old_apologetic_path(self):
        # 当 fallback 未被触发时（_fallback_used = False），仍应回到老的道歉文案
        self.assertIn('not _fallback_used', self.src)
        self.assertIn('I stopped repeating the same tool call', self.src)


if __name__ == '__main__':
    loader = unittest.TestLoader()
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(TestFactualRecallTier),
        loader.loadTestsFromTestCase(TestSourceContractFactualRecallPromptBranch),
        loader.loadTestsFromTestCase(TestSourceContractSmartRouting),
        loader.loadTestsFromTestCase(TestCircuitBrokenWorkingFeedFallback),
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("\n[OK] All R7-β1/FactualRecall tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)
