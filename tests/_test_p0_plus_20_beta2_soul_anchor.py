# -*- coding: utf-8 -*-
"""[P0+20-β.2.0 + β.2.1 / 2026-05-16] 灵魂工程 Layer 0+1 测试

Layer 0 — SelfAnchor (jarvis_self_anchor.py)
Layer 1 — Concerns (jarvis_concerns.py)

详 docs/JARVIS_SOUL_DRIVE.md
"""
import os
import sys
import time
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_self_anchor import (
    SelfAnchor, get_default_self_anchor, reset_default_self_anchor_for_test,
    _derive_mood, _extract_topic,
)
from jarvis_concerns import (
    Concern, ConcernsLedger, bootstrap_default_concerns,
    get_default_ledger, reset_default_ledger_for_test,
    STATE_ACTIVE, STATE_REVIEW, STATE_ARCHIVED, STATE_SNOOZED,
)


# ============================================================
# A. SelfAnchor (Layer 0)
# ============================================================
class TestSelfAnchorBasics(unittest.TestCase):

    def setUp(self):
        reset_default_self_anchor_for_test()

    def test_init_defaults(self):
        sa = SelfAnchor()
        self.assertEqual(sa.get_turn_count(), 0)

    def test_record_turn_increments(self):
        sa = SelfAnchor()
        sa.record_turn()
        sa.record_turn()
        sa.record_turn()
        self.assertEqual(sa.get_turn_count(), 3)

    def test_build_block_has_required_sections(self):
        sa = SelfAnchor()
        sa.record_turn()
        block = sa.build_block()
        for marker in [
            'I AM J.A.R.V.I.S',
            '[WHO I AM]',
            '[MY CURRENT CONTINUITY]',
            '[MY OWN HEALTH RIGHT NOW]',
            '[REFERENT MAP',
            'session uptime',
            'turns I',
            '"you"',  # Sir 说"你"指代的解释
        ]:
            self.assertIn(marker, block, f"missing required marker: {marker}")

    def test_build_block_respects_max_chars(self):
        sa = SelfAnchor()
        block = sa.build_block(max_chars=300)
        self.assertLessEqual(len(block), 300)

    def test_build_block_length_under_900(self):
        """实际注入到 prompt 的长度应该 ≤ 900 chars"""
        sa = SelfAnchor()
        block = sa.build_block(max_chars=900)
        self.assertLessEqual(len(block), 900)

    def test_singleton_instance(self):
        a1 = get_default_self_anchor()
        a2 = get_default_self_anchor()
        self.assertIs(a1, a2)


class TestSelfAnchorHelpers(unittest.TestCase):

    def test_extract_topic_empty_stm(self):
        self.assertIn("no prior topic", _extract_topic([]))

    def test_extract_topic_with_stm(self):
        stm = [
            {'user': '今天几点了？', 'jarvis': '21:30, Sir.'},
            {'user': '我想早点睡', 'jarvis': 'I shall hold you to that.'},
        ]
        topic = _extract_topic(stm)
        # 应该包含最后一条对话的部分内容
        self.assertTrue(
            'Sir' in topic or '早' in topic or 'I replied' in topic or 'hold' in topic,
            f"topic 不含预期标识符: {topic!r}"
        )

    def test_derive_mood_healthy(self):
        health = {'dead_keys': 0, 'healthy_keys': 3, 'memory_chains': 10, 'active_concerns': 5}
        mood = _derive_mood(health, [])
        self.assertIn('steady', mood)

    def test_derive_mood_diminished(self):
        health = {'dead_keys': 2, 'healthy_keys': 1, 'memory_chains': 10}
        mood = _derive_mood(health, [])
        self.assertIn('diminished', mood)


# ============================================================
# B. Concerns Ledger (Layer 1)
# ============================================================
class TestConcernsLedgerCRUD(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
        self.tmp.close()
        self.tmp_review = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
        self.tmp_review.close()
        self.ledger = ConcernsLedger(
            persist_path=self.tmp.name,
            review_path=self.tmp_review.name,
        )

    def tearDown(self):
        for p in [self.tmp.name, self.tmp_review.name]:
            try:
                os.unlink(p)
            except Exception:
                pass

    def test_register_new_concern(self):
        c = Concern(
            id='test_c1', what_i_watch="测试", why_i_care="测试原因",
            severity=0.4, source='test'
        )
        self.assertTrue(self.ledger.register(c))
        self.assertEqual(len(self.ledger.list_all()), 1)

    def test_register_duplicate_id_rejected(self):
        c1 = Concern(id='dup', what_i_watch="w", why_i_care="y")
        c2 = Concern(id='dup', what_i_watch="w2", why_i_care="y2")
        self.assertTrue(self.ledger.register(c1))
        self.assertFalse(self.ledger.register(c2))

    def test_get_returns_none_if_missing(self):
        self.assertIsNone(self.ledger.get('nonexistent'))

    def test_record_signal_updates_severity(self):
        c = Concern(id='s1', what_i_watch="w", why_i_care="y", severity=0.3)
        self.ledger.register(c)
        ok = self.ledger.record_signal('s1', '测试信号', severity_delta=0.2)
        self.assertTrue(ok)
        self.assertAlmostEqual(self.ledger.get('s1').severity, 0.5, places=2)
        self.assertEqual(len(self.ledger.get('s1').recent_signals), 1)

    def test_record_signal_caps_at_1_and_0(self):
        c = Concern(id='cap', what_i_watch="w", why_i_care="y", severity=0.8)
        self.ledger.register(c)
        self.ledger.record_signal('cap', 's', severity_delta=0.5)
        self.assertLessEqual(self.ledger.get('cap').severity, 1.0)
        self.ledger.record_signal('cap', 's', severity_delta=-2.0)
        self.assertGreaterEqual(self.ledger.get('cap').severity, 0.0)

    def test_list_active_filters_state(self):
        self.ledger.register(Concern(id='a', what_i_watch="w", why_i_care="y", state=STATE_ACTIVE))
        self.ledger.register(Concern(id='r', what_i_watch="w", why_i_care="y", state=STATE_REVIEW))
        active = self.ledger.list_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].id, 'a')

    def test_activate_promotes_from_review(self):
        c = Concern(id='rev', what_i_watch="w", why_i_care="y", state=STATE_REVIEW)
        self.ledger.register(c)
        self.assertTrue(self.ledger.activate('rev'))
        self.assertEqual(self.ledger.get('rev').state, STATE_ACTIVE)

    def test_reject_archives(self):
        c = Concern(id='bad', what_i_watch="w", why_i_care="y", state=STATE_REVIEW)
        self.ledger.register(c)
        self.assertTrue(self.ledger.reject('bad'))
        self.assertEqual(self.ledger.get('bad').state, STATE_ARCHIVED)

    def test_persist_load_roundtrip(self):
        c = Concern(
            id='persist_test', what_i_watch="持久化", why_i_care="测试",
            severity=0.7, source='test', source_marker='test.1'
        )
        c.record_signal("信号1", severity_delta=0.1)
        self.ledger.register(c)
        self.ledger.persist()

        # 新 ledger 从 disk 加载
        ledger2 = ConcernsLedger(
            persist_path=self.tmp.name, review_path=self.tmp_review.name
        )
        n = ledger2.load()
        self.assertEqual(n, 1)
        loaded = ledger2.get('persist_test')
        self.assertIsNotNone(loaded)
        self.assertAlmostEqual(loaded.severity, 0.8, places=2)
        self.assertEqual(len(loaded.recent_signals), 1)


class TestBootstrapDefaultConcerns(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
        self.tmp.close()
        self.tmp_review = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
        self.tmp_review.close()
        self.ledger = ConcernsLedger(
            persist_path=self.tmp.name,
            review_path=self.tmp_review.name,
        )

    def tearDown(self):
        for p in [self.tmp.name, self.tmp_review.name]:
            try:
                os.unlink(p)
            except Exception:
                pass

    def test_5_seeds_registered(self):
        n = bootstrap_default_concerns(self.ledger)
        self.assertEqual(n, 5)

    def test_seeds_have_required_fields(self):
        bootstrap_default_concerns(self.ledger)
        expected_ids = {
            'sir_sleep_streak', 'sir_pomodoro_compliance', 'sir_cursor_payment',
            'unfinished_jiazhao_ke1', 'jarvis_keyrouter_health'
        }
        actual = {c.id for c in self.ledger.list_all()}
        self.assertEqual(actual, expected_ids)

    def test_seeds_all_have_why_i_care(self):
        """每条种子 concern 必须有 rationale（防止凭空 propose）"""
        bootstrap_default_concerns(self.ledger)
        for c in self.ledger.list_all():
            self.assertTrue(c.why_i_care.strip(), f"{c.id} missing why_i_care")

    def test_jarvis_self_concern_present(self):
        """关键：Jarvis 必须有'对自己的关心'，不只是对 Sir 的"""
        bootstrap_default_concerns(self.ledger)
        jarvis_c = self.ledger.get('jarvis_keyrouter_health')
        self.assertIsNotNone(jarvis_c)
        # 这条不应触发主动 nudge（只影响语气）
        self.assertFalse(jarvis_c.triggers_proactive)


class TestConcernsToPromptBlock(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
        self.tmp.close()
        self.tmp_review = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
        self.tmp_review.close()
        self.ledger = ConcernsLedger(
            persist_path=self.tmp.name,
            review_path=self.tmp_review.name,
        )
        bootstrap_default_concerns(self.ledger)

    def tearDown(self):
        for p in [self.tmp.name, self.tmp_review.name]:
            try:
                os.unlink(p)
            except Exception:
                pass

    def test_block_has_header(self):
        block = self.ledger.to_prompt_block()
        self.assertIn('MY SELF / SOUL', block)
        self.assertIn('CONCERNS', block)

    def test_block_orders_by_severity(self):
        block = self.ledger.to_prompt_block(top_n=2)
        # severity 最高的两个：jarvis_keyrouter (0.5) + sir_cursor_payment (0.4)
        self.assertIn('jarvis_keyrouter_health', block)
        self.assertIn('sir_cursor_payment', block)

    def test_block_respects_max_chars(self):
        block = self.ledger.to_prompt_block(top_n=5, max_chars=400)
        self.assertLessEqual(len(block), 400)

    def test_empty_ledger_returns_empty_string(self):
        empty = ConcernsLedger(
            persist_path=self.tmp.name + '.empty', review_path=self.tmp_review.name + '.empty'
        )
        self.assertEqual(empty.to_prompt_block(), '')


class TestConcernsDecay(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
        self.tmp.close()
        self.tmp_review = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
        self.tmp_review.close()
        self.ledger = ConcernsLedger(
            persist_path=self.tmp.name,
            review_path=self.tmp_review.name,
        )

    def tearDown(self):
        for p in [self.tmp.name, self.tmp_review.name]:
            try:
                os.unlink(p)
            except Exception:
                pass

    def test_expired_concern_archives(self):
        # severity 低 + 超过 ttl_days*86400 没 signal
        c = Concern(
            id='old', what_i_watch="老的", why_i_care="测试",
            severity=0.2, ttl_days=1
        )
        c.last_updated = time.time() - 3 * 86400  # 3 天前
        self.ledger.register(c)
        stats = self.ledger.apply_decay()
        self.assertEqual(stats['archived'], 1)
        self.assertEqual(self.ledger.get('old').state, STATE_ARCHIVED)

    def test_high_severity_not_expired(self):
        # 🆕 [反刍治本-Fix2 / Sir 2026-06-02] 契约变更: severity>0.5 不再"永不过期".
        # Sir 真意 "活物会淡忘": 高 severity 但**有近期真 Sir signal** → 锚新鲜 → 不衰不过期;
        # 久无 Sir signal (本例 30 天) → severity 半衰 → 自然降温/过期。旧"永不过期"是反刍根因。
        c = Concern(
            id='important', what_i_watch="重要", why_i_care="必须保留",
            severity=0.8, ttl_days=1
        )
        # Sir 刚真提过 → 锚新鲜
        c.last_user_signal_ts = time.time()
        c.last_updated = time.time()
        self.ledger.register(c)
        stats = self.ledger.apply_decay()
        # 有近期 Sir signal → severity 不衰, 不过期
        self.assertEqual(self.ledger.get('important').state, STATE_ACTIVE)
        self.assertAlmostEqual(self.ledger.get('important').severity, 0.8, places=2)

    def test_high_severity_stale_decays(self):
        # 🆕 [反刍治本-Fix2] 高 severity 但久无真 Sir signal (30 天) → 半衰 → 降温.
        # 这是 Sir 2026-06-02 痛点的直接修复: 他久不提了, 关心该自然凉.
        c = Concern(
            id='stale_important', what_i_watch="老牵挂", why_i_care="Sir 久不提了",
            severity=1.0, ttl_days=60
        )
        c.last_user_signal_ts = time.time() - 30 * 86400  # 30 天前最后真 signal
        c.last_updated = time.time() - 30 * 86400
        self.ledger.register(c)
        self.ledger.apply_decay()
        # half_life=7d, grace=2d, age=30d → 衰 28d ≈ 4 半衰期 → 远 < 0.5
        self.assertLess(self.ledger.get('stale_important').severity, 0.3,
                        '久无 Sir signal 的高 severity concern 应半衰降温')


# ============================================================
# C. 集成：Self Anchor + Concerns 都能正常构造
# ============================================================
class TestSoulIntegration(unittest.TestCase):

    def setUp(self):
        reset_default_self_anchor_for_test()
        reset_default_ledger_for_test()

    def tearDown(self):
        # 清理 disk 的 memory_pool/concerns.json（如果是 default ledger 创建的）
        try:
            for path in ['memory_pool/concerns.json',
                         'memory_pool/concerns_review.json']:
                if os.path.exists(path):
                    # 只删测试创建的，原有 prod 的留着
                    pass  # 默认 ledger 走 default path 会写真盘，但测试只需检查行为
        except Exception:
            pass
        reset_default_self_anchor_for_test()
        reset_default_ledger_for_test()

    def test_both_blocks_can_combine(self):
        sa = SelfAnchor()
        sa.record_turn()
        self_block = sa.build_block(max_chars=900)

        # 用一个临时 ledger
        tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
        tmp.close()
        tmp_r = tempfile.NamedTemporaryFile(suffix='.json', delete=False)
        tmp_r.close()
        try:
            ledger = ConcernsLedger(persist_path=tmp.name, review_path=tmp_r.name)
            bootstrap_default_concerns(ledger)
            concerns_block = ledger.to_prompt_block(top_n=3, max_chars=600)

            # 合并应该正确
            combined = self_block + '\n\n' + concerns_block
            self.assertIn('I AM J.A.R.V.I.S', combined)
            self.assertIn('MY SELF / SOUL', combined)
            self.assertLess(len(combined), 1600)  # 两块加起来不超 1.6K
        finally:
            for p in [tmp.name, tmp_r.name]:
                try:
                    os.unlink(p)
                except Exception:
                    pass


if __name__ == '__main__':
    unittest.main(verbosity=2)
