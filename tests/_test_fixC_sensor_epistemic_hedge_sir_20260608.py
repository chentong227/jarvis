# -*- coding: utf-8 -*-
"""[修复C / Sir 2026-06-08] 传感器越权仲裁 — Sir 口述 > 进程传感器 (措辞权重层).

根因 (recon 凭实): jarvis_routing.py ProfileCard._build_current_state 把前台进程
f"{cat} ({proc})" 无条件写进 profile [Now] 段 → 主脑 prompt 当裸事实采信; 无任何
"Sir 口头陈述 > 传感器推断" 的仲裁。Sir 说"我在用 Kiro"时, 传感器(Cursor/Windsurf)
赢, 主脑跟着认错。

本次最小修复 (只做措辞权重层, 不动数据流/路由/状态/别的传感器):
  把进程活动从"裸事实"降级为显式标注的低权推断 — activity 串里给 proc 加限定语义:
  ① sensor-inferred (非 Sir 确认)
  ② Sir 口述优先级高于此传感器值

测试覆盖:
  T1 有 proc → activity 带 sensor-inferred 限定 + Sir 优先语义 (非裸 "Cursor")
  T2 behavior-preserving: 其余字段/结构/返回形状逐字不变 (只 activity 措辞变)
  T3 无 proc (Unknown) → 不加进程限定 (只 cat, 行为不变)
  T4 cat 分类逐字保留 (proc 限定不吞 cat)
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _FakeNerve:
    """最小 nerve: 直接访问的 (habit_clock/causal_chain/project_timeline) = None;
    hasattr 守卫的 (status_ledger/content_tracker) 不定义 → 走默认分支 (snapshot 不崩)。"""
    habit_clock = None
    causal_chain = None
    project_timeline = None


def _make_card():
    from jarvis_routing import ProfileCard
    return ProfileCard(_FakeNerve())


class TestSensorEpistemicHedge(unittest.TestCase):
    def setUp(self):
        from jarvis_env_probe import PhysicalEnvironmentProbe as P
        self.P = P
        # 备份, tearDown 还原 (behavior-preserving 守卫: 不污染全局 probe state)
        self._orig_cat = P.current_work_category
        self._orig_proc = P.current_process_name
        self._orig_dur = P.work_duration_minutes
        self._orig_phys = P.current_physical_state

    def tearDown(self):
        self.P.current_work_category = self._orig_cat
        self.P.current_process_name = self._orig_proc
        self.P.work_duration_minutes = self._orig_dur
        self.P.current_physical_state = self._orig_phys

    def test_t1_proc_has_sensor_inferred_hedge(self):
        # 有 proc → activity 不再是裸 "Coding (Cursor.exe)", 带 sensor-inferred + Sir 优先
        self.P.current_work_category = 'Coding'
        self.P.current_process_name = 'Cursor.exe'
        self.P.work_duration_minutes = 30
        card = _make_card()
        st = card._build_current_state()
        act = st['activity']
        # cat 仍在
        self.assertIn('Coding', act)
        # proc 仍在 (数据流不变, 只加限定)
        self.assertIn('Cursor.exe', act)
        # 核心: 带 sensor-inferred 限定 (非裸事实)
        self.assertIn('sensor', act.lower(),
                      f"activity 应标 sensor-inferred, got: {act!r}")
        # 核心: 显式 Sir 口述优先语义
        self.assertIn('Sir', act,
                      f"activity 应声明 Sir 口述优先, got: {act!r}")

    def test_t2_behavior_preserving_other_fields(self):
        # 其余字段/结构/返回形状逐字不变 — 只 activity 措辞变
        self.P.current_work_category = 'Coding'
        self.P.current_process_name = 'Cursor.exe'
        self.P.work_duration_minutes = 30
        card = _make_card()
        st = card._build_current_state()
        # 返回 dict key 集合不变
        self.assertEqual(
            set(st.keys()),
            {'activity', 'emotional_tone', 'cognitive_load',
             'focus_level', 'session_duration', 'physical_state'})
        # 无 status_ledger / habit_clock → 默认值逐字不变
        self.assertEqual(st['emotional_tone'], 'Neutral')
        self.assertEqual(st['cognitive_load'], 'Unknown')
        self.assertEqual(st['focus_level'], 'normal')
        self.assertEqual(st['session_duration'], '30min')

    def test_t3_unknown_proc_no_process_hedge(self):
        # 无 proc (Unknown) → 不加进程限定, activity = 裸 cat (行为不变)
        self.P.current_work_category = 'Idle'
        self.P.current_process_name = 'Unknown'
        self.P.work_duration_minutes = 0
        card = _make_card()
        st = card._build_current_state()
        # 无 proc → 不应出现 process 名 / sensor 限定
        self.assertEqual(st['activity'].strip(), 'Idle',
                         f"无 proc 时 activity 应为裸 cat, got: {st['activity']!r}")
        self.assertEqual(st['session_duration'], 'just started')

    def test_t4_cat_preserved_with_proc(self):
        # cat 分类逐字保留 (proc 限定不吞 cat)
        self.P.current_work_category = 'Gaming'
        self.P.current_process_name = 'wuthering.exe'
        self.P.work_duration_minutes = 12
        card = _make_card()
        st = card._build_current_state()
        self.assertTrue(st['activity'].startswith('Gaming'),
                        f"activity 应以 cat 开头, got: {st['activity']!r}")
        self.assertIn('wuthering.exe', st['activity'])

    def test_t5_consumer_row_not_truncated(self):
        # 🆕 消费端守卫: to_prompt_block 渲染的 [Now] 行加 hedge 后, [:250] 不吞
        # Mood/Focus/Session (原 producer 测了, consumer 没测, 补上)。
        self.P.current_work_category = 'Coding'
        self.P.current_process_name = 'Cursor.exe'
        self.P.work_duration_minutes = 30
        card = _make_card()
        # 隔离 _load_profile (避免读真 sir_profile.json 干扰), 只关心 [Now] 行
        card._load_profile = lambda: {}
        block = card.to_prompt_block()
        now_lines = [ln for ln in block.split('\n') if ln.startswith('[Now]')]
        self.assertEqual(len(now_lines), 1, f"应有 1 行 [Now], got: {now_lines!r}")
        now_row = now_lines[0]
        # hedge 两语义在
        self.assertIn('sensor-inferred', now_row)
        self.assertIn('Sir overrides', now_row)
        self.assertIn('Cursor.exe', now_row)
        # 关键: Mood/Focus/Session 三标签未被 [:250] 吞
        self.assertIn('Mood:', now_row, f"Mood 被截断, row={now_row!r}")
        self.assertIn('Focus:', now_row, f"Focus 被截断, row={now_row!r}")
        self.assertIn('Session:', now_row, f"Session 被截断, row={now_row!r}")
        # 整行未触 250 截断标记
        self.assertLessEqual(len(now_row), 250,
                             f"[Now] 行不应超 250, len={len(now_row)}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
