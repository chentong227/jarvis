# -*- coding: utf-8 -*-
"""[Sir 2026-05-26 20:21 真测追根 BUG 治本] 两类 regression test.

源 BUG (Sir 真测 turn 20260526_202056_de33):
  BUG-A: [Bilingual/Truncated] false positive — ZH=76ch / EN=216ch = 35%
         < ratio 0.4 触发 truncate, 但 ends_ok=True (末尾 '。') 明明完整,
         还误触 worker 补一次字幕给 Sir.
  BUG-B: InnerThought 输出 "I noticed I've been fixating..." casual 口气
         不像 butler — 真根因 system prompt 没引 JARVIS_CORE_PERSONA,
         思考层人设和主脑分裂.

治本 (准则 8 优雅 > 最简):
  A: jarvis_chat_bypass.py 删 ratio 0.4 elif (ends_ok 已是 LLM 完成的强证据).
  B: jarvis_inner_thought_daemon.py _build_prompt lazy import PERSONA →
     拼到 system 开头 + THOUGHT 调性改 "first-person but JARVIS-voice".
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(name: str) -> str:
    with open(os.path.join(ROOT, name), 'r', encoding='utf-8') as f:
        return f.read()


# ==========================================================================
# BUG-A: [Bilingual/Truncated] false positive — ratio 0.4 elif 误伤
# ==========================================================================
class TestBugATruncateFalsePositive(unittest.TestCase):
    """复现 chat_bypass _stream_main 里的 truncate detection 逻辑.

    源逻辑 ~line 4498-4514. 这里复现核心条件 (3 elif 链) 验证修后行为.
    """

    @staticmethod
    def _detect(en_net: str, zh_clean: str) -> bool:
        """复现 chat_bypass truncate detection (修后)."""
        zh_endings = set('.?!。？！…')
        _zh_truncated = False
        if en_net and len(en_net) >= 30:
            if not zh_clean:
                _zh_truncated = True
            elif zh_clean[-1] not in zh_endings:
                _zh_truncated = True
            # 🆕 删 ratio elif (准则 8 优雅, ends_ok 已是强证据)
        return _zh_truncated

    def test_ends_ok_short_ratio_not_truncated(self):
        """Sir 真测场景: ZH=76ch / EN=216ch = 35% 但末尾 '。' → 不该 truncate."""
        en = ('I was monitoring your hydration levels, Sir. You have been quite '
              'absorbed in your work, and you were trailing behind your daily '
              'target of 3000 ml. I have updated your progress to 1500 ml '
              'following your recent intake.')
        zh = ('我刚才在监测您的水分摄入情况，先生。您一直沉浸在工作中，'
              '进度落后于每日 3000 毫升的目标。根据您刚才的反馈，'
              '我已经将进度更新至 1500 毫升。')
        # 前提 sanity: ZH/EN ratio < 0.4 + 末尾收束 (Sir 真测场景的核心特征)
        self.assertTrue(len(en) >= 30, '前提: EN 足够长触发 detection')
        self.assertTrue(len(zh) < len(en) * 0.4,
                         '前提: ZH/EN ratio < 0.4 (Sir 真测 35%)')
        self.assertEqual(zh[-1], '。', '前提: ZH 末尾收束 (ends_ok=True)')
        self.assertFalse(
            self._detect(en, zh),
            'ends_ok=True 时不该判 truncate (准则 8: ratio 太严误伤)',
        )

    def test_no_zh_still_truncated(self):
        """完全没 ZH → 仍应判 truncate (强证据)."""
        en = 'This is a long English reply with more than 30 characters total.'
        self.assertTrue(self._detect(en, ''))

    def test_zh_mid_sentence_still_truncated(self):
        """末尾不收束 (LLM stop 半途) → 仍应判 truncate."""
        en = 'This is a long English reply with more than 30 characters total.'
        zh_partial = '这是一段被截断的中文翻译, 末尾没有标点'
        self.assertFalse(zh_partial.endswith(tuple('.?!。？！…')))
        self.assertTrue(self._detect(en, zh_partial))

    def test_short_en_below_threshold_skip(self):
        """EN < 30ch → 不检 truncate (本身就是 short reply)."""
        en = 'Yes.'
        self.assertFalse(self._detect(en, ''))

    def test_source_ratio_elif_removed(self):
        """source 不应再含 'len(_zh_clean) < len(_en_net) * 0.4' 的 elif 判定."""
        src = _read('jarvis_chat_bypass.py')
        # 注释里可以提 0.4 (历史追因), 但不应该有可执行的 elif 条件
        # 用 regex 抓 elif 开头的 ratio 条件 (排除注释)
        for line in src.split('\n'):
            stripped = line.strip()
            if stripped.startswith('#'):
                continue
            if 'len(_zh_clean)' in line and 'len(_en_net)' in line and '0.4' in line:
                self.fail(
                    f'ratio 0.4 elif 应该已删 (修法准则 8 优雅), 但找到: {line!r}')

    def test_source_keeps_ends_ok_check(self):
        """source 仍应保留 ends_ok (末尾收束) 检查 — 这是修后保留的核心."""
        src = _read('jarvis_chat_bypass.py')
        # 找 _zh_endings 集合 + elif 末尾不收束
        self.assertIn('_zh_endings = set', src,
                       '_zh_endings 集合必须保留')
        self.assertIn('_zh_clean[-1] not in _zh_endings', src,
                       '末尾不收束 elif 必须保留 (强证据 truncate)')


# ==========================================================================
# BUG-B: InnerThought system prompt 缺 JARVIS_CORE_PERSONA → 人设分裂
# ==========================================================================
class TestBugBInnerThoughtPersonaAlignment(unittest.TestCase):
    """验 InnerThought _build_prompt system 引入 PERSONA, 思考也守 butler 人设."""

    def setUp(self):
        from jarvis_inner_thought_daemon import InnerThoughtDaemon
        self.daemon = InnerThoughtDaemon(
            key_router=MagicMock(),
            concerns_ledger=None,
            relational_state=None,
        )

    def test_system_prompt_contains_jarvis_persona_identity(self):
        """system 必须含 JARVIS_CORE_PERSONA 的核心 identity (主脑同款)."""
        sys_p, _ = self.daemon._build_prompt('active', {})
        # 关键 PERSONA 标记 (jarvis_central_nerve.JARVIS_CORE_PERSONA 真有)
        self.assertIn('J.A.R.V.I.S.', sys_p,
                       'system 必须含 JARVIS 身份')
        self.assertIn('butler', sys_p.lower(),
                       'system 必须含 butler 身份 (主脑一致人设)')
        # PERSONA 里的 immutable trait — composed / loyal / Sir
        self.assertIn('Sir', sys_p, 'system 必须 reference Sir')

    def test_system_prompt_contains_integrity_clause(self):
        """system 必须含 INTEGRITY 准则 (思考层也要言出必行)."""
        sys_p, _ = self.daemon._build_prompt('active', {})
        # PERSONA 含 'INTEGRITY' 大写
        self.assertIn('INTEGRITY', sys_p,
                       'system 必须含 INTEGRITY 段 (思考层也守 claim honesty)')

    def test_system_prompt_inner_monologue_mode_marker(self):
        """system 必须含 INNER MONOLOGUE MODE 标记 (private mental note 桥接)."""
        sys_p, _ = self.daemon._build_prompt('active', {})
        self.assertIn('INNER MONOLOGUE MODE', sys_p,
                       'system 必须含 INNER MONOLOGUE MODE 标记 (PERSONA → 思考桥)')
        self.assertIn('private', sys_p.lower(),
                       'system 必须强调 private (Sir 看不到这条)')

    def test_system_prompt_no_casual_self_talk_phrase(self):
        """THOUGHT 调性改成 JARVIS-voice, 不再用 'casual self-talk'."""
        sys_p, _ = self.daemon._build_prompt('active', {})
        # 旧 prompt 含 "casual self-talk, NOT formal speech to Sir" (BUG-B 根因)
        self.assertNotIn('casual self-talk', sys_p,
                          'casual self-talk 调性应已废 (Sir 真痛 — 人设怪)')
        # 新 prompt 应有 JARVIS-voice
        self.assertIn('JARVIS-voice', sys_p,
                       'system THOUGHT 调性应改成 JARVIS-voice')

    def test_system_prompt_keeps_5_categories_and_format(self):
        """改 PERSONA 后不应破坏原有 5 类 + 5 tag output format."""
        sys_p, _ = self.daemon._build_prompt('active', {})
        # 5 类标签全保留
        for tag in ('OBSERVATION', 'SELF-REFLECT', 'CONCERN-EVOLUTION',
                     'PROACTIVE-SEED', 'RELATIONSHIP'):
            self.assertIn(tag, sys_p, f'5 类标签 {tag} 必须保留')
        # 5 个 output tag 全保留 (CATEGORY/THOUGHT/SALIENCE/ACTIONABLE/EVIDENCE_LINK)
        for tag in ('<CATEGORY>', '<THOUGHT>', '<SALIENCE>',
                     '<ACTIONABLE>', '<EVIDENCE_LINK>'):
            self.assertIn(tag, sys_p, f'output tag {tag} 必须保留')

    def test_lazy_import_persona_fallback_safe(self):
        """PERSONA import fail → fallback 空字符串, 不阻塞 thought 生成."""
        # 模拟: 用 monkey patch 把 JARVIS_CORE_PERSONA 模块级 attr 删除
        import jarvis_central_nerve as _jcn
        original = getattr(_jcn, 'JARVIS_CORE_PERSONA', None)
        try:
            if hasattr(_jcn, 'JARVIS_CORE_PERSONA'):
                del _jcn.JARVIS_CORE_PERSONA
            # 重新调 _build_prompt — 应能 fallback (空 PERSONA, 但格式还在)
            sys_p, _ = self.daemon._build_prompt('active', {})
            # 即便 PERSONA 没了, INNER MONOLOGUE MODE + 5 类 + 5 tag 必须还在
            self.assertIn('INNER MONOLOGUE MODE', sys_p,
                           'PERSONA fail 时, INNER MONOLOGUE 段仍必须在 (fallback 安全)')
            self.assertIn('<CATEGORY>', sys_p, 'output format 仍必须在')
        finally:
            if original is not None:
                _jcn.JARVIS_CORE_PERSONA = original


if __name__ == '__main__':
    unittest.main()
