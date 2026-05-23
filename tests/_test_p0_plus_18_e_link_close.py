# -*- coding: utf-8 -*-
"""[P0+18-e / 2026-05-15] 待办链路收口 + d.5/轴5.2/c.99 留尾清扫

修 Sir 20:28-20:32 实测 BUG 链（jarvis_20260515_202835.log）：
- E.1 Memory Correction 兜底无脑覆盖 gate_data_to_save → REMINDER 变 CHAT
       → DB id=747 is_future_task=0 trigger=0 → "代办事项" 永远 queue is clear
- E.2 Memory Correction 后主脑直接出中文-only sentence (无 ---ZH---)
       → splitter 喂 _put_audio → 兜底 Audio Guard 拦下但 log 仍 warn
- E.3 CommitmentWatcher in-memory list，重启就丢
- E.4 终端 Human/Jarvis/Action/Subtitle/Error 色彩化分区

测试设计：以静态源扫描 + DB schema/CRUD 模拟为主，避免依赖运行时 LLM。
"""

import os
import re
import sys
import time
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# [P0+19-0 / 2026-05-16] 拆分后多文件 corpus 扫描垫层
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _source_corpus import read_nerve_corpus


def _read(rel: str) -> str:
    """保留：其它文件（如 jarvis_utils.py）仍直接读。"""
    with open(os.path.join(ROOT, rel), 'r', encoding='utf-8') as f:
        return f.read()


# =================================================================
# E.1 Memory Correction 兜底不再无脑降级 REMINDER 为 CHAT
# =================================================================
class TestE1MemoryCorrectionFallbackPreservesReminder(unittest.TestCase):
    """E.1: Memory Correction "Original record not found" 兜底必须保留上游 REMINDER"""

    def setUp(self):
        self.src = read_nerve_corpus()

    def test_fallback_has_e1_marker(self):
        self.assertIn('P0+18-e.1', self.src,
                      "应有 P0+18-e.1 修复 marker")

    def test_fallback_checks_upstream_future_task(self):
        # 兜底分支应检测 gate_data_list 是否含 is_future_task + trigger_timestamp
        m = re.search(r'P0\+18-e\.1.*?_has_future_with_trigger', self.src, re.DOTALL)
        self.assertIsNotNone(m, "兜底分支应有 _has_future_with_trigger 变量")

    def test_fallback_preserves_list_when_has_future_task(self):
        # 找到 e.1 修复段（截取 _has_future_with_trigger 后 600 字内的内容）
        idx = self.src.find('_has_future_with_trigger = any(')
        self.assertGreater(idx, 0, "应有 _has_future_with_trigger 赋值")
        body = self.src[idx:idx + 600]
        self.assertIn('is_future_task', body)
        self.assertIn('trigger_timestamp', body)

    def test_fallback_reminder_branch_when_time_anchor_only(self):
        # 当 new_val 含时间锚 + 上游无 future_task → 兜底成 REMINDER (is_future_task=True)
        # 🆕 [P5-fix35-emergency / 2026-05-23] 窗口 8000 → 12000:
        # 加 BUG#11 完成态分支 (~1500 char) + 嵌套结构, REMINDER 分支推到 ~8500 char.
        snippet = self.src[self.src.find('P0+18-e.1'):self.src.find('P0+18-e.1') + 12000]
        # 关键守门：time_anchors 词典 + REMINDER 兜底
        self.assertIn('_time_anchors', snippet)
        self.assertIn('需重新确认时间', snippet)
        # 兜底分支必须写 is_future_task: True
        m_block = re.search(r'_new_has_time:.*?"memory_type":\s*"REMINDER".*?"is_future_task":\s*True', snippet, re.DOTALL)
        self.assertIsNotNone(m_block, "时间锚分支应写 REMINDER + is_future_task=True")

    def test_fallback_chat_branch_for_pure_name_correction(self):
        # 当 new_val 不含时间锚 → 仍保留 CHAT 兜底（语义纠正）
        # 🆕 [P5-fix35-emergency / 2026-05-23] 同上, 窗口 8000 → 12000
        snippet = self.src[self.src.find('P0+18-e.1'):self.src.find('P0+18-e.1') + 12000]
        self.assertIn('[纠正]', snippet, "纯语义纠正仍走 [纠正] CHAT 兜底")


# =================================================================
# E.2 上游 Audio Guard —— 中文 sentence 无 ---ZH--- 时自动进 subtitle_mode
# =================================================================
class TestE2UpstreamAudioGuard(unittest.TestCase):
    """E.2: splitter 切句时检测中文 → 自动 subtitle_mode，杜绝中文进 _put_audio"""

    def setUp(self):
        self.src = read_nerve_corpus()

    def test_helper_defined(self):
        self.assertIn('def _sentence_is_chinese_lean', self.src,
                      "应定义 _sentence_is_chinese_lean helper")
        self.assertIn('_CHINESE_CHAR_RE', self.src)

    def test_helper_returns_true_for_three_or_more_cjk(self):
        # 动态 import 检测语义
        from jarvis_nerve import _sentence_is_chinese_lean
        # 1) 多字符 + 多 CJK → True（核心反幻觉场景）
        self.assertTrue(_sentence_is_chinese_lean('并归档了那个已经过期的快递提醒'))
        self.assertTrue(_sentence_is_chinese_lean('我会确保'))
        # 2) 空字符串 / 纯英文 → False
        self.assertFalse(_sentence_is_chinese_lean('Hello Sir'))
        self.assertFalse(_sentence_is_chinese_lean(''))
        # 3) 中英文混合但中文 < 30% → False（非纯中文,不算泄漏）
        self.assertFalse(_sentence_is_chinese_lean('OK Sir, I will handle it now.'))
        self.assertFalse(_sentence_is_chinese_lean('Loading subprocess for project A_v1.'))
        # 4) 中文占比 >30% 算泄漏（即使 < 3 个 CJK）
        self.assertTrue(_sentence_is_chinese_lean('我去'))  # 2 CJK / 2 chars = 100%

    def test_splitter_uses_helper_in_main_streaming(self):
        # 主流式 splitter 应使用 _sentence_is_chinese_lean
        # 至少出现 5 次（主流 / cloud-followup / FAST_CALL flush / GK flush / local fallback）
        cnt = self.src.count('_sentence_is_chinese_lean(sentence)')
        self.assertGreaterEqual(cnt, 5,
                                f"splitter 应至少 5 处使用 _sentence_is_chinese_lean,实际 {cnt}")

    def test_zh_subtitle_route_uses_subtitle_queue(self):
        # 检测到中文后必须 put 到 subtitle_queue
        # 找含 "Audio Guard / Upstream" 的段，验证后续是 subtitle_queue.put(("zh", sentence))
        cnt = self.src.count('subtitle_queue.put(("zh", sentence))')
        self.assertGreaterEqual(cnt, 5, "至少 5 处把中文 sentence 转 subtitle_queue 而非 TTS")


# =================================================================
# E.3 CommitmentWatcher 持久化到 SQLite Commitments 表
# =================================================================
class TestE3CommitmentsSchemaAndCRUD(unittest.TestCase):
    """E.3: SQLite Commitments 表 + CRUD + CW 启动反查"""

    def setUp(self):
        self.hippo_src = _read('jarvis_hippocampus.py')
        self.nerve_src = read_nerve_corpus()

    def test_schema_exists(self):
        self.assertIn('CREATE TABLE IF NOT EXISTS Commitments', self.hippo_src,
                      "应有 Commitments 表 schema")
        self.assertIn('deadline_ts REAL NOT NULL', self.hippo_src)
        self.assertIn('grace_minutes INTEGER DEFAULT 10', self.hippo_src)
        self.assertIn('nudged INTEGER DEFAULT 0', self.hippo_src)
        self.assertIn('is_deleted INTEGER DEFAULT 0', self.hippo_src)

    def test_crud_methods_defined(self):
        for fn in ('add_commitment_row', 'mark_commitment_nudged',
                   'update_commitment_row', 'soft_delete_commitment',
                   'load_active_commitments'):
            self.assertIn(f'def {fn}(self', self.hippo_src,
                          f"Hippocampus 应有 {fn} 方法")

    def test_cw_init_loads_from_db(self):
        self.assertIn('load_active_commitments', self.nerve_src,
                      "CW.__init__ 应调用 load_active_commitments")
        self.assertIn('CommitmentWatcher/Persist', self.nerve_src,
                      "应有 CommitmentWatcher/Persist log marker")

    def test_cw_extract_from_input_persists(self):
        # extract_from_input 添加 in-memory 之前应 add_commitment_row
        # 找到 extract_from_input 的 commitments.append 段，附近应有 add_commitment_row
        m = re.search(r'def extract_from_input\(self.*?self\.commitments\.append', self.nerve_src, re.DOTALL)
        self.assertIsNotNone(m, "找不到 extract_from_input 的 append 段")
        chunk = self.nerve_src[m.start():m.end() + 200]
        self.assertIn('add_commitment_row', chunk,
                      "extract_from_input 的 append 之前应调 add_commitment_row")

    def test_cw_add_commitment_persists(self):
        m = re.search(r'def add_commitment\(self.*?self\.commitments\.append', self.nerve_src, re.DOTALL)
        self.assertIsNotNone(m)
        chunk = self.nerve_src[m.start():m.end() + 200]
        self.assertIn('add_commitment_row', chunk)

    def test_cw_cancel_by_keyword_soft_deletes_db(self):
        m = re.search(r'def cancel_by_keyword\(self.*?return removed', self.nerve_src, re.DOTALL)
        self.assertIsNotNone(m)
        chunk = m.group(0)
        self.assertIn('soft_delete_commitment', chunk,
                      "cancel_by_keyword 应同步 soft_delete_commitment")

    def test_cw_update_by_keyword_updates_db(self):
        m = re.search(r'def update_by_keyword\(self.*?return updated', self.nerve_src, re.DOTALL)
        self.assertIsNotNone(m)
        chunk = m.group(0)
        self.assertIn('update_commitment_row', chunk,
                      "update_by_keyword 应同步 update_commitment_row")

    def test_cw_run_nudged_persists(self):
        # CW.run 里 nudged=True 后应 mark_commitment_nudged
        m = re.search(r"c\['nudged'\] = True.*?_dispatch_commitment_nudge", self.nerve_src, re.DOTALL)
        self.assertIsNotNone(m)
        chunk = m.group(0)
        self.assertIn('mark_commitment_nudged', chunk,
                      "CW.run 标 nudged 时应同步 mark_commitment_nudged DB")

    def test_db_roundtrip(self):
        """实际 CRUD 一遍：INSERT → load → UPDATE → soft_delete"""
        # 用临时 DB
        from jarvis_hippocampus import Hippocampus
        tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        tmp.close()
        db_path = tmp.name
        try:
            h = Hippocampus(db_path=db_path, key_router=None)
            # INSERT
            rid = h.add_commitment_row(
                description='测试：明天九点起床',
                deadline_ts=time.time() + 3600,
                grace_minutes=10,
                source_text='测试 source',
                created_at=time.time(),
            )
            self.assertGreater(rid, 0)
            # LOAD
            rows = h.load_active_commitments(max_age_hours=48.0)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['description'], '测试：明天九点起床')
            self.assertEqual(rows[0]['nudged'], False)
            # UPDATE
            ok = h.update_commitment_row(rid, new_description='已修正', new_deadline_ts=time.time() + 7200)
            self.assertTrue(ok)
            rows = h.load_active_commitments()
            self.assertEqual(rows[0]['description'], '已修正')
            # nudged
            ok = h.mark_commitment_nudged(rid)
            self.assertTrue(ok)
            rows = h.load_active_commitments()
            self.assertEqual(len(rows), 0, "标 nudged 后不应再出现在 active 列表")
            # soft delete
            ok = h.soft_delete_commitment(rid)
            self.assertTrue(ok)
        finally:
            try:
                os.remove(db_path)
                # WAL 文件也清
                for suf in ('-wal', '-shm'):
                    p = db_path + suf
                    if os.path.exists(p):
                        os.remove(p)
            except Exception:
                pass


# =================================================================
# E.4 终端色彩化分区
# =================================================================
class TestE4TerminalColorZoning(unittest.TestCase):
    """E.4: ANSI 色彩 + log 文件 strip ANSI"""

    def setUp(self):
        self.utils_src = _read('jarvis_utils.py')
        self.nerve_src = read_nerve_corpus()

    def test_ansi_constants_defined(self):
        self.assertIn('class _ANSI', self.utils_src)
        for c in ('CYAN', 'GREEN', 'YELLOW', 'MAGENTA', 'BLUE', 'RED', 'RESET'):
            self.assertIn(f'{c} = "', self.utils_src,
                          f"应定义 _ANSI.{c} 颜色常量")

    def test_colorize_helper_defined(self):
        self.assertIn('def colorize_terminal_line', self.utils_src)
        self.assertIn('def strip_ansi_codes', self.utils_src)

    def test_box_newline_uses_colorize(self):
        m = re.search(r'def _box_newline\(text:.*?return joined', self.nerve_src, re.DOTALL)
        self.assertIsNotNone(m)
        chunk = m.group(0)
        self.assertIn('colorize_terminal_line', chunk)

    def test_teestream_strips_ansi(self):
        # _TeeStream.write 应在写 log 前 strip ANSI
        self.assertIn('strip_ansi_codes', self.utils_src)
        # write 函数体内应调用 strip_ansi_codes
        m = re.search(r'def write\(self, data\):.*?self\._log\.write\(_log_data\)', self.utils_src, re.DOTALL)
        self.assertIsNotNone(m, "TeeStream.write 应使用 _log_data (strip 后的版本)")

    def test_colorize_round_trip(self):
        """实际跑一遍 colorize → strip 应回到原文"""
        from jarvis_utils import colorize_terminal_line, strip_ansi_codes
        s1 = '║ 🗣️  [Human] hello'
        s2 = colorize_terminal_line(s1)
        # 着色后长度变长（包含 ANSI 转义）
        self.assertGreater(len(s2), len(s1))
        # strip 后回到原文
        s3 = strip_ansi_codes(s2)
        self.assertEqual(s3, s1)

    def test_unmatched_line_pass_through(self):
        from jarvis_utils import colorize_terminal_line
        s = '某随机 log 行没匹配 emoji'
        self.assertEqual(colorize_terminal_line(s), s)


# =================================================================
# E.1 reminder 落库语义集成测：模拟 Sir 改时间场景
# =================================================================
class TestE1ScenarioReminderRescheduleSaves(unittest.TestCase):
    """E.1 端到端语义测：模拟 Sir 改时间场景,检查兜底分支的关键关键字"""

    def setUp(self):
        self.src = read_nerve_corpus()

    def test_e1_block_documents_log_marker(self):
        # 修复段应引用日志文件 + Sir 实测时间作 marker
        self.assertIn('jarvis_20260515_202835.log', self.src,
                      "e.1 修复段应引用日志文件路径")

    def test_e1_block_documents_root_cause(self):
        # 应说明根因：Cancel 抹老 + Correction 找不到 + 兜底降级
        idx = self.src.find('P0+18-e.1')
        self.assertGreaterEqual(idx, 0)
        snippet = self.src[idx:idx + 4000]
        self.assertIn('Cancel', snippet)
        self.assertIn('Memory Correction', snippet)
        self.assertIn('降级', snippet, "应解释为何兜底降级是错的")


if __name__ == '__main__':
    unittest.main()
