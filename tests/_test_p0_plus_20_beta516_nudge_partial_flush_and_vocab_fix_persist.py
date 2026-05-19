# -*- coding: utf-8 -*-
"""
[P0+20-β.5.16 / 2026-05-19] 2 个 β.5 边界 BUG 修

Sir 22:21 真机实测 + 日志排查 (jarvis_20260519_220906.log) 发现:

=== BUG-D: stream_nudge 同款 β.5.12 BUG-A partial-flush 问题 ===
ProactiveCare nudge 主回复 stream 出 ("I've been watching..."), 然后 read_timeout
导致 ZH 翻译没流回. stream_nudge except 直接 `return ""` → 上层 nudge_reply 空
→ 触发 [Nudge/NoSound] bg_log + 用户看到无中文字幕.

修法: jarvis_chat_bypass.py:4199 except 加 partial-flush 守卫:
  - full_text 净化后 >= 12 char → 视作"实质内容已说出"
  - 拆 ---ZH--- (有就 flush 字幕)
  - 返 final_reply 非空让上层认知"说过了"
  - bg_log [β.5.16/Nudge-Partial] 标记诊断

=== BUG-F (β.5 头号边界): jarvis_utils.read_gate_mode 一直返 hard ===
根因: jarvis_utils.py 全文用 alias (`import os as _os_for_log` 等), 没裸 import.
read_gate_mode 函数体内裸用 `os.path.xxx` / `json.load(f)` → NameError →
silent except 返 'hard'. β.5.x 整个 publish_only 重构从未真生效 — 所有 sentinel
一直跑 hard 模式. Sir log 22:23 line 419 `❌ [OfferGuard] blocked (mode=hard)` 实锤.

修法:
  1. jarvis_utils.py 顶部加裸 `import os` `import json` (与 alias 共存兼容)
  2. read_gate_mode 函数体内本地 `import os as _os_local, json as _json_local`
     (belt-and-suspenders 防御)

测试覆盖:
  A. BUG-D stream_nudge partial-flush 守卫 (字面 marker + 净化逻辑)
  B. BUG-F read_gate_mode 真返 vocab 配置值 (publish_only, 不再 hard)
  C. 顶部 `import os` / `import json` 持久化
  D. _GATE_MODE_CACHE 写入正确 (不空)
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


# ==========================================================================
# A: BUG-D stream_nudge partial-flush 守卫
# ==========================================================================

class TestBeta516BugD_NudgePartialFlush(unittest.TestCase):
    """stream_nudge except 已 stream 实质内容时不补道歉, 尝试 flush ZH."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_chat_bypass.py'))

    def test_marker_comment_present(self):
        self.assertIn('β.5.16', self.src,
            'β.5.16 marker 必须在 jarvis_chat_bypass.py (stream_nudge except)')
        self.assertIn('BUG-D', self.src, 'BUG-D 标记必须存在')

    def test_partial_flush_threshold_12(self):
        """阈值 12 字符 跟 β.5.12 BUG-A 一致."""
        # stream_nudge except 应有 `len(_net_clean) >= 12` 判定
        self.assertIn('>= 12', self.src,
            '阈值 12 字符 (与 β.5.12 BUG-A 一致)')

    def test_partial_flush_emits_diagnostic_log(self):
        """守卫触发时 bg_log 含 'Nudge-Partial' 标记."""
        self.assertIn('Nudge-Partial', self.src,
            'partial-flush 必须 bg_log 含 Nudge-Partial 标记便于 grep')

    def test_partial_flush_handles_zh_split(self):
        """守卫内必须处理 ---ZH--- 拆分."""
        # 找 except 之后到 return _final_reply 之前的 block
        idx = self.src.find("BUG-D: stream_nudge partial-flush")
        self.assertGreater(idx, 0)
        block_end = self.src.find('return _final_reply', idx)
        self.assertGreater(block_end, idx)
        block = self.src[idx:block_end]
        self.assertIn("'---ZH---' in _net", block,
            '守卫块必须检测 ---ZH--- 标记')
        self.assertIn('subtitle_queue.put', block,
            '守卫块必须 flush ZH 到 subtitle_queue')

    def test_partial_flush_returns_nonempty(self):
        """守卫触发时 return _final_reply 非空, 不是老的 return ""."""
        # except 体内最终 return 应是 _final_reply (变量), 不是空字符串
        idx = self.src.find('BUG-D: stream_nudge partial-flush')
        self.assertGreater(idx, 0)
        # 找紧跟其后第一个 return
        return_idx = self.src.find('return ', idx)
        # 紧接的 return 应不是 'return ""'
        snippet = self.src[return_idx:return_idx + 30]
        self.assertNotIn('return ""', snippet,
            '老 `return ""` 必须替换为 `return _final_reply`')


# ==========================================================================
# B: BUG-F read_gate_mode 真返 vocab 配置值
# ==========================================================================

class TestBeta516BugF_ReadGateModeFix(unittest.TestCase):
    """read_gate_mode 修复后真返 vocab 配置 (不再 silent NameError → hard)."""

    def test_read_gate_mode_returns_publish_only(self):
        import jarvis_utils as u
        u.reset_gate_mode_cache()
        # vocab.json current 中 NudgeGate / OfferGuard 都是 publish_only
        self.assertEqual(u.read_gate_mode('NudgeGate'), 'publish_only',
            'NudgeGate 必须返 vocab 配置 publish_only, 不再 hard')
        self.assertEqual(u.read_gate_mode('OfferGuard'), 'publish_only',
            'OfferGuard 必须返 vocab 配置 publish_only')
        self.assertEqual(u.read_gate_mode('Conductor'), 'publish_only',
            'Conductor 必须返 vocab 配置 publish_only')

    def test_cache_populated_after_call(self):
        """第一次调用后 cache 不空 (说明 try block 跑通了, 不再走 silent except)."""
        import jarvis_utils as u
        u.reset_gate_mode_cache()
        u.read_gate_mode('NudgeGate')
        self.assertNotEqual(u._GATE_MODE_CACHE, {},
            'cache 必须被写入, 空 cache 说明 try block 抛 exception 走 silent except')
        self.assertIn('NudgeGate', u._GATE_MODE_CACHE,
            'cache 必须含 NudgeGate key')

    def test_unknown_sentinel_returns_hard(self):
        """未知 sentinel 名 fallback hard (兼容)."""
        import jarvis_utils as u
        u.reset_gate_mode_cache()
        self.assertEqual(u.read_gate_mode('NotASentinel'), 'hard',
            '未知 sentinel 应 fallback hard')


# ==========================================================================
# C: jarvis_utils.py 顶部裸 import os / json
# ==========================================================================

class TestBeta516TopLevelImports(unittest.TestCase):
    """jarvis_utils.py 顶部必须有裸 `import os` 和 `import json` (防 NameError 复发)."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_utils.py'))

    def test_bare_import_os_present(self):
        """顶部必须有裸 `import os` (不只 alias)."""
        self.assertIn('\nimport os\n', self.src,
            'jarvis_utils.py 顶部必须有裸 `import os` 行 (β.5.16-fix-vocab)')

    def test_bare_import_json_present(self):
        self.assertIn('\nimport json\n', self.src,
            'jarvis_utils.py 顶部必须有裸 `import json` 行')

    def test_jarvis_utils_module_has_os(self):
        """import 后 module namespace 应有 os 和 json 属性."""
        import jarvis_utils as u
        self.assertTrue(hasattr(u, 'os'),
            'jarvis_utils 必须 expose 裸 os (函数体内可裸用)')
        self.assertTrue(hasattr(u, 'json'),
            'jarvis_utils 必须 expose 裸 json')

    def test_marker_comment_present(self):
        self.assertIn('β.5.16-fix-vocab', self.src,
            'β.5.16-fix-vocab marker 必须在 jarvis_utils.py')
        self.assertIn('BUG-F', self.src, 'BUG-F 标记必须存在')


# ==========================================================================
# D: read_gate_mode 函数体内 belt-and-suspenders 本地 import (防御性)
# ==========================================================================

class TestBeta516ReadGateModeLocalImport(unittest.TestCase):
    """read_gate_mode 函数体内仍有本地 import (即便顶部 import 出意外仍能工作)."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(os.path.join(ROOT, 'jarvis_utils.py'))

    def test_local_import_os_present(self):
        # read_gate_mode 函数体内必须有 `import os as _os_local`
        idx = self.src.find('def read_gate_mode')
        self.assertGreater(idx, 0)
        end = self.src.find('\ndef reset_gate_mode_cache', idx)
        block = self.src[idx:end if end > 0 else idx + 2000]
        self.assertIn('import os as _os_local', block,
            'read_gate_mode 函数体内必须本地 import os as _os_local (belt-and-suspenders)')
        self.assertIn('import json as _json_local', block,
            'read_gate_mode 函数体内必须本地 import json as _json_local')


# ==========================================================================
# E: 实际 sentinel 行为验证 — NudgeGate 在 publish_only 模式下永真
# ==========================================================================

class TestBeta516SentinelBehaviorActuallyPublishOnly(unittest.TestCase):
    """publish_only 真生效后 NudgeGate.can_speak 永真 (老 hard 模式下被 cooldown 拦)."""

    def test_offer_guard_publish_only_override(self):
        """OfferGuard.check_offer 在 publish_only 模式下永远 return (True, ...)."""
        import jarvis_utils as u
        u.reset_gate_mode_cache()
        # 验证 read_gate_mode 现在确实返 publish_only (前置条件)
        self.assertEqual(u.read_gate_mode('OfferGuard'), 'publish_only',
            '前置条件: OfferGuard 必须真 publish_only')

        # 直接调 OfferGuard.check_offer 看返值
        try:
            from jarvis_skill_registry import OfferGuard
            # publish_event_bus_on_block=False 避免实际 publish 副作用
            ok, reason = OfferGuard.check_offer(
                'offer_help', publish_event_bus_on_block=False)
            self.assertTrue(ok,
                'publish_only 模式 OfferGuard.check_offer 必须永真')
            # reason 应含 'publish_only_override' 字面 (β.5.2 设计)
            self.assertIn('publish_only_override', reason,
                f'publish_only override reason 必须标 publish_only_override, 实际 {reason}')
        except ImportError:
            self.skipTest('OfferGuard import 不可用')


if __name__ == '__main__':
    unittest.main()
