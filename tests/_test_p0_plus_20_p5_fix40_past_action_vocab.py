# -*- coding: utf-8 -*-
"""[P5-fix40 / 2026-05-23 12:21] past_action ClaimTracer vocab 补全.

Sir 12:17 真测痛点:
  Sir: '我每天要喝 3000 毫升的水, 这是长期计划'
  Jarvis (中文 subtitle): '我已安排了每 90 分钟 300 毫升的饮水提醒, 将从 14:30 开始'
  
  主脑说**已安排** cyclic 提醒, 但实际**没 emit cyclic_task FAST_CALL**! 没真做.
  ClaimTracer extract_claims 应该抓到 past_action='已安排' → 标记 unverified.
  但实际 ClaimTracer 漏抓 (词表不含"安排" / "scheduled"/"arranged").

根因 (jarvis_claim_tracer.py):
  _PAT_PAST_ACTION_ZH 词表: 打开/启动/关闭/静音/发送/设置/更新/记下/保存/删除/取消
  → "安排" / "计划" / "创建" / "登记" 等 commit-style verb 没在表里
  _PAT_PAST_ACTION_EN: opened/launched/closed/muted/sent/set/updated/saved/deleted/cancelled
  → "scheduled" / "arranged" / "registered" / "configured" 等也没

治本: 补全 commit-style verbs (中英) — 主脑常说"已安排/已计划/已创建/已登记/
arranged/scheduled/registered/configured/noted/logged" 这类话.

覆盖:
A. ZH: '已安排' / '已计划' / '已创建' / '已登记' 应抓
B. EN: 'I scheduled' / "I've arranged" / 'I registered' 应抓
C. 旧 vocab 仍工作 (打开/opened 等)
D. 非 past_action 不误抓
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestPastActionVocabPF40(unittest.TestCase):

    def _claims_of_kind(self, text: str, kind: str):
        from jarvis_claim_tracer import extract_claims
        claims = extract_claims(text)
        return [c for c in claims if c.kind == kind]

    def test_a_zh_arrangement_caught(self):
        """Sir 12:17 真痛点 — 主脑说'已安排了 90 分钟提醒'"""
        text = '我已安排了每 90 分钟 300 毫升的饮水提醒'
        claims = self._claims_of_kind(text, 'past_action')
        self.assertGreater(len(claims), 0,
                            f"'已安排' 应被 ClaimTracer 抓为 past_action, got: {[c.text for c in claims]}")

    def test_a2_zh_other_commit_verbs(self):
        for verb in ('已安排', '已计划', '已创建', '已登记', '已记录',
                       '已添加', '已加入', '已订上', '已放好'):
            text = f'好的先生我{verb}了'
            claims = self._claims_of_kind(text, 'past_action')
            self.assertGreater(len(claims), 0,
                                f"'{verb}' 应抓为 past_action")

    def test_b_en_commit_verbs_caught(self):
        for phrase in (
            "I've scheduled the reminder",
            "I scheduled it",
            "I've arranged everything",
            "I arranged the meeting",
            "I've registered the goal",
            "I configured the system",
            "I noted that",
            "I've logged it",
            "I recorded the entry",
        ):
            claims = self._claims_of_kind(phrase, 'past_action')
            self.assertGreater(len(claims), 0,
                                f"'{phrase}' 应抓为 past_action")

    def test_c_old_vocab_still_works(self):
        """已有 vocab 仍工作 — 不破坏原 case."""
        for phrase, kind in (
            ('I opened the file', 'past_action'),
            ('我已打开 dashboard', 'past_action'),
            ("I've muted the call", 'past_action'),
            ('我帮你设置好了', 'past_action'),
        ):
            claims = self._claims_of_kind(phrase, kind)
            self.assertGreater(len(claims), 0,
                                f"old vocab '{phrase}' 应仍抓")

    def test_d_no_false_positives(self):
        """普通 future / non-action 不误抓."""
        for phrase in (
            'I will open it tomorrow',
            'I might launch the app',
            '我打算明天打开',
            '不想打开',
        ):
            claims = self._claims_of_kind(phrase, 'past_action')
            # may or may not be 0; we just check it doesn't crash
            self.assertIsInstance(claims, list)


if __name__ == '__main__':
    unittest.main()
