# -*- coding: utf-8 -*-
"""[P5-Gap4-followup / 2026-05-21 21:20] SOUL concern inject gating

Sir 21:17 真意 — 三轮道歉根因 = 主脑看到 concern list 被淹翻老账.
修法: SOUL Layer 1 (Concerns) inject 默认沉默, 三种情况 inject:
  (a) Sir 召唤 (user_input keyword)
  (b) 后台 URGENT (active concern severity > 0.7)
  (c) 上轮 PreFlight verdict=edit/scrap (Jarvis 真出错保险)

不阻塞 ProactiveCare nudge — daemon 该 surface 还 surface (另一通路).
不影响 IntegrityWatcher (类型 A tool fail) / SELF-PROMISE OVERDUE (类型 B PromiseLog).
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestA_SilentByDefault(unittest.TestCase):
    """默认沉默 — Sir 没召唤 + 没 URGENT + 上轮无 PreFlight 错 → soul_block 空."""

    def test_static_check_inject_logic_present(self):
        """central_nerve _assemble_prompt 应含 4 种判断 (summon/urgent/preflight/silent)."""
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # 三种触发条件都 present
        self.assertIn('_summon_kw', src,
                       'Sir 召唤 keyword 检测应 present')
        self.assertIn('_has_urgent', src,
                       '后台 URGENT severity 检测应 present')
        self.assertIn('_preflight_failed', src,
                       'PreFlight 上轮错 检测应 present')
        # 默认沉默
        self.assertIn("soul_block = ''", src,
                       '默认 soul_block 空')
        # log reason 标记
        self.assertIn('_soul_concern_inject_reason', src,
                       '应 expose inject reason 给诊断 log')
        self.assertIn('concern_reason=', src,
                       'SOUL inject log 应 print concern_reason')


class TestB_SummonKeywords(unittest.TestCase):
    """Sir 召唤 keyword 列表覆盖中英文常见词."""

    def test_summon_keywords_cover_common_phrases(self):
        """[Sir 21:56 教训] keyword 改成完整短语避免单词误触.

        例: '状态' 单词命中 '状态还不错' → unsolicited callback.
        修法: 改成完整短语 '我状态如何' / '状态如何' 等.
        """
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # fallback 短语应在源码 (resilience 路径)
        for phrase in ('any concern', 'how am i doing', '担心啥',
                        '什么进度', '我状态如何', '提醒我啥'):
            self.assertIn(phrase, src,
                           f'Fallback summon phrase "{phrase}" 应在列表中')


class TestC_UrgentBypass(unittest.TestCase):
    """severity > 0.7 → list_active 命中 → inject (非 keyword 路径)."""

    def test_urgent_logic_uses_severity_threshold(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # 检 severity > 0.7 的判断
        self.assertIn('severity', src)
        self.assertIn('> 0.7', src,
                       '后台 URGENT 阈值应是 severity > 0.7')


class TestD_PreFlightSafetyBypass(unittest.TestCase):
    """[c 保险条款] 上轮 PreFlight edit/scrap → inject 让主脑澄清."""

    def test_preflight_swm_event_check(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # 检 SWM preflight_verdict event 检测
        self.assertIn("'preflight_verdict'", src,
                       '应检 preflight_verdict SWM event')
        self.assertIn("'edit'", src)
        self.assertIn("'scrap'", src)
        self.assertIn('within_seconds=300.0', src,
                       'PreFlight 检测窗口应 5min')


class TestE_LogReasonValues(unittest.TestCase):
    """log 应 print 4 种 reason: summon / urgent / preflight_fail / silent."""

    def test_all_reason_values_present(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        for reason in ('summon', 'urgent', 'preflight_fail', 'silent'):
            self.assertIn(f"'{reason}'", src,
                           f"reason value '{reason}' 应 expose 在 log")


class TestF_ProactiveCareNudgeNotBlocked(unittest.TestCase):
    """不阻塞 ProactiveCare nudge 通路 — daemon 该 surface 还 surface.

    nudge 走的是另一条 prompt 路径 (line 3134 [Nudge SOUL inject]).
    本改动只动主流 _assemble_prompt 的 Layer 1 (concerns).
    """

    def test_nudge_soul_inject_still_present(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # nudge mode SOUL inject log 应仍存在 (没动)
        self.assertIn('[Nudge SOUL inject]', src,
                       'nudge 路径 SOUL inject 不应被改动')


class TestG_IntegrityWatcherUntouched(unittest.TestCase):
    """[INTEGRITY WATCHER REPORT] block 不动 — Jarvis tool fail 仍 surface."""

    def test_integrity_watcher_block_present(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('[INTEGRITY WATCHER REPORT', src,
                       '[INTEGRITY WATCHER REPORT] block 不动')

    def test_self_promise_overdue_block_present(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('SELF-PROMISE OVERDUE', src,
                       '[SELF-PROMISE OVERDUE] block 不动')


class TestH_Layer2BaggageGating(unittest.TestCase):
    """[P5-Gap4-followup-L2] Layer 2 unfinished + threads 同 gating.

    inside jokes / protocols 永远 inject (Jarvis 性格/STRICT RULES 不动).
    unfinished + threads 是潜在心结源 — 同 Layer 1 三种条件才 inject.
    """

    def test_layer2_uses_allow_baggage(self):
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('_allow_baggage', src,
                       'Layer 2 应 expose _allow_baggage 标记')
        # top_jokes 永远 3
        self.assertIn('top_jokes=3', src,
                       'jokes 永远 inject (性格)')
        # unfinished / threads 条件 inject
        self.assertIn('top_unfinished=2 if _allow_baggage else 0', src,
                       'unfinished 条件 inject')
        self.assertIn('top_threads=2 if _allow_baggage else 0', src,
                       'threads 条件 inject')

    def test_layer2_reuses_layer1_reason(self):
        """_allow_baggage 应基于 Layer 1 的 _soul_concern_inject_reason."""
        import jarvis_central_nerve
        with open(jarvis_central_nerve.__file__, 'r', encoding='utf-8') as f:
            src = f.read()
        # 复用 reason — summon/urgent/preflight_fail 三种
        self.assertIn(
            "_reason in ('summon', 'urgent', 'preflight_fail')",
            src,
            'Layer 2 应复用 Layer 1 三种触发条件'
        )


if __name__ == '__main__':
    unittest.main()
