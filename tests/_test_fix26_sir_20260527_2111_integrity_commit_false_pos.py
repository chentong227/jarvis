# -*- coding: utf-8 -*-
"""[Sir 2026-05-27 21:11 真测 P2] IntegrityWatcher commitment 假阳修复.

真测 log 反例 (旧 vocab 误抓):
  - "Understood. I shall keep the commentary to a minimum and focus on the
     task at hand." → 旧版抓 commitment claim (action='Understood')
  - "明白" 单 ack → 旧版抓 commitment claim (action='明白')

这俩**不是承诺**, 是普通 ack 词. 旧 pattern:
  EN: `(?:got\s+it|noted|understood|locked\s+in|saved|recorded|will\s+hold\s+you)`
  ZH: `(?:记下了|记住了|收到|明白|这就|帮您记|记到|没问题)`
→ 单词出现就匹配, 太宽松.

修法 (准则 6 三维耦合):
  - vocab json 持久化 (memory_pool/integrity_claim_vocab.json) — 主路径
  - .py _FALLBACK_DETECTORS 同步 (vocab json 缺失时兜底)
  - CLI scripts/integrity_claim_vocab_dump.py 可改 (已有)
  - L7 reflector TODO (vocab json _meta 已注)

新规则:
  - 单 ack ('Understood' / '明白' / 'Got it') 必须跟 commit verb (remind /
    track / hold / register / set / monitor / follow / ...) 才算 commitment
  - 单 phrase commit ("I'll hold you to that" / "Consider it done" /
    "记下了" / "这就帮你...") 保留 — 本身就是承诺
"""
from __future__ import annotations

import os
import sys
import unittest


_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)


class TestCommitmentFalsePositive(unittest.TestCase):
    """🩹 单 ack 词不该被抓 commitment."""

    def setUp(self):
        from jarvis_integrity_watcher import reset_vocab_cache
        reset_vocab_cache()

    def _get_commitment_hits(self, text: str):
        from jarvis_integrity_watcher import detect_claims_via_regex
        hits = detect_claims_via_regex(text) or []
        return [h for h in hits if h.get('claim_type') == 'commitment']

    def test_false_positive_understood_alone(self):
        """'Understood.' 单独 → 不该抓."""
        text = "Understood. I shall keep the commentary to a minimum and focus on the task at hand."
        self.assertEqual(self._get_commitment_hits(text), [],
                         f'Should NOT match commitment on ack-only: {text!r}')

    def test_false_positive_mingbai_alone(self):
        """'明白.' 单独 → 不该抓."""
        text = "明白. 我会努力让我的观察更易理解."
        self.assertEqual(self._get_commitment_hits(text), [],
                         f'Should NOT match commitment on ack-only: {text!r}')

    def test_false_positive_got_it_alone(self):
        """'Got it.' 单独 → 不该抓."""
        for text in ("Got it.", "Got it, Sir.", "Noted.", "Noted, Sir."):
            self.assertEqual(self._get_commitment_hits(text), [],
                             f'Should NOT match: {text!r}')

    def test_false_positive_zh_ack_alone(self):
        """ZH ack 词单独 → 不该抓."""
        for text in ("没问题.", "收到, 先生.", "好的好的, 没问题.", "明白了."):
            self.assertEqual(self._get_commitment_hits(text), [],
                             f'Should NOT match: {text!r}')


class TestCommitmentTruePositive(unittest.TestCase):
    """🟢 真承诺必须能抓到."""

    def setUp(self):
        from jarvis_integrity_watcher import reset_vocab_cache
        reset_vocab_cache()

    def _get_commitment_hits(self, text: str):
        from jarvis_integrity_watcher import detect_claims_via_regex
        hits = detect_claims_via_regex(text) or []
        return [h for h in hits if h.get('claim_type') == 'commitment']

    def test_true_positive_hold_you_to_that(self):
        for text in ("I'll hold you to that, Sir.",
                     "I will hold you to that.",
                     "i'll hold you to this"):
            self.assertGreater(
                len(self._get_commitment_hits(text)), 0,
                f'Should match phrase commit: {text!r}'
            )

    def test_true_positive_consider_it_done(self):
        for text in ("Consider it done.",
                     "Consider that done, Sir.",
                     "Consider it locked.",
                     "Consider it noted."):
            self.assertGreater(
                len(self._get_commitment_hits(text)), 0,
                f'Should match phrase commit: {text!r}'
            )

    def test_true_positive_ack_plus_commit_verb_en(self):
        """单 ack 跟 commit verb → 算 commit."""
        for text in ("Got it, Sir. I'll remind you in 10 minutes.",
                     "Noted, I'll track that for you.",
                     "Understood, I'll register your reminder.",
                     "Locked in. I'll monitor your hydration."):
            self.assertGreater(
                len(self._get_commitment_hits(text)), 0,
                f'Should match ack+verb: {text!r}'
            )

    def test_true_positive_zh_self_commit(self):
        """ZH 单 phrase commit. (text 至少 5 字符, detect_claims_via_regex
        filter `< 5`.)
        """
        for text in ("好的, 记下了.",
                     "记住了, 先生.",
                     "这就帮你设个 5 分钟闹钟.",
                     "马上帮你登记一下.",
                     "帮您记到提醒清单了."):
            self.assertGreater(
                len(self._get_commitment_hits(text)), 0,
                f'Should match ZH commit: {text!r}'
            )

    def test_true_positive_zh_ack_plus_verb(self):
        """ZH ack + verb."""
        for text in ("收到, 我帮你跟进进度.",
                     "好的, 我帮你登记一下.",
                     "没问题, 我提醒您."):
            self.assertGreater(
                len(self._get_commitment_hits(text)), 0,
                f'Should match ZH ack+verb: {text!r}'
            )


class TestRevisionMetaDocumented(unittest.TestCase):
    """vocab json _revision_note 注明本次改动原因 (准则 6)."""

    def test_vocab_has_revision_note(self):
        import json
        path = os.path.join(_REPO, 'memory_pool', 'integrity_claim_vocab.json')
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        commit = data['patterns']['commitment']
        self.assertIn('_revision_note', commit)
        self.assertIn('Sir 2026-05-27 21:11', commit['_revision_note'])

    def test_fallback_py_synced(self):
        """fallback .py _RE_COMMITMENT_EN/ZH 同步 (vocab json 缺失时兜底)."""
        import re
        from jarvis_integrity_watcher import (
            _RE_COMMITMENT_EN, _RE_COMMITMENT_ZH,
        )
        # 反例不命中 .py fallback
        self.assertIsNone(_RE_COMMITMENT_EN.search(
            "Understood. I shall keep the commentary."
        ))
        self.assertIsNone(_RE_COMMITMENT_ZH.search(
            "明白. 我会努力让我的观察更易理解."
        ))
        # 正例命中
        self.assertIsNotNone(_RE_COMMITMENT_EN.search(
            "I'll hold you to that, Sir."
        ))
        self.assertIsNotNone(_RE_COMMITMENT_ZH.search(
            "记下了."
        ))


if __name__ == '__main__':
    unittest.main(verbosity=2)
