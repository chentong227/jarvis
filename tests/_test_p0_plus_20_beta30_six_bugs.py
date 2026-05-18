# -*- coding: utf-8 -*-
"""[P0+20-β.3.0 / 2026-05-18] Sir 14:00 实测 6 BUG 修复回归 testcase.

Sir 反馈 6 个 BUG:
  1. scripts\\jarvis_dashboard.cmd 静默失败 → 改 python.exe 拉 console
  2. dashboard_intent "给我看" 过广 → vocab 迁 json + archived
  3. ui_control 未知指令 dashboard_open → chat_bypass 已加 (Sir 重启生效)
  4. 言行不一 "已打开 dashboard" 但工具失败 → ClaimTracer past_action + directive
  5. 说睡觉瞬间黑屏 → 30s 倒数 + Sir 可撤回
  6. 微信静音没生效 → vocab 迁 json + 循环 mute 多进程
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestBUG2DashboardIntentVocab(unittest.TestCase):
    """BUG#2 dashboard_intent vocab 迁 json + '给我看' archived"""

    def test_vocab_file_exists(self):
        path = os.path.join(ROOT, 'memory_pool', 'dashboard_intent_vocab.json')
        self.assertTrue(os.path.exists(path),
                        "dashboard_intent_vocab.json 应存在")

    def test_geime_kan_archived(self):
        path = os.path.join(ROOT, 'memory_pool', 'dashboard_intent_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for p in data['patterns']:
            if '给我看' in p.get('keywords', []):
                self.assertEqual(p['state'], 'archived',
                                  "'给我看' 必须 archived 不再触发")
                return
        self.assertTrue(False, "'给我看' 应该在 vocab 里 archived")

    def test_get_dashboard_intent_patterns_caches(self):
        from jarvis_directives import get_dashboard_intent_patterns
        kws = get_dashboard_intent_patterns()
        self.assertIsInstance(kws, tuple)
        self.assertIn('面板', kws)
        # archived 词不在
        self.assertNotIn('给我看', kws)

    def test_fan_dakai_geimekanyisxia_no_trigger(self):
        """Sir 真实输入: '烦打开给我看一下' 不应触发 dashboard"""
        from jarvis_directives import _trigger_dashboard_intent, DirectiveContext
        ctx = DirectiveContext(user_input='烦打开给我看一下')
        # 现在的 active vocab 不含 '给我看' / '看一下' → 不触发
        result = _trigger_dashboard_intent(ctx)
        self.assertFalse(
            result, "Sir 14:00 痛点输入不应再触发 dashboard_intent"
        )

    def test_dashboard_intent_explicit_trigger(self):
        """明确说面板/dashboard 应该触发"""
        from jarvis_directives import _trigger_dashboard_intent, DirectiveContext
        for utt in ['打开面板', '让我看看你的看板', 'open the dashboard',
                     'show me the dashboard']:
            ctx = DirectiveContext(user_input=utt)
            self.assertTrue(_trigger_dashboard_intent(ctx),
                              f"'{utt}' 应触发 dashboard_intent")


class TestBUG4PastActionHonesty(unittest.TestCase):
    """BUG#4 言行不一 — ClaimTracer past_action + directive"""

    def test_past_action_zh_extracted(self):
        from jarvis_claim_tracer import extract_claims
        text = "好的, 已经打开了 dashboard, 您慢慢看."
        claims = extract_claims(text)
        kinds = [c.kind for c in claims]
        self.assertIn('past_action', kinds,
                       "'已打开' 应被抽为 past_action claim")

    def test_past_action_en_extracted(self):
        from jarvis_claim_tracer import extract_claims
        text = "I've opened the dashboard, Sir."
        claims = extract_claims(text)
        kinds = [c.kind for c in claims]
        self.assertIn('past_action', kinds)

    def test_past_action_no_tool_unverified(self):
        """Sir 14:00 真实场景: 主脑说'已打开'但 tool 没 ✅ → unverified"""
        from jarvis_claim_tracer import trace_reply
        result = trace_reply(
            jarvis_reply="已经帮您打开了 dashboard.",
            tool_results=[],  # 工具失败/未调用
            stm_recent=[],
        )
        self.assertGreater(result['n_unverified'], 0,
                            "past_action 无 tool ✅ 必须 unverified")

    def test_past_action_with_tool_success_verified(self):
        from jarvis_claim_tracer import trace_reply
        result = trace_reply(
            jarvis_reply="已经打开了, Sir.",
            tool_results=["✅ ui_control.dashboard_open: 看板已启动 (PID=12345)"],
            stm_recent=[],
        )
        self.assertEqual(result['n_unverified'], 0,
                         "tool 真 ✅ 时 past_action 应 verified")

    def test_past_action_directive_registered(self):
        """confirm directive 进入了 default registry"""
        from jarvis_directives import DirectiveRegistry, bootstrap_default_registry
        reg = DirectiveRegistry()
        bootstrap_default_registry(reg)
        ids = list(reg.directives.keys())
        self.assertIn('past_action_honesty', ids,
                       "past_action_honesty directive 应注册")


class TestBUG5SleepCancel(unittest.TestCase):
    """BUG#5 睡觉瞬间黑屏 — 30s 倒数 + 撤回"""

    def test_sleep_cancel_vocab_file(self):
        path = os.path.join(ROOT, 'memory_pool', 'sleep_cancel_vocab.json')
        self.assertTrue(os.path.exists(path),
                        "sleep_cancel_vocab.json 应存在")

    def test_audio_ducking_targets_file(self):
        path = os.path.join(ROOT, 'memory_pool', 'audio_ducking_targets.json')
        self.assertTrue(os.path.exists(path))
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        active_ids = [t['id'] for t in data['targets']
                       if t['state'] == 'active']
        # 默认 WeChat 必须 active
        self.assertIn('wechat', active_ids)


class TestBUG6AudioDuckingVocab(unittest.TestCase):
    """BUG#6 微信静音 — vocab 驱动多进程循环"""

    def test_load_audio_ducking_targets(self):
        # 直接读 vocab 不依赖 worker
        path = os.path.join(ROOT, 'memory_pool', 'audio_ducking_targets.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        active_names = [t['process_name'] for t in data['targets']
                         if t['state'] == 'active']
        self.assertIn('WeChat', active_names)


class TestBUG3DashboardOpenCommand(unittest.TestCase):
    """BUG#3 dashboard_open 端到端: chat_bypass 路由 + 假成功修"""

    def test_dashboard_open_branch_exists(self):
        """grep 检查 chat_bypass 里 dashboard_open 分支真的在"""
        path = os.path.join(ROOT, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('dashboard_open', content)
        # β.3.0 修: 不再用 pythonw 静默失败
        self.assertIn('CREATE_NEW_CONSOLE', content,
                       "β.3.0 改用 CREATE_NEW_CONSOLE 不再 pythonw 静默")
        # β.3.0 修: 启动后 poll() 检测秒退
        self.assertIn('proc.poll()', content,
                       "β.3.0 启动后 check 进程是否秒退")

    def test_dashboard_open_in_both_paths(self):
        """β.3.0-hotfix: Sir 16:08 实测 — 旧同步 fast_call 路径也必须有 dashboard_open"""
        path = os.path.join(ROOT, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        # 新异步路径 (line ~1319) + 旧同步路径 (line ~2667 elif organ == 'ui_control')
        # 两处都必须能识别 dashboard_open
        count = content.count('dashboard_open')
        # 至少 3 次: 注释 + 新路径 + 旧路径 + 关闭路径关联
        self.assertGreaterEqual(count, 3,
                                 f"两路径都需路由 dashboard_open, 当前命中 {count} 次")
        # 验证旧路径有显式 elif/if ctrl_cmd in ("dashboard_open"...)
        self.assertIn('dashboard_open", "dashboard_close"', content,
                       "旧同步路径必须 elif ctrl_cmd in dashboard 元组")


class TestBUG4ActivClaimDetection(unittest.TestCase):
    """🩹 [β.3.0 BUG#4 / 2026-05-18] Sir 16:08 实测: 'active' 漏检 → 撒谎话漏出去"""

    def test_active_in_done_claim_pattern(self):
        """Sir 实测: 'The dashboard is active, Sir.' 必须被 _claim_pattern 捕获"""
        import re as _re
        # 复用 chat_bypass.py 同款 pattern
        path = os.path.join(ROOT, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        # 验证 pattern 含 active
        self.assertIn('active|running|launched', content,
                       "β.3.0 pattern 必须含 active/running/launched 漏检词")

    def test_zh_done_claim_pattern(self):
        """中文也需要漏检词覆盖: '已激活/已启动/已开启'"""
        path = os.path.join(ROOT, 'jarvis_chat_bypass.py')
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('_claim_pattern_zh', content,
                       "β.3.0 必须有中文 done_claim pattern")
        self.assertIn('已激活', content)
        self.assertIn('已启动', content)


if __name__ == '__main__':
    unittest.main()
