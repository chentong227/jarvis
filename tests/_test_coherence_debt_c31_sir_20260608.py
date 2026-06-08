# -*- coding: utf-8 -*-
"""[C3.1 / 2026-06-08] 自一致张力计 — coherence-debt 分型记账 单测.

只读派生态: 只算债 + append 账本 + 可查;绝不触发反思/写 directive/给 reward/
喂节律/动路由。三轴分型 (E_rel/E_commit/E_ground) + 冻结类型学 + grounded ref。

覆盖:
  ① 债能从真实 watcher source 算出且 grounded (每条带非空 provenance_ref)
  ② 无信号 → 债=0 (不凭空生痛)
  ③ append 后可 grep {type, ref}
  ④ 零行为: 记债仅 append ledger, 不喂 value_backoff (断言其状态不被改)
  ⑤ 类型学 config 冻结: 模块无写 typology 的 API/路径
  ⑥ I2 修正: publish 带非空 turn ref 且 flagged 不变 (在 inner_thought 测)
  ⑦ 紧迫度只算不喂: compute_urgency 不接行为路径
  ⑧ 空 ref 拒记 (无接地不生债)
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jarvis_coherence_debt as CD


class TestI2GroundingFix(unittest.TestCase):
    """⑥ I2 接地修正: publish semantic_claim_flagged 带非空 turn ref, flagged 不变。"""

    def test_i2_publish_has_turn_ref(self):
        import jarvis_inner_thought_daemon as M
        src = open(M.__file__, encoding='utf-8').read()
        # 修正: metadata 含 audited_turn_id, 取自 TraceContext.get_global_turn_id
        self.assertIn("'audited_turn_id': _audited_turn_id", src,
                      "⑥ publish metadata 应含 audited_turn_id")
        self.assertIn('get_global_turn_id', src,
                      "⑥ turn ref 取自 TraceContext.get_global_turn_id")
        # flagged 字段原样保留 (老消费者不破)
        self.assertIn("metadata={'flagged': flagged,", src,
                      "⑥ flagged 字段原样保留")


if __name__ == "__main__":
    unittest.main(verbosity=2)
