# -*- coding: utf-8 -*-
"""[P5-fix23-meta-protect / 2026-05-22] critical priority directive 不可被 decay

Sir 17:40 真测痛点:
> "我们之前的思考链显示是被你关掉了吗? 怎么都没有了呢?"

Root: meta_self_check_directive (priority=10, P5-Layer1-fix19) 因为 not_helped=11 /
      helped=0 被 DirectiveDecayWorker 自动 decay 到 state=review + priority=1 →
      不再 inject prompt → 主脑没收到 self check 指令 → 不写 [META] 行 →
      思考链 audit jsonl 自 15:07 后空白 (3.5h gap).

修法: jarvis_directives.py:apply_decay 加 critical priority protect — priority>=10
是 always-on 红线 directive (Sir 设计的结构性规则), 不参与 helped/not_helped 评分降级.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis_directives import (
    Directive,
    DirectiveRegistry,
    STATE_ACTIVE,
    STATE_REVIEW,
)


def _make_directive(did, priority, helped=0, not_helped=0, fired=0,
                      rejected=0, trigger=None):
    return Directive(
        id=did,
        text=f"text for {did}",
        trigger=trigger or (lambda ctx: True),
        priority=priority,
        ttl_days=365,
    )


class TestCriticalPriorityProtect(unittest.TestCase):
    """P5-fix23-meta-protect: priority>=10 不参与 decay.

    🆕 [Sir 2026-05-28 14:00 test pollution root cause fix] setUp 用 tmpdir
    隔离 prod path. 之前 `DirectiveRegistry()` 无 args → review_path hardcode
    prod, test 触发 apply_decay 写 prod queue → 15+ 'regular_directive' 污染.
    """

    def setUp(self):
        self._tmp_persist = tempfile.NamedTemporaryFile(
            mode='w', delete=False, suffix='.json')
        self._tmp_persist.close()
        self._tmp_review = tempfile.NamedTemporaryFile(
            mode='w', delete=False, suffix='.review.json')
        self._tmp_review.close()
        self.reg = DirectiveRegistry(
            persist_path=self._tmp_persist.name,
            review_path=self._tmp_review.name,
        )

    def tearDown(self):
        for p in (self._tmp_persist.name, self._tmp_review.name):
            try:
                os.unlink(p)
            except OSError:
                pass

    def test_priority_10_with_high_not_helped_stays_active(self):
        """priority=10 + not_helped=11 / helped=0 → 不被降级 (Sir 真痛点)."""
        d = _make_directive('meta_self_check_directive', priority=10)
        d.not_helped = 11
        d.helped = 0
        d.fired = 20
        self.reg.directives[d.id] = d

        stats = self.reg.apply_decay()
        self.assertEqual(d.state, STATE_ACTIVE)
        self.assertEqual(d.priority, 10)
        self.assertEqual(stats.get('critical_protected', 0), 1)
        self.assertEqual(stats.get('review', 0), 0)
        self.assertEqual(stats.get('priority_drop', 0), 0)

    def test_priority_10_with_high_rejected_stays_active(self):
        """priority=10 + rejected=10 → 仍不降级 (规则 2 也跳过)."""
        d = _make_directive('bilingual_directive', priority=10)
        d.rejected = 10
        d.fired = 20
        self.reg.directives[d.id] = d

        stats = self.reg.apply_decay()
        self.assertEqual(d.state, STATE_ACTIVE)
        self.assertEqual(d.priority, 10)

    def test_priority_11_protected(self):
        """priority=11 (e.g. morning_warmth_priority) 也保护."""
        d = _make_directive('morning_warmth_priority', priority=11)
        d.not_helped = 20
        d.helped = 0
        d.fired = 30
        self.reg.directives[d.id] = d

        stats = self.reg.apply_decay()
        self.assertEqual(d.state, STATE_ACTIVE)
        self.assertEqual(d.priority, 11)

    def test_priority_12_protected(self):
        """priority=12 (e.g. no_hallucinated_tool_use_judge) 也保护."""
        d = _make_directive('no_hallucinated_tool_use_judge', priority=12)
        d.not_helped = 50
        d.helped = 0
        d.fired = 100
        self.reg.directives[d.id] = d

        stats = self.reg.apply_decay()
        self.assertEqual(d.state, STATE_ACTIVE)
        self.assertEqual(d.priority, 12)

    def test_priority_9_still_decays_normally(self):
        """priority=9 < 10 → 仍按规则 4 降级 (回归保证 protect 不过度)."""
        d = _make_directive('regular_directive', priority=9)
        d.not_helped = 11
        d.helped = 0
        d.fired = 20
        self.reg.directives[d.id] = d

        stats = self.reg.apply_decay()
        # priority=9 not protected → 应进 review
        self.assertEqual(d.state, STATE_REVIEW)
        self.assertEqual(stats.get('review', 0), 1)

    def test_priority_8_priority_drops_normally(self):
        """priority=8 + not_helped=5 + helped_ratio<0.3 → priority drop 仍生效."""
        d = _make_directive('reg2', priority=8)
        d.not_helped = 5
        d.helped = 1  # ratio 1/6 = 0.17 < 0.3
        d.fired = 6
        self.reg.directives[d.id] = d

        stats = self.reg.apply_decay()
        self.assertEqual(d.state, STATE_ACTIVE)
        self.assertEqual(d.priority, 6)  # 8-2
        self.assertEqual(stats.get('priority_drop', 0), 1)


class TestCriticalProtectStats(unittest.TestCase):
    """stats dict 含 critical_protected count."""

    def test_stats_has_critical_protected_key(self):
        reg = DirectiveRegistry()
        d = _make_directive('test', priority=10)
        d.not_helped = 11
        reg.directives[d.id] = d
        stats = reg.apply_decay()
        self.assertIn('critical_protected', stats)

    def test_stats_count_multiple_critical(self):
        reg = DirectiveRegistry()
        for i, pri in enumerate([10, 11, 12, 10]):
            d = _make_directive(f'd{i}', priority=pri)
            d.not_helped = 50
            reg.directives[d.id] = d
        stats = reg.apply_decay()
        self.assertEqual(stats['critical_protected'], 4)
        self.assertEqual(stats['review'], 0)
        self.assertEqual(stats['priority_drop'], 0)


if __name__ == '__main__':
    unittest.main()
