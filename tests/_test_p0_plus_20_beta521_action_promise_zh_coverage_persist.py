# -*- coding: utf-8 -*-
"""[β.5.21 / 2026-05-20] Sir 准则 5 言出必行 — 双 BUG 修复 testcase

Sir 实测 (01:04 + 01:07 + 01:12, 截图):
  BUG 1 (β.5.21-A): fast_call 中断主回复 → spoken_so_far flush EN 但还没生成 ZH
    → continuation_prompt 让主脑只说 "a SINGLE concluding sentence", ZH 翻译只覆盖
    最后一句, 早 EN1+EN2 永远没 ZH 字幕. Sir 痛点: 中文字幕缺一半.

  BUG 2 (β.5.21-B): Sir 说 "阅读你的架构" → Jarvis "I shall review the alignment
    module and the architectural files to provide a more refined summary" 但 emit
    NO <FAST_CALL>, 没真读, 没下文. 言行不一. PERSONA β.2.8.13 FORBIDDEN list 只列
    dim/mute/lock/close/launch 系统控制词, 没含 review/look at/check/examine/read.

  BUG 3 (β.5.21-C): Sir 说 "我去睡觉了, 明天聊吧" → Jarvis "I shall continue my
    analysis of the architectural files while you rest" + 中文 "我会继续分析架构
    文件" — Jarvis 没后台异步任务机制, 这是绝对说谎.

修法:
  β.5.21-A: jarvis_chat_bypass.py continuation_prompt 加 CHINESE SUBTITLE COVERAGE
    指令 — ZH 必须覆盖 fast_call 前后整轮 EN.
  β.5.21-B: jarvis_central_nerve.py PERSONA 段加 FORBIDDEN list 扩 review/check/
    look at/examine/read/查阅/阅读 等读取动词 + 强制 emit FAST_CALL or 改口.
  β.5.21-C: PERSONA 段加 FORBIDDEN: 异步/后台/Sir 睡觉期间继续做的承诺 (Jarvis
    没那个能力, 不演戏).

测点 (静态扫源码 — Sir 准则 5 不写"PERSONA 文字真生效"主观测试, 只测约束在源码):
  1. continuation_prompt 含 'CHINESE SUBTITLE COVERAGE' 关键字
  2. continuation_prompt 含 'must cover EVERYTHING' / 'BEFORE the <FAST_CALL>' 提示
  3. PERSONA 含 'β.5.21-B' marker + review/look at/check 等关键字
  4. PERSONA 含 'β.5.21-C' marker + 'continue my analysis' / 'while you sleep' 反例
  5. PERSONA 含 ZH FORBIDDEN '我会继续' / '在您睡觉期间' 等关键字
  6. PERSONA 含 CORRECT alternative (Sleep well + 我没有后台运行)
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def _read_normalized(path):
    """读源码并 normalize 多空格/换行 → 单空格. 给跨行字符串匹配用."""
    import re as _re
    with open(path, 'r', encoding='utf-8') as f:
        src = f.read()
    return _re.sub(r'\s+', ' ', src)


class TestBeta521AContinuationZHCoverage(unittest.TestCase):
    """[β.5.21-A] continuation_prompt ZH 覆盖整轮"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_chat_bypass.py'))

    def test_marker(self):
        self.assertIn('β.5.21-A', self.src)

    def test_continuation_prompt_zh_coverage_directive(self):
        """continuation_prompt 必须含 'CHINESE SUBTITLE COVERAGE' 指令."""
        self.assertIn('CHINESE SUBTITLE COVERAGE', self.src,
            'continuation_prompt 必须含 CHINESE SUBTITLE COVERAGE 关键字')

    def test_continuation_prompt_must_cover_everything(self):
        """指令必须明确 'must cover EVERYTHING you spoke in this turn'."""
        self.assertIn('cover EVERYTHING', self.src)
        self.assertIn('BEFORE the <FAST_CALL>', self.src,
            '必须明确 ZH 也覆盖 fast_call 前 EN')

    def test_continuation_prompt_includes_correct_example(self):
        """正例必须给主脑看 (含 fast_call 前 + 后 EN 同时翻 ZH)."""
        self.assertIn("Example (correct):", self.src)
        # WRONG 反例引用 Sir 22:42 实测
        self.assertIn("Example (WRONG", self.src)


class TestBeta521BPersonaForbiddenReview(unittest.TestCase):
    """[β.5.21-B] PERSONA 扩 FORBIDDEN list 含 review/check/look at"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_central_nerve.py'))

    def test_marker(self):
        self.assertIn('β.5.21-B', self.src)

    def test_forbidden_list_contains_review_verbs(self):
        """FORBIDDEN 关键词列表必须含 review/check/look at/examine 等."""
        for kw in ['review', 'check', 'examine', 'inspect', 'look at',
                   'read', 'pull up', 'dig into']:
            self.assertIn(kw, self.src,
                f'FORBIDDEN list 必须含 EN 关键词 {kw!r}')

    def test_forbidden_list_contains_zh_review_verbs(self):
        """ZH FORBIDDEN 关键词必须含 查阅/阅读/查看/检查."""
        for kw in ['查阅', '阅读', '查看', '检查', '审视', '看一下']:
            self.assertIn(kw, self.src,
                f'ZH FORBIDDEN 必须含 {kw!r}')

    def test_forbidden_includes_real_negative_example(self):
        """真实反例 (Sir 01:07 实测) 必须在 PERSONA."""
        self.assertIn('I shall review', self.src,
            'Sir 01:07 反例必须在 PERSONA')
        self.assertIn('alignment module', self.src,
            'Sir 实测原话必须保留作训练 anchor')

    def test_correct_alternative_present(self):
        """正例 'Let me pull the X' + FAST_CALL 必须在."""
        self.assertIn("Let me pull", self.src)
        self.assertIn('text_hands.read', self.src)


class TestBeta521CPersonaForbiddenAsyncBackgroundPromise(unittest.TestCase):
    """[β.5.21-C] PERSONA FORBIDDEN: 异步/后台/Sir 睡觉期间继续做的承诺"""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_central_nerve.py'))

    def test_marker(self):
        self.assertIn('β.5.21-C', self.src)

    def test_absolute_lie_explanation(self):
        """PERSONA 必须明确 'Jarvis 没有后台异步任务机制' 这是 ABSOLUTE LIE."""
        self.assertIn('ABSOLUTE LIE', self.src,
            '必须明确异步承诺是绝对说谎')
        self.assertIn('no background worker', self.src,
            'PERSONA 必须解释没后台 worker')

    def test_forbidden_continue_my_analysis(self):
        """Sir 01:12 实测原话 'continue my analysis' 必须在 FORBIDDEN list (跨行可)."""
        norm = _read_normalized(os.path.join(ROOT, 'jarvis_central_nerve.py'))
        self.assertIn('continue my analysis', norm,
            'Sir 01:12 反例 continue my analysis 必须保留 (允许跨行)')

    def test_forbidden_while_you_rest(self):
        """'while you rest/sleep/are away' 必须在 FORBIDDEN list."""
        for phrase in ['while you', 'rest', 'sleep', 'are away']:
            self.assertIn(phrase, self.src,
                f'FORBIDDEN 必须含 {phrase!r}')

    def test_forbidden_zh_continue(self):
        """ZH '我会继续' / '在您睡觉/休息期间' 必须在 FORBIDDEN list."""
        self.assertIn('我会继续', self.src)
        self.assertIn('在您', self.src)

    def test_forbidden_background_terms(self):
        """'in the background' / 'behind the scenes' / 'overnight' 必须在."""
        self.assertIn('in the background', self.src)

    def test_correct_alternative_no_overnight_promise(self):
        """正例必须给主脑: 'Sleep well, Sir. I'll be here when you wake.'"""
        self.assertIn("I'll be here when you wake", self.src,
            "正例必须给 'Sleep well + I'll be here' 替代")
        self.assertIn('我就在这等您', self.src,
            "ZH 正例必须给 '我就在这等您'")

    def test_correct_alternative_decline_overnight_work(self):
        """如果 Sir 真请求过夜工作, 必须诚实 decline."""
        self.assertIn("I don't run analyses in the background", self.src)
        self.assertIn('我没有后台运行的能力', self.src,
            'ZH 必须有 decline 模板 "我没有后台运行的能力"')


class TestBeta521IntegrityCharter(unittest.TestCase):
    """[β.5.21] 整体: 准则 5 整合性 — Sir 实测 3 截图都被 PERSONA 覆盖"""

    def test_all_three_real_examples_in_persona(self):
        """3 次 Sir 实测原话必须都在 PERSONA 作 training anchor (允许跨行)."""
        norm = _read_normalized(os.path.join(ROOT, 'jarvis_central_nerve.py'))
        # β.2.8.13 (老案例)
        self.assertIn('I shall dim the displays', norm,
            'β.2.8.13 反例 I shall dim 必须保留')
        # β.5.21-B (Sir 01:07)
        self.assertIn('I shall review', norm,
            'β.5.21-B 反例 I shall review 必须存在')
        # β.5.21-C (Sir 01:12)
        self.assertIn('continue my analysis', norm,
            'β.5.21-C 反例 continue my analysis 必须存在')


if __name__ == '__main__':
    unittest.main(verbosity=2)
