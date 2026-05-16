# -*- coding: utf-8 -*-
"""[P0+18 / 2026-05-15] 轴3 实测 6 项 → 抓到 10 个 BUG 修复套件 — 测试

Sir 13:00-13:08 实测 6 项话术清单 + 13:19:41 又触发 2 个新 bug = 10 BUG。
本套覆盖 a.1-a.10 + a.14-a.15 的源码契约 + 关键行为。

跑法：
    cd d:\\Jarvis
    python tests/_test_p0_plus_18_axis3_bugs.py
"""
import os
import re
import sys
import unittest

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

NERVE_PATH = os.path.join(ROOT, 'jarvis_nerve.py')
UTILS_PATH = os.path.join(ROOT, 'jarvis_utils.py')
VOCAL_PATH = os.path.join(ROOT, 'jarvis_vocal_cord.py')


def _read(path):
    # [P0+19 / 2026-05-16] 拆分后 nerve.py 内容分散到多文件
    if 'jarvis_nerve.py' in str(path):
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _source_corpus import read_nerve_corpus
        return read_nerve_corpus()
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# ============================================================================
# a.1 — SkillRegistry.bootstrap() 必须被 CentralNerve.__init__ 调用
# ============================================================================
class TestP0Plus18_a1_RegistryBootstrap(unittest.TestCase):
    """BUG #0 (P0): 不调 bootstrap → registry 空 → AVAILABLE SKILLS 块空 → PromiseExecutor 无 skill 可跑"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(NERVE_PATH)

    def test_central_nerve_calls_bootstrap(self):
        """CentralNerve.__init__ 必须 import + 调 get_registry().bootstrap()"""
        self.assertIn('P0+18-a.1', self.src,
            "必须留下 [P0+18-a.1] marker")
        # 必须有 bootstrap 调用（可能写成 _reg.bootstrap(...) 或 get_registry().bootstrap()）
        m = re.search(r"\.bootstrap\(\s*\n?\s*pools_root", self.src)
        self.assertIsNotNone(m, "CentralNerve 必须调 .bootstrap(pools_root=...)")

    def test_bootstrap_passes_pools_root(self):
        """bootstrap 必须传 pools_root 参数（让 SkillScanner 扫 l4_hands_pool / l2_eyes_pool）"""
        m = re.search(r"\.bootstrap\(\s*\n?\s*pools_root\s*=", self.src)
        self.assertIsNotNone(m, "bootstrap() 必须传 pools_root 参数")

    def test_bootstrap_in_central_nerve_init(self):
        """bootstrap 必须在 CentralNerve.__init__ 范围内（不能在别处）"""
        # CentralNerve __init__ 段必须含 P0+18-a.1 marker + 对应的 bootstrap 段
        m = re.search(
            r"class CentralNerve.*?def __init__.*?P0\+18-a\.1.*?\.bootstrap\(",
            self.src, re.DOTALL)
        self.assertIsNotNone(m,
            "P0+18-a.1 bootstrap 段必须在 CentralNerve.__init__ 范围内")


# ============================================================================
# a.2 — PromiseExecutor 启动异常不再静默吞，traceback 强暴露
# ============================================================================
class TestP0Plus18_a2_PromiseExecutorExceptionVisibility(unittest.TestCase):
    """BUG #0 (P0): 启动失败 try/except 静默吞 → Sir 看不到根因"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(NERVE_PATH)

    def test_traceback_print_exc_present(self):
        """PromiseExecutor 启动失败必须 traceback 强暴露 (.print_exc() 或类似)"""
        self.assertIn('P0+18-a.2', self.src,
            "必须留下 [P0+18-a.2] marker")
        # PromiseExecutor 段必须有 traceback 调用（.print_exc() 或 import traceback as _tb 后 _tb.print_exc()）
        m = re.search(
            r"PromiseExecutor.*?(?:traceback\.print_exc\(\)|_tb\.print_exc\(\))",
            self.src, re.DOTALL)
        self.assertIsNotNone(m,
            "PromiseExecutor 段必须有 traceback.print_exc() 强暴露异常（直接或别名）")

    def test_startup_visible_log(self):
        """启动相关必须有可见日志"""
        self.assertIn('[PromiseExecutor]', self.src)
        # 实例创建 / 后台执行器已启动 / wire 成功 任意一种均可
        self.assertTrue(
            '后台执行器已启动' in self.src
            or '实例已创建' in self.src
            or 'PromiseExecutor wire' in self.src,
            "PromiseExecutor 启动必须留下可见日志"
        )


# ============================================================================
# a.3 — SHORT_CHAT tier 注入 PROMISE_PROTOCOL_MINI + ACTIVE PLAN
# ============================================================================
class TestP0Plus18_a3_ShortChatPromiseInjection(unittest.TestCase):
    """BUG #2 (P0): SHORT_CHAT 没注 PROMISE 协议 → 主脑写不出 <PROMISE> 标签"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(NERVE_PATH)

    def test_a3_marker_present(self):
        self.assertIn('P0+18-a.3', self.src)

    def test_short_chat_injects_promise_protocol(self):
        """SHORT_CHAT 分支必须注入 PROMISE_PROTOCOL_DIRECTIVE_MINI 或 PROMISE 协议提示"""
        # 至少要在 SHORT_CHAT 分支末尾追加 PROMISE 提示
        self.assertTrue(
            'PROMISE_PROTOCOL' in self.src or 'PROMISE protocol' in self.src.lower(),
            "SHORT_CHAT 必须能看到 PROMISE 协议提示"
        )

    def test_short_chat_injects_active_plan(self):
        """SHORT_CHAT 必须能看见 ACTIVE PLAN 块（Sir 说 'go' 时主脑要有上下文）"""
        self.assertIn('ACTIVE PLAN', self.src,
            "SHORT_CHAT 必须能看见 ACTIVE PLAN 块")


# ============================================================================
# a.4 — _classify_prompt_tier 加 _DEEP_QUERY_VERBS 把"排查/诊断/帮我看"升 DEEP_QUERY
# ============================================================================
class TestP0Plus18_a4_DeepQueryVerbs(unittest.TestCase):
    """BUG #1 (P1): tier 路由把"排查 403"误归 SHORT_CHAT → 必须升 DEEP_QUERY"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(NERVE_PATH)

    def test_a4_marker_present(self):
        self.assertIn('P0+18-a.4', self.src)

    def test_deep_query_verbs_english(self):
        """必须覆盖英文 diagnose/analyze/investigate/review/inspect 等"""
        for verb in ['diagnose', 'analyze', 'investigate', 'review', 'inspect',
                     'audit', 'debug', 'troubleshoot']:
            self.assertIn(verb, self.src,
                f"_DEEP_QUERY_VERBS 必须含英文 {verb!r}")

    def test_deep_query_verbs_chinese(self):
        """必须覆盖中文 排查 / 诊断 / 分析 / 审 / 帮我看"""
        # 这些至少 1 个出现在 _DEEP_QUERY_VERBS 段
        m = re.search(r"P0\+18-a\.4.*?(?=\n#|\nclass|\ndef)", self.src, re.DOTALL)
        section = m.group(0) if m else self.src
        chinese_verbs_found = sum(
            1 for v in ['排查', '诊断', '分析', '审', '检查', '帮我看', '帮我查']
            if v in section
        )
        self.assertGreaterEqual(chinese_verbs_found, 3,
            f"_DEEP_QUERY_VERBS 必须至少含 3 个中文动词，当前 {chinese_verbs_found} 个")


# ============================================================================
# a.5 — 物理文件删除意图识别 + 接入两条 delete 路径
# ============================================================================
class TestP0Plus18_a5_PhysicalFileDeleteGuard(unittest.TestCase):
    """BUG #3 (P0/SAFETY): hint='D盘 test.txt 文件' 又删了 5 条无辜记忆 → 第 5 层守卫"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(NERVE_PATH)
        # 把 helper 取出来直接调
        from jarvis_nerve import _is_physical_file_delete_intent, _PHYSICAL_FILE_DELETE_MARKERS
        cls.f = staticmethod(_is_physical_file_delete_intent)
        cls.markers = _PHYSICAL_FILE_DELETE_MARKERS

    def test_a5_marker_present(self):
        self.assertIn('P0+18-a.5', self.src)

    def test_markers_cover_suffixes(self):
        """marker 必须覆盖常见文件后缀"""
        for sfx in ['.txt', '.md', '.py', '.exe', '.pdf', '.png', '.json']:
            self.assertIn(sfx, self.markers,
                f"_PHYSICAL_FILE_DELETE_MARKERS 缺后缀 {sfx!r}")

    def test_markers_cover_paths_and_folders(self):
        for marker in ['\\', '/', 'd盘', '桌面', 'desktop', '文件', '文件夹', 'folder']:
            self.assertIn(marker, self.markers,
                f"_PHYSICAL_FILE_DELETE_MARKERS 缺关键词 {marker!r}")

    def test_detects_actual_incident_hint(self):
        """13:03:37 实测 hint='D盘 test.txt 文件' 必须返回 True"""
        self.assertTrue(self.f('D盘 test.txt 文件'),
            "实测 hint 必须被识别为 physical_file_intent")
        self.assertTrue(self.f('d:\\jarvis\\test_dummy.txt'),
            "Windows path 必须识别")
        self.assertTrue(self.f('桌面那个 readme'),
            "桌面 + readme 必须识别")
        self.assertTrue(self.f('the file on desktop'),
            "英文 'desktop' 必须识别")

    def test_does_not_misfire_on_memory_hints(self):
        """删 STM 记忆条目不应被误伤"""
        for hint in ['两点睡觉', '音量 30%', 'sleep at 2am', 'volume 30']:
            self.assertFalse(self.f(hint),
                f"STM 记忆 hint {hint!r} 不应被识别为 physical_file_intent")

    def test_guard_wired_into_direct_delete_path(self):
        """守卫必须接入直接 delete 路径（line 14583+ 入口）"""
        # Guard 5（physical-file）必须出现在 delete_hint 处理段开头
        m = re.search(
            r"if delete_hint and len\(delete_hint\) >= 2:.*?_is_physical_file_delete_intent",
            self.src, re.DOTALL)
        self.assertIsNotNone(m,
            "_is_physical_file_delete_intent 必须接入 delete_hint 直接路径")

    def test_guard_wired_into_correction_delete_path(self):
        """守卫必须接入 correction→delete 路径"""
        m = re.search(
            r"new_value.*?delete.*?Correction Guard.*?_is_physical_file_delete_intent",
            self.src, re.DOTALL)
        self.assertIsNotNone(m,
            "_is_physical_file_delete_intent 必须接入 correction→delete 路径")


# ============================================================================
# a.6 — Gatekeeper rule 13a [PHYSICAL FILE vs MEMORY ENTRY] 反例段
# ============================================================================
class TestP0Plus18_a6_GatekeeperRule13a(unittest.TestCase):
    """BUG #3 cont.: Gatekeeper prompt 需要从源头教 LLM 区分物理文件 vs 记忆条目"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(NERVE_PATH)

    def test_a6_marker_present(self):
        self.assertIn('P0+18-a.6', self.src)

    def test_rule_13a_subsection_present(self):
        """规则 13a 必须含 [PHYSICAL FILE vs MEMORY ENTRY] 标题"""
        self.assertIn('PHYSICAL FILE vs MEMORY ENTRY', self.src,
            "规则 13a 必须有明显标题")

    def test_examples_include_wrong_right_pairs(self):
        """必须有 WRONG / RIGHT 反例对"""
        m = re.search(
            r"13a\.\s*\[PHYSICAL FILE vs MEMORY ENTRY.*?(?=\n\d+\.|\nContext:)",
            self.src, re.DOTALL)
        self.assertIsNotNone(m, "规则 13a 段必须能匹到")
        section = m.group(0)
        wrong_count = len(re.findall(r"WRONG:", section))
        right_count = len(re.findall(r"RIGHT:", section))
        self.assertGreaterEqual(wrong_count, 3, f"至少 3 个 WRONG 反例，当前 {wrong_count}")
        self.assertGreaterEqual(right_count, 3, f"至少 3 个 RIGHT 正例，当前 {right_count}")


# ============================================================================
# a.7 — set_speaking_state EXECUTING/IDLE 边界续命 last_interaction_time
# ============================================================================
class TestP0Plus18_a7_FocusKeepalive(unittest.TestCase):
    """BUG #5 (P0): Jarvis 说话期间 30s 倒计时误触发 standby"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(NERVE_PATH)

    def test_a7_marker_present(self):
        self.assertIn('P0+18-a.7', self.src)

    def test_executing_branch_resets_last_interaction(self):
        """EXECUTING 分支必须续 last_interaction_time = time.time()"""
        m = re.search(
            r"if state_str == \"EXECUTING\":.*?self\.last_interaction_time\s*=\s*time\.time\(\)",
            self.src, re.DOTALL)
        self.assertIsNotNone(m,
            "EXECUTING 分支必须 reset last_interaction_time = time.time()")

    def test_idle_branch_resets_last_interaction(self):
        """IDLE 分支（was_speaking=True）也要续命一次"""
        m = re.search(
            r"if state_str == \"IDLE\".*?was_speaking.*?self\.last_interaction_time\s*=\s*time\.time\(\)",
            self.src, re.DOTALL)
        self.assertIsNotNone(m,
            "IDLE 分支 was_speaking 路径必须 reset last_interaction_time")

    def test_thinking_branch_still_does_not_reset(self):
        """THINKING 分支必须仍不续命（Bug E 修复保留）"""
        m = re.search(
            r"elif state_str == \"THINKING\":(.*?)elif state_str == \"IDLE\":",
            self.src, re.DOTALL)
        self.assertIsNotNone(m, "THINKING 分支段必须能匹到")
        thinking_section = m.group(1)
        # THINKING 分支内不应有 last_interaction_time = time.time() 续命语句
        # （注释里可以提，但实际赋值不行）
        # 用更松的检查：去掉注释行后看是否还有赋值
        non_comment_lines = [
            ln for ln in thinking_section.split('\n')
            if not ln.strip().startswith('#')
        ]
        non_comment = '\n'.join(non_comment_lines)
        m2 = re.search(r"self\.last_interaction_time\s*=\s*time\.time\(\)", non_comment)
        self.assertIsNone(m2,
            "THINKING 分支非注释代码不应续 last_interaction_time（Bug E 修复必须保留）")


# ============================================================================
# a.8 — ghost_hallucinations 加缩写短词 + _TTSEchoRing.is_echo 短词宽容
# ============================================================================
class TestP0Plus18_a8_EchoGuardShortWords(unittest.TestCase):
    """BUG #6 (P0): ASR 把 Jarvis 末尾 "It's"/"if"/"or" 当用户输入"""

    @classmethod
    def setUpClass(cls):
        cls.nerve_src = _read(NERVE_PATH)
        cls.utils_src = _read(UTILS_PATH)

    def test_a8_marker_present(self):
        self.assertIn('P0+18-a.8', self.nerve_src)
        self.assertIn('P0+18-a.8', self.utils_src)

    def test_ghost_hallucinations_has_contractions(self):
        """ghost_hallucinations 必须含 it's/i'll/we're 等缩写"""
        for w in ["it's", "i'll", "we're", "you're", "that's"]:
            self.assertIn(f'"{w}"', self.nerve_src,
                f"ghost_hallucinations 必须含 {w!r}")

    def test_ghost_hallucinations_has_chinese_fillers(self):
        """中文短助词（嗯/呃/啊/好的/对）也要加"""
        for w in ['"嗯"', '"呃"', '"啊"', '"好的"']:
            self.assertIn(w, self.nerve_src,
                f"ghost_hallucinations 必须含中文短助词 {w!r}")

    def test_tts_echo_ring_short_word_path(self):
        """_TTSEchoRing.is_echo 对 ≤4 字符 ASR 走宽容判定"""
        # 必须有"if 0 < len(norm) <= 4" 之类的短词分支
        self.assertIn('len(norm) <= 4', self.utils_src,
            "_TTSEchoRing.is_echo 必须有短词分支 (len(norm) <= 4)")

    def test_tts_echo_ring_short_word_token_match(self):
        """短词路径必须用 token 集合相交判定"""
        m = re.search(
            r"len\(norm\) <= 4.*?asr_tokens.*?cand_tokens.*?return True",
            self.utils_src, re.DOTALL)
        self.assertIsNotNone(m,
            "短词分支必须用 token 集合相交逻辑")


# ============================================================================
# a.9 — Local Phrase 在 TOOL_REQUEST tier 不触发 + 阈值 2.5s → 3.5s
# ============================================================================
class TestP0Plus18_a9_LocalPhraseThreshold(unittest.TestCase):
    """BUG #8 (P1): "On it, Sir." 预渲在 Fast Path 反而割裂"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(NERVE_PATH)

    def test_a9_marker_present(self):
        self.assertIn('P0+18-a.9', self.src)

    def test_tool_request_route_is_none(self):
        """TOOL_REQUEST 路由必须改成 None（不补位）"""
        m = re.search(
            r"_LOCAL_PHRASE_TIER_ROUTE\s*=\s*\{[^}]*?'TOOL_REQUEST'\s*:\s*None",
            self.src, re.DOTALL)
        self.assertIsNotNone(m,
            "_LOCAL_PHRASE_TIER_ROUTE['TOOL_REQUEST'] 必须改成 None")

    def test_threshold_raised_to_35(self):
        """阈值必须从 2.5 提到 3.5"""
        m = re.search(
            r"_LOCAL_PHRASE_THRESHOLD\s*=\s*3\.5",
            self.src)
        self.assertIsNotNone(m,
            "_LOCAL_PHRASE_THRESHOLD 必须改成 3.5")

    def test_start_backchannel_uses_constant_not_literal(self):
        """stream_chat 调 _start_backchannel_timer 必须用 self._LOCAL_PHRASE_THRESHOLD 而非硬编码 2.5"""
        m = re.search(
            r"local_utterance_threshold\s*=\s*self\._LOCAL_PHRASE_THRESHOLD",
            self.src)
        self.assertIsNotNone(m,
            "stream_chat 必须传 self._LOCAL_PHRASE_THRESHOLD 给 _start_backchannel_timer")


# ============================================================================
# a.14 — _put_audio / _render_worker / vocal.say 中文守门
# ============================================================================
class TestP0Plus18_a14_AudioChineseGuard(unittest.TestCase):
    """BUG #9 (P0/UX): 调用功能的对话第一句念中文"""

    @classmethod
    def setUpClass(cls):
        cls.nerve_src = _read(NERVE_PATH)
        cls.vocal_src = _read(VOCAL_PATH)

    def test_a14_marker_present(self):
        self.assertIn('P0+18-a.14', self.nerve_src)
        self.assertIn('P0+18-a.14', self.vocal_src)

    def test_put_audio_has_chinese_guard(self):
        """_put_audio 入口必须有 [\u4e00-\u9fa5] 检测 + strip"""
        m = re.search(
            r"def _put_audio.*?\[\\u4e00-\\u9fa5\]",
            self.nerve_src, re.DOTALL)
        self.assertIsNotNone(m,
            "_put_audio 必须有中文检测正则")

    def test_render_worker_has_chinese_guard(self):
        """_render_worker 入口必须有中文检测兜底"""
        m = re.search(
            r"def _render_worker.*?\[\\u4e00-\\u9fa5\]",
            self.nerve_src, re.DOTALL)
        self.assertIsNotNone(m,
            "_render_worker 必须有中文检测兜底")

    def test_vocal_say_has_chinese_guard(self):
        """vocal.say 入口必须有中文检测兜底"""
        m = re.search(
            r"def say\(self, text: str\):.*?\[\\u4e00-\\u9fa5\]",
            self.vocal_src, re.DOTALL)
        self.assertIsNotNone(m,
            "vocal.say 必须有中文检测兜底")

    def test_finish_default_msg_is_english(self):
        """action.command == 'finish' 的默认 message 必须英文"""
        # 用 quote-aware 正则：匹配 "..." 或 '...'（允许内部撇号）
        m = re.search(
            r"params\.get\(['\"]message['\"],\s*(?:\"([^\"]+)\"|'([^']+)')",
            self.nerve_src)
        self.assertIsNotNone(m, "必须能找到 finish 默认 message")
        default_msg = m.group(1) or m.group(2)
        zh_chars = re.findall(r'[\u4e00-\u9fa5]', default_msg)
        self.assertEqual(zh_chars, [],
            f"finish 默认 message 不应含中文，当前: {default_msg!r}")

    def test_ask_user_default_question_is_english(self):
        """ask_user 默认 question 也必须英文"""
        m = re.search(
            r"params\.get\(['\"]question['\"],\s*(?:\"([^\"]+)\"|'([^']+)')",
            self.nerve_src)
        self.assertIsNotNone(m, "必须能找到 ask_user 默认 question")
        default_q = m.group(1) or m.group(2)
        zh_chars = re.findall(r'[\u4e00-\u9fa5]', default_q)
        self.assertEqual(zh_chars, [],
            f"ask_user 默认 question 不应含中文，当前: {default_q!r}")


# ============================================================================
# a.15 — 主对话框排版整顿
# ============================================================================
class TestP0Plus18_a15_TerminalLayout(unittest.TestCase):
    """BUG #10 (P0/UX): 终端按 "说话→回答→行动→回答" 模式重构"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(NERVE_PATH)

    def test_a15_marker_present(self):
        self.assertIn('P0+18-a.15', self.src)

    def test_pipeline_first_token_goes_to_bg_log(self):
        """[Pipeline] First token 必须走 bg_log，不再在主对话框 print"""
        # 不应有 print(f"║ ⏱️  [Pipeline] First token: ...") 这种主框内 print
        m_old = re.search(
            r"print\(f['\"]║ ⏱️  \[Pipeline\] First token:",
            self.src)
        self.assertIsNone(m_old,
            "[Pipeline] First token 不应再用 print 进主对话框")
        # 必须有 bg_log 路径
        self.assertIn('Pipeline] First token:', self.src,
            "[Pipeline] First token 消息体仍保留（走 bg_log）")

    def test_gatekeeper_oneshot_goes_to_bg_log(self):
        """[Gatekeeper One-Shot] 必须走 bg_log"""
        # 旧路径不应存在
        m_old = re.search(
            r"print\(f['\"]\\n║ 🚪 \[Gatekeeper One-Shot\]",
            self.src)
        self.assertIsNone(m_old,
            "[Gatekeeper One-Shot] 不应再用 print 进主对话框")

    def test_tool_results_uses_inline_separator(self):
        """[Tool Results] 必须用 ╟─── 内嵌分隔符，不再开独立 ╔..╚ 框"""
        # 旧路径：║ 🔧 [Tool Results] (box 内独立框标题) 不应再在 print 语句里出现
        m_old = re.search(
            r"print\([^)]*?║ 🔧 \[Tool Results\]",
            self.src)
        self.assertIsNone(m_old,
            "[Tool Results] 框标题不应再在 print 语句里出现（已改用 ╟─── [Action]）")
        # 新路径：╟─── [Action] 应该有
        m_new = re.search(
            r"╟─── 🛠️  \[Action\]",
            self.src)
        self.assertIsNotNone(m_new,
            "[Tool Results] 必须改成 ╟─── [Action] 内嵌段")

    def test_wrapup_synthesis_goes_to_bg_log(self):
        """[Wrap-up Synthesis] 必须走 bg_log"""
        m_old = re.search(
            r"print\(f['\"]\\n║ 🩹 \[Wrap-up Synthesis\]",
            self.src)
        self.assertIsNone(m_old,
            "[Wrap-up Synthesis] 不应再 print 进主对话框")

    def test_hallucinated_claim_goes_to_bg_log(self):
        """[Hallucinated Claim] 必须走 bg_log"""
        m_old = re.search(
            r"print\(f['\"]\\n║ 🚨 \[Hallucinated Claim\]",
            self.src)
        self.assertIsNone(m_old,
            "[Hallucinated Claim] 不应再 print 进主对话框")


# ============================================================================
# 集成（行为）测试
# ============================================================================
class TestP0Plus18_Integration(unittest.TestCase):
    """13:19:41 / 13:03:37 实测事件级回归"""

    def test_physical_file_hint_actually_refused_at_runtime(self):
        """实测 hint='D盘 test.txt 文件' 必须返回 True，绝不能再触发 LTM 搜索"""
        from jarvis_nerve import _is_physical_file_delete_intent
        # 13:03:37 实测 hint
        self.assertTrue(_is_physical_file_delete_intent('D盘 test.txt 文件'))
        self.assertTrue(_is_physical_file_delete_intent('d:\\jarvis\\test_dummy.txt'))
        # 而典型 STM 记忆 hint 必须放行
        self.assertFalse(_is_physical_file_delete_intent('两点睡觉'))
        self.assertFalse(_is_physical_file_delete_intent('音量 30'))

    def test_echo_ring_short_word_runtime(self):
        """实测：Jarvis 说 "If you wish, I'll do that or just check it, Sir."
        → ASR 切碎 "if" / "or" / "it" 等短词应被识别为 echo"""
        from jarvis_utils import _TTSEchoRing, register_jarvis_tts, is_recent_jarvis_echo, clear_jarvis_tts_ring
        clear_jarvis_tts_ring()
        # 这段话 token 含: {if, you, wish, i, ll, do, that, or, just, check, it, sir}
        register_jarvis_tts("If you wish, I'll do that or just check it, Sir.")
        # 切碎的 "if" / "or" / "it" 在最近 12s Jarvis 答语 token 集合里 → 应判 echo
        self.assertTrue(is_recent_jarvis_echo("if"),
            "ASR 切碎的 'if' 应被识别为 echo（Jarvis 答语含 if）")
        self.assertTrue(is_recent_jarvis_echo("or"),
            "ASR 切碎的 'or' 应被识别为 echo")
        self.assertTrue(is_recent_jarvis_echo("it"),
            "ASR 切碎的 'it' 应被识别为 echo")
        # 但完全不相关的短词不应判 echo
        self.assertFalse(is_recent_jarvis_echo("xy"),
            "无关短词 'xy' 不应被误判为 echo")
        self.assertFalse(is_recent_jarvis_echo("qq"),
            "无关短词 'qq' 不应被误判为 echo")
        clear_jarvis_tts_ring()


if __name__ == '__main__':
    unittest.main(verbosity=2)
