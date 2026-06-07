# -*- coding: utf-8 -*-
"""[innerthought-read-promise / 2026-06-07] InnerThought 读结构化 promise (体).

顾问转 agent · 修-识读体. 对症失真②(母亲渲成"到访/方向反"):
根因 InnerThought _build_prompt 从不读 promise store, 只啃 STM 5-turn 截断摘要猜.

本测覆盖:
  T1 _collect_active_promises 选 pending/overdue/untracked (未 fulfilled/cancelled)
  T2 fulfilled 近 24h 仍收 (覆盖"刚做完"); 老 fulfilled (>24h) 不收
  T3 cancelled 永不收
  T4 字段精简: 只 description/deadline_str/state/who_promised(/fulfilled_at),
     绝不含 evidence[] (cw_nudge_fired 噪音)
  T5 离散排序: 有 deadline 优先, 无相似度 (纯字段)
  T6 母亲情境重放: 喂 p_434796c0 (下午去医院看望母亲) →
     _build_prompt 含 [ACTIVE PROMISES ...] block + 含该 description +
     不含 cw_nudge 噪音字样
  T7 block 头标注 "GROUNDED FACTS" (和 STM 片段区分)
  T8 不回归: 现有 15 个 evidence key 仍在 (active_promises 是新增, 不挤掉旧)
"""
from __future__ import annotations

import os
import sys
import time
import tempfile
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_daemon():
    from jarvis_inner_thought_daemon import InnerThoughtDaemon
    return InnerThoughtDaemon(key_router=MagicMock())


def _fresh_log():
    """隔离 promise log 单例到 temp 文件."""
    import jarvis_promise_log as pl
    tmp = tempfile.mktemp(suffix='.json')
    pl.reset_default_log_for_test(persist_path=tmp)
    return pl.get_default_log()


class TestCollectActivePromises(unittest.TestCase):
    def setUp(self):
        self.daemon = _make_daemon()
        self.log = _fresh_log()

    def _add(self, desc, state='pending', deadline='', author='sir',
             fulfilled_at=0.0, evidence=None):
        from jarvis_promise_log import Promise
        import uuid
        pid = 'p_' + uuid.uuid4().hex[:8]
        p = Promise(
            id=pid, description=desc, kind='commitment',
            deadline_str=deadline, state=state, author=author,
            who_promised=author,
        )
        p.fulfilled_at = fulfilled_at
        if evidence:
            p.evidence = evidence
        self.log.promises[pid] = p
        return pid

    def test_t1_selects_pending_overdue_untracked(self):
        self._add('pending one', state='pending')
        self._add('overdue one', state='overdue')
        self._add('untracked one', state='untracked')
        out = self.daemon._collect_active_promises(max_n=6)
        descs = {e['description'] for e in out}
        self.assertIn('pending one', descs)
        self.assertIn('overdue one', descs)
        self.assertIn('untracked one', descs)

    def test_t2_fulfilled_recent_in_old_out(self):
        now = time.time()
        self._add('just done', state='fulfilled', fulfilled_at=now - 3600)
        self._add('old done', state='fulfilled', fulfilled_at=now - 200000)
        out = self.daemon._collect_active_promises(max_n=6)
        descs = {e['description'] for e in out}
        self.assertIn('just done', descs, 'fulfilled 近 24h 应收 (覆盖刚做完)')
        self.assertNotIn('old done', descs, 'fulfilled >24h 不收')

    def test_t3_cancelled_never(self):
        self._add('cancelled one', state='cancelled')
        out = self.daemon._collect_active_promises(max_n=6)
        descs = {e['description'] for e in out}
        self.assertNotIn('cancelled one', descs)

    def test_t4_fields_pruned_no_evidence_noise(self):
        noise = [
            {'when': time.time(), 'kind': 'cw_nudge_fired',
             'what': 'CW daemon fired nudge: x @ deadline_ts=1'}
            for _ in range(20)
        ]
        self._add('go visit', state='pending', deadline='2026-06-07 15:00:00',
                  evidence=noise)
        out = self.daemon._collect_active_promises(max_n=6)
        self.assertEqual(len(out), 1)
        e = out[0]
        self.assertEqual(set(e.keys()),
                         {'description', 'deadline_str', 'state', 'who_promised'})
        # 绝无 evidence / cw_nudge 噪音字段
        self.assertNotIn('evidence', e)
        for v in e.values():
            self.assertNotIn('cw_nudge', str(v))

    def test_t5_discrete_sort_deadline_first(self):
        now = time.time()
        near = time.strftime('%Y-%m-%d %H:%M:%S',
                             time.localtime(now + 3600))
        far = time.strftime('%Y-%m-%d %H:%M:%S',
                            time.localtime(now + 100000))
        self._add('no deadline', state='pending', deadline='')
        self._add('far deadline', state='pending', deadline=far)
        self._add('near deadline', state='pending', deadline=near)
        out = self.daemon._collect_active_promises(max_n=6)
        # 有 deadline 的排前, near 比 far 更前; no-deadline 排最后
        self.assertEqual(out[0]['description'], 'near deadline')
        self.assertEqual(out[1]['description'], 'far deadline')
        self.assertEqual(out[-1]['description'], 'no deadline')


class TestMotherScenarioReplay(unittest.TestCase):
    """T6/T7 母亲情境重放 — 失真② 核心验收."""

    def setUp(self):
        self.daemon = _make_daemon()
        self.log = _fresh_log()

    def test_t6_t7_mother_promise_in_prompt(self):
        from jarvis_promise_log import Promise
        now = time.time()
        noise = [
            {'when': now, 'kind': 'cw_nudge_fired',
             'what': 'CW daemon fired nudge: 下午去医院看望母亲 @ deadline_ts=1780815600'}
            for _ in range(20)
        ]
        p = Promise(
            id='p_434796c0', description='下午去医院看望母亲',
            kind='commitment', deadline_str='2026-06-07 15:00:00',
            state='fulfilled', author='sir', who_promised='sir',
        )
        p.fulfilled_at = now - 1800
        p.evidence = noise
        self.log.promises['p_434796c0'] = p

        # 组 evidence (含 active_promises) + build prompt
        promises = self.daemon._collect_active_promises(max_n=6)
        self.assertTrue(promises, '应收到母亲 promise')
        self.assertEqual(promises[0]['description'], '下午去医院看望母亲')

        ev = {
            'sir_state': 'active', 'idle_seconds': 0, 'hour': 19,
            'swm_events': [], 'stm': [], 'concerns': [],
            'recent_thoughts': [],
            'active_promises': promises,
        }
        system, human = self.daemon._build_prompt('active', ev)
        prompt = system + "\n" + human
        # T6: prompt 含 block + 含 description + 不含 cw_nudge 噪音
        self.assertIn('ACTIVE PROMISES', prompt)
        self.assertIn('下午去医院看望母亲', prompt)
        self.assertNotIn('cw_nudge', prompt)
        # T7: block 头标注 GROUNDED FACTS (和 STM 片段区分)
        self.assertIn('GROUNDED FACTS', prompt)
        # who=sir 渲染进 prompt → 让识知道是 Sir 去看母亲 (非"到访"反向)
        self.assertIn('by sir', prompt)


class TestNoRegression(unittest.TestCase):
    """T8 不回归: active_promises 是新增, 不挤掉旧 evidence 路径."""

    def test_t8_build_prompt_without_promises_still_works(self):
        daemon = _make_daemon()
        ev = {
            'sir_state': 'active', 'idle_seconds': 0, 'hour': 12,
            'swm_events': [], 'stm': [
                {'user': 'hello', 'jarvis': 'hi sir', 'when': '12:00'}
            ],
            'concerns': [], 'recent_thoughts': [],
            # 无 active_promises key → block 不渲染, STM 照常
        }
        system, human = daemon._build_prompt('active', ev)
        prompt = system + "\n" + human
        self.assertIn('STM LAST 5 TURNS', prompt)
        # 无 promise → 不渲染 ACTIVE PROMISES block
        self.assertNotIn('ACTIVE PROMISES', prompt)

    def test_t8b_empty_promises_no_block(self):
        daemon = _make_daemon()
        ev = {
            'sir_state': 'active', 'idle_seconds': 0, 'hour': 12,
            'swm_events': [], 'stm': [], 'concerns': [],
            'recent_thoughts': [], 'active_promises': [],
        }
        system, human = daemon._build_prompt('active', ev)
        prompt = system + "\n" + human
        self.assertNotIn('ACTIVE PROMISES', prompt)


if __name__ == '__main__':
    unittest.main()
