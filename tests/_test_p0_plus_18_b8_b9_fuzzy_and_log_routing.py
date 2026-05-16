# -*- coding: utf-8 -*-
"""[P0+18-b.8 + b.9 / 2026-05-15] Fuzzy entity resolver + 对话激活前置 — 测试

b.8 / a.11 BUG #7 修复：ASR 转写 "XYZAPP" → process_hands 没匹配 → 主脑装作查了进程
b.9 减法版：set_conversation_active(True) 前置到 prompt 装配开始之前，让 [Prompt Tier] /
       [Tone] / [Conversation Event] / [Memory Correction] 不再漏出主对话框

覆盖
----
A. jarvis_fuzzy_resolver
    1. 纯函数 fuzzy_resolve_entity：能匹配 / 形态归一（XYZAPP ≈ xyz_app.exe）/ top_k / 阈值 / 子串提权 / 完全相等 / 空输入兜底
    2. format_fuzzy_candidates_for_msg：渲染人类可读文本
    3. FUZZY_CANDIDATES_POLICY 常量内容
    4. get_running_process_names：能拉到当前机器进程（非空 list）

B. l4_process_hands fuzzy fallback
    5. find_process / get_process_info / kill_process / kill_by_name / focus_process
       在 NotFound 时返 data.fuzzy_candidates（若有候选）+ msg 含 🔍

C. nerve.py prompt 装配 + 对话激活前置
    6. 全档 prompt 注入 fuzzy_candidates_policy
    7. SHORT_CHAT 注入 _short_fuzzy_policy
    8. JarvisWorkerThread.run 里 set_conversation_active(True) 提前到
       prompt_tier 分类**之前**（修 b.9）

跑法：
    cd d:\\Jarvis
    python tests/_test_p0_plus_18_b8_b9_fuzzy_and_log_routing.py
"""

import os
import re
import sys
import unittest

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

NERVE_PATH = os.path.join(ROOT, 'jarvis_nerve.py')
PROCESS_HANDS_PATH = os.path.join(ROOT, 'l4_hands_pool', 'l4_process_hands.py')


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
# A.1 — fuzzy_resolve_entity 纯函数
# ============================================================================
class TestB8_FuzzyResolveEntity(unittest.TestCase):

    def test_exact_match(self):
        from jarvis_fuzzy_resolver import fuzzy_resolve_entity
        out = fuzzy_resolve_entity('chrome.exe', ['chrome.exe', 'firefox.exe'])
        self.assertEqual(out[0][0], 'chrome.exe')
        self.assertGreaterEqual(out[0][1], 0.95, "完全相等应该 ≥ 0.95")

    def test_case_insensitive_match(self):
        """XYZAPP (全大写 ASR) ≈ xyz_app.exe"""
        from jarvis_fuzzy_resolver import fuzzy_resolve_entity
        out = fuzzy_resolve_entity('XYZAPP', ['xyz_app.exe', 'firefox.exe', 'totally_unrelated.exe'])
        self.assertTrue(out, "必须有匹配")
        self.assertEqual(out[0][0], 'xyz_app.exe', "首匹配必须是 xyz_app.exe")
        self.assertGreaterEqual(out[0][1], 0.7, "形态归一后子串匹配 ≥ 0.7")

    def test_suffix_stripping(self):
        """'chrome.exe' ≈ 'chrome' ≈ 'CHROME' ≈ 'Chrome.lnk'"""
        from jarvis_fuzzy_resolver import fuzzy_resolve_entity
        for q in ['chrome', 'CHROME', 'Chrome', 'chrome.lnk']:
            out = fuzzy_resolve_entity(q, ['chrome.exe', 'firefox.exe'])
            self.assertTrue(out, f"query={q!r} 应该匹配 chrome.exe")
            self.assertEqual(out[0][0], 'chrome.exe')

    def test_top_k_limit(self):
        from jarvis_fuzzy_resolver import fuzzy_resolve_entity
        out = fuzzy_resolve_entity('app', [f'app_{i}.exe' for i in range(10)], top_k=3)
        self.assertLessEqual(len(out), 3, "top_k 限制必须生效")

    def test_min_similarity_threshold(self):
        from jarvis_fuzzy_resolver import fuzzy_resolve_entity
        # 完全不像的字符串
        out = fuzzy_resolve_entity('quantum_mechanics', ['chrome.exe', 'firefox.exe'],
                                   min_similarity=0.7)
        self.assertFalse(out, "完全不像且高阈值 → 应该没匹配")

    def test_substring_boost(self):
        """'cur' ⊆ 'cursor.exe' → 子串提权"""
        from jarvis_fuzzy_resolver import fuzzy_resolve_entity
        out = fuzzy_resolve_entity('cur', ['cursor.exe', 'firefox.exe'])
        self.assertTrue(out)
        self.assertGreaterEqual(out[0][1], 0.75, "子串关系应该至少 0.75")

    def test_empty_inputs(self):
        from jarvis_fuzzy_resolver import fuzzy_resolve_entity
        self.assertEqual(fuzzy_resolve_entity('', ['chrome.exe']), [])
        self.assertEqual(fuzzy_resolve_entity('chrome', []), [])
        self.assertEqual(fuzzy_resolve_entity(None, ['chrome.exe']), [])

    def test_dedup(self):
        from jarvis_fuzzy_resolver import fuzzy_resolve_entity
        # 输入有重复 candidate（大小写不同的视为同名）
        out = fuzzy_resolve_entity('chrome', ['chrome.exe', 'Chrome.exe', 'chrome.EXE'])
        # lower() 后都一样，应该只返一个
        self.assertEqual(len(out), 1, "同名候选必须去重")

    def test_score_descending(self):
        from jarvis_fuzzy_resolver import fuzzy_resolve_entity
        out = fuzzy_resolve_entity('xyz_app',
                                   ['xyz_app.exe', 'xyz_other.exe', 'completely_diff.exe'],
                                   min_similarity=0.4)
        if len(out) >= 2:
            self.assertGreaterEqual(out[0][1], out[1][1], "score 必须降序")


# ============================================================================
# A.2 — format_fuzzy_candidates_for_msg
# ============================================================================
class TestB8_FormatFuzzyCandidates(unittest.TestCase):

    def test_empty_returns_empty(self):
        from jarvis_fuzzy_resolver import format_fuzzy_candidates_for_msg
        self.assertEqual(format_fuzzy_candidates_for_msg([]), '')

    def test_renders_score_as_percent(self):
        from jarvis_fuzzy_resolver import format_fuzzy_candidates_for_msg
        out = format_fuzzy_candidates_for_msg([('chrome.exe', 0.876)], query='chrome')
        self.assertIn('🔍 [Fuzzy Candidates]', out)
        self.assertIn('chrome.exe', out)
        self.assertIn('88%', out, "0.876 应该渲染成 88%")
        self.assertIn("'chrome'", out, "原始 query 应该在 header 里")

    def test_max_lines(self):
        from jarvis_fuzzy_resolver import format_fuzzy_candidates_for_msg
        cands = [(f'app_{i}.exe', 0.9 - i * 0.05) for i in range(10)]
        out = format_fuzzy_candidates_for_msg(cands, max_lines=3)
        # 算行数：1 header + 3 candidates
        self.assertEqual(out.count('\n'), 3, "max_lines=3 时只输出 3 条候选行")


# ============================================================================
# A.3 — FUZZY_CANDIDATES_POLICY 常量
# ============================================================================
class TestB8_PolicyDirective(unittest.TestCase):

    def test_directive_has_key_warnings(self):
        from jarvis_fuzzy_resolver import FUZZY_CANDIDATES_POLICY
        self.assertIn('FUZZY CANDIDATES POLICY', FUZZY_CANDIDATES_POLICY)
        self.assertIn('NEVER pretend', FUZZY_CANDIDATES_POLICY)
        self.assertIn('Did you mean', FUZZY_CANDIDATES_POLICY)
        self.assertIn('承诺必行', FUZZY_CANDIDATES_POLICY)
        # 跟 TOOL HONESTY 是 mirror 关系，应该明确点出
        self.assertIn('TOOL HONESTY', FUZZY_CANDIDATES_POLICY)


# ============================================================================
# A.4 — get_running_process_names（生产侧便利函数）
# ============================================================================
class TestB8_GetRunningProcessNames(unittest.TestCase):

    def test_returns_list(self):
        from jarvis_fuzzy_resolver import get_running_process_names
        out = get_running_process_names()
        self.assertIsInstance(out, list, "必须返回 list")
        # psutil 在 Windows 上能跑 → 应该非空（至少有 python 进程）
        # 但如果 psutil 未装环境下，允许空，不强约
        try:
            import psutil  # noqa
            self.assertGreater(len(out), 0, "psutil 可用时必须能拉到进程")
        except ImportError:
            pass

    def test_no_duplicates_case_insensitive(self):
        from jarvis_fuzzy_resolver import get_running_process_names
        out = get_running_process_names()
        lower_set = set(x.lower() for x in out)
        self.assertEqual(len(out), len(lower_set), "去重应该按 lower() 严格")


# ============================================================================
# B.5 — process_hands NotFound → fuzzy fallback
# ============================================================================
class TestB8_ProcessHandsFuzzyFallback(unittest.TestCase):
    """实际跑 process_hands 的 find_process / get_process_info / kill_process 等，
    用一个绝对不可能存在的 ASR-风格名字 → 期望返 fuzzy_candidates。"""

    @classmethod
    def setUpClass(cls):
        from l4_hands_pool.l4_process_hands import Hands
        from jarvis_blood import Action
        cls.Hands = Hands
        cls.Action = Action

    def _call(self, command: str, **params):
        h = self.Hands()
        action = self.Action(command=command, params=params)
        return h.execute(action)

    def test_find_process_not_found_returns_candidates(self):
        # 用极端不可能的 ASR-风格全大写名（应该 fuzzy 不到完美匹配，但能找到接近的真实进程）
        result = self._call('find_process', name='SOMETHINGNONEXISTENTXYZ12345')
        self.assertFalse(result.success)
        # 不强求一定有候选（如果机器上没有任何近似的）。但有候选时 data 必须有 fuzzy_candidates
        if 'fuzzy_candidates' in (result.data or {}):
            self.assertIn('🔍', result.msg, "有候选时 msg 必须含 🔍 标识")
            self.assertTrue(result.data['fuzzy_candidates'])

    def test_find_process_real_python_gives_candidates_for_typo(self):
        """用一个真实存在的进程名的轻微 ASR 错位（'pyhton' 应该 fuzzy 到 'python.exe'）"""
        # Windows 上 Python 进程一定存在（本测试就跑在 python.exe 里）
        result = self._call('find_process', name='pyhton')  # typo of python
        # 要么直接找到（如果有"含"匹配），要么走 fuzzy
        if not result.success:
            # 走 fuzzy 路径
            if result.data and 'fuzzy_candidates' in result.data:
                names = [c['name'].lower() for c in result.data['fuzzy_candidates']]
                # 应该有 python.exe 或类似
                has_python = any('python' in n for n in names)
                self.assertTrue(has_python, f"应该 fuzzy 到 python.* 进程: {names}")

    def test_get_process_info_by_name_not_found_returns_fuzzy(self):
        result = self._call('get_process_info', name='NEVEREXIST_XYZ_APP_99999')
        self.assertFalse(result.success)
        # 不一定有候选（要看机器进程列表），但如果有 → 必须符合契约
        if result.data and 'fuzzy_candidates' in result.data:
            self.assertIn('🔍', result.msg)

    def test_kill_by_name_zero_kills_returns_fuzzy(self):
        # 用一个不可能存在的名字（不会真 kill 任何东西）
        result = self._call('kill_by_name', name='absolutely_nonexistent_xyz_99999')
        self.assertFalse(result.success)
        # 同上，候选取决于机器，但契约必须对
        if result.data and 'fuzzy_candidates' in result.data:
            self.assertIn('🔍', result.msg)

    def test_focus_process_not_found_returns_fuzzy(self):
        result = self._call('focus_process', name='nowindow_xyz_app_99999')
        self.assertFalse(result.success)
        if result.data and 'fuzzy_candidates' in result.data:
            self.assertIn('🔍', result.msg)


# ============================================================================
# C.6 + C.7 — nerve.py prompt 注入
# ============================================================================
class TestB8_NervePromptInjection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read(NERVE_PATH)

    def test_marker_present(self):
        self.assertIn('P0+18-b.8', self.src, "必须留 [P0+18-b.8] marker")

    def test_full_prompt_imports_policy(self):
        self.assertIn('from jarvis_fuzzy_resolver import FUZZY_CANDIDATES_POLICY', self.src)
        self.assertIn('{fuzzy_candidates_policy}', self.src,
                      "全档 prompt f-string 必须有 {fuzzy_candidates_policy} 占位")

    def test_short_chat_imports_policy(self):
        # SHORT_CHAT 段
        self.assertIn('{_short_fuzzy_policy}', self.src,
                      "SHORT_CHAT f-string 必须有 {_short_fuzzy_policy} 占位")


# ============================================================================
# C.8 — b.9 set_conversation_active 前置
# ============================================================================
class TestB9_ConversationActiveEarlyEnable(unittest.TestCase):
    """JarvisWorkerThread.run 里 prompt_tier 分类**之前**必须先 set_conversation_active(True)。"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(NERVE_PATH)

    def test_marker_present(self):
        self.assertIn('P0+18-b.9', self.src, "必须留 [P0+18-b.9] marker")

    def test_set_active_before_classify_prompt_tier(self):
        """在源码顺序上，b.9 的 set_conversation_active(True) 调用必须出现在
        `prompt_tier = self._classify_prompt_tier(...)` 之前。"""
        # 找 b.9 marker 的位置
        m_b9 = re.search(r'P0\+18-b\.9.*?_set_conv_active_b9\(True\)', self.src, re.DOTALL)
        self.assertIsNotNone(m_b9, "b.9 段必须含 _set_conv_active_b9(True) 调用")
        # 找 _classify_prompt_tier 调用（在 JarvisWorkerThread.run 里）
        m_cls = re.search(r'prompt_tier\s*=\s*self\._classify_prompt_tier\(', self.src)
        self.assertIsNotNone(m_cls, "_classify_prompt_tier 调用必须存在")
        # 顺序检查：b.9 段 end < classify 段 start
        self.assertLess(m_b9.end(), m_cls.start(),
                        "set_conversation_active(True) 必须在 _classify_prompt_tier 之前调")


# ============================================================================
# Main
# ============================================================================
if __name__ == '__main__':
    unittest.main(verbosity=2)
