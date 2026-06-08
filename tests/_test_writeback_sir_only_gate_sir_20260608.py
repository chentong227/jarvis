# -*- coding: utf-8 -*-
"""[writeback-sir-only-gate / 2026-06-08] 写侧接地入口「仅 Sir 原话」闸 (方案 C).

红线 (TASK 4 坐实): 合成 [SYSTEM BACKGROUND EVENT] 类 pseudo-input 经 stream_chat
把系统文本当 Sir 原话喂进 _run_body_writeback, 污染 canonical + observe_sir_relational_link
两消费者。方案 C: jarvis_utils.is_system_event_text 单一真理源 (4 前缀) + worker:2184
改调它 + writeback 闭包入口加闸 (整条 skip, 含 COOCCUR)。

覆盖 (顾问硬命门):
  ④ helper 单测: 4 前缀全 True / Sir 原话 False / 空串 False
  ③ 路径乙专项 (红线命门): clean_intent=[SYSTEM BACKGROUND EVENT]... (非 [后台系统) → skip
  ⑤ worker 等价 (零回归): 改 helper 后 worker _is_system_event 对 4 前缀判定逐字不变
  ① 改后绿: 合成 reminder 含妈妈 → 闸命中 → 无新 canonical 链 + 无新 SAID 边
  ②a 不误杀: Sir 真原话含亲属词 → 闸不命中 → 正常建 canonical
  ②b 不误杀: Sir 真原话 turn → 闸不命中 (COOCCUR 整条不被误杀)
  ⑥ __NUDGE__ 路径不受影响 (闸只在 stream_chat writeback, nudge 文本非系统前缀)
"""
from __future__ import annotations

import os
import sys
import json
import time
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_utils import is_system_event_text, _SYSTEM_EVENT_PREFIXES


# 模拟 writeback 闭包入口闸 — 与 chat_bypass.py:6116 _run_body_writeback 入口逐字同逻辑。
# (闭包是 stream_chat 内嵌函数无法直接调; 此 helper 复刻入口判定, canonical 部分用真 registry。)
def _writeback_gate_skips(su: str, ci: str) -> bool:
    """复刻 _run_body_writeback 入口闸: is_system_event_text(_su) or is_system_event_text(_ci)。"""
    try:
        if is_system_event_text(su) or is_system_event_text(ci):
            return True
    except Exception:
        pass
    return False


class TestHelperUnit(unittest.TestCase):
    """④ helper 单测。"""

    def test_04_all_prefixes_true(self):
        for p in _SYSTEM_EVENT_PREFIXES:
            self.assertTrue(is_system_event_text(p + " 出发去医院陪妈妈"),
                            f"前缀 {p} 应判 True")

    def test_04_sir_real_speech_false(self):
        for s in ("我妈明天来", "记得喝水", "Sir here, mother is visiting tomorrow",
                  "妈妈做手术的事还记得吗"):
            self.assertFalse(is_system_event_text(s), f"Sir 原话 '{s}' 应判 False")

    def test_04_empty_false(self):
        self.assertFalse(is_system_event_text(''))
        self.assertFalse(is_system_event_text(None))

    def test_04_leading_whitespace_tolerated(self):
        self.assertTrue(is_system_event_text("  [SYSTEM ALERT] foo"),
                        "前导空白应被 lstrip 容忍")


class TestPathBGate(unittest.TestCase):
    """③ 路径乙专项 (红线命门): [SYSTEM BACKGROUND EVENT] 非 [后台系统 也 skip。"""

    def test_03_path_b_system_background_skips(self):
        # 路径乙: worker reminder clean_intent = [SYSTEM BACKGROUND EVENT]:...
        ci = "[SYSTEM BACKGROUND EVENT]: 出发去医院陪妈妈"
        su = "[SYSTEM BACKGROUND EVENT]: 出发去医院陪妈妈"
        self.assertTrue(_writeback_gate_skips(su, ci),
                        "🔴 路径乙 [SYSTEM BACKGROUND EVENT] 必须 skip (4 前缀全集生效)")

    def test_03_path_b_not_only_houtai(self):
        # 证: 旧窄判 startswith('[后台系统') 挡不住, 新 helper 挡住
        ci = "[SYSTEM BACKGROUND EVENT]: x"
        self.assertFalse(ci.startswith('[后台系统'),
                         "前提: 路径乙不以 [后台系统 开头 (旧窄判漏)")
        self.assertTrue(is_system_event_text(ci),
                        "🔴 新 helper 必须命中 (不只窄 [后台系统)")

    def test_03_path_a_houtai_also_skips(self):
        # 路径甲: sentinel clean_intent = [后台系统异步唤醒]
        self.assertTrue(_writeback_gate_skips('', '[后台系统异步唤醒]'),
                        "路径甲 [后台系统异步唤醒] 也 skip")


class TestWorkerEquivalence(unittest.TestCase):
    """⑤ worker 等价 (零回归): 改 helper 后 _is_system_event 对 4 前缀判定逐字不变。"""

    def _old_inline(self, cmd: str) -> bool:
        """改前 worker:2184 inline 逻辑 (基准)。"""
        return (
            cmd.startswith('[SYSTEM BACKGROUND EVENT]')
            or cmd.startswith('[系统主动提醒]')
            or cmd.startswith('[SYSTEM ALERT]')
            or cmd.startswith('[后台系统异步唤醒]')
        )

    def test_05_equivalence_across_cases(self):
        cases = [
            '[SYSTEM BACKGROUND EVENT]: 出发去医院陪妈妈',
            '[系统主动提醒]: 喝水',
            '[SYSTEM ALERT] OpenRouter fallback active',
            '[后台系统异步唤醒]',
            '我妈明天来',
            '记得喝水',
            '',
            'Sir here',
            '[SYSTEM] partial not matching',  # 非完整前缀
        ]
        for cmd in cases:
            self.assertEqual(
                self._old_inline(cmd), is_system_event_text(cmd),
                f"worker 等价破: cmd={cmd!r} old={self._old_inline(cmd)} "
                f"new={is_system_event_text(cmd)}")


class TestCanonicalWriteSkipVsBuild(unittest.TestCase):
    """① 改后绿 (合成 → 无新链) + ②a 不误杀 (Sir 原话 → 建链)。

    用真 CanonicalEntityRegistry + 真 lookup_kinship_surfaces, 隔离临时 registry 文件。
    复刻 _run_body_writeback 入口闸 + canonical 分支 (与 chat_bypass:6116 同逻辑)。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='wb_gate_')
        self.reg_path = os.path.join(self.tmp, 'canonical_entities.json')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_writeback_canonical(self, su: str, ci: str, tid: str):
        """复刻 chat_bypass:6116 闭包: 入口闸 + canonical 分支 (隔离 registry)。"""
        from jarvis_canonical_entities import (
            CanonicalEntityRegistry, lookup_kinship_surfaces)
        # 入口闸 (本片新增)
        if _writeback_gate_skips(su, ci):
            return None  # 整条 skip
        reg = CanonicalEntityRegistry(path=self.reg_path)
        if su.strip():
            hits = lookup_kinship_surfaces(su)
            for surface, (cid, label, rel) in hits:
                resolved = reg.resolve_surface_to_cid(surface)
                if resolved is None and reg._alias_links.get(
                        surface, {}).get('status') == 'revoked':
                    continue
                gref = {"source_kind": "exact", "ref": "kinship_exact",
                        "ts": time.time(), "detail": f"kinship:{surface}->{cid}"}
                reg.create_canonical_entity(
                    cid, {"canonical_label": label, "relation_to_sir": rel}, [gref])
                reg.add_canonical_alias_link(surface, cid, source="exact",
                                             ref=(tid or "kinship_exact"))
                reg.touch(cid, tid)
            reg.save()
        return reg

    def test_01_synthetic_reminder_builds_nothing(self):
        # 合成 reminder fire 含 "妈妈" — 闸命中 → 整条 skip → 无 registry 文件 / 无链
        su = "[SYSTEM BACKGROUND EVENT]: 出发去医院陪妈妈 (步行)"
        ci = "[后台系统异步唤醒]"
        reg = self._run_writeback_canonical(su, ci, 'turn_synth_001')
        self.assertIsNone(reg, "合成 reminder 应整条 skip (返 None)")
        self.assertFalse(os.path.exists(self.reg_path),
                         "🔴 合成事件不应建 canonical registry 文件")

    def test_02a_real_sir_speech_builds_canonical(self):
        # Sir 真原话含亲属词 → 闸不命中 → 正常建 person:mother
        su = "我妈明天来看我"
        ci = "我妈明天来看我"
        reg = self._run_writeback_canonical(su, ci, 'turn_real_001')
        self.assertIsNotNone(reg, "Sir 原话不应被 skip")
        cid = reg.resolve_surface_to_cid("我妈")
        self.assertEqual(cid, "person:mother",
                         "Sir 原话 '我妈' 应正常建 person:mother canonical 链")

    def test_02a_real_sir_mama_builds(self):
        su = "妈妈做手术的事我一直记着"
        reg = self._run_writeback_canonical(su, su, 'turn_real_002')
        self.assertIsNotNone(reg)
        self.assertEqual(reg.resolve_surface_to_cid("妈妈"), "person:mother")


class TestCoOccurAndNudge(unittest.TestCase):
    """②b COOCCUR 不误杀 + ⑥ __NUDGE__ 路径不受影响。"""

    def test_02b_real_turn_not_skipped(self):
        # Sir 真原话 turn → 闸不命中 → COOCCUR 会跑 (整条不被误杀)
        self.assertFalse(_writeback_gate_skips("今天和妈妈通了电话", "今天和妈妈通了电话"),
                         "Sir 真原话 turn 不应被闸 skip (COOCCUR 不误杀)")

    def test_06_nudge_text_not_system_prefix(self):
        # __NUDGE__ push 文本 (CommitmentWatcher/ReturnSentinel) 不带系统前缀,
        # 且 nudge 走 stream_nudge 不经本闸; 这里验 nudge 内容本身不会误命中 helper。
        for nudge in ("__NUDGE__: Sir, it's time to rest.",
                      "Welcome back, Sir.",
                      "It's 7 AM, time to head to the hospital."):
            self.assertFalse(is_system_event_text(nudge),
                             f"nudge 文本 '{nudge}' 不应命中系统前缀")


if __name__ == "__main__":
    unittest.main(verbosity=2)
