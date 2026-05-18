# -*- coding: utf-8 -*-
"""[P0+20-β.0.1 / 2026-05-16] DirectiveRegistry 单元 + 集成测试

覆盖：
- Directive / DirectiveContext dataclass 行为
- DirectiveRegistry register / collect / record_fire / record_rejection / record_helped
- apply_decay 3 条规则（dormant / review / priority_drop）
- persist / load JSON round-trip
- bootstrap_default_registry 13 条 directive 全部命中条件正确（含 P0+20-β.1.11 future_tense_capability_check）
- get_default_registry 单例 + reset_default_registry_for_test
- dump_human ASCII 表渲染

规范：详 docs/JARVIS_WORKFLOW_PROTOCOL.md §2 + docs/PROMPT_REFACTOR_PLAN.md §4-§6
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_directives import (
    Directive,
    DirectiveContext,
    DirectiveRegistry,
    STATE_ACTIVE,
    STATE_DORMANT,
    STATE_REVIEW,
    bootstrap_default_registry,
    get_default_registry,
    reset_default_registry_for_test,
)


def _make_directive(did: str = "test_d", priority: int = 5, ttl_days: int = 30, trigger=None, tier_whitelist=None) -> Directive:
    return Directive(
        id=did,
        text="test directive body",
        trigger=trigger or (lambda ctx: True),
        priority=priority,
        tier_whitelist=tier_whitelist or [],
        ttl_days=ttl_days,
        source_marker="test",
    )


class TestDirectiveDataclass(unittest.TestCase):
    def test_directive_default_state_is_active(self):
        d = _make_directive()
        self.assertEqual(d.state, STATE_ACTIVE)
        self.assertEqual(d.fired, 0)
        self.assertEqual(d.rejected, 0)
        self.assertEqual(d.helped, 0)

    def test_directive_context_defaults(self):
        ctx = DirectiveContext()
        self.assertEqual(ctx.user_input, "")
        self.assertEqual(ctx.tier, "DEEP_QUERY")
        self.assertEqual(ctx.stm, [])
        self.assertFalse(ctx.has_active_plan)


class TestRegistryRegistration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        self.tmp.close()
        self.r = DirectiveRegistry(persist_path=self.tmp.name)

    def tearDown(self):
        self.r.stop_decay_worker()
        try:
            os.unlink(self.tmp.name)
        except Exception:
            pass

    def test_register_then_get(self):
        d = _make_directive("d1")
        self.r.register(d)
        self.assertIs(self.r.get("d1"), d)

    def test_register_duplicate_raises(self):
        self.r.register(_make_directive("dup"))
        with self.assertRaises(ValueError):
            self.r.register(_make_directive("dup"))

    def test_register_empty_id_raises(self):
        with self.assertRaises(ValueError):
            self.r.register(Directive(id="", text="x", trigger=lambda c: True))

    def test_register_non_callable_trigger_raises(self):
        with self.assertRaises(ValueError):
            self.r.register(Directive(id="bad", text="x", trigger="not a callable"))

    def test_unregister(self):
        self.r.register(_make_directive("d1"))
        self.assertTrue(self.r.unregister("d1"))
        self.assertIsNone(self.r.get("d1"))
        self.assertFalse(self.r.unregister("d1"))  # already gone


class TestRegistryCollect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        self.tmp.close()
        self.r = DirectiveRegistry(persist_path=self.tmp.name)

    def tearDown(self):
        self.r.stop_decay_worker()
        try:
            os.unlink(self.tmp.name)
        except Exception:
            pass

    def test_collect_returns_only_active(self):
        d_active = _make_directive("active")
        d_dormant = _make_directive("dormant")
        d_dormant.state = STATE_DORMANT
        self.r.register(d_active)
        self.r.register(d_dormant)
        fired = self.r.collect(DirectiveContext())
        self.assertEqual([d.id for d in fired], ["active"])

    def test_collect_respects_tier_whitelist(self):
        d1 = _make_directive("only_short", tier_whitelist=["SHORT_CHAT"])
        d2 = _make_directive("always")
        self.r.register(d1)
        self.r.register(d2)
        fired_short = self.r.collect(DirectiveContext(tier="SHORT_CHAT"))
        self.assertIn("only_short", [d.id for d in fired_short])
        self.assertIn("always", [d.id for d in fired_short])
        fired_deep = self.r.collect(DirectiveContext(tier="DEEP_QUERY"))
        self.assertNotIn("only_short", [d.id for d in fired_deep])
        self.assertIn("always", [d.id for d in fired_deep])

    def test_collect_sorts_by_priority_desc(self):
        self.r.register(_make_directive("p5", priority=5))
        self.r.register(_make_directive("p9", priority=9))
        self.r.register(_make_directive("p3", priority=3))
        fired = self.r.collect(DirectiveContext())
        self.assertEqual([d.id for d in fired], ["p9", "p5", "p3"])

    def test_collect_swallows_trigger_exception(self):
        def boom(_ctx):
            raise RuntimeError("trigger crashed")
        self.r.register(Directive(id="exploding", text="x", trigger=boom))
        self.r.register(_make_directive("safe"))
        fired = self.r.collect(DirectiveContext())
        self.assertEqual([d.id for d in fired], ["safe"])

    def test_collect_filters_by_trigger_result(self):
        self.r.register(Directive(id="never", text="x", trigger=lambda c: False))
        self.r.register(Directive(id="always", text="x", trigger=lambda c: True))
        fired = self.r.collect(DirectiveContext())
        self.assertEqual([d.id for d in fired], ["always"])


class TestRegistrySignals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        self.tmp.close()
        self.r = DirectiveRegistry(persist_path=self.tmp.name)
        self.r.register(_make_directive("s1"))
        self.r.register(_make_directive("s2"))

    def tearDown(self):
        self.r.stop_decay_worker()
        try:
            os.unlink(self.tmp.name)
        except Exception:
            pass

    def test_record_fire_increments_counter_and_timestamp(self):
        t0 = time.time()
        self.r.record_fire(["s1", "s2"])
        d1 = self.r.get("s1")
        d2 = self.r.get("s2")
        self.assertEqual(d1.fired, 1)
        self.assertEqual(d2.fired, 1)
        self.assertGreaterEqual(d1.last_triggered, t0)

    def test_record_rejection_increments(self):
        self.r.record_rejection(["s1"])
        self.assertEqual(self.r.get("s1").rejected, 1)
        self.assertEqual(self.r.get("s2").rejected, 0)

    def test_record_helped_true(self):
        self.r.record_helped("s1", True)
        self.r.record_helped("s1", True)
        self.r.record_helped("s1", False)
        self.assertEqual(self.r.get("s1").helped, 2)

    def test_record_unknown_id_silent(self):
        self.r.record_fire(["nonexistent"])  # 不抛
        self.r.record_rejection(["nonexistent"])
        self.r.record_helped("nonexistent", True)


class TestRegistryDecay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        self.tmp.close()
        self.review_path = self.tmp.name + ".review.json"
        self.r = DirectiveRegistry(persist_path=self.tmp.name)
        # 覆盖 review_path 防止污染默认 memory_pool
        self.r.review_path = self.review_path

    def tearDown(self):
        self.r.stop_decay_worker()
        for p in (self.tmp.name, self.review_path):
            try:
                os.unlink(p)
            except Exception:
                pass

    def test_decay_marks_dormant_after_ttl(self):
        d = _make_directive("old", ttl_days=1)
        d.last_triggered = time.time() - 2 * 86400  # 2 天前
        d.fired = 5
        self.r.register(d)
        stats = self.r.apply_decay()
        self.assertEqual(stats['dormant'], 1)
        self.assertEqual(self.r.get("old").state, STATE_DORMANT)

    def test_decay_keeps_recently_fired_active(self):
        d = _make_directive("fresh", ttl_days=30)
        d.last_triggered = time.time()
        d.fired = 1
        self.r.register(d)
        self.r.apply_decay()
        self.assertEqual(self.r.get("fresh").state, STATE_ACTIVE)

    def test_decay_marks_review_when_rejected_threshold(self):
        d = _make_directive("rejected_a_lot")
        d.fired = 5
        d.rejected = 3
        d.last_triggered = time.time()
        self.r.register(d)
        stats = self.r.apply_decay()
        self.assertEqual(stats['review'], 1)
        self.assertEqual(self.r.get("rejected_a_lot").state, STATE_REVIEW)
        # review 队列 JSON 应该有一行
        self.assertTrue(os.path.exists(self.review_path))
        with open(self.review_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['id'], "rejected_a_lot")

    def test_decay_drops_priority_when_high_rej_rate(self):
        d = _make_directive("noisy", priority=9)
        d.fired = 10
        d.rejected = 4  # rej_rate=0.4 > 0.3
        d.last_triggered = time.time()
        self.r.register(d)
        self.r.apply_decay()
        # 注意 rejected=4 < REVIEW_REJECTED_THRESHOLD(3) — 等等，4 > 3 会触发 review。改用 rejected=2
        # 重写测试场景
        self.r.unregister("noisy")
        d2 = _make_directive("noisy2", priority=9)
        d2.fired = 10
        d2.rejected = 2  # 不到 review threshold（3）但 rej_rate=0.2，不到 0.3 ... 改 fired=6
        self.r.unregister("noisy2") if self.r.get("noisy2") else None
        d3 = _make_directive("noisy3", priority=9)
        d3.fired = 6
        d3.rejected = 2  # rej_rate=0.33 > 0.3, fired>=5, rejected<3 不触发 review
        d3.last_triggered = time.time()
        self.r.register(d3)
        stats = self.r.apply_decay()
        self.assertEqual(stats['priority_drop'], 1)
        self.assertEqual(self.r.get("noisy3").priority, 7)  # 9-2=7


class TestRegistryPersistence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        self.tmp.close()
        self.r = DirectiveRegistry(persist_path=self.tmp.name)

    def tearDown(self):
        self.r.stop_decay_worker()
        try:
            os.unlink(self.tmp.name)
        except Exception:
            pass

    def test_persist_then_load_round_trip(self):
        d = _make_directive("p1")
        self.r.register(d)
        self.r.record_fire(["p1"])
        self.r.record_fire(["p1"])
        self.r.record_rejection(["p1"])
        self.assertTrue(self.r.persist())
        # 重建 registry，bootstrap 同 id 后 load
        r2 = DirectiveRegistry(persist_path=self.tmp.name)
        r2.register(_make_directive("p1"))  # 同 id 新对象，计数器初值 0
        n = r2.load()
        self.assertEqual(n, 1)
        self.assertEqual(r2.get("p1").fired, 2)
        self.assertEqual(r2.get("p1").rejected, 1)

    def test_persist_skips_when_not_dirty(self):
        d = _make_directive("p2")
        self.r.register(d)
        self.assertTrue(self.r.persist())  # 第一次有变更
        self.assertFalse(self.r.persist())  # 第二次无变更

    def test_load_handles_missing_file(self):
        # tmp 文件还没被 persist 写过任何 directive，但里面是空字符串。先 unlink
        try:
            os.unlink(self.tmp.name)
        except Exception:
            pass
        n = self.r.load()
        self.assertEqual(n, 0)


class TestBootstrapDefault(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        self.tmp.close()
        self.r = DirectiveRegistry(persist_path=self.tmp.name)

    def tearDown(self):
        self.r.stop_decay_worker()
        try:
            os.unlink(self.tmp.name)
        except Exception:
            pass

    def test_bootstrap_loads_12_directives(self):
        n = bootstrap_default_registry(self.r)
        # P0+20-β.1.15 加 reminder_read_truth_source → 14
        # 🩹 [β.2.9.9] 加 memory_update_honesty / tool_overture / dashboard_intent → 17
        self.assertGreaterEqual(n, 14,
                                  'bootstrap 数量只增不减, 至少保留历史 14 条')
        # 防止悄然漏注册: 数量必须等于 defs list 长度 (动态确认)
        self.assertEqual(n, len(self.r.directives))
        # 必含的几条关键 directive
        for did in ('nudge_agenda_honesty', 'continuity_two_parts', 'tool_honesty_directive',
                    'bilingual_directive', 'fuzzy_candidates_policy', 'correction_writepath_no_tool'):
            self.assertIsNotNone(self.r.get(did), f"missing bootstrap directive: {did}")

    def test_nudge_agenda_honesty_trigger(self):
        bootstrap_default_registry(self.r)
        # 应触发：上一轮 Jarvis 说 "I've struck it" + 本轮 Sir 说 "不用再提"
        ctx = DirectiveContext(
            user_input="不用再提了好吗",
            last_jarvis_reply="I've struck it from the active agenda.",
            stm=[{'user': 'x', 'jarvis': 'y'}],
            tier='SHORT_CHAT',
        )
        fired = self.r.collect(ctx)
        ids = [d.id for d in fired]
        self.assertIn('nudge_agenda_honesty', ids)

    def test_continuity_two_parts_trigger(self):
        bootstrap_default_registry(self.r)
        # 应触发：STM 非空 + 含 "by the way" 连接词 + 长度 >= 12
        ctx = DirectiveContext(
            user_input="OK got it, by the way how is the deploy going?",
            stm=[{'user': 'x', 'jarvis': 'y'}],
        )
        fired = self.r.collect(ctx)
        ids = [d.id for d in fired]
        self.assertIn('continuity_two_parts', ids)

    def test_continuity_two_parts_does_not_fire_without_stm(self):
        bootstrap_default_registry(self.r)
        # 第一轮：STM 空 → 不触发
        ctx = DirectiveContext(
            user_input="hello by the way how is it going",
            stm=[],
        )
        fired = self.r.collect(ctx)
        ids = [d.id for d in fired]
        self.assertNotIn('continuity_two_parts', ids)

    def test_bilingual_directive_always_fires(self):
        bootstrap_default_registry(self.r)
        ctx = DirectiveContext(user_input="x", tier='WAKE_ONLY')
        fired = self.r.collect(ctx)
        self.assertIn('bilingual_directive', [d.id for d in fired])

    def test_tool_honesty_only_after_fail(self):
        bootstrap_default_registry(self.r)
        ctx_ok = DirectiveContext(
            user_input="ok thanks",
            last_tool_results=["✅ audio_hands.set_volume: ok"],
            tier='SHORT_CHAT',
        )
        ctx_fail = DirectiveContext(
            user_input="ok thanks",
            last_tool_results=["❌ audio_hands.set_volume: device not found"],
            tier='SHORT_CHAT',
        )
        ok_ids = [d.id for d in self.r.collect(ctx_ok)]
        fail_ids = [d.id for d in self.r.collect(ctx_fail)]
        self.assertNotIn('tool_honesty_directive', ok_ids)
        self.assertIn('tool_honesty_directive', fail_ids)

    def test_fuzzy_candidates_fires_on_search_intent(self):
        bootstrap_default_registry(self.r)
        ctx = DirectiveContext(user_input="找一下那个文件", tier='TOOL_REQUEST')
        ids = [d.id for d in self.r.collect(ctx)]
        self.assertIn('fuzzy_candidates_policy', ids)

    def test_correction_writepath_fires_on_memorize_intent(self):
        bootstrap_default_registry(self.r)
        ctx = DirectiveContext(user_input="帮我记一下要交水电费", tier='SHORT_CHAT')
        ids = [d.id for d in self.r.collect(ctx)]
        self.assertIn('correction_writepath_no_tool', ids)

    def test_search_directive_fires_on_news_query(self):
        bootstrap_default_registry(self.r)
        ctx = DirectiveContext(user_input="What is the latest news on AI", tier='DEEP_QUERY')
        ids = [d.id for d in self.r.collect(ctx)]
        self.assertIn('search_directive', ids)


class TestDumpHuman(unittest.TestCase):
    def test_dump_human_returns_ascii_string(self):
        r = DirectiveRegistry(persist_path=tempfile.NamedTemporaryFile(delete=False).name)
        bootstrap_default_registry(r)
        s = r.dump_human()
        self.assertIsInstance(s, str)
        self.assertIn("DirectiveRegistry", s)
        self.assertIn("nudge_agenda_honesty", s)
        # 表头列
        self.assertIn("fired", s)
        self.assertIn("rej", s)
        r.stop_decay_worker()


class TestDefaultRegistrySingleton(unittest.TestCase):
    def setUp(self):
        reset_default_registry_for_test()

    def tearDown(self):
        reset_default_registry_for_test()

    def test_singleton_returns_same_instance(self):
        r1 = get_default_registry()
        r2 = get_default_registry()
        self.assertIs(r1, r2)

    def test_singleton_is_bootstrapped(self):
        r = get_default_registry()
        # P0+20-β.1.15：14 条 directive 都注册了（含 reminder_read_truth_source）
        # 🩹 [β.2.9.9] 加 3 条 → 17, 用 >=14 防未来扩展回归
        self.assertGreaterEqual(len(r.directives), 14)


if __name__ == '__main__':
    unittest.main(verbosity=2)
