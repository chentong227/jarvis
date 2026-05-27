# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 12:22 真问 anchor] 思考链 alive 感 Phase 2 + 3.

Sir 真问 (重点不是 jarvis_chat_bypass.py 的 metrics / counter / SoulArchivist 反思,
而是):
> '我在什么方面能感受到他思考链的连续 + 对时间流逝的感知?'

Phase 1 已 commit f1fff95 (主脑 TIME PULSE evidence).
Phase 2: 思考脑 surface 时, 主脑 reference 必明示来源 ('我后台想到您...').
Phase 3: Dashboard /inner_thoughts 实时 pulse 动画 + NEW badge + counter flash
         + heartbeat dot + polling 30s→10s.

测试 (7 testcase):
  Phase 2 (3):
    T1: jarvis_inner_thought_daemon.py [DAEMON SURFACED] block 含
        '[IF YOU REFERENCE — SHOW THE SOURCE]' directive
    T2: directive 含示范句 ('我刚才在想' / '后台还记得')
    T3: directive 含避坑 ('根据系统记录' 机械感)

  Phase 3 (4):
    T4: jarvis_dashboard_web.py 含 '#new-pulse-banner' CSS + DOM
    T5: dashboard 含 '.thought-card.is-fresh' CSS + 'is-fresh' JS class
    T6: dashboard 含 '.heartbeat-dot' CSS (思考脑 alive 视觉)
    T7: dashboard polling 缩短到 10s (loadRecords 10000ms)
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestPhase2SurfaceShowSource(unittest.TestCase):
    """思考脑 surface 时主脑必明示来源."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_inner_thought_daemon.py'),
                  'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_t1_directive_has_show_source_marker(self):
        """[DAEMON SURFACED] block 必含 'SHOW THE SOURCE' directive."""
        self.assertIn('Sir 2026-05-27 12:22 真问 Phase 2', self.src,
            "Phase 2 anchor marker 必存在")
        self.assertIn('SHOW THE SOURCE', self.src,
            "directive 必含 'SHOW THE SOURCE' 引导明示来源")
        self.assertIn('IF YOU REFERENCE', self.src,
            "directive 必含 'IF YOU REFERENCE' 触发条件")

    def test_t2_directive_has_concrete_phrasing_examples(self):
        """directive 必含中英示范句让主脑学."""
        # 中文示范
        self.assertIn('我刚才在想', self.src,
            "directive 必含中文示范 '我刚才在想'")
        self.assertIn('后台还记得', self.src,
            "directive 必含中文示范 '后台还记得'")
        # 英文示范 (Sir 主语英文)
        self.assertIn("I've been thinking", self.src,
            "directive 必含英文示范 'I've been thinking'")
        self.assertIn('back of my mind', self.src,
            "directive 必含英文示范 'back of my mind'")

    def test_t3_directive_has_anti_robotic_warning(self):
        """directive 必含避坑提醒避免机械感."""
        self.assertIn('根据系统记录', self.src,
            "directive 必示警 '根据系统记录' 机械感")
        self.assertIn('机械感', self.src,
            "directive 必含 '机械感' 警告关键词")


class TestPhase3DashboardPulse(unittest.TestCase):
    """Dashboard /inner_thoughts 实时视觉感."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'scripts', 'jarvis_dashboard_web.py'),
                  'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_t4_pulse_banner_css_and_dom_exist(self):
        """顶部 pulse banner CSS + DOM 必存在."""
        self.assertIn('#new-pulse-banner', self.src,
            "CSS '#new-pulse-banner' selector 必存在")
        self.assertIn('id="new-pulse-banner"', self.src,
            "DOM div id='new-pulse-banner' 必存在")
        self.assertIn('id="pulse-count"', self.src,
            "pulse counter span 必存在")
        # JS function showPulseBanner 必存在
        self.assertIn('function showPulseBanner', self.src,
            "JS function 'showPulseBanner' 必存在")

    def test_t5_fresh_thought_card_visual(self):
        """新 thought card 'is-fresh' class + ✨ NEW badge 必存在."""
        self.assertIn('.thought-card.is-fresh', self.src,
            "CSS '.thought-card.is-fresh' selector 必存在")
        self.assertIn('fresh-badge', self.src,
            "CSS 'fresh-badge' class 必存在 (✨ NEW 徽章)")
        self.assertIn('✨ NEW', self.src,
            "JS render 必输出 '✨ NEW' badge")
        # diff detect logic
        self.assertIn('_lastTopId', self.src,
            "JS 必有 _lastTopId 记录上次顶端 thought (diff detect)")
        self.assertIn('freshIds', self.src,
            "JS 必有 freshIds set 标记新进 thought")

    def test_t6_heartbeat_dot_alive_signal(self):
        """heartbeat dot CSS 必存在让 Sir 一眼看 daemon alive."""
        self.assertIn('.heartbeat-dot', self.src,
            "CSS '.heartbeat-dot' selector 必存在")
        self.assertIn('@keyframes heartbeat', self.src,
            "CSS '@keyframes heartbeat' animation 必存在")
        self.assertIn('class="heartbeat-dot"', self.src,
            "DOM span class='heartbeat-dot' 必存在 (title bar)")

    def test_t7_polling_interval_shortened_to_10s(self):
        """loadRecords polling 必缩短到 10s (不再 30s)."""
        self.assertIn('setInterval(loadRecords, 10000)', self.src,
            "loadRecords polling 必为 10000ms (Phase 3 缩短)")
        self.assertIn('Phase 3 缩短', self.src,
            "polling 缩短必有 'Phase 3 缩短' 注释")
        # counter flash function
        self.assertIn('function flashCounter', self.src,
            "JS function 'flashCounter' 必存在 (counter 闪光)")
        # tab title flash
        self.assertIn('updateTitleBadge', self.src,
            "JS function 'updateTitleBadge' 必存在 (tab title flash)")


if __name__ == '__main__':
    unittest.main(verbosity=2)
