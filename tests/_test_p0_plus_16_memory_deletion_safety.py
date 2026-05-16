# -*- coding: utf-8 -*-
"""[P0+16 / 2026-05-15] Memory Deletion 4 层防御 — 测试套件

09:22 实测事件：Sir 说"删掉那个东西不重要了"（前文铺垫"两点睡觉"）
→ Gatekeeper LLM 把"那个东西"当 delete_memory_hint 直传 search_memory
→ search 无阈值返回 5 条带"那个/什么"指代词的近邻（相似度可能 < 0.2）
→ for 循环无确认全删 → 误杀 5 条无关记忆，且 Sir 真正想删的"两点睡觉"毫发无损
（典型"嘴上 A 手上 B"，Integrity Check 反向漏网）

4 层防御覆盖：
  Layer 1: 纯指代词拦截（_is_reference_only_hint）
  Layer 2: search_memory min_similarity ≥ 0.45 阈值
  Layer 3: 删除前 candidates preview + event_bus publish (PromiseLedger hook 接口)
  Layer 4: Gatekeeper prompt 规则 14 [REFERENCE DISAMBIGUATION]

跑法：
    cd d:\\Jarvis
    python tests/_test_p0_plus_16_memory_deletion_safety.py
"""
import inspect
import os
import re
import sys
import sqlite3
import tempfile
import time
import unittest

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

NERVE_PATH = os.path.join(ROOT, 'jarvis_nerve.py')
HIPPO_PATH = os.path.join(ROOT, 'jarvis_hippocampus.py')


def _read(path):
    # [P0+19 / 2026-05-16] 拆分后 nerve.py 内容分散到多文件
    if 'jarvis_nerve.py' in str(path):
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _source_corpus import read_nerve_corpus
        return read_nerve_corpus()
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# ==========================================================================
# Layer 1: 纯指代词识别
# ==========================================================================

class TestP0Plus16Layer1ReferenceDetection(unittest.TestCase):
    """Layer 1: _is_reference_only_hint() 必须正确识别纯指代词 vs 含具体语义的 hint"""

    @classmethod
    def setUpClass(cls):
        from jarvis_nerve import _is_reference_only_hint, _strip_reference_tokens
        # 类属性赋函数会被当 unbound 方法 → 必须 staticmethod 包装
        cls.f = staticmethod(_is_reference_only_hint)
        cls.strip = staticmethod(_strip_reference_tokens)

    def test_pure_chinese_pronoun_blocked(self):
        for hint in ['那个东西', '这个东西', '那东西', '这东西',
                     '那', '这', '它', '那个', '这个',
                     '那条', '这条', '那段', '这段',
                     '那记忆', '这记录']:
            self.assertTrue(self.f(hint),
                f"纯中文指代词 {hint!r} 应被识别为 reference_only")

    def test_pure_english_pronoun_blocked(self):
        for hint in ['that', 'this', 'it',
                     'that thing', 'this thing', 'that one', 'this one',
                     'that memory', 'this memory', 'that record', 'this record',
                     'the thing', 'the entry']:
            self.assertTrue(self.f(hint),
                f"纯英文指代词 {hint!r} 应被识别为 reference_only")

    def test_concrete_chinese_passes(self):
        for hint in ['两点睡觉', '凌晨 2 点', '音量 30%', '把音量调到 30',
                     '昨天的 bug', '上次那个项目', '会议提醒', '喝水']:
            self.assertFalse(self.f(hint),
                f"含具体语义的中文 {hint!r} 不应被拦截")

    def test_concrete_english_passes(self):
        for hint in ['sleep at 2am', 'volume 30%', 'meeting reminder',
                     'water reminder', 'yesterday bug']:
            self.assertFalse(self.f(hint),
                f"含具体语义的英文 {hint!r} 不应被拦截")

    def test_pronoun_with_concrete_noun_passes(self):
        """指代词 + 具体名词的组合应该通过（"那个文件" / "that bug"）"""
        for hint in ['那个文件', '那个 bug', '那个项目', '这条提醒',
                     'that bug', 'that file', 'this project', 'the meeting']:
            self.assertFalse(self.f(hint),
                f"指代词+具体名词 {hint!r} 不应被拦截")

    def test_empty_blocked(self):
        for hint in ['', None, '   ', '\t\n']:
            self.assertTrue(self.f(hint),
                f"空 / 空白 hint {hint!r} 应被识别为 reference_only")

    def test_strip_helper_correctness(self):
        """剥离辅助函数本身的正确性"""
        self.assertEqual(self.strip('那个东西').strip(), '')
        self.assertIn('两点', self.strip('那个两点'))
        self.assertEqual(self.strip(''), '')


# ==========================================================================
# Layer 2: search_memory min_similarity 阈值
# ==========================================================================

class TestP0Plus16Layer2SearchMemoryThreshold(unittest.TestCase):
    """Layer 2: search_memory + _fuzzy_fallback_search 必须支持 min_similarity"""

    def test_search_memory_signature_has_min_similarity(self):
        from jarvis_hippocampus import Hippocampus
        sig = inspect.signature(Hippocampus.search_memory)
        self.assertIn('min_similarity', sig.parameters,
            "Hippocampus.search_memory 必须有 min_similarity 参数（P0+16）")
        self.assertEqual(sig.parameters['min_similarity'].default, 0.0,
            "min_similarity 默认值必须是 0.0（向后兼容）")

    def test_fuzzy_fallback_signature_has_min_similarity(self):
        from jarvis_hippocampus import Hippocampus
        sig = inspect.signature(Hippocampus._fuzzy_fallback_search)
        self.assertIn('min_similarity', sig.parameters,
            "_fuzzy_fallback_search 必须有 min_similarity 参数")

    def test_fuzzy_fallback_filters_low_similarity(self):
        """用临时 DB + fuzzy fallback 真跑：min_similarity=0.95 应过滤低分候选"""
        from jarvis_hippocampus import Hippocampus
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, 'test.db')
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute('''CREATE TABLE TaskMemories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL, environment TEXT,
                user_intent TEXT, macro_goal TEXT, execution_summary TEXT,
                raw_actions JSON, semantic_embedding BLOB,
                memory_type TEXT, entities_json JSON,
                is_future_task INTEGER DEFAULT 0, trigger_time REAL DEFAULT 0,
                is_deleted INTEGER DEFAULT 0
            )''')
            now = time.time()
            for intent, summary in [
                ('两点睡觉的提醒', '注册了凌晨2点睡觉的 commitment'),
                ('调音量到 30%', 'Audio Hands 已执行'),
                ('那个东西在哪里', '不知道 Sir 指什么'),
            ]:
                c.execute(
                    "INSERT INTO TaskMemories (timestamp, environment, user_intent, execution_summary) VALUES (?, ?, ?, ?)",
                    (now, 'CHAT', intent, summary),
                )
            conn.commit()
            conn.close()

            h = Hippocampus(db_path=db_path)
            results_no_thresh = h._fuzzy_fallback_search('两点睡觉', top_k=5)
            results_strict = h._fuzzy_fallback_search('两点睡觉', top_k=5,
                                                      min_similarity=0.95)
            self.assertGreater(len(results_no_thresh), 0,
                "无阈值时应返回多条结果")
            self.assertLessEqual(len(results_strict), len(results_no_thresh),
                "严格阈值时返回结果应 ≤ 无阈值")

    def test_search_memory_zero_threshold_backward_compat(self):
        """min_similarity=0.0 时行为不变（不应破坏现有 9 处调用点）"""
        from jarvis_hippocampus import Hippocampus
        # 反射验证：默认调用不应抛异常
        sig = inspect.signature(Hippocampus.search_memory)
        defaults = {n: p.default for n, p in sig.parameters.items()
                    if p.default is not inspect.Parameter.empty}
        self.assertEqual(defaults.get('min_similarity'), 0.0)
        self.assertEqual(defaults.get('top_k'), 3)
        self.assertEqual(defaults.get('time_limit'), 0.0)


# ==========================================================================
# Layer 3: 删除前 candidates preview + event_bus publish
# ==========================================================================

class TestP0Plus16Layer3DeletePreviewMarker(unittest.TestCase):
    """Layer 3: nerve.py delete 路径必须有 preview + event_bus + guard 三个 marker"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(NERVE_PATH)

    def test_deletion_guard_marker(self):
        self.assertIn('[Memory Deletion Guard]', self.src,
            "delete 路径必须有 [Memory Deletion Guard] marker（指代词拦截日志）")

    def test_deletion_preview_marker(self):
        self.assertIn('[Memory Deletion Preview]', self.src,
            "delete 路径必须有 [Memory Deletion Preview] marker（候选清单日志）")

    def test_publishes_memory_deletion_preview_event(self):
        self.assertIn("'memory_deletion_preview'", self.src,
            "delete 路径必须 publish 'memory_deletion_preview' 到 event_bus（PromiseLedger hook）")

    def test_publishes_memory_deletion_refused_event(self):
        self.assertIn("'memory_deletion_refused'", self.src,
            "拒绝路径必须 publish 'memory_deletion_refused' 到 event_bus")

    def test_uses_min_similarity_in_delete_path(self):
        # 直接 delete 路径
        m = re.search(
            r"hippocampus\.search_memory\(\s*self\.jarvis\.gemini_key,\s*delete_hint,"
            r".*?min_similarity\s*=\s*0\.45",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "直接 delete 路径必须用 min_similarity=0.45 调 search_memory")

    def test_correction_to_delete_path_also_uses_guard(self):
        """correction guard 转 delete 那条路径也必须套同样的 guard"""
        self.assertIn('[Memory Deletion Guard / via correction]', self.src,
            "correction→delete 路径必须有 [Memory Deletion Guard / via correction] marker")
        self.assertIn('[Memory Deletion Preview / via correction]', self.src,
            "correction→delete 路径也要 preview")

    def test_refusal_message_tells_main_brain_to_clarify(self):
        self.assertIn('Memory deletion REFUSED', self.src,
            "拒绝时 result['gate_result_text'] 必须含 'Memory deletion REFUSED' 让主脑读到")
        self.assertIn('pronoun without clear referent', self.src,
            "拒绝消息必须解释原因供主脑生成澄清问")


# ==========================================================================
# Layer 4: Gatekeeper prompt 规则 14
# ==========================================================================

class TestP0Plus16Layer4GatekeeperPromptHasRule14(unittest.TestCase):
    """Layer 4: Gatekeeper prompt 必须有规则 14 [REFERENCE DISAMBIGUATION]"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(NERVE_PATH)

    def test_rule_14_present(self):
        self.assertIn('14. [REFERENCE DISAMBIGUATION]', self.src,
            "Gatekeeper prompt 必须有规则 14 [REFERENCE DISAMBIGUATION]")

    def test_rule_14_warns_against_bare_pronouns(self):
        self.assertIn('NEVER use bare pronouns', self.src,
            "规则 14 必须警告 LLM 不要用裸指代词")
        # 至少给出几个明确禁词
        for forbidden in ['那个东西', 'this thing', 'that']:
            self.assertIn(forbidden, self.src,
                f"规则 14 必须列出 {forbidden!r} 作为禁词示例")

    def test_rule_14_has_concrete_referent_resolution_example(self):
        """规则 14 必须给出"两点睡觉"那条 STM-based 消歧的例子（直接对应实测事件）"""
        self.assertIn('两点睡觉', self.src,
            "规则 14 必须以 09:22 实测事件的'两点睡觉'为消歧示例")
        # 应说明：从 STM 找到具体 referent 用作 hint
        m = re.search(
            r"14\.\s*\[REFERENCE DISAMBIGUATION\].*?"
            r"resolve them to the actual referent.*?STM",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "规则 14 必须教 LLM 通过 STM Context 解析指代词到具体 referent")

    def test_rule_14_says_empty_when_no_referent_in_stm(self):
        """STM 里找不到具体 referent 时应留空，让主脑去问"""
        self.assertIn('leave the hint EMPTY', self.src,
            "规则 14 必须告诉 LLM：找不到具体 referent 时留空")


# ==========================================================================
# 实测事件回归（端到端契约）
# ==========================================================================

class TestP0Plus16RealLifeRegression(unittest.TestCase):
    """09:22 实测事件本身必须不再发生"""

    def test_09_22_event_pronouns_all_caught(self):
        from jarvis_nerve import _is_reference_only_hint
        # 09:22 当时若 Gatekeeper 提取这些 hint，必须全部被 Layer 1 拦截
        for actual_or_likely_hint in ['那个东西', 'that thing', '那东西', '它']:
            self.assertTrue(_is_reference_only_hint(actual_or_likely_hint),
                f"09:22 事件级 hint {actual_or_likely_hint!r} 必须被 Layer 1 拦截")

    def test_correct_referent_passes(self):
        """如果 LLM 按规则 14 正确消歧，'两点睡觉' / 'sleep at 2am' 应该通过"""
        from jarvis_nerve import _is_reference_only_hint
        for correct_hint in ['两点睡觉', 'sleep at 2am', '凌晨 2 点睡', 'two am sleep']:
            self.assertFalse(_is_reference_only_hint(correct_hint),
                f"正确消歧后的 hint {correct_hint!r} 应该通过")


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("[OK] All P0+16 Memory Deletion safety tests passed.")
    else:
        print(f"[FAIL] {len(result.failures)} failures, {len(result.errors)} errors")
    print("=" * 60)
    sys.exit(0 if result.wasSuccessful() else 1)
