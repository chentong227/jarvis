# -*- coding: utf-8 -*-
"""[放权 T0.2 / Sir 2026-06-01] 回路外机械墙 (no_fabrication) — record-only.

真相源 docs/JARVIS_LETTING_GO_ROLLOUT.md §0/§3 (第 0 格 T0.2)。
机械墙 = 回路外真兜底: 确定性 (无 vocab/LLM), 系统改不动 (原语硬编码), breach=硬证。

覆盖:
  T1  grounded past-action (tool_results 有 ✅) → 无 breach
  T2  ungrounded past-action ("已设置" 但 tool_results 空) → breach
  T3  hedge ("I think about 5") → 不算 breach (非硬断言)
  T4  non-past-action claim (count/number) → 墙不判 (留给回路内 ClaimTracer)
  T5  ungrounded past-action ("已删除") → breach
  T6  确定性: 同输入跑两次结果一致 (无随机/LLM)
  T7  breach 写 ledger (record-only) + breach_count 读硬证
  T8  空 reply / 无 claim → checked 但 0 breach
  T9  墙不读 vocab JSON (回路外: 删/改 integrity_claim_vocab 不影响墙判定)
  T10 镜像实测回归: 引用真实过去时间戳 ("created at 20:37") 不该误报 breach
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class TestIntegrityWallT02(unittest.TestCase):
    def setUp(self):
        import jarvis_integrity_wall as wall
        self.wall = wall
        wall.reset_session_count_for_test()
        # 每个测试用临时 ledger, 不污染真 memory_pool
        self._td = tempfile.TemporaryDirectory()
        self._ledger = os.path.join(self._td.name, "breach.jsonl")
        self._patch = patch.object(wall, "_BREACH_LEDGER_PATH", self._ledger)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._td.cleanup()
        self.wall.reset_session_count_for_test()

    def test_t1_grounded_past_action_no_breach(self):
        r = self.wall.check_reply(
            jarvis_reply="I've set the reminder for you, Sir.",
            tool_results=["✅ add_reminder success: reminder set"],
            turn_id="t1", record=True)
        self.assertTrue(r["checked"])
        self.assertEqual(r["n_breach"], 0, f"grounded 不该 breach: {r}")

    def test_t2_ungrounded_past_action_breach(self):
        r = self.wall.check_reply(
            jarvis_reply="I've opened the dashboard for you.",
            tool_results=[],  # 没有任何成功标记 = 假装完成
            turn_id="t2", record=True)
        self.assertGreaterEqual(r["n_breach"], 1,
                                f"无据 past-action 该 breach: {r}")

    def test_t3_hedge_no_breach(self):
        r = self.wall.check_reply(
            jarvis_reply="I think you've had about 5 cups today, roughly.",
            tool_results=[], turn_id="t3", record=True)
        self.assertEqual(r["n_breach"], 0, f"hedge 不是硬断言: {r}")

    def test_t4_non_past_action_claim_ignored(self):
        # 收窄后: count/number claim 不归回路外墙 (留回路内 ClaimTracer)。
        r = self.wall.check_reply(
            jarvis_reply="You worked 87 hours this week.",
            tool_results=["status: nothing logged"],
            turn_id="t4", record=True)
        self.assertEqual(r["n_breach"], 0,
                         f"非 past_action claim 墙不判: {r}")

    def test_t5_ungrounded_past_action_breach(self):
        r = self.wall.check_reply(
            jarvis_reply="I've deleted all the temporary records for you.",
            tool_results=[],  # 零成功证据 = 假装完成
            stm_recent=[], turn_id="t5", record=True)
        self.assertGreaterEqual(r["n_breach"], 1,
                                f"无据 past-action 该 breach: {r}")

    def test_t6_deterministic(self):
        kw = dict(jarvis_reply="I've saved the configuration file.",
                  tool_results=[], turn_id="t6", record=False)
        r1 = self.wall.check_reply(**kw)
        r2 = self.wall.check_reply(**kw)
        self.assertEqual(r1["n_breach"], r2["n_breach"],
                         "确定性: 同输入同输出")
        self.assertEqual([b["kind"] for b in r1["breaches"]],
                         [b["kind"] for b in r2["breaches"]])

    def test_t7_breach_written_to_ledger(self):
        self.wall.check_reply(
            jarvis_reply="I've launched the app and set 99 alarms.",
            tool_results=[], turn_id="t7", record=True)
        self.assertTrue(os.path.exists(self._ledger))
        n = self.wall.breach_count(ledger_path=self._ledger)
        self.assertGreaterEqual(n, 1)
        stats = self.wall.breach_stats(ledger_path=self._ledger)
        self.assertGreaterEqual(stats["total_breaches"], 1)
        self.assertGreaterEqual(stats["session_breaches"], 1)

    def test_t8_empty_and_no_claim(self):
        r0 = self.wall.check_reply(jarvis_reply="", turn_id="t8a")
        self.assertEqual(r0["n_breach"], 0)
        r1 = self.wall.check_reply(
            jarvis_reply="Understood, Sir.", tool_results=[], turn_id="t8b")
        self.assertEqual(r1["n_breach"], 0, "社交语无 specific claim")

    def test_t9_wall_ignores_vocab_json(self):
        # 回路外铁律: 墙判定不依赖 integrity_claim_vocab.json。
        # 即便指向一个不存在/被改的 vocab 路径, 墙仍确定性判 breach。
        fake_vocab = os.path.join(self._td.name, "tampered_vocab.json")
        with open(fake_vocab, "w", encoding="utf-8") as f:
            json.dump({"patterns": []}, f)  # 空 vocab = 想让 tracer 啥都不抓
        # 墙不读这个文件, 仍该抓到无据 past-action
        r = self.wall.check_reply(
            jarvis_reply="I've deleted all the records.",
            tool_results=[], turn_id="t9", record=False)
        self.assertGreaterEqual(r["n_breach"], 1,
                                "墙是回路外: 不被 vocab 篡改影响")

    def test_t10_true_past_timestamp_no_false_breach(self):
        # 镜像实测回归: 主脑诚实回复引用真实过去时间戳 + 明确说"无记录" →
        # 老逻辑把 "20:37" time claim 当 fabrication 误报。收窄后墙只判 past_action,
        # 此句无"已做X" past_action → 0 breach。
        reply = ("I cannot confirm a completed backup, Sir. The logs show a "
                 "directory was created at 20:37, but I have no record of a "
                 "successful file transfer. Shall I verify the D drive?")
        r = self.wall.check_reply(
            jarvis_reply=reply, tool_results=[], turn_id="t10", record=True)
        self.assertEqual(r["n_breach"], 0,
                         f"诚实回复引用真过去时间戳不该误报: {r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
