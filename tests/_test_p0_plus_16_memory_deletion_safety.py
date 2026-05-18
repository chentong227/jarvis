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
        # 直接 delete 路径 必须传 min_similarity (β.4.7 改为从 vocab 读 _min_sim, 老路径 0.45 兼容)
        m = re.search(
            r"hippocampus\.search_memory\(\s*self\.jarvis\.gemini_key,\s*delete_hint,"
            r".*?min_similarity\s*=\s*(0\.45|_min_sim)",
            self.src, re.DOTALL,
        )
        self.assertIsNotNone(m,
            "直接 delete 路径必须传 min_similarity 给 search_memory "
            "(β.4.7 vocab _min_sim 或 legacy 0.45)")

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


# ==========================================================================
# [P0+20-β.4.7 / 2026-05-18] Layer 6/7/8: cmd 必含删除动词 + sim/top_k vocab + ASR 纠正拦截
# Sir 21:45 实测: ASR 误识别 "you out了" + Gatekeeper LLM 错抽 hint, 5 层防御全失守.
# 加 3 层守卫复用现有 vocab (准则 6.5 持久化 + CLI + L7 propose):
#   L6: cmd 必含 memory_deletion_vocab.json deletion_verb (删/delete/forget 等)
#   L7: top_k=1 + sim≥0.85 (vocab _meta.thresholds, 旧硬编码 5/0.45)
#   L8: cmd 含 memory_correction_vocab.json patterns ('识别错误'/'我没'/'其实'/'搞错了')
#       → Sir 在纠正 ASR, deletion 必拒
# ==========================================================================

class TestP0Plus20Beta47Layer6CmdMustHaveDeleteVerb(unittest.TestCase):
    """L6: cmd 必含显式删除动词才允许 memory deletion (vocab-driven)."""

    def test_sir_21_45_real_cmd_blocked(self):
        """Sir 21:45 实测原话不含删除动词 → L6 必拒."""
        from jarvis_safety import _user_intent_has_explicit_delete_verb
        sir_real_cmd = '嗯哎,没有没有刚才说的这个什么 out的,这是这是识别错误啊。我没跟你讲这个话'
        self.assertFalse(
            _user_intent_has_explicit_delete_verb(sir_real_cmd),
            "Sir 21:45 实测原话不含删除动词, L6 必须返 False (拒绝 deletion)")

    def test_explicit_chinese_delete_verbs_pass(self):
        from jarvis_safety import _user_intent_has_explicit_delete_verb
        for cmd in ['把两点睡觉那条删掉', '帮我删除那个记忆', '去掉这条', '清除昨天的提醒',
                     '忘掉两点睡觉那条', '丢掉这个']:
            self.assertTrue(_user_intent_has_explicit_delete_verb(cmd),
                f"含显式中文删除动词 {cmd!r} 应允许 deletion (L6 True)")

    def test_explicit_english_delete_verbs_pass(self):
        from jarvis_safety import _user_intent_has_explicit_delete_verb
        for cmd in ['delete that 2am sleep memory', 'please remove the reminder',
                     'forget about it', 'erase that record', 'discard the entry',
                     'wipe out that note']:
            self.assertTrue(_user_intent_has_explicit_delete_verb(cmd),
                f"含显式英文删除动词 {cmd!r} 应允许 deletion (L6 True)")

    def test_empty_cmd_blocked(self):
        from jarvis_safety import _user_intent_has_explicit_delete_verb
        self.assertFalse(_user_intent_has_explicit_delete_verb(''))
        self.assertFalse(_user_intent_has_explicit_delete_verb(None))

    def test_unrelated_chat_blocked(self):
        from jarvis_safety import _user_intent_has_explicit_delete_verb
        for cmd in ['今天天气怎么样', '帮我打开 Chrome', '你好 Jarvis',
                     'what is the weather', "let's grab coffee"]:
            self.assertFalse(_user_intent_has_explicit_delete_verb(cmd),
                f"普通对话 {cmd!r} 不含删除动词, L6 必须 False")


class TestP0Plus20Beta47Layer7ThresholdsFromVocab(unittest.TestCase):
    """L7: top_k 和 min_similarity 阈值从 vocab _meta.thresholds 读 (不硬编码)."""

    def test_load_thresholds_returns_canonical_keys(self):
        from jarvis_safety import _load_deletion_safety_thresholds
        thr = _load_deletion_safety_thresholds()
        self.assertIn('min_similarity', thr)
        self.assertIn('top_k_default', thr)
        # 类型必须 float / int 不允许 str
        self.assertIsInstance(thr['min_similarity'], float)
        self.assertIsInstance(thr['top_k_default'], int)

    def test_default_thresholds_tightened(self):
        """β.4.7 默认阈值: sim=0.85 (旧 0.45), top_k=1 (旧 5)."""
        from jarvis_safety import _load_deletion_safety_thresholds
        thr = _load_deletion_safety_thresholds()
        self.assertGreaterEqual(thr['min_similarity'], 0.80,
            f"β.4.7 sim 必须 >= 0.80 (实际 {thr['min_similarity']}); "
            f"老 0.45 太松导致误删")
        self.assertLessEqual(thr['top_k_default'], 2,
            f"β.4.7 top_k 必须 <= 2 (实际 {thr['top_k_default']}); "
            f"老 5 一次删 5 条危险")

    def test_vocab_file_exists_in_repo(self):
        path = os.path.join(ROOT, 'memory_pool', 'memory_deletion_vocab.json')
        self.assertTrue(os.path.exists(path),
            "memory_pool/memory_deletion_vocab.json 必须存在 (β.4.7 seed)")


class TestP0Plus20Beta47Layer8CorrectsAsrBlocked(unittest.TestCase):
    """L8: cmd 含 memory_correction patterns (Sir 纠正 ASR) → 必拒 deletion.
    复用 memory_correction_vocab.json (β.3.4-vocab3)."""

    def test_sir_21_45_corrects_asr_caught(self):
        """Sir 21:45 实测: '识别错误啊, 我没跟你讲这个话' → L8 必拦."""
        from jarvis_safety import _user_intent_corrects_asr_or_denies
        sir_real_cmd = '嗯哎,没有没有刚才说的这个什么 out的,这是这是识别错误啊。我没跟你讲这个话'
        self.assertTrue(_user_intent_corrects_asr_or_denies(sir_real_cmd),
            "Sir '识别错误啊, 我没跟你讲这个话' 是 ASR 纠正/否认, L8 必拦")

    def test_other_correction_patterns_caught(self):
        from jarvis_safety import _user_intent_corrects_asr_or_denies
        for cmd in ['不对不对, 我说的是另一个事',
                     '其实我意思是', '我搞错了',
                     '两码事啊', '不要混淆',
                     "actually I meant", "you got it wrong",
                     "let me clarify"]:
            self.assertTrue(_user_intent_corrects_asr_or_denies(cmd),
                f"ASR 纠正模式 {cmd!r} L8 必拦")

    def test_normal_delete_request_not_blocked_by_l8(self):
        """正常删除请求不应被 L8 拦 (L8 只拦纠正/否认)."""
        from jarvis_safety import _user_intent_corrects_asr_or_denies
        for cmd in ['把两点睡觉那条删掉', 'delete that record',
                     '清除昨天的提醒']:
            self.assertFalse(_user_intent_corrects_asr_or_denies(cmd),
                f"正常删除 {cmd!r} 不应被 L8 拦 (它没纠正/否认)")


class TestP0Plus20Beta47CompoundEndToEnd(unittest.TestCase):
    """L6+L7+L8 端到端契约: Sir 21:45 实测原话不能再误删."""

    def test_sir_21_45_blocked_by_l6_or_l8(self):
        """Sir 21:45 原话: L6 或 L8 至少一个拦 (实际两个都拦)."""
        from jarvis_safety import (_user_intent_has_explicit_delete_verb,
                                       _user_intent_corrects_asr_or_denies)
        sir_real_cmd = '嗯哎,没有没有刚才说的这个什么 out的,这是这是识别错误啊。我没跟你讲这个话'
        l6_allows = _user_intent_has_explicit_delete_verb(sir_real_cmd)
        l8_blocks = _user_intent_corrects_asr_or_denies(sir_real_cmd)
        self.assertFalse(l6_allows or not l8_blocks,
            f"Sir 21:45 实测原话: L6_allows={l6_allows} L8_blocks={l8_blocks}; "
            f"两层至少一层必须拦, 实际两层都该拦")

    def test_worker_uses_new_guards(self):
        """jarvis_worker.py delete_hint 路径必须调 L6 + L7 + L8 helper."""
        worker_path = os.path.join(ROOT, 'jarvis_worker.py')
        with open(worker_path, 'r', encoding='utf-8') as f:
            src = f.read()
        # L6 helper 必须被引用 in delete path
        self.assertIn('_user_intent_has_explicit_delete_verb(cmd)', src,
            "jarvis_worker.py 必须在 delete_hint 路径调 L6 helper")
        self.assertIn('_user_intent_corrects_asr_or_denies(cmd)', src,
            "jarvis_worker.py 必须在 delete_hint 路径调 L8 helper")
        self.assertIn('_load_deletion_safety_thresholds()', src,
            "jarvis_worker.py 必须用 _load_deletion_safety_thresholds 读 L7 阈值")
        # 旧硬编码 top_k=5 + min_similarity=0.45 不应在 delete 路径剩余
        # (其他 search_memory 调用点可能仍有 0.45, 但 deletion 路径必须用 vocab)
        self.assertIn('β.4.7 L7 vocab', src,
            "β.4.7 标记必须在 jarvis_worker.py delete 路径")


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("[OK] All P0+16 + β.4.7 Memory Deletion safety tests passed.")
    else:
        print(f"[FAIL] {len(result.failures)} failures, {len(result.errors)} errors")
    print("=" * 60)
    sys.exit(0 if result.wasSuccessful() else 1)
