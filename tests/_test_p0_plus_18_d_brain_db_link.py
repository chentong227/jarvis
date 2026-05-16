# -*- coding: utf-8 -*-
"""[P0+18-d / 2026-05-15] 主脑 ↔ Reminder/Commitment/Memory 数据库链路打通

修 Sir 18:22-18:31 实测的连环 BUG 链：
- D.1 主脑列代办时凭 LLM 上下文猜测，不查数据库
- D.2 凭空编造 "明天 3 点取快递" 提醒（数据库 0 条）
- D.3 "明天早上起来刷科目一" 被 AFP 硬规则清掉 → 没注册成 reminder
- D.4 Memory Correction 把"取消快递 + 加科目一"两件事拼成乱串
- D.6 主脑只看到 hand 名字字符串，不知道 list_reminders 子命令
- D.7 AFP 硬编码语义匹配漏自然口语承诺

测试目的：用纯静态文本扫描验证修复落地，避免依赖运行时 LLM。
"""

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# [P0+19-0 / 2026-05-16] 拆分后多文件 corpus 扫描垫层
# 旧 `read_nerve_corpus()` → 用 `read_nerve_corpus()` 跟随拆分自动扩展
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _source_corpus import read_nerve_corpus


def _read(rel: str) -> str:
    """保留：其它文件（如 jarvis_utils.py / jarvis_hippocampus.py）仍直接读。"""
    with open(os.path.join(ROOT, rel), 'r', encoding='utf-8') as f:
        return f.read()


class TestD1ActiveRemindersBlockInjected(unittest.TestCase):
    """D.1: active_reminders_block 在 prompt 装配中被注入"""

    def test_nerve_assemble_prompt_builds_block(self):
        src = read_nerve_corpus()
        # nerve.py 中应当从 utils 引入 render_active_reminders_block + 装配 block 变量
        self.assertIn('render_active_reminders_block', src,
                      "_assemble_prompt 应引用 render_active_reminders_block")
        self.assertIn('active_reminders_block', src,
                      "_assemble_prompt 应组装 active_reminders_block 变量")
        # block 应被注入到 prompt 主串里（{active_reminders_block} f-string 引用）
        self.assertIn('{active_reminders_block}', src,
                      "active_reminders_block 应被 f-string 注入 prompt 主串")

    def test_nerve_reads_taskmemories_for_reminders(self):
        src = read_nerve_corpus()
        # [P0+19-final / 2026-05-16] 拆分后 corpus 中 `render_active_reminders_block` 多次出现：
        # 1) 在 jarvis_central_nerve.py 的 import 行（首次）
        # 2) 实际调用 `render_active_reminders_block(...)`（带括号）
        # 找带括号的调用位置（实际 _assemble_prompt 装配段）
        m = re.search(r'render_active_reminders_block\s*\(', src)
        self.assertIsNotNone(m, "找不到 active_reminders_block 装配位（调用）")
        # 装配段附近应当含读 TaskMemories 的 SQL
        chunk = src[max(0, m.start() - 2000):m.start() + 2000]
        self.assertRegex(chunk, r'is_future_task\s*=\s*1',
                         "active_reminders_block 装配段应读 is_future_task=1 的行")
        self.assertIn('TaskMemories', chunk,
                      "装配段应直接读 TaskMemories 表")


class TestD1RendererImpl(unittest.TestCase):
    """D.1: render_active_reminders_block 函数行为"""

    def setUp(self):
        from jarvis_utils import render_active_reminders_block
        self.render = render_active_reminders_block

    def test_empty_returns_honest_directive(self):
        block = self.render([], [])
        self.assertIn('ACTIVE REMINDERS / COMMITMENTS', block)
        self.assertIn('none', block.lower())
        self.assertIn('承诺必行', block, "空 block 也必须含承诺必行 directive，禁止编造")

    def test_with_reminders_quotes_intent_verbatim(self):
        import time as _time
        future = _time.time() + 3600
        block = self.render(
            [{"id": 729, "intent": "明天早上起来刷科目一的题", "trigger_time": future}],
            [],
        )
        self.assertIn('明天早上起来刷科目一的题', block,
                      "block 必须照实念 intent，禁止改写")
        self.assertIn('DB#729', block, "应标 DB ID 让主脑能引用具体条目")
        self.assertRegex(block, r'\[(TODAY|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{2}:\d{2}\]',
                         "应有可读时间标签")
        self.assertIn('HOW TO LIST TODOS', block,
                      "必须含 HOW TO LIST TODOS directive")

    def test_overdue_label(self):
        import time as _time
        past = _time.time() - 7200
        block = self.render(
            [{"id": 100, "intent": "昨天 3 点取快递", "trigger_time": past}],
            [],
        )
        self.assertIn('OVERDUE', block, "已过期 reminder 必须明确标 OVERDUE")

    def test_directive_forbids_inventing(self):
        block = self.render(
            [{"id": 1, "intent": "test item", "trigger_time": 0}],
            [],
        )
        self.assertIn('DO NOT invent', block, "directive 必须明令禁止编造")
        self.assertIn('reminders DB', block, "必须明示 DB 是 source of truth")

    def test_commitment_dedup_with_reminder(self):
        """同源去重：DB reminder 和 CW commitment 前 15 字相同只显示一条"""
        import time as _time
        future = _time.time() + 3600
        block = self.render(
            [{"id": 1, "intent": "明天早上起来刷科目一的题", "trigger_time": future}],
            [{"description": "明天早上起来刷科目一的题", "deadline_ts": future, "source_text": ""}],
        )
        # 数清楚科目一出现的次数；应该只有 DB#1 那条
        self.assertEqual(block.count('科目一'), 1,
                         "同源 reminder + commitment 不应重复输出")


class TestD1HowToRespondDirective(unittest.TestCase):
    """D.1+D.2: HOW TO RESPOND 区里应当有"列代办时照实念 block"的规则"""

    def test_how_to_respond_has_read_directive(self):
        src = read_nerve_corpus()
        # 应当含针对"列代办（READ 类）"的 SOP（避免被 WRITE 类 do-NOT-call-any-tool 误外推）
        # 关键标志：含 "READ" + "reminders" / "代办" 字样
        self.assertRegex(
            src,
            r'REMINDER/TODO\s+LIST\s*\(READ',
            "HOW TO RESPOND 应区分 READ vs WRITE，READ 分支必须存在"
        )
        # 必须禁止编造
        self.assertIn('reminders 数据库是唯一真实来源', src,
                      "READ directive 必须把 DB 锚定为唯一真实来源")


class TestD3AfpDictExpanded(unittest.TestCase):
    """D.3+D.7: AFP 词典扩展 + 信任上游

    抽取方式：用 ast 解析源代码，找到 schedule_keywords = [...] 的字面值后直接 eval。
    """

    def setUp(self):
        import ast
        src = read_nerve_corpus()
        tree = ast.parse(src)
        keywords = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            targets = node.targets
            if len(targets) != 1:
                continue
            tgt = targets[0]
            if not isinstance(tgt, ast.Name):
                continue
            if tgt.id != 'schedule_keywords':
                continue
            if not isinstance(node.value, (ast.List, ast.Tuple)):
                continue
            extracted = []
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    extracted.append(elt.value)
            keywords = extracted
            break
        self.assertIsNotNone(keywords, "找不到 schedule_keywords = [...] 字面定义")
        self.assertGreater(len(keywords), 10,
                           f"schedule_keywords 抽取异常，仅 {len(keywords)} 条")
        self.keywords = keywords

    def test_natural_morning_commit_matched(self):
        """'明天早上起来 X' 这种自然承诺必须被词典覆盖"""
        cases = [
            "不如明天早上起来刷怎么样",
            "我打算明天早上起来刷题",
            "明天下午做一个新视频",
            "明早起床",
        ]
        for case in cases:
            hits = [p for p in self.keywords if re.search(p, case.lower())]
            self.assertTrue(
                hits,
                f"自然口语承诺 {case!r} 未被任何 AFP 关键词命中（旧词典 BUG 复现）"
            )

    def test_explicit_remind_still_matched(self):
        """老的显式承诺不能漏匹配"""
        cases = [
            "提醒我两分钟后喝水",
            "明天 8 点叫醒我",
            "remind me to drink water in 2 minutes",
            "tomorrow morning at 7 am",
        ]
        for case in cases:
            hits = [p for p in self.keywords if re.search(p, case.lower())]
            self.assertTrue(hits, f"显式承诺 {case!r} 不应被漏掉")

    def test_afp_trusts_upstream(self):
        src = read_nerve_corpus()
        # AFP 段必须有"上游 trigger_time_str 已给 → 信任 LLM"的分支
        self.assertIn('TrustUpstream', src,
                      "AFP 必须有 TrustUpstream 分支信任 Gatekeeper LLM 的判定")
        # 信任时必须明确 continue（保留 is_future_task=True）
        m = re.search(
            r'TrustUpstream.*?continue',
            src,
            re.DOTALL,
        )
        self.assertIsNotNone(m,
                             "TrustUpstream 分支必须 continue 而非清除 is_future_task")


class TestD4MultiOpSupport(unittest.TestCase):
    """D.4: Memory Correction / Commitment 支持多 op"""

    def test_gatekeeper_prompt_explains_multi_op(self):
        src = read_nerve_corpus()
        # Gatekeeper prompt 必须教 LLM "多事拆多条"。检查关键字眼即可
        self.assertIn('MULTI-OP', src, "Gatekeeper prompt 必须含 MULTI-OP 标志")
        self.assertIn('ONE record per', src,
                      "Gatekeeper prompt 必须含 ONE record per ... 的拆条 directive")
        self.assertIn('cram multiple operations', src,
                      "Gatekeeper prompt 必须明示 anti-pattern (禁止拼字符串)")

    def test_commitment_iter_list(self):
        src = read_nerve_corpus()
        # commitment 处理段必须 for-iter gate_data_list 而非只取 [0]
        self.assertIn('for _commit_gd in gate_data_list', src,
                      "commitment 处理必须循环 gate_data_list")

    def test_correction_scans_list_for_has_correction(self):
        src = read_nerve_corpus()
        # correction / delete_hint 必须扫描 list 找第一条 has_correction 的
        # 这样即便 [0] 是 future_task、[1] 是 correction，也能正确取到 [1]
        self.assertIn('for _scan_gd in gate_data_list', src,
                      "correction/delete_hint 必须扫描 list 而非硬取 [0]")


class TestD6HandSubcommandsExposed(unittest.TestCase):
    """D.6: 主脑能看到 hand 的关键子命令"""

    def test_memory_hands_subcommands_in_tool_instructions(self):
        src = read_nerve_corpus()
        # tool_instructions 装配段应当显式注入 memory_hands.list_reminders 等子命令 hint
        self.assertIn('_KEY_SUBCOMMAND_HINTS', src,
                      "应有 _KEY_SUBCOMMAND_HINTS 字典")
        self.assertIn('list_reminders', src,
                      "tool_instructions 必须明示 list_reminders 子命令")
        # 用字面定位（lazy .+? 遇到 hint 字符串里的 }) 会断），找 dict 起点 +
        # 验证里面含关键子命令字眼
        idx = src.find('_KEY_SUBCOMMAND_HINTS = {')
        self.assertNotEqual(idx, -1, "找不到 _KEY_SUBCOMMAND_HINTS 字典起点")
        # 取下方一段（含整个字典体）
        hints_block = src[idx:idx + 3000]
        self.assertIn("'memory_hands'", hints_block)
        self.assertIn('list_reminders', hints_block)
        self.assertIn('search_memory', hints_block)
        self.assertIn('add_reminder', hints_block)


class TestEndToEndArchitecturalGuarantee(unittest.TestCase):
    """端到端保证：主脑 ↔ 数据库链路 4 条主血管全部通"""

    def test_blood_vessel_1_taskmemories_to_prompt(self):
        """血管 1: TaskMemories DB → prompt (D.1)"""
        src = read_nerve_corpus()
        self.assertIn('render_active_reminders_block', src)
        self.assertIn('{active_reminders_block}', src)

    def test_blood_vessel_2_commitment_watcher_to_prompt(self):
        """血管 2: CommitmentWatcher in-memory → prompt (D.1)"""
        src = read_nerve_corpus()
        # 装配段应当读 commitment_watcher.commitments
        self.assertRegex(src,
                         r'getattr\(self,\s*[\'"]commitment_watcher[\'"]',
                         "装配段应读 self.commitment_watcher")
        self.assertRegex(src, r'cw\.commitments\b|c\.commitments\b|hasattr\(cw,\s*[\'"]commitments[\'"]\)')

    def test_blood_vessel_3_directive_anchored_to_db(self):
        """血管 3: directive 明确锚 DB 为唯一真实来源 (D.2 反幻觉)

        directive 有两段，一段在 nerve.py 的 [HOW TO RESPOND] (READ 分支)，
        一段在 utils.py 的 render_active_reminders_block。两段都必须含 anti-hallucination 字眼。
        """
        nerve_src = read_nerve_corpus()
        utils_src = _read('jarvis_utils.py')
        # nerve.py 的 HOW TO RESPOND READ 分支
        self.assertIn('reminders 数据库是唯一真实来源', nerve_src)
        # utils.py 的 block-level directive
        self.assertIn('DO NOT invent', utils_src,
                      "render_active_reminders_block 必须明令禁止编造")
        self.assertIn('reminders DB', utils_src)

    def test_blood_vessel_4_hand_subcommands_visible(self):
        """血管 4: 主脑能看到 list_reminders / add_reminder 工具 (D.6)"""
        src = read_nerve_corpus()
        self.assertIn('list_reminders', src)
        self.assertIn('add_reminder', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
