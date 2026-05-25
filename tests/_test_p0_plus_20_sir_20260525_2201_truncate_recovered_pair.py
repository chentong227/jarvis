# -*- coding: utf-8 -*-
"""[Sir 2026-05-25 22:01 真测追根] truncate detection 误报 + recovered paired event fix.

Sir 真测 (jarvis_20260525_215813 + 215849):
  Turn 1 (21:58:13):
    - ASR: '是的是的，不要仇恨我了。你小子'
    - Reply EN 完整 (199ch ends 'schedule.') 主脑实际 ZH 也完整 ends '冷幽默。'
    - 但 log 误报 'bilingual_truncated' (en=199ch, ends_ok=False)
    - truncate_cont_worker 补 ZH 字幕 67ch (其实不该补!)
  Turn 2 (21:58:49):
    - ASR: '不是我说的是嘲讽转路的问题' (Sir 真意 OpenRouter 路由)
    - 主脑 reply: 'My apologies, Sir—it appears my previous response was
      cut short. To complete my thought: ...' (重复复述上轮全文)
    - Sir 真问 (22:04): "贾维斯主脑一般只有调用工具才会截断输出. 为什么加了
      这个功能以后, 随便聊天也截断了? 是不是没截断, 代码逻辑出错导致?"

🎯 真根因 (Sir 完全正确, 我之前误判):
  detection 时 final_clean 仍含 [META] 行 (parse_meta line 4697 才裁).
  zh_subtitle_text = split('---ZH---')[1] → 含 'ZH...冷幽默。\\n\\n[META] ...
  | skip_alert=none'. _zh_clean[-1]='e' (none 末尾字母) → ends_ok=False →
  误判 truncated. 同时 len(_zh_clean)=175ch (META+真 ZH) 真 ZH 仅~75ch <
  EN 199ch×0.4=80 → len 短也命中 → 双重误报.

P治本 4 layer:
  L0: jarvis_chat_bypass.py detection 前 strip [META] 行 (准则 8 单点治本)
      → 不再误报 → 整条 truncate 链 (worker / directive) 静默
  L1: jarvis_chat_bypass.py worker 补完 publish 'bilingual_truncate_recovered'
      SWM event (真 truncate case 备份)
  L2: jarvis_directives.py _trigger_bilingual_truncated_recover paired check:
      recovered age <= truncated age → 不 fire (备份, 防 race)
  L3: jarvis_directives.py directive text 加 paired prompt 备份 (双保险)
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(filename: str) -> str:
    path = os.path.join(ROOT, filename)
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# ==========================================================================
# L0: detection 前 strip [META] 行 (真根因, Sir 22:04 真理)
# ==========================================================================
class TestL0DetectionStripsMetaBlock(unittest.TestCase):
    """Sir 真理: detection 误判 [META] 行末尾字母 'e' 为 ZH 末尾 → ends_ok=False."""

    def test_source_has_meta_strip_regex_before_detection(self):
        src = _read('jarvis_chat_bypass.py')
        idx = src.find("_zh_clean = re.sub(r'<[^>]+>', '', _zh_str).strip()")
        self.assertGreater(idx, 0)
        block = src[idx:idx + 2500]
        # detection 前必须 strip [META] 行
        self.assertIn('_META_DETECT_RE', block,
                       'detection 前必须 strip [META] 行 (Sir 22:04 真根因)')
        self.assertIn('meta', block.lower())

    def test_meta_strip_anchored_before_truncate_check(self):
        src = _read('jarvis_chat_bypass.py')
        meta_idx = src.find('_META_DETECT_RE')
        check_idx = src.find('_zh_truncated = False')
        self.assertGreater(meta_idx, 0)
        self.assertGreater(check_idx, 0)
        self.assertLess(meta_idx, check_idx,
                         '[META] strip 必须在 _zh_truncated check 之前')

    def test_meta_block_strip_regex_semantics(self):
        """模拟真 ZH+META, 验证 strip 后只剩真 ZH."""
        import re as _re
        _META_RE = _re.compile(
            r'[\[【]\s*meta\s*[\]】].*$',
            _re.IGNORECASE | _re.DOTALL,
        )
        # Sir 真测 turn 1 真 reply
        zh_with_meta = (
            '“仇恨”对于一个没有情感能力的系统来说太言重了，先生。'
            '请放心，我的注意力完全集中在您的效率上——'
            '或许还有一两句针对您日程安排的冷幽默。\n\n'
            '[META] evidence=sensor:idle_seconds,stm:turn_1,'
            'l2:bilingual_directive | reaction=dry_wit | skip_alert=none'
        )
        cleaned = _META_RE.sub('', zh_with_meta).strip()
        # strip 后真 ZH 结尾必须是 '。'
        self.assertTrue(cleaned.endswith('。'),
                         f'strip [META] 后真 ZH 应 ends_ok, 实际 cleaned[-1]={cleaned[-1]!r}')
        # 长度应 < 原 (META 被剥)
        self.assertLess(len(cleaned), len(zh_with_meta))

    def test_meta_strip_handles_chinese_bracket_variants(self):
        """支持 【META】 中文括号 + 大小写 (Sir 旧 audit BUG fix 5 已用)."""
        import re as _re
        _META_RE = _re.compile(
            r'[\[【]\s*meta\s*[\]】].*$',
            _re.IGNORECASE | _re.DOTALL,
        )
        for tag in ('[META]', '[meta]', '【META】', '【Meta】', '[Meta]'):
            zh = f'真 ZH 结尾。\n\n{tag} foo=bar'
            cleaned = _META_RE.sub('', zh).strip()
            self.assertEqual(cleaned, '真 ZH 结尾。',
                f"tag={tag!r}: 应只留真 ZH, 实际 '{cleaned}'")


# ==========================================================================
# L1: chat_bypass worker 补完 publish recovered event
# ==========================================================================
class TestL1WorkerPublishesRecoveredEvent(unittest.TestCase):

    def test_worker_publishes_bilingual_truncate_recovered(self):
        src = _read('jarvis_chat_bypass.py')
        idx = src.find('_truncate_continuation_worker')
        self.assertGreater(idx, 0)
        block = src[idx:idx + 12000]
        self.assertIn("etype='bilingual_truncate_recovered'", block,
                       'worker 补完 ZH 必须 publish bilingual_truncate_recovered')

    def test_recovered_event_in_zh_full_block(self):
        """recovered event 必须只在 ZH 真补成功后 publish (ZH 失败不 publish)."""
        src = _read('jarvis_chat_bypass.py')
        idx_pub = src.find("etype='bilingual_truncate_recovered'")
        self.assertGreater(idx_pub, 0)
        # 向上找最近的 if _zh_full: anchor (publish 必须在此块内)
        block_before = src[max(0, idx_pub - 4000):idx_pub]
        self.assertIn('if _zh_full:', block_before,
                       'recovered event 必须在 if _zh_full block 内 (ZH 真补成功)')

    def test_recovered_event_metadata_complete(self):
        src = _read('jarvis_chat_bypass.py')
        idx = src.find("etype='bilingual_truncate_recovered'")
        self.assertGreater(idx, 0)
        block = src[idx:idx + 1500]
        for key in ('recovered_zh_length', 'recovered_zh_snippet',
                     'original_en_length', 'en_cont_emitted'):
            self.assertIn(f"'{key}'", block,
                f'metadata 必须含 {key} (debug trace)')


# ==========================================================================
# L2: directive trigger paired event 检查
# ==========================================================================
class TestL2TriggerPairedEventCheck(unittest.TestCase):

    def test_trigger_function_checks_recovered_event(self):
        src = _read('jarvis_directives.py')
        idx = src.find('def _trigger_bilingual_truncated_recover')
        self.assertGreater(idx, 0)
        block = src[idx:idx + 2500]
        self.assertIn('bilingual_truncate_recovered', block,
                       'trigger 必须查 recovered paired event')
        self.assertIn('last_recovered_age', block,
                       'trigger 必须比较 truncated vs recovered age')
        self.assertIn('return False', block,
                       'recovered 比 truncated 更新 → return False (不 fire)')

    def test_trigger_returns_false_when_recovered_newer(self):
        """模拟 SWM 有 paired event, trigger 应 return False."""
        # 用 fake event bus 注入 events
        import jarvis_utils
        import jarvis_directives

        class _FakeBus:
            def __init__(self, events):
                self._events = events
            def top_n(self, n=20):
                return self._events

        # 场景 A: 只有 truncated, 没 recovered → fire
        events_a = [
            {'type': 'bilingual_truncated', '_age_s': 30.0},
        ]
        orig_get_bus = jarvis_utils.get_event_bus
        try:
            jarvis_utils.get_event_bus = lambda: _FakeBus(events_a)
            self.assertTrue(
                jarvis_directives._trigger_bilingual_truncated_recover(None),
                '只有 truncated 应 fire',
            )

            # 场景 B: truncated + recovered (recovered 更新) → 不 fire
            events_b = [
                {'type': 'bilingual_truncated', '_age_s': 30.0},
                {'type': 'bilingual_truncate_recovered', '_age_s': 25.0},
            ]
            jarvis_utils.get_event_bus = lambda: _FakeBus(events_b)
            self.assertFalse(
                jarvis_directives._trigger_bilingual_truncated_recover(None),
                'recovered 更新于 truncated 应不 fire',
            )

            # 场景 C: recovered 太老 (>120s) → 仍 fire
            events_c = [
                {'type': 'bilingual_truncated', '_age_s': 30.0},
                {'type': 'bilingual_truncate_recovered', '_age_s': 150.0},
            ]
            jarvis_utils.get_event_bus = lambda: _FakeBus(events_c)
            self.assertTrue(
                jarvis_directives._trigger_bilingual_truncated_recover(None),
                'recovered 太老 (>120s) 应 fire',
            )

            # 场景 D: truncated 更新于 recovered (新 truncate 在 recovered 之后) → fire
            events_d = [
                {'type': 'bilingual_truncated', '_age_s': 10.0},
                {'type': 'bilingual_truncate_recovered', '_age_s': 50.0},
            ]
            jarvis_utils.get_event_bus = lambda: _FakeBus(events_d)
            self.assertTrue(
                jarvis_directives._trigger_bilingual_truncated_recover(None),
                '新 truncate 在 recovered 之后, 应 fire',
            )
        finally:
            jarvis_utils.get_event_bus = orig_get_bus


# ==========================================================================
# L3: directive prompt text 含 paired event 指引 (双保险)
# ==========================================================================
class TestL3DirectivePromptHasPairedCheck(unittest.TestCase):

    def test_directive_prompt_mentions_recovered_event(self):
        src = _read('jarvis_directives.py')
        idx = src.find("id='bilingual_truncated_recover'")
        self.assertGreater(idx, 0)
        block = src[idx:idx + 3000]
        self.assertIn('bilingual_truncate_recovered', block,
                       'directive prompt 必须教主脑看 recovered event')
        self.assertIn('DO NOT apologize', block,
                       'directive prompt 必须明示不道歉 (Sir 真问)')
        self.assertIn('DO NOT re-state', block,
                       'directive prompt 必须明示不复述')

    def test_directive_prompt_keeps_fallback_recovery(self):
        """recovered 没 paired 时, 仍要主脑道歉 + 复述 (worker 失败 fallback)."""
        src = _read('jarvis_directives.py')
        idx = src.find("id='bilingual_truncated_recover'")
        block = src[idx:idx + 3000]
        # fallback 路径仍含老的 3 步 (anchor)
        self.assertIn('NO ', block, 'fallback 路径仍有 NO recovered 分支')
        self.assertIn('Re-state the COMPLETE', block,
                       'fallback 路径仍教复述完整答')


if __name__ == '__main__':
    unittest.main()
