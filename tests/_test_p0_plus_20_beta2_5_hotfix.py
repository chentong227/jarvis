# -*- coding: utf-8 -*-
"""[P0+20-β.2.5 hotfix / 2026-05-17] Sir 23:58 实测三 BUG 修复测试

BUG #1: text_hands.read 失败时无 fuzzy 文件名建议 → LLM 没足够信息向 Sir 反问
BUG #2: 工具全失败 + 熔断 + LLM 只说启动语 → 没合成"打开失败"兜底回复 → Sir 不知情
BUG #3: detect_stop_command 不识别"不是不是，是 stand down"句末模式 → 焦点不退出

详 jarvis_20260516_235840.log:299 / line 335 / line 721
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# BUG #3: detect_stop_command 句末 stand down 触发
# ============================================================
class TestStandDownTailDetection(unittest.TestCase):
    """[β.2.5 hotfix] stand down 出现在句末（不在首部）也应触发停止。
    Sir 23:58 实测：'不是不是我说错了，是stand down' 没触发 → 焦点没退。"""

    def setUp(self):
        # 不实例化整个 VoiceListenThread（涉及 ASR / Qt），直接绑 method
        from jarvis_worker import VoiceListenThread
        self.detect_stop = lambda txt: VoiceListenThread.detect_stop_command(
            VoiceListenThread.__new__(VoiceListenThread), txt
        )

    def test_pure_stand_down(self):
        self.assertTrue(self.detect_stop("stand down"))

    def test_sir_correction_pattern(self):
        """Sir 实测原句：'不是不是我说错了，是stand down'"""
        self.assertTrue(
            self.detect_stop("不是不是我说错了，是stand down"),
            "Sir 纠正模式 'X 我说错了，是 stand down' 应触发停止"
        )

    def test_short_correction_with_stand_down(self):
        self.assertTrue(self.detect_stop("不，是 stand down"))
        self.assertTrue(self.detect_stop("oh wait, stand down"))
        self.assertTrue(self.detect_stop("err, stand down please"))

    def test_long_discussion_does_not_trigger(self):
        """长句讨论不应误触发（避免'I want to talk about stand down protocols'被误炸）"""
        long_discussion = (
            "I want to talk about stand down protocols and how they "
            "differ from emergency shutdowns in operational doctrine"
        )
        self.assertFalse(
            self.detect_stop(long_discussion),
            "长 (>26 字符) 句末出现 stand down 不应触发停止（话题讨论）"
        )

    def test_phrase_at_tail_helper(self):
        from jarvis_worker import VoiceListenThread as VL
        self.assertTrue(VL._phrase_at_tail("stand down", "yes, stand down"))
        self.assertTrue(VL._phrase_at_tail("退下", "好吧，那退下"))
        self.assertFalse(VL._phrase_at_tail("stand down", "stand down means..."))

    def test_other_stop_words_at_tail(self):
        """退下 / 闭嘴 / 终止 这些硬停止词也应在句末触发"""
        self.assertTrue(self.detect_stop("好的好的，那退下吧"))
        self.assertTrue(self.detect_stop("ok, that's enough, shut up"))


# ============================================================
# BUG #1: text_hands fuzzy 文件名建议
# ============================================================
class TestFuzzyFileSuggestion(unittest.TestCase):
    """[β.2.5 hotfix] LLM 把 TODO.md 听成 to do.txt → 应在失败 msg 里附 'Did you mean'"""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        # 创建几个 fixture 文件
        for fname in ('TODO.md', 'README.md', 'AGENTS.md', 'notes.txt'):
            with open(os.path.join(self.tmpdir, fname), 'w', encoding='utf-8') as f:
                f.write('test')

    def tearDown(self):
        import shutil
        try:
            shutil.rmtree(self.tmpdir)
        except Exception:
            pass

    def test_to_do_txt_suggests_todo_md(self):
        """Sir 23:58 实测的精确场景：'to do.txt' 应优先建议 TODO.md"""
        from l4_hands_pool.l4_text_hands import _suggest_similar_paths
        path = os.path.join(self.tmpdir, 'to do.txt')
        suggestions = _suggest_similar_paths(path)
        self.assertTrue(len(suggestions) > 0, "fuzzy 没返回任何 suggestion")
        # TODO.md 应该是第一推荐（紧凑形式 'todo' == 'todo' exact stem match）
        first_basename = os.path.basename(suggestions[0])
        self.assertEqual(first_basename, 'TODO.md',
                         f"first suggestion 应是 TODO.md，实际 {first_basename}")

    def test_case_insensitive_match(self):
        from l4_hands_pool.l4_text_hands import _suggest_similar_paths
        path = os.path.join(self.tmpdir, 'agents.md')  # lowercase
        suggestions = _suggest_similar_paths(path)
        first_basename = os.path.basename(suggestions[0])
        self.assertEqual(first_basename, 'AGENTS.md')

    def test_no_match_returns_empty(self):
        from l4_hands_pool.l4_text_hands import _suggest_similar_paths
        path = os.path.join(self.tmpdir, 'completely_unrelated_xyz_file_12345.qzj')
        suggestions = _suggest_similar_paths(path)
        # cutoff=0.4，所以可能 0-1 个 weak match。最差返回空，不应抛
        self.assertIsInstance(suggestions, list)

    def test_file_not_found_msg_contains_did_you_mean(self):
        from l4_hands_pool.l4_text_hands import _file_not_found_msg
        path = os.path.join(self.tmpdir, 'to do.txt')
        msg = _file_not_found_msg(path)
        self.assertIn('文件不存在', msg)
        self.assertIn('Did you mean', msg)
        self.assertIn('TODO.md', msg)

    def test_nonexistent_dir_no_crash(self):
        """目录不存在不抛"""
        from l4_hands_pool.l4_text_hands import _suggest_similar_paths
        sugs = _suggest_similar_paths('/nonexistent/dir/foo.txt')
        self.assertEqual(sugs, [])

    def test_end_to_end_read_failure_msg(self):
        """端到端：text_hands.read('不存在文件') → ExecutionResult.msg 含 fuzzy 建议"""
        from l4_hands_pool.l4_text_hands import Hands
        from jarvis_blood import Action
        path = os.path.join(self.tmpdir, 'to do.txt')
        result = Hands().execute(Action(command='read', params={'path': path}))
        self.assertFalse(result.success)
        self.assertIn('Did you mean', result.msg)
        self.assertIn('TODO.md', result.msg)


# ============================================================
# BUG #2: 工具全失败 + 熔断 → 强制兜底（静态扫源码确认逻辑加进去了）
# ============================================================
class TestForceSynthesisOnToolFailure(unittest.TestCase):
    """[β.2.5 hotfix] chat_bypass._need_synthesis 在 consecutive_failures + all_tools_failed
    时强制合成兜底回复，而不论 LLM 是否输出了启动语。"""

    def test_chat_bypass_need_synthesis_includes_all_failures_path(self):
        """静态扫 jarvis_chat_bypass.py 含 _all_tools_failed 强制兜底条件"""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        fpath = os.path.join(repo_root, 'jarvis_chat_bypass.py')
        with open(fpath, encoding='utf-8') as f:
            content = f.read()
        # 找到 _need_synthesis 的定义到结束闭括号（多行，非贪婪匹配嵌套圆括号）
        # 简化：取从 `_need_synthesis = bool(` 开始到 `\n            )` 的整段
        idx = content.find('_need_synthesis = bool(')
        self.assertGreaterEqual(idx, 0, "未找到 _need_synthesis 定义")
        # 取 250 字符窗口看 hotfix 条件是否在
        block = content[idx:idx + 1000]
        self.assertIn('consecutive_failures', block,
                      "_need_synthesis 条件未覆盖 consecutive_failures")
        self.assertIn('_all_tools_failed', block,
                      "_need_synthesis 条件未覆盖 _all_tools_failed")

    def test_synthesis_uses_failure_tail(self):
        """consecutive_failures 路径会从 last_bad 取 fuzzy 建议尾部（含 Did you mean）"""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        fpath = os.path.join(repo_root, 'jarvis_chat_bypass.py')
        with open(fpath, encoding='utf-8') as f:
            content = f.read()
        # consecutive_failures 分支应当从 last_bad 取尾部到回复
        self.assertIn('consecutive_failures', content)
        self.assertIn("I couldn't complete that, Sir", content)


if __name__ == '__main__':
    unittest.main(verbosity=2)
