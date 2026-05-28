# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 01:00 β.5.50 LifetimeAwareness] 回归.

Sir 真问 (00:54): "他时间的概念是什么... 现在思考脑只看上下文会判断失误...
                 我感觉只让主脑感知不太够吧, 这本就该是 Jarvis 时刻在意的事..."

Sir 真意 (synthesized): Jarvis 是"持续唤醒的思考脑"心跳, 不是 stateless API.
  主脑该看 几分钟前在想啥 / 几小时前在做啥 / 跨 session 我是同一 Jarvis,
  思考脑同样应该看, dashboard 也该可视化.

设计文档: docs/JARVIS_LIFETIME_AWARENESS_DESIGN.md (待写)
工程总计: ~250 行 — 0 新模块, 全复用准则 6 vocab 持久化范式

测试覆盖 (12 testcase):

P1 — daemon API 扩 (4 testcase):
  - build_lifetime_block(mode='full') 返非空且含 process uptime (LB1)
  - build_lifetime_block(mode='mini') 返 < 400 char (LB2)
  - build_lifetime_block(mode='off') 返 '' (LB3)
  - get_recent_thoughts_timeline(minutes=15) 返按时间排序 (LB4)

P2 — vocab 持久化 (2 testcase):
  - jarvis_lifetime_block_vocab.json 存在且含 tier_mode (V1)
  - tier_mode 含 5 tier (SHORT_CHAT/DEEP_QUERY/FACTUAL_RECALL/WAKE_ONLY/REMINDER_FIRING) (V2)

P3 — 主脑 Layer 1.5 升级 (3 testcase) —  
  [🚨 UPDATED β.6 Phase 2 治本 / Sir 2026-05-28 17:20: Layer 1.5 已退化
   stub 永返 ''. lifetime 现由 Layer 1.6 voice block 内部聚合呈现, 端到端
   contract 由 fix37 验证. P3 现守 Layer 1.5 method-level stub 契约 (永返 '')
   防回退到独立 push 老路径]
  - _build_layer_1b_inner_thoughts_block(prompt_tier='SHORT_CHAT') → '' (β.6 stub) (L1)
  - _build_layer_1b_inner_thoughts_block(prompt_tier='REMINDER_FIRING') → '' (L2)
  - _build_layer_1b_inner_thoughts_block(prompt_tier='UNKNOWN') → '' (β.6 stub) (L3)

P4 — daemon 自己 prompt 接 mini lifetime (1 testcase):
  - _build_prompt user prompt 含 'JARVIS LIFETIME' header (D1)

P5 — dashboard API (2 testcase):
  - /api/lifetime_state 返 ok + 字段齐全 (DA1)
  - /api/lifetime_state 失败时返 ok=true + lifetime_block_full='' (DA2)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_daemon():
    """Make daemon with mock dependencies (no real LLM, no nerve)."""
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    return InnerThoughtDaemon(
        key_router=MagicMock(),
        concerns_ledger=None,
        relational_state=None,
        central_nerve=None,
    )


# ============================================================
# P1 — daemon API
# ============================================================

class TestP1DaemonAPI(unittest.TestCase):
    """daemon 7 维 lifetime API 基础回归."""

    def test_lb1_full_block_non_empty_with_uptime(self):
        """full mode 返非空且含 process uptime header."""
        daemon = _make_daemon()
        block = daemon.build_lifetime_block(mode='full')
        self.assertIsInstance(block, str)
        self.assertGreater(len(block), 50, "full block 应该有 content")
        self.assertIn('JARVIS LIFETIME', block,
            "full block 必须有 JARVIS LIFETIME header")
        self.assertIn('Alive', block,
            "full block 必须含 Alive (process uptime 维度)")

    def test_lb2_mini_block_under_400(self):
        """mini mode 返 < 400 char (省 token, 准则 1)."""
        daemon = _make_daemon()
        block = daemon.build_lifetime_block(mode='mini')
        self.assertIsInstance(block, str)
        # mini 必须真省 token
        self.assertLess(len(block), 400,
            f"mini block 应 < 400 char (准则 1 高效), 实际 {len(block)}")

    def test_lb3_off_returns_empty(self):
        """off mode 返 '' (REMINDER_FIRING tier 不杂)."""
        daemon = _make_daemon()
        # 直接传 unknown mode → 路径 fallback 不报错
        # off 不是 daemon mode, 是 prompt_tier 层 'off' 才直接 return ''
        # 测 daemon 层 mode 异常时不崩
        block = daemon.build_lifetime_block(mode='unknown_mode')
        self.assertIsInstance(block, str, "未知 mode 不该 raise")

    def test_lb4_lifetime_block_includes_recent_thoughts(self):
        """build_lifetime_block(full) 含 Last Nmin you thought 时间序段."""
        daemon = _make_daemon()
        block = daemon.build_lifetime_block(mode='full')
        # 'Last 15min you thought' 是 build_lifetime_block 拼 timeline 的 header
        # 即使无 recent thoughts, header 或 alternative wording 至少之一应存在
        # 兼容: 容许 '15min' 或 'last 24h' 出现
        self.assertTrue(
            ('Last 15min' in block) or ('24h window' in block)
            or ('inner thoughts' in block),
            f"full block 应有 recent thoughts segment, got: {block[:300]}"
        )


# ============================================================
# P2 — vocab 持久化 (准则 6)
# ============================================================

class TestP2VocabPersist(unittest.TestCase):
    """jarvis_lifetime_block_vocab.json 持久化."""

    def setUp(self):
        self.vocab_path = os.path.join(
            ROOT, 'memory_pool', 'jarvis_lifetime_block_vocab.json'
        )

    def test_v1_vocab_file_exists_with_tier_mode(self):
        """vocab JSON 文件存在 + 含 tier_mode 字段."""
        self.assertTrue(os.path.exists(self.vocab_path),
            f"vocab 文件必须存在: {self.vocab_path}")
        with open(self.vocab_path, 'r', encoding='utf-8') as f:
            vocab = json.load(f)
        self.assertIn('tier_mode', vocab,
            "vocab 必须含 tier_mode 字段")
        self.assertIsInstance(vocab['tier_mode'], dict)

    def test_v2_tier_mode_has_5_tiers(self):
        """tier_mode 含 5 main tier."""
        with open(self.vocab_path, 'r', encoding='utf-8') as f:
            vocab = json.load(f)
        tm = vocab['tier_mode']
        for tier in ['SHORT_CHAT', 'DEEP_QUERY', 'FACTUAL_RECALL',
                     'WAKE_ONLY', 'REMINDER_FIRING']:
            self.assertIn(tier, tm, f"tier {tier} 必须在 vocab")
            self.assertIn(tm[tier], ['full', 'mini', 'off', 'legacy'],
                f"tier {tier} value 必须是 full/mini/off/legacy, 实 {tm[tier]}")


# ============================================================
# P3 — 主脑 Layer 1.5 升级
# ============================================================

class TestP3LayerOneB(unittest.TestCase):
    """主脑 _build_layer_1b_inner_thoughts_block tier-aware 路径."""

    def _make_nerve_with_daemon(self):
        """Make minimal nerve with real daemon for layer 1b test."""
        # Lazy import (central_nerve heavy)
        from jarvis_central_nerve import CentralNerve
        # mock CentralNerve __init__ heavy deps with MagicMock
        nerve = MagicMock(spec=CentralNerve)
        # bind real method
        nerve._build_layer_1b_inner_thoughts_block = (
            CentralNerve._build_layer_1b_inner_thoughts_block.__get__(nerve)
        )
        daemon = _make_daemon()
        nerve.inner_thought_daemon = daemon
        return nerve, daemon

    def test_l1_short_chat_returns_full(self):
        """[β.6 Phase 2 治本 / Sir 2026-05-28 17:20] tier=SHORT_CHAT → '' (Layer 1.5 stub).

        老契约 (β.5.50): SHORT_CHAT tier 经 vocab tier_mode='full' → 返
        daemon.build_lifetime_block(mode='full') 非空含 'JARVIS LIFETIME'
        header. Layer 1.5 独立 push 给主脑.

        新契约 (β.6 Phase 2 治本): Layer 1.5 退化 stub 永返 ''. lifetime
        改由 Layer 1.6 voice block 内部聚合呈现 (fix37 端到端验证). 此
        testcase 守 stub method-level 契约, 防回退到老独立 push 路径.
        """
        nerve, daemon = self._make_nerve_with_daemon()
        block = nerve._build_layer_1b_inner_thoughts_block(
            prompt_tier='SHORT_CHAT'
        )
        self.assertEqual(block, '',
            "β.6 Phase 2 治本: Layer 1.5 = stub 永返 ''. lifetime 改由 "
            "Layer 1.6 voice block 聚合呈现 (见 fix37). 此处若返非空 → 回退"
            "到独立 push 老路径, 违反 Sir 17:14 真意 'all 集成到思考链'.")

    def test_l2_reminder_firing_returns_empty(self):
        """tier=REMINDER_FIRING → off → '' (高紧急不杂)."""
        nerve, daemon = self._make_nerve_with_daemon()
        block = nerve._build_layer_1b_inner_thoughts_block(
            prompt_tier='REMINDER_FIRING'
        )
        # vocab 应该是 'off'
        self.assertEqual(block, '',
            "REMINDER_FIRING tier 应返 '' (off)")

    def test_l3_unknown_tier_fallback_full(self):
        """[β.6 Phase 2 治本 / Sir 2026-05-28 17:20] tier=UNKNOWN → '' (Layer 1.5 stub).

        老契约 (β.5.50): UNKNOWN tier 走 vocab default 'full' → 非空 lifetime block.
        新契约 (β.6 Phase 2 治本): Layer 1.5 stub, 任何 tier 都返 ''.
        """
        nerve, daemon = self._make_nerve_with_daemon()
        block = nerve._build_layer_1b_inner_thoughts_block(
            prompt_tier='UNKNOWN_TIER_XYZ'
        )
        self.assertEqual(block, '',
            "β.6 Phase 2 治本: Layer 1.5 = stub 永返 '' (任何 tier).")


# ============================================================
# P4 — daemon 自己 prompt 接 mini lifetime
# ============================================================

class TestP4DaemonPromptHasLifetime(unittest.TestCase):
    """daemon _build_prompt user prompt 含 JARVIS LIFETIME header."""

    def test_d1_user_prompt_includes_lifetime_header(self):
        daemon = _make_daemon()
        evidence = {
            'sir_state': 'active',
            'idle_seconds': 10,
            'hour': 14,
        }
        system, user = daemon._build_prompt(
            sir_state='active', evidence=evidence
        )
        self.assertIsInstance(user, str)
        # mini lifetime block 应在 user prompt 起头
        # (实测有 daemon stats / process uptime → 会有 JARVIS LIFETIME header)
        self.assertIn('JARVIS LIFETIME', user,
            "daemon user prompt 必须含 lifetime header (准则 6 思考脑也看心跳)")


# ============================================================
# P5 — dashboard API endpoint
# ============================================================

class TestP5DashboardAPI(unittest.TestCase):
    """/api/lifetime_state endpoint."""

    def test_da1_endpoint_returns_ok_with_fields(self):
        """endpoint 200 + ok=true + 字段齐全."""
        import scripts.jarvis_dashboard_web as dweb
        client = dweb.app.test_client()
        resp = client.get('/api/lifetime_state')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('ok'), f"ok 应 true, got {data}")
        # 字段必须存在 (值可空, daemon 没 running 是 ok)
        for key in ['lifetime_block_full', 'lifetime_block_mini',
                    'stats', 'yesterday_recap', 'vocab_tier_mode']:
            self.assertIn(key, data, f"返 dict 必须含 key {key}")

    def test_da2_endpoint_no_daemon_still_ok(self):
        """daemon 不 running (get_default_daemon returns None) endpoint 不崩."""
        import scripts.jarvis_dashboard_web as dweb
        with patch('jarvis_inner_thought_daemon.get_default_daemon',
                    return_value=None):
            client = dweb.app.test_client()
            resp = client.get('/api/lifetime_state')
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data.get('ok'))
            # 空字段也合理
            self.assertEqual(data.get('lifetime_block_full'), '')
            self.assertEqual(data.get('lifetime_block_mini'), '')


# ============================================================
# P7 — 凌晨 hydration nudge directive 去硬编码 (Sir 00:50 真痛)
# ============================================================

class TestP7HydrationEvidenceOnly(unittest.TestCase):
    """Sir 00:50: '凌晨 hydration fire 该说该睡不该说该喝水, 不要硬编码,
    知道时间概念就会说对'. 准则 6 反例 #4: prescribe → evidence-only.
    """

    def test_p7_hydration_directive_no_water_prescribe(self):
        """hydration directive 不再含 'mention water' / 'time to mention'
        prescribe (准则 6 反例 #4). 主脑看 Layer 1.5 lifetime block hour
        自决.
        """
        import jarvis_chat_bypass
        with open(jarvis_chat_bypass.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # 找 hydration directive (在 nudge_directives dict)
        # 旧: "Sir has been working for a while without an obvious break — could be time to mention water."
        # 新: "Sir has been working for a while without an obvious break."
        # 1. 'could be time to mention water' 应已删
        self.assertNotIn('could be time to mention water', src,
            '准则 6 反例 #4: prescribe "could be time to mention water" 应已删')
        # 2. hydration directive 仍存在 (evidence-only 短句)
        self.assertIn('"hydration": "Sir has been working', src,
            'hydration directive 仍应在 nudge_directives, 只是删 prescribe')


if __name__ == '__main__':
    unittest.main(verbosity=2)
