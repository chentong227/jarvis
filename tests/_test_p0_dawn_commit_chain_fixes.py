"""P0 补丁包回归测试（2026-05-15 凌晨 Sir 实测发现的 7 处连环 bug 修复验证）

实测起点（Sir 凌晨 1:24 日志）：
- 01:24 Sir 说"我会在大概两点的时候睡觉" → 注册成 `@ 14:00:00`（下午 2 点）
- Sleep Intent 没触发（终端无 🌙 痕迹）
- Anti-False-Positive 清掉 is_future_task 标记但 CommitmentWatcher 还活着
- Sir 抱怨"我说的是凌晨2点" → Memory Correction → 不联动 commitment
- 主脑幻觉 "I have corrected the record" → Integrity Check 只 STM 留痕
- CRITICAL 档跑去播 "One moment, Sir." 罐头
- 海马体 backfill worker 90s 内没起来

跑法：
    cd d:\\Jarvis
    python tests/_test_p0_dawn_commit_chain_fixes.py
"""
import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


# ===========================================================================
# P0-1：_to_24h 凌晨上下文修复 + Commitment Sanity 兜底
# ===========================================================================

class TestP01ToTwentyFourHourDawnContext(unittest.TestCase):
    """凌晨 1 点说"两点睡觉" 不再被映射到 14:00。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_to_24h_function_has_dawn_branch(self):
        """_to_24h 必须有 now.tm_hour < 6 分支"""
        m = re.search(
            r"def _to_24h\(self, hour, minute, am_pm\):.*?if now\.tm_hour\s*<\s*6:",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m, "_to_24h 必须显式有 now.tm_hour<6 凌晨分支")

    def test_add_commitment_has_sanity_bottom_guard(self):
        """add_commitment 必须有"凌晨说睡眠 + deadline 在 8h 以外 → 修正"兜底"""
        self.assertIn('Commitment Sanity', self.src,
                      "add_commitment 必须有 Commitment Sanity 注释 marker")
        self.assertIn('has_rest_kw', self.src, "必须有 has_rest_kw 变量")
        self.assertIn('gap_hours > 8', self.src,
                      "必须有 gap_hours > 8 判定（睡眠延迟超 8h 视为异常）")

    def test_gatekeeper_prompt_has_time_context_rule(self):
        """Gatekeeper prompt 必须有 TIME-OF-DAY CONTEXT 强化规则"""
        self.assertIn('5a.', self.src, "Gatekeeper prompt 必须有规则 5a TIME-OF-DAY CONTEXT")
        self.assertIn('TIME-OF-DAY CONTEXT', self.src)
        self.assertIn('early morning', self.src)


# ===========================================================================
# P0-2：_SLEEP_INTENT_PATTERNS 补全 + 绝对时间点解析
# ===========================================================================

class TestP02SleepIntentPatternsExpanded(unittest.TestCase):
    """Sir 的"我会在大概两点的时候睡觉" 这类自然表述必须命中。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_intent_patterns_cover_natural_chinese(self):
        """\u201c我会在大概两点的时候睡觉\u201d 类自然表述必须命中。
        用 unicode escape 避开终端编码干扰。"""
        # 用 _SLEEP_INTENT_PATTERNS 到 _SLEEP_TIME_EXTRACTORS 之间的范围（避免正则
        # 匹配遇到 patterns 内的字符类 ] 提前结束）。
        start = self.src.find('_SLEEP_INTENT_PATTERNS = [')
        self.assertGreater(start, 0, "找不到 _SLEEP_INTENT_PATTERNS 定义")
        end = self.src.find('_SLEEP_TIME_EXTRACTORS', start)
        self.assertGreater(end, start, "找不到 _SLEEP_TIME_EXTRACTORS 边界")
        block = self.src[start:end]
        # \u4f1a = 会, \u6253\u7b97 = 打算, \u51c6\u5907 = 准备, \u5927\u6982 = 大概
        self.assertIn('\u4f1a', block, "_SLEEP_INTENT_PATTERNS 必须含 '会'")
        self.assertIn('\u6253\u7b97', block, "必须含 '打算'")
        self.assertIn('\u51c6\u5907', block, "必须含 '准备'")
        self.assertIn('\u5927\u6982', block, "必须含 '大概'")
        # 必须含 "等下|等一下|晚点" 等延迟词
        # \u7b49\u4e0b = 等下, \u665a\u70b9 = 晚点
        self.assertTrue(
            '\u7b49\u4e0b' in block or '\u7b49\u4e00\u4e0b' in block or '\u665a\u70b9' in block,
            "_SLEEP_INTENT_PATTERNS 应支持'等下/等一下/晚点 + 睡'",
        )

    def test_detect_sleep_intent_has_absolute_time_parsing(self):
        """_detect_sleep_intent (JarvisWorkerThread) 必须能解析'X 点'绝对时间点。
        注意：源码有两个同名方法（CentralNerve 在 11701 / JarvisWorkerThread 在 13211），
        语义完全不同。这里要测的是 JarvisWorkerThread 那个（静默催睡窗口）。"""
        # 用宽松搜索：cn_hour_pat 这个变量只在 JarvisWorkerThread._detect_sleep_intent 里出现
        self.assertIn('cn_hour_pat', self.src,
                      "JarvisWorkerThread._detect_sleep_intent 必须有 cn_hour_pat 中文小时正则")
        self.assertIn('_CN_DIGIT_MAP', self.src, "必须定义 _CN_DIGIT_MAP 中文数字映射")
        # 顺手验证英文绝对时间点也有 (at/by/around + N (am/pm))
        self.assertIn('en_hour_pat', self.src, "必须有 en_hour_pat 英文绝对时间锚")

    def test_cn_digit_map_covers_basic(self):
        """中文数字映射 必须含 0-12（"两" 也要）"""
        self.assertIn("'两': 2", self.src)
        self.assertIn("'十二': 12", self.src)


# ===========================================================================
# P0-3：CommitmentWatcher update/cancel + Memory Correction 联动
# ===========================================================================

class TestP03CommitmentMemoryLinkage(unittest.TestCase):
    """Memory Correction 必须同步联动 CommitmentWatcher。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_cancel_by_keyword_method_exists(self):
        self.assertIn('def cancel_by_keyword(self, keyword: str', self.src,
                      "CommitmentWatcher.cancel_by_keyword 必须存在")

    def test_update_by_keyword_method_exists(self):
        self.assertIn('def update_by_keyword(self, keyword: str', self.src,
                      "CommitmentWatcher.update_by_keyword 必须存在")

    def test_memory_correction_calls_commitment_update(self):
        """Memory Correction 段必须调用 cw.update_by_keyword"""
        m = re.search(
            r"Memory Correction.*?CommitmentWatcher.*?cw\.update_by_keyword",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m, "Memory Correction 段必须挂钩 cw.update_by_keyword")

    def test_memory_correction_has_time_signal_check(self):
        """只有当 correction 涉及时间时才联动 commitment"""
        m = re.search(
            r"time_signal_chars\s*=\s*\([^)]*'点'[^)]*'时'",
            self.src,
        )
        self.assertIsNotNone(m, "联动必须先检查 correction 是否涉及时间")


# ===========================================================================
# P0-4：Integrity Check → event_bus 同步通知
# ===========================================================================

class TestP04IntegrityCheckEventBus(unittest.TestCase):
    """主脑幻觉信号必须 publish 到 event_bus 让下一轮和其他模块都看到。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 / 2026-05-16] 拆分后用 corpus 扫多文件
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _source_corpus import read_nerve_corpus
        cls.nerve_src = read_nerve_corpus()
        utils_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'jarvis_utils.py'))
        with open(utils_path, 'r', encoding='utf-8') as f:
            cls.utils_src = f.read()

    def test_hallucination_detected_in_default_ttl(self):
        self.assertIn("'hallucination_detected': 300", self.utils_src,
                      "ConversationEventBus.DEFAULT_TTL 必须含 hallucination_detected")

    def test_hallucination_detected_in_priority(self):
        self.assertIn("'hallucination_detected':", self.utils_src)
        m = re.search(
            r"'hallucination_detected':\s*8",
            self.utils_src,
        )
        self.assertIsNotNone(m, "hallucination_detected 优先级应为 8 (高，仅次于 commitment_overdue/manual_standby)")

    def test_integrity_check_publishes_to_bus(self):
        """Integrity Check 段必须 publish hallucination_detected"""
        m = re.search(
            r"Integrity Check.*?言行不一警告.*?_bus\.publish.*?etype='hallucination_detected'",
            self.nerve_src, re.DOTALL,
        )
        self.assertIsNotNone(m, "Integrity Check 抓到 claim 后必须 publish hallucination_detected")

    def test_sleep_intent_declared_in_default_ttl(self):
        """[P0-2 顺便] sleep_intent_declared 也应该在 DEFAULT_TTL 表里"""
        self.assertIn("'sleep_intent_declared':", self.utils_src)


# ===========================================================================
# P0-5：本地短句池路由表 CRITICAL → None
# ===========================================================================

class TestP05CriticalTierNoFallbackPhrase(unittest.TestCase):
    """CRITICAL 档不应该播 "One moment, Sir." 罐头。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_critical_tier_routes_to_none(self):
        m = re.search(
            r"_LOCAL_PHRASE_TIER_ROUTE\s*=\s*\{[^}]*'CRITICAL':\s*None",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m, "_LOCAL_PHRASE_TIER_ROUTE['CRITICAL'] 必须是 None（不补位）")

    def test_tool_request_still_routes_to_on_it(self):
        """[P0+18-a.9 / 2026-05-15] TOOL_REQUEST 改成 None（Sir 反馈"画蛇添足"）
        — Fast Path ~3s 完成时 "On it, Sir." 预渲反而和 "Done, Sir." 割裂。
        本测试断言路由配置已更新为 None（参考 _test_p0_plus_18_axis3_bugs.py::TestP0Plus18_a9）。"""
        # P0+18-a.9 升级：TOOL_REQUEST 不再补位
        m = re.search(
            r"_LOCAL_PHRASE_TIER_ROUTE\s*=\s*\{[^}]*?'TOOL_REQUEST'\s*:\s*None",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "P0+18-a.9 后 _LOCAL_PHRASE_TIER_ROUTE['TOOL_REQUEST'] 必须是 None")


# ===========================================================================
# P0-6：Anti-False-Positive 中文小时锚词补全
# ===========================================================================

class TestP06AntiFalsePositiveChineseHourAnchors(unittest.TestCase):
    """实测"两点睡觉" Anti-FP 没识别，必须补中文小时词。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 corpus 扫源码 — auto-patched]

        import sys as _sys

        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        from _source_corpus import read_nerve_corpus as _read_corpus

        cls.src = _read_corpus()

    def test_schedule_keywords_include_chinese_hours(self):
        """anti-false-positive schedule_keywords 必须补全中文数字小时词
        ("两点" / "凌晨X点" / "今晚再")"""
        # 直接源码级别检测 P0-6 标识 + 必要中文锚词存在
        self.assertIn('[P0-6', self.src,
                      "Anti-False-Positive 段必须有 [P0-6 marker")
        # 中文数字小时词: \u96f6\u4e00\u4e8c\u4e24\u4e09\u56db = 零一二两三四
        self.assertIn('\u96f6\u4e00\u4e8c\u4e24\u4e09\u56db', self.src,
                      "schedule_keywords 必须含中文数字小时锚词集合")
        # \u51cc\u6668 = 凌晨, \u4eca\u665a = 今晚
        self.assertIn('\u51cc\u6668', self.src)
        self.assertIn('\u4eca\u665a', self.src)


# ===========================================================================
# P0-7：Hippocampus backfill worker tick 加快 + 启动 log
# ===========================================================================

class TestP07HippocampusBackfillWorkerImproved(unittest.TestCase):
    """backfill worker tick 周期改 15s + 启动时立刻打 log。"""

    @classmethod
    def setUpClass(cls):
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'jarvis_hippocampus.py'))
        with open(path, 'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_tick_interval_is_15s(self):
        self.assertIn('tick_interval = 15.0', self.src,
                      "_start_backfill_worker tick_interval 必须 15s")

    def test_worker_logs_startup(self):
        self.assertIn('[Embedding Backfill Worker] 后台守护线程已启动', self.src,
                      "worker 启动时必须 bg_log 让 Sir 看到")

    def test_backfill_worker_started_in_init(self):
        """__init__ 必须调用 _start_backfill_worker"""
        m = re.search(
            r"def __init__\(self.*?self\._start_backfill_worker\(\)",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m, "Hippocampus.__init__ 必须调 _start_backfill_worker()")


# ===========================================================================
# 集成：Sir 凌晨实测复盘
# ===========================================================================

# ===========================================================================
# P0-8：Conductor Check-in 不再错映射成 return_greeting
# ===========================================================================

class TestP08ConductorCheckInNoLongerImpersonatesReturnGreeting(unittest.TestCase):
    """实测 01:44-01:45 47s 内被骚扰两次的根因：Conductor 'Check-in' 决策被映射成
    'return_greeting' nudge_type → 绕过 8 处 nudge_type != 'return_greeting' 豁免条件。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 / 2026-05-16] 拆分后用 corpus 扫多文件
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _source_corpus import read_nerve_corpus
        cls.nerve_src = read_nerve_corpus()
        utils_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'jarvis_utils.py'))
        with open(utils_path, 'r', encoding='utf-8') as f:
            cls.utils_src = f.read()

    def test_nudge_type_map_checkin_no_longer_aliases_return_greeting(self):
        """'Check-in': 'return_greeting' 必须被替换为 'check_in'"""
        # 不应再出现 'Check-in': 'return_greeting' 这样的映射
        m = re.search(
            r"'Check-in':\s*'return_greeting'",
            self.nerve_src,
        )
        self.assertIsNone(m, "Check-in 必须映射成独立的 check_in，不能再借用 return_greeting")
        # 必须出现新的正确映射
        self.assertIn("'Check-in': 'check_in'", self.nerve_src,
                      "_nudge_type_map 必须有 'Check-in': 'check_in'")

    def test_check_in_in_default_channel_map(self):
        """check_in 必须在 DEFAULT_NUDGE_CHANNEL_MAP 里有归属（默认 VOICE）"""
        m = re.search(
            r"DEFAULT_NUDGE_CHANNEL_MAP\s*=\s*\{[^}]*'check_in':\s*NUDGE_CHANNEL_VOICE",
            self.utils_src, re.DOTALL,
        )
        self.assertIsNotNone(m, "DEFAULT_NUDGE_CHANNEL_MAP 必须含 'check_in': NUDGE_CHANNEL_VOICE")

    def test_check_in_has_soft_focus_branch(self):
        """check_in 必须有独立的 soft_focus 激活分支（45s）"""
        m = re.search(
            r"if nudge_type == \"check_in\".*?soft_focus_until\s*=\s*time\.time\(\)\s*\+\s*45\.0",
            self.nerve_src, re.DOTALL,
        )
        self.assertIsNotNone(m, "check_in 必须有 soft_focus 45s 激活分支")

    def test_decision_llm_prompt_uses_check_in(self):
        """Conductor 决策 LLM 的 prompt 里 nudge_type 列表必须含 check_in 不含 return_greeting"""
        m = re.search(
            r'"nudge_type":\s*"offer_help/suggest_break/late_night/context_switch_alert/(check_in|return_greeting)/atmosphere"',
            self.nerve_src,
        )
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), 'check_in',
            "Conductor 决策 LLM prompt 中 nudge_type 列表应包含 check_in，不应仍有 return_greeting")

    def test_nudge_terminal_print_shows_source(self):
        """Smart Nudge 终端打印必须显示 source（让 Sir 区分 ReturnSentinel/Conductor/SmartNudge）"""
        m = re.search(
            r"\[Smart Nudge\] \{nudge_type\}\{_src_tag\}",
            self.nerve_src,
        )
        self.assertIsNotNone(m, "Smart Nudge 终端打印应附加 _src_tag")
        self.assertIn('_nudge_source', self.nerve_src)
        self.assertIn("nudge_context.get('source', '')", self.nerve_src)


class TestDawnRealLifeScenarioIntegration(unittest.TestCase):
    """以 Sir 实际日志为剧本，验证修复后各处契约都到位。"""

    @classmethod
    def setUpClass(cls):
        # [P0+19 / 2026-05-16] 拆分后用 corpus 扫多文件
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _source_corpus import read_nerve_corpus
        cls.nerve_src = read_nerve_corpus()

    def test_eight_p0_marker_comments_present(self):
        """所有 8 处 P0 修复都应该有 [P0-X / 2026-05-15] 注释，方便后续审计"""
        # 在 nerve 文件里至少应该看到 P0-1~P0-8 这 7 处 marker（P0-7 在 hippocampus）
        markers = ['[P0-1', '[P0-2', '[P0-3', '[P0-4', '[P0-5', '[P0-6', '[P0-8']
        missing = [m for m in markers if m not in self.nerve_src]
        self.assertEqual(missing, [], f"缺失 P0 marker: {missing}")


if __name__ == '__main__':
    print("=" * 60)
    print("P0 补丁包回归测试（commit 联动 + 凌晨上下文 + 幻觉总线）")
    print("=" * 60)
    unittest.main(verbosity=2)
