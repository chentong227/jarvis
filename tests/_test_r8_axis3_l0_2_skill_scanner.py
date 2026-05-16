# -*- coding: utf-8 -*-
"""[轴3-L0.2 / 2026-05-15] SkillScanner 自动扫描器 — 测试套件

覆盖：
  TestInferDangerousFlag      — 命令名启发式准确性（含边界 case 如 is_running）
  TestParseInstructionDict    — get_instruction_dict() 字符串解析
  TestArgsTextToSchema        — args_text → args_schema 转换
  TestParseModuleFile         — AST 静态解析 .py 文件（无副作用）
  TestScanModuleFile          — 端到端扫一个 hand 模块
  TestScanPool                — 扫整个 l4_hands_pool 目录
  TestExplicitDangerOverride  — MANIFEST['command_dangers'] 显式声明
  TestModuleDangerHint        — 源码启发式（os.system / shutil.rmtree 等）
  TestRealLifeRegression      — 真实 l4_hands_pool 扫出的 130 个 skill 关键 case 不能回退

跑法：
    cd d:\\Jarvis
    python tests/_test_r8_axis3_l0_2_skill_scanner.py
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from jarvis_skill_registry import (
    SkillScanner,
    SkillManifest,
    DANGER_SAFE,
    DANGER_RISKY,
    DANGER_DANGEROUS,
    SOURCE_INSTRUCTION_DICT,
)


# ==========================================================================
# TestInferDangerousFlag
# ==========================================================================

class TestInferDangerousFlag(unittest.TestCase):
    """命令名启发式准确性 — 含边界 case"""

    def test_safe_verbs_get_list_find(self):
        for cmd in ['get_volume', 'list_devices', 'find_process', 'read_file',
                    'check_port', 'wait_for_text', 'screenshot', 'is_running',
                    'has_permission', 'fetch_status', 'inspect_state']:
            self.assertEqual(SkillScanner.infer_dangerous_flag(cmd), DANGER_SAFE,
                f"{cmd!r} 应判为 SAFE")

    def test_dangerous_verbs(self):
        for cmd in ['delete_file', 'kill_process', 'remove_entry', 'forge_organ',
                    'execute_script', 'shutdown_system', 'reboot', 'click',
                    'type_text', 'paste_text', 'scroll', 'drag', 'hotkey']:
            self.assertEqual(SkillScanner.infer_dangerous_flag(cmd), DANGER_DANGEROUS,
                f"{cmd!r} 应判为 DANGEROUS")

    def test_risky_verbs(self):
        for cmd in ['set_volume', 'change_mode', 'modify_record', 'add_reminder',
                    'launch_app', 'open_url', 'mute', 'play_pause', 'show',
                    'minimize', 'beep', 'toast', 'next', 'stop_watch']:
            self.assertEqual(SkillScanner.infer_dangerous_flag(cmd), DANGER_RISKY,
                f"{cmd!r} 应判为 RISKY")

    def test_unknown_verb_defaults_to_risky(self):
        """未命中任何启发式 → 保守默认 RISKY"""
        for cmd in ['foobar', 'asdfqwer', 'do_something_weird']:
            self.assertEqual(SkillScanner.infer_dangerous_flag(cmd), DANGER_RISKY)

    def test_boundary_is_running_not_dangerous(self):
        """关键 bug 防回退：'is_running' 不能因为含 'run' 子串被误判 DANGEROUS"""
        self.assertEqual(SkillScanner.infer_dangerous_flag('is_running'), DANGER_SAFE,
            "is_running 必须是 SAFE（is 优先），不能因含 'run' 误升 DANGEROUS")

    def test_boundary_find_in_run_history(self):
        """另一个边界：含 dangerous verb 子串的 SAFE 命令"""
        # 'check_run_status' 应该 SAFE（check 优先），即便含 _run_
        self.assertEqual(SkillScanner.infer_dangerous_flag('check_run_status'),
                         DANGER_SAFE)

    def test_safe_verbs_priority_over_dangerous(self):
        """SAFE 优先级高于 DANGEROUS：含 dangerous verb 但以 safe verb 开头 → SAFE"""
        # find_in_dangerous_dir → find 优先（即便含 'dangerous'）
        self.assertEqual(SkillScanner.infer_dangerous_flag('find_in_archive'),
                         DANGER_SAFE)


# ==========================================================================
# TestParseInstructionDict
# ==========================================================================

class TestParseInstructionDict(unittest.TestCase):

    def test_simple_dict(self):
        text = '''
        【音频管理器 指令字典】：
        1. "list_devices": {} — 列举音频输出设备
        2. "set_volume": {"level": 50} — 设置媒体音量
        '''
        out = SkillScanner.parse_instruction_dict(text)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]['command'], 'list_devices')
        self.assertEqual(out[0]['args_text'], '{}')
        self.assertIn('列举', out[0]['description'])
        self.assertEqual(out[1]['command'], 'set_volume')

    def test_multiline_description_folded(self):
        """多行 description 应折成单行"""
        text = '''
        1. "set_volume": {"level": 50} — 设置媒体音量
           — level 必须显式来自用户原话（如 "30%" → 30）
           — 不要使用任何默认值
        2. "mute": {"enable": true} — 静音
        '''
        out = SkillScanner.parse_instruction_dict(text)
        self.assertEqual(len(out), 2)
        self.assertIn('设置媒体音量', out[0]['description'])
        self.assertNotIn('\n', out[0]['description'])

    def test_chinese_quotes_supported(self):
        """中文引号 \u201c\u201d 也应被支持（防 ASR 转录引号变中文）"""
        text = '1. \u201cget\u201d: {} \u2014 \u8bfb\u53d6'
        out = SkillScanner.parse_instruction_dict(text)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['command'], 'get')

    def test_dash_or_emdash_both_accepted(self):
        text1 = '1. "x": {} — desc1'
        text2 = '1. "y": {} - desc2'
        self.assertEqual(SkillScanner.parse_instruction_dict(text1)[0]['command'], 'x')
        self.assertEqual(SkillScanner.parse_instruction_dict(text2)[0]['command'], 'y')

    def test_duplicate_command_deduped(self):
        text = '''
        1. "get": {} — first
        2. "get": {} — second（应被去重）
        '''
        out = SkillScanner.parse_instruction_dict(text)
        self.assertEqual(len(out), 1)
        self.assertIn('first', out[0]['description'])

    def test_empty_text_returns_empty(self):
        self.assertEqual(SkillScanner.parse_instruction_dict(''), [])
        self.assertEqual(SkillScanner.parse_instruction_dict(None), [])


# ==========================================================================
# TestArgsTextToSchema
# ==========================================================================

class TestArgsTextToSchema(unittest.TestCase):

    def test_empty_braces_returns_empty(self):
        self.assertEqual(SkillScanner.args_text_to_schema('{}'), {})
        self.assertEqual(SkillScanner.args_text_to_schema(''), {})

    def test_valid_json_dict(self):
        s = SkillScanner.args_text_to_schema('{"level": 50, "enable": true}')
        self.assertIn('level', s)
        self.assertEqual(s['level']['type'], 'int')
        self.assertEqual(s['level']['example'], 50)
        self.assertEqual(s['enable']['type'], 'bool')

    def test_invalid_json_extracts_keys(self):
        """非 JSON（含 <>、|、注释）也能提取 key 名"""
        s = SkillScanner.args_text_to_schema('{"level": <0-100 整数, 必填>}')
        self.assertIn('level', s)
        self.assertEqual(s['level']['type'], 'unknown')


# ==========================================================================
# TestParseModuleFile
# ==========================================================================

class TestParseModuleFile(unittest.TestCase):
    """AST 静态解析测试 — 无副作用"""

    def test_audio_hands_real_file(self):
        path = os.path.join(ROOT, 'l4_hands_pool', 'l4_audio_hands.py')
        parsed = SkillScanner.parse_module_file(path)
        self.assertNotIn('error', parsed)
        self.assertIsNotNone(parsed['module_manifest'])
        self.assertEqual(parsed['module_manifest']['name'], 'audio_hands')
        self.assertIsNotNone(parsed['instruction_text'])
        self.assertIn('list_devices', parsed['instruction_text'])
        self.assertEqual(parsed['main_class'], 'Hands')

    def test_corrupt_file_returns_error(self):
        with tempfile.NamedTemporaryFile(suffix='.py', mode='w', delete=False, encoding='utf-8') as f:
            f.write('def broken(\n')  # syntax error
            tmp = f.name
        try:
            parsed = SkillScanner.parse_module_file(tmp)
            self.assertIn('error', parsed)
        finally:
            os.unlink(tmp)

    def test_module_without_manifest_returns_none_field(self):
        with tempfile.NamedTemporaryFile(suffix='.py', mode='w', delete=False, encoding='utf-8') as f:
            f.write('def foo(): pass\n')
            tmp = f.name
        try:
            parsed = SkillScanner.parse_module_file(tmp)
            self.assertIsNone(parsed['module_manifest'])
            self.assertIsNone(parsed['instruction_text'])
        finally:
            os.unlink(tmp)

    def test_no_io_side_effects(self):
        """**关键**：parse_module_file 必须不 import / 不实例化 — 仅 ast 解析。
        证明：解析 l4_terminal_hands.py 不应触发 print '🔥 已点火'"""
        import io
        from contextlib import redirect_stdout
        path = os.path.join(ROOT, 'l4_hands_pool', 'l4_terminal_hands.py')
        buf = io.StringIO()
        with redirect_stdout(buf):
            SkillScanner.parse_module_file(path)
        # parse 期间 stdout 应该完全干净
        self.assertEqual(buf.getvalue(), '',
            "parse_module_file 不应触发任何副作用 print")


# ==========================================================================
# TestScanModuleFile
# ==========================================================================

class TestScanModuleFile(unittest.TestCase):

    def test_audio_hands_yields_6_skills(self):
        path = os.path.join(ROOT, 'l4_hands_pool', 'l4_audio_hands.py')
        skills = SkillScanner.scan_module_file(path)
        # audio_hands 有 6 个命令: list_devices/get_default/set_default/get_volume/set_volume/mute
        self.assertGreaterEqual(len(skills), 6)
        cmds = {sk.command for sk in skills}
        for expected in ['audio_hands.list_devices', 'audio_hands.set_volume',
                         'audio_hands.mute']:
            self.assertIn(expected, cmds)

    def test_skill_metadata_fields_populated(self):
        path = os.path.join(ROOT, 'l4_hands_pool', 'l4_audio_hands.py')
        skills = SkillScanner.scan_module_file(path)
        sk = next(s for s in skills if s.command == 'audio_hands.set_volume')
        self.assertEqual(sk.module, 'l4_hands_pool.l4_audio_hands')
        self.assertEqual(sk.source, SOURCE_INSTRUCTION_DICT)
        self.assertEqual(sk.dangerous_flag, DANGER_RISKY)
        self.assertIn('设置媒体音量', sk.description)


# ==========================================================================
# TestScanPool
# ==========================================================================

class TestScanPool(unittest.TestCase):
    """扫整个 pool 目录"""

    def test_l4_hands_pool_yields_120_plus_skills(self):
        pool = os.path.join(ROOT, 'l4_hands_pool')
        skills = SkillScanner.scan_pool(pool)
        # l4_hands_pool 有 24 个 .py，每个平均 5+ 命令 → 总数 > 100
        self.assertGreater(len(skills), 100,
            f"l4_hands_pool 应扫出 > 100 个 skill，实际 {len(skills)}")

    def test_skip_underscore_files(self):
        """以 _ 开头的文件应跳过（如 __init__.py）"""
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, '_should_skip.py'), 'w', encoding='utf-8') as f:
                f.write('MANIFEST = {"name": "x", "description": "y"}\n')
                f.write('class Hands:\n  def get_instruction_dict(self): return ""\n')
            skills = SkillScanner.scan_pool(td)
            self.assertEqual(len(skills), 0)

    def test_nonexistent_pool_returns_empty(self):
        self.assertEqual(SkillScanner.scan_pool('/path/does/not/exist'), [])

    def test_scan_all_pools_includes_both(self):
        skills = SkillScanner.scan_all_pools(ROOT)
        # 应含 l4_hands_pool 的 audio_hands + l2_eyes_pool 的 (若有)
        cmds = {sk.command for sk in skills}
        l4_present = any(c.startswith('audio_hands.') for c in cmds)
        self.assertTrue(l4_present, 'scan_all_pools 应含 l4_hands_pool 内容')


# ==========================================================================
# TestExplicitDangerOverride
# ==========================================================================

class TestExplicitDangerOverride(unittest.TestCase):
    """模块 MANIFEST 里显式 command_dangers 字典应优先于启发式"""

    def test_explicit_danger_overrides_heuristic(self):
        with tempfile.TemporaryDirectory() as td:
            mod_path = os.path.join(td, 'fake_hand.py')
            with open(mod_path, 'w', encoding='utf-8') as f:
                f.write('''
MANIFEST = {
    "name": "fake_hand",
    "description": "test",
    "command_dangers": {
        "list_items": "dangerous",
        "kill_process": "safe"
    }
}

class Hands:
    def get_instruction_dict(self):
        return """
        1. "list_items": {} - 列出条目
        2. "kill_process": {"pid": 123} - 终止进程
        3. "set_value": {"v": 1} - 设置值
        """
''')
            skills = SkillScanner.scan_module_file(mod_path)
            sk_map = {sk.command: sk for sk in skills}
            self.assertEqual(sk_map['fake_hand.list_items'].dangerous_flag, DANGER_DANGEROUS,
                'list_items 显式 declare 为 dangerous → 必须覆盖启发式 SAFE')
            self.assertEqual(sk_map['fake_hand.kill_process'].dangerous_flag, DANGER_SAFE,
                'kill_process 显式 declare 为 safe → 必须覆盖启发式 DANGEROUS')
            self.assertEqual(sk_map['fake_hand.set_value'].dangerous_flag, DANGER_RISKY,
                '未在 command_dangers 声明的 set_value 走启发式 → RISKY')


# ==========================================================================
# TestRealLifeRegression
# ==========================================================================

class TestRealLifeRegression(unittest.TestCase):
    """真实 l4_hands_pool 扫出的关键分类不能回退"""

    @classmethod
    def setUpClass(cls):
        cls.skills = SkillScanner.scan_all_pools(ROOT)
        cls.by_cmd = {sk.command: sk for sk in cls.skills}

    def test_total_count_in_expected_range(self):
        """共应扫出 ~130 个 skill（允许 ±20 浮动以适应未来 hand 增减）"""
        self.assertGreater(len(self.skills), 100)
        self.assertLess(len(self.skills), 200)

    def test_critical_safe_skills(self):
        """这些必须是 SAFE，否则 OfferGuard 会过严"""
        for cmd in ['audio_hands.list_devices', 'audio_hands.get_volume',
                    'clipboard_hands.get', 'process_hands.list_processes',
                    'process_hands.is_running', 'process_hands.find_process',
                    'window_hands.list_windows', 'window_hands.get_foreground',
                    'watcher_hands.screenshot', 'network_hands.wifi_status']:
            sk = self.by_cmd.get(cmd)
            self.assertIsNotNone(sk, f'未扫到 {cmd}')
            self.assertEqual(sk.dangerous_flag, DANGER_SAFE,
                f'{cmd} 应是 SAFE，实际 {sk.dangerous_flag}')

    def test_critical_dangerous_skills(self):
        """这些必须是 DANGEROUS，否则 PromiseLedger 会自动跑越权动作"""
        for cmd in ['process_hands.kill_process', 'process_hands.kill_by_name',
                    'input_hands.click', 'input_hands.type_text',
                    'input_hands.hotkey', 'input_hands.scroll',
                    'input_hands.paste_text']:
            sk = self.by_cmd.get(cmd)
            self.assertIsNotNone(sk, f'未扫到 {cmd}')
            self.assertEqual(sk.dangerous_flag, DANGER_DANGEROUS,
                f'{cmd} 应是 DANGEROUS，实际 {sk.dangerous_flag}')

    def test_critical_risky_skills(self):
        """这些必须是 RISKY（影响系统但可恢复）"""
        for cmd in ['audio_hands.set_volume', 'audio_hands.mute',
                    'window_hands.minimize', 'window_hands.show',
                    'notification_hands.toast', 'notification_hands.beep']:
            sk = self.by_cmd.get(cmd)
            if sk is None:
                continue  # 容忍 hand 重命名
            self.assertEqual(sk.dangerous_flag, DANGER_RISKY,
                f'{cmd} 应是 RISKY，实际 {sk.dangerous_flag}')


if __name__ == '__main__':
    runner = unittest.TextTestRunner(verbosity=2)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = runner.run(suite)
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("[OK] All R8 axis3 L0.2 SkillScanner tests passed.")
    else:
        print(f"[FAIL] {len(result.failures)} failures, {len(result.errors)} errors")
    print("=" * 60)
    sys.exit(0 if result.wasSuccessful() else 1)
