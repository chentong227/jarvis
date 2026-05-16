# -*- coding: utf-8 -*-
"""[P0+20-β.2.3 / 2026-05-16] 灵魂工程 Layer 3 测试

Layer 3 — Attention Allocation (jarvis_attention.py)
- classify_input: 启发式分类 user_input
- is_short_input: 短输入判定
- build_attention_block: 主入口 — 综合 concerns + relational + user_input

详 docs/JARVIS_SOUL_DRIVE.md §2.2（Layer 3）+ §3.4
"""
import os
import sys
import time
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_attention import (
    classify_input,
    is_short_input,
    build_attention_block,
    _top_concerns,
    _top_unfinished,
)

from jarvis_concerns import (
    Concern, ConcernsLedger, STATE_ACTIVE,
)
from jarvis_relational import (
    RelationalStateStore, InsideJoke, UnfinishedBusiness,
    UB_OPEN,
)


# ============================================================
# A. classify_input
# ============================================================
class TestClassifyInput(unittest.TestCase):

    def test_empty_is_silence(self):
        self.assertEqual(classify_input(''), 'silence')
        self.assertEqual(classify_input('   '), 'silence')

    def test_english_question(self):
        for q in ['Why did this fail?', 'How long until?',
                  "what's the time", 'when does it start']:
            self.assertEqual(classify_input(q), 'question', f"{q!r}")

    def test_chinese_question(self):
        for q in ['为什么', '现在几点了？', '这是什么', '怎么办']:
            self.assertEqual(classify_input(q), 'question', f"{q!r}")

    def test_english_request(self):
        for r in ['Please open D drive', 'help me find that file',
                  'Open Cursor', 'Remind me in 5 min', 'Find foo.txt',
                  'Search for X']:
            self.assertEqual(classify_input(r), 'request', f"{r!r}")

    def test_chinese_request(self):
        for r in ['帮我打开 D 盘', '请提醒我 8 点起床', '播放音乐']:
            self.assertEqual(classify_input(r), 'request', f"{r!r}")

    def test_commitment(self):
        for c in ["I'll go to bed early", 'I will quit smoking', 'I promise',
                  '我会早睡', '我打算戒烟', '我答应']:
            self.assertEqual(classify_input(c), 'commitment', f"{c!r}")

    def test_continuation(self):
        for c in ['Actually, wait', 'Also one more thing', '对了, 我还想问',
                  '另外，那个项目']:
            self.assertEqual(classify_input(c), 'continuation', f"{c!r}")

    def test_chat_default(self):
        self.assertEqual(classify_input('hello there'), 'chat')
        self.assertEqual(classify_input('mmm interesting'), 'chat')


class TestIsShortInput(unittest.TestCase):

    def test_empty_is_short(self):
        self.assertTrue(is_short_input(''))
        self.assertTrue(is_short_input('   '))

    def test_few_words_is_short(self):
        self.assertTrue(is_short_input('yes'))
        self.assertTrue(is_short_input('Jarvis'))

    def test_long_is_not_short(self):
        self.assertFalse(is_short_input(
            'Could you explain how the build pipeline works in detail?'
        ))


# ============================================================
# B. _top_concerns / _top_unfinished
# ============================================================
class TestTopHelpers(unittest.TestCase):

    def test_top_concerns_empty(self):
        self.assertEqual(_top_concerns(None), [])
        self.assertEqual(_top_concerns(ConcernsLedger()), [])

    def test_top_concerns_sorted_by_severity(self):
        ledger = ConcernsLedger()
        ledger.register(Concern(id='low', what_i_watch='X', why_i_care='Y',
                                severity=0.1))
        ledger.register(Concern(id='mid', what_i_watch='X', why_i_care='Y',
                                severity=0.5))
        ledger.register(Concern(id='high', what_i_watch='X', why_i_care='Y',
                                severity=0.9))
        out = _top_concerns(ledger, top_n=2)
        self.assertEqual(out[0]['id'], 'high')
        self.assertEqual(out[1]['id'], 'mid')

    def test_top_unfinished_empty(self):
        """_top_unfinished 仍可用作 helper（API 保留），但 build_attention_block 不再用它。"""
        self.assertEqual(_top_unfinished(None), [])

    def test_top_unfinished_overdue_first(self):
        """helper 仍工作（API 保留），但 attention 块不再注入 unfinished。"""
        store = RelationalStateStore(
            persist_path=tempfile.mktemp(suffix='.json')
        )
        store.add_unfinished(UnfinishedBusiness(id='normal', topic='X'))
        store.add_unfinished(UnfinishedBusiness(
            id='overdue', topic='Y', next_touch_due=time.time() - 100
        ))
        out = _top_unfinished(store, top_n=2)
        self.assertEqual(out[0]['id'], 'overdue')
        self.assertTrue(out[0]['overdue'])


# ============================================================
# C. build_attention_block
# ============================================================
class TestBuildAttentionBlock(unittest.TestCase):

    def setUp(self):
        self.ledger = ConcernsLedger()
        self.store = RelationalStateStore(
            persist_path=tempfile.mktemp(suffix='.json')
        )

    def test_all_empty_returns_empty(self):
        out = build_attention_block(
            concerns_ledger=None,
            relational_state=None,
            user_input='',
        )
        self.assertEqual(out, '')

    def test_with_concerns_only(self):
        self.ledger.register(Concern(
            id='c1', what_i_watch='sleep', why_i_care='health', severity=0.5
        ))
        out = build_attention_block(
            concerns_ledger=self.ledger,
            relational_state=None,
            user_input='',
        )
        self.assertIn('ATTENTION RIGHT NOW', out)
        self.assertIn('LONG-TERM WATCH', out)
        self.assertIn('c1', out)

    def test_with_unfinished_only_no_pending_section(self):
        """[β.2.3 / 2026-05-16] Layer 3 不再注入 PENDING FOLLOWUPS（Layer 2
        BETWEEN US 块的 UNFINISHED BUSINESS 段单源接管）。仅 unfinished 时
        没 concerns / 没 user_input → 整体返回空。"""
        self.store.add_unfinished(UnfinishedBusiness(
            id='u1', topic='driver license test'
        ))
        out = build_attention_block(
            concerns_ledger=None,
            relational_state=self.store,
            user_input='',
        )
        # PENDING FOLLOWUPS 段已删
        self.assertNotIn('PENDING FOLLOWUPS', out)
        # 因为没 concerns / 没 user_input，整体应当空
        self.assertEqual(out, '')

    def test_with_user_input_long_includes_current_focus(self):
        self.ledger.register(Concern(
            id='c1', what_i_watch='X', why_i_care='Y', severity=0.5
        ))
        out = build_attention_block(
            concerns_ledger=self.ledger,
            relational_state=None,
            user_input='Could you walk me through how Cursor build works',
        )
        self.assertIn('CURRENT FOCUS', out)
        self.assertIn('kind:', out)
        self.assertIn('preview:', out)
        self.assertIn('Cursor', out)

    def test_short_input_skips_current_focus(self):
        self.ledger.register(Concern(
            id='c1', what_i_watch='X', why_i_care='Y', severity=0.5
        ))
        out = build_attention_block(
            concerns_ledger=self.ledger,
            relational_state=None,
            user_input='Yes',
        )
        self.assertNotIn('CURRENT FOCUS', out)
        self.assertIn('LONG-TERM WATCH', out)

    def test_max_chars_truncates(self):
        for i in range(20):
            self.ledger.register(Concern(
                id=f'c{i}', what_i_watch=f'watch {i} which is moderately long',
                why_i_care='reason', severity=0.5
            ))
        out = build_attention_block(
            concerns_ledger=self.ledger,
            relational_state=None,
            user_input='Could you explain this in great detail please',
            top_concerns=10,
            max_chars=200,
        )
        self.assertLessEqual(len(out), 200)

    def test_overdue_unfinished_does_not_appear_in_attention(self):
        """[β.2.3 / 2026-05-16] PENDING FOLLOWUPS 已删，OVERDUE 标也不会出现
        在 attention 块。Layer 2 BETWEEN US.UNFINISHED BUSINESS 段单源标 OVERDUE。"""
        self.store.add_unfinished(UnfinishedBusiness(
            id='u1', topic='driver license test',
            next_touch_due=time.time() - 3600
        ))
        out = build_attention_block(
            concerns_ledger=None,
            relational_state=self.store,
            user_input='',
        )
        self.assertNotIn('OVERDUE', out)
        self.assertNotIn('PENDING FOLLOWUPS', out)

    def test_two_sections_when_focus_and_concerns(self):
        """[β.2.3 / 2026-05-16] Layer 3 现在最多两段：CURRENT FOCUS + LONG-TERM WATCH。"""
        self.ledger.register(Concern(
            id='c1', what_i_watch='X', why_i_care='Y', severity=0.7
        ))
        self.store.add_unfinished(UnfinishedBusiness(id='u1', topic='study'))
        out = build_attention_block(
            concerns_ledger=self.ledger,
            relational_state=self.store,
            user_input='Could you explain how this works in detail',
        )
        self.assertIn('CURRENT FOCUS', out)
        self.assertIn('LONG-TERM WATCH', out)
        self.assertNotIn('PENDING FOLLOWUPS', out)


# ============================================================
# D. 集成测试 — central_nerve 注入路径 (不真起 nerve，只验 prompt 拼接顺序)
# ============================================================
class TestIntegrationOrder(unittest.TestCase):
    """验证 Layer 0/1/2/3 顺序在 prompt 里正确：
        SelfAnchor → Concerns → Relational → Attention
    """

    def test_layer_block_order(self):
        ledger = ConcernsLedger()
        ledger.register(Concern(
            id='c1', what_i_watch='X', why_i_care='Y', severity=0.5
        ))
        store = RelationalStateStore(
            persist_path=tempfile.mktemp(suffix='.json')
        )
        store.add_inside_joke(InsideJoke(id='j1', phrase='joke X', tone='dry'))
        store.add_unfinished(UnfinishedBusiness(id='u1', topic='study'))

        # Layer 1 / 2 / 3 块
        l1 = ledger.to_prompt_block()
        l2 = store.to_prompt_block()
        l3 = build_attention_block(
            concerns_ledger=ledger,
            relational_state=store,
            user_input='Could you explain in some detail',
        )

        self.assertIn('MY SELF / SOUL', l1)
        self.assertIn('BETWEEN US', l2)
        self.assertIn('ATTENTION RIGHT NOW', l3)

        # [β.2.3 / 2026-05-16] 验证 Layer 2/3 内部去重：
        # Layer 2 含 UNFINISHED BUSINESS 段（study 应该出现在这里）
        self.assertIn('UNFINISHED BUSINESS', l2)
        self.assertIn('study', l2)
        # Layer 3 不再含 PENDING FOLLOWUPS 或重复 unfinished 内容
        self.assertNotIn('PENDING FOLLOWUPS', l3)
        self.assertNotIn('study', l3)

        combined = '\n\n'.join([l1, l2, l3])
        i1 = combined.find('MY SELF / SOUL')
        i2 = combined.find('BETWEEN US')
        i3 = combined.find('ATTENTION RIGHT NOW')
        self.assertGreater(i2, i1)
        self.assertGreater(i3, i2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
