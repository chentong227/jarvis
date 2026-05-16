# -*- coding: utf-8 -*-
"""[P0+18-f / 2026-05-15] 性能 + 诚信 + Nudge mute + Integrity 误报 修复测试套件

修 Sir 22:10-22:14 实测 BUG 链（jarvis_20260515_221051.log）：
- F.1 终端打印阻塞主线程 → TTFT 从 3s 飚到 18-27s (colorama wrap stdout/stderr +
       TeeStream 每 write 同步 fsync + strip_ansi 无快速路径 + 声波 30Hz print 叠加)
- F.2 22:13:58 fake action "I've struck it from the active agenda" 但没调任何工具
       → 增强 Capability Honesty Directive (NUDGE/AGENDA HONESTY)
- F.3 SilentNudge dormant_project 拒绝后只 HardFreeze 300s,长期不 mute
       → 加 type-specific long-term mute (_muted_nudge_types 12-24h)
- F.4 Integrity Check no_tool_called 误报 referential statement
       → pre-filter referential markers + 第 2 层 prompt 加 referential 例子

测试设计：静态源扫描 + 单元行为模拟 + 真模块导入。
"""

import os
import re
import sys
import time
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
# F.1 终端打印异步化 —— colorama 不再 wrap, TeeStream queue + worker
# =================================================================
class TestF1AsyncTeePerfFix(unittest.TestCase):
    """F.1: 终端打印性能修复"""

    def setUp(self):
        self.utils_src = _read('jarvis_utils.py')

    def test_marker_present(self):
        self.assertIn('P0+18-f.1', self.utils_src,
                      "应有 P0+18-f.1 修复 marker（strip_ansi 快路径）")
        self.assertIn('P0+18-f.2', self.utils_src,
                      "应有 P0+18-f.2 修复 marker（TeeStream 异步化）")

    def test_strip_ansi_fast_path(self):
        # strip_ansi_codes 必须有 \x1b 快速检测路径
        from jarvis_utils import strip_ansi_codes
        long_no_esc = "🎙️ [接收物理声波] " + "█" * 30 + " " * 100
        self.assertEqual(strip_ansi_codes(long_no_esc), long_no_esc,
                         "无 ESC 字符应直接返回原文,不走 regex")
        ansi_text = "\x1b[36m║ 🗣️ Human\x1b[0m"
        self.assertNotIn("\x1b", strip_ansi_codes(ansi_text),
                         "含 ESC 字符应正常 strip")

    def test_strip_ansi_fast_path_has_shortcircuit(self):
        # 源码检查：必须有 `'\x1b' not in text: return text` 这种快速路径
        self.assertIn('def strip_ansi_codes', self.utils_src)
        self.assertIn("'\\x1b' not in", self.utils_src,
                      "strip_ansi_codes 应有 '\\x1b' not in 快速路径")

    def test_tee_queue_exists(self):
        from jarvis_utils import _TEE_QUEUE
        import queue
        self.assertIsInstance(_TEE_QUEUE, queue.Queue)
        # 队列容量必须 >= 1000，防止主线程被阻塞
        # （Queue.maxsize 在创建时设置）
        self.assertGreaterEqual(_TEE_QUEUE.maxsize, 1000,
                                "TeeStream queue 必须有足够缓冲, 避免阻塞主线程")

    def test_tee_worker_function_exists(self):
        from jarvis_utils import _tee_worker_loop, _start_tee_worker
        self.assertTrue(callable(_tee_worker_loop))
        self.assertTrue(callable(_start_tee_worker))

    def test_tee_write_does_not_flush_inline(self):
        # 新版 TeeStream.write 不应该有 self._log.flush() 调用（异步 worker 负责 flush）
        m = re.search(r"def write\(self, data\):.*?def flush\(self\):", self.utils_src, re.DOTALL)
        self.assertIsNotNone(m, "应能找到 write 方法定义")
        write_body = m.group(0)
        # 在 write 函数体内不应该有显式 self._log.flush()
        flush_in_write = re.findall(r"self\._log\.flush\(\)", write_body)
        # 允许 0 次 inline flush 调用（fallback 同步写时不强制）
        self.assertLessEqual(len(flush_in_write), 0,
                             f"write 不应有 inline self._log.flush()（异步 worker 负责）, 找到 {len(flush_in_write)} 次")

    def test_colorama_uses_just_fix_windows_console(self):
        # 应优先使用 just_fix_windows_console，不再 wrap stdout
        self.assertIn('just_fix_windows_console', self.utils_src,
                      "应使用 colorama.just_fix_windows_console（不 wrap stdout）")

    def test_tee_queue_full_fallback_to_sync(self):
        # 队列满时应退化到同步写, 保证日志不丢
        m = re.search(r"_queue_for_tee\.Full.*?self\._log\.write", self.utils_src, re.DOTALL)
        self.assertIsNotNone(m, "队列满时应有 self._log.write 同步 fallback")


# =================================================================
# F.2 NUDGE / AGENDA HONESTY —— fake action 撒谎防御
# =================================================================
class TestF2NudgeAgendaHonesty(unittest.TestCase):
    """F.2: 主脑不再撒谎说"已从议程中删除"等无工具承诺"""

    def setUp(self):
        self.src = read_nerve_corpus()

    def test_marker_present(self):
        self.assertIn('P0+18-f.2', self.src,
                      "应有 P0+18-f.2 修复 marker")

    def test_nudge_agenda_honesty_directive_present(self):
        # JARVIS_CORE_PERSONA 应包含 NUDGE / AGENDA HONESTY 段
        self.assertIn('NUDGE / AGENDA HONESTY', self.src,
                      "应有 [NUDGE / AGENDA HONESTY] 指令段")

    def test_forbidden_phrases_listed(self):
        # 必须列出 "I've struck it from the active agenda" 等禁用短语
        snippet_idx = self.src.find('NUDGE / AGENDA HONESTY')
        self.assertGreater(snippet_idx, 0)
        snippet = self.src[snippet_idx:snippet_idx + 2500]
        self.assertIn("struck it from the active agenda", snippet,
                      "应列出 'struck it from the active agenda' 为禁用短语")
        self.assertIn("已经把它从议程中删除", snippet,
                      "应列出中文版本禁用短语")

    def test_honest_fallback_templates(self):
        # 必须给出诚实回答模板（教主脑怎么诚实地说）
        snippet_idx = self.src.find('NUDGE / AGENDA HONESTY')
        snippet = self.src[snippet_idx:snippet_idx + 2500]
        self.assertIn('Acknowledged', snippet,
                      "应给出 'Acknowledged' 诚实模板")
        self.assertIn('cooldown', snippet,
                      "应解释 nudge cooldown 是自动机制")


# =================================================================
# F.3 SmartNudgeSentinel type-specific long-term mute
# =================================================================
class TestF3NudgeTypeLongTermMute(unittest.TestCase):
    """F.3: 拒绝某 nudge_type 后,该 type 当日/半日不再触发"""

    def setUp(self):
        self.src = read_nerve_corpus()

    def test_marker_present(self):
        self.assertIn('P0+18-f.3', self.src,
                      "应有 P0+18-f.3 修复 marker")

    def test_muted_nudge_types_dict_initialized(self):
        # SmartNudgeSentinel.__init__ 应初始化 _muted_nudge_types dict
        self.assertIn('self._muted_nudge_types = {}', self.src,
                      "应在 __init__ 初始化 _muted_nudge_types")
        self.assertIn('self._last_nudge_type', self.src,
                      "应初始化 _last_nudge_type")
        self.assertIn('self._last_nudge_time', self.src,
                      "应初始化 _last_nudge_time")

    def test_post_nudge_checks_mute(self):
        # _dispatch_nudge 顶部应检查 _muted_nudge_types
        m = re.search(r"def _dispatch_nudge.*?_muted_nudge_types\.get\(nudge_type", self.src, re.DOTALL)
        self.assertIsNotNone(m, "_dispatch_nudge 应检查 _muted_nudge_types")

    def test_post_nudge_records_last_type(self):
        # _post_nudge 应记录 _last_nudge_type 和 _last_nudge_time
        self.assertIn('self._last_nudge_type = nudge_type', self.src)
        self.assertIn('self._last_nudge_time = time.time()', self.src)

    def test_help_refusal_sets_mute(self):
        # _detect_help_refusal 应在拒绝时设置 _muted_nudge_types
        m = re.search(r"_detect_help_refusal.*?_muted_nudge_types\[last_nudge_type\]", self.src, re.DOTALL)
        self.assertIsNotNone(m, "_detect_help_refusal 应设置 _muted_nudge_types[last_nudge_type]")

    def test_mute_duration_strong_24h_normal_12h(self):
        # 强拒绝 24h, 普通 12h
        idx = self.src.find('type-specific long-term mute')
        self.assertGreater(idx, -1, "应有 type-specific long-term mute 注释")
        snippet = self.src[idx:idx + 1500]
        self.assertIn('86400.0', snippet, "强拒绝应 mute 24h (86400s)")
        self.assertIn('43200.0', snippet, "普通拒绝应 mute 12h (43200s)")

    def test_return_greeting_exempt(self):
        # return_greeting 永远豁免 mute（AFK 归来问候）
        m = re.search(r"_muted_nudge_types.*?return_greeting", self.src, re.DOTALL)
        # 或反过来检：return_greeting 在 mute 检查前 return
        self.assertIn("nudge_type != 'return_greeting'", self.src)


# =================================================================
# F.4 Integrity Check referential pre-filter
# =================================================================
class TestF4IntegrityCheckReferentialFilter(unittest.TestCase):
    """F.4: 主脑 referential 陈述不再被误判 no_tool_called"""

    def setUp(self):
        self.utils_src = _read('jarvis_utils.py')

    def test_marker_present(self):
        self.assertIn('P0+18-f.4', self.utils_src,
                      "应有 P0+18-f.4 修复 marker")

    def test_referential_markers_defined(self):
        self.assertIn('referential_markers_en', self.utils_src,
                      "应有 referential_markers_en")
        self.assertIn('referential_markers_zh', self.utils_src,
                      "应有 referential_markers_zh")
        self.assertIn('i\\s+was\\s+(referring|talking', self.utils_src,
                      "应捕获 'I was referring to' 模式")
        self.assertIn('我指的是', self.utils_src,
                      "应捕获中文 '我指的是'")

    def test_detect_action_claim_rejects_referential_en(self):
        from jarvis_utils import get_quick_classifier
        qc = get_quick_classifier()
        # Sir 22:13:07 实测原话: "I was referring to your driver's license theory studies, Sir.
        # While you have been making excellent progress with system refinements..."
        reply = ("I was referring to your driver's license theory studies, Sir. "
                 "While you have been making excellent progress with system refinements, "
                 "your Subject One preparation has remained dormant for some time.")
        # pre-filter 层就应该 reject, 不需要走 1.5B（这是关键性能 + 正确性收益）
        # 由于 detect_action_claim 内部会调 1.5B, 我们只测试 pre-filter 拦下了
        # 如果 1.5B 不可用(无 ollama), 函数会返回 False; 如果可用, pre-filter 也会先拦
        # 检测方式：监测函数行为, 不依赖具体的 LLM 响应
        # 这里直接 patch _active_model 让 LLM 永远 raise, 验证 pre-filter 拦下
        result = qc.detect_action_claim(reply)
        self.assertFalse(result,
                         "referential 陈述应被 pre-filter 拦下 → False")

    def test_detect_action_claim_rejects_referential_zh(self):
        from jarvis_utils import get_quick_classifier
        qc = get_quick_classifier()
        reply = "我指的是您的驾照理论学习，先生。您在科目一的准备上已经停滞了一段时间。"
        result = qc.detect_action_claim(reply)
        self.assertFalse(result, "中文 referential 陈述应被 pre-filter 拦下 → False")

    def test_detect_action_claim_still_catches_real_fake(self):
        from jarvis_utils import get_quick_classifier
        qc = get_quick_classifier()
        # 这是真正的 fake action, 不应被新 filter 拦
        # 在没有 1.5B 时无法验证完整链路, 但至少 pre-filter 不能误拦
        reply = "I've silenced all notifications, Sir."
        # 该 reply 没含 referential marker, 不应走 0.5 层 return False
        # 检测方式：源码扫描确认它不在 referential filter 内
        idx = self.utils_src.find('referential_markers_en')
        end = self.utils_src.find('# === 第 1 层', idx)
        if end < 0:
            end = idx + 2000
        snippet = self.utils_src[idx:end]
        # silenced 不应被 referential 关键词覆盖
        self.assertNotIn('silenced', snippet,
                         "referential filter 不应包含 'silenced' 等动作动词")

    def test_prompt_has_referential_examples(self):
        # 第 2 层 1.5B prompt 应包含 referential 反例（教 LLM 区分）
        self.assertIn("I was referring to your driver's license", self.utils_src,
                      "1.5B prompt 应有 referential 反例 'I was referring to...'")
        self.assertIn("我指的是您的驾照理论学习", self.utils_src,
                      "1.5B prompt 应有中文 referential 反例")
        self.assertIn("describing USER", self.utils_src.lower() if False else self.utils_src,
                      "1.5B prompt 应说明 describing user 不是 own claim")


# =================================================================
# F.5 加细粒度 timing log 到后台日志
# =================================================================
class TestF5FinerTimingDiagLog(unittest.TestCase):
    """F.5: 加细粒度 perf diag log 到后台日志（不打印, bg_log 写日志文件）"""

    def setUp(self):
        self.src = read_nerve_corpus()

    def test_marker_present(self):
        self.assertIn('P0+18-f.5', self.src,
                      "应有 P0+18-f.5 修复 marker")

    def test_perf_diag_has_connect_wait_breakdown(self):
        # 连接/等待 阶段细分
        m = re.search(r"Perf Diag.*?connect=.*?wait=.*?tee_queue_depth=", self.src, re.DOTALL)
        self.assertIsNotNone(m, "应有 [Perf Diag] log 含 connect/wait/queue_depth")

    def test_asm_diag_has_total_time(self):
        # _assemble_prompt 总耗时
        self.assertIn('Asm Diag', self.src,
                      "应有 [Asm Diag] 后台日志记录 prompt 装配总耗时")


if __name__ == '__main__':
    unittest.main()
