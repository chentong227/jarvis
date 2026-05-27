"""[Sir 2026-05-28 07:18 真痛 BUG 治本] PromiseLog description quality check.

源 BUG: SmartNudge '您 02:43 定的 25min 番茄钟逾期 4h' = promise_log 真有
author=jarvis description='pomodoro 25min' 的 placeholder commitment (Sir 测 CLI
塞 + testcase 残留). LLM 看脏数据当真生成幻觉 nudge.

修法 (准则 6 + 8):
- 写入端 PromiseLog.register() 加 description 质量校验 (vocab blacklist)
- 读取端 CommitmentWatcher._load_pending_from_promise_log() 过滤脏 description
- 加 author 字段进 commitments dict (下游 LLM 看 author=sir vs jarvis 自决)
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestPromiseQualityVocab(unittest.TestCase):
    """vocab json 持久化 + helper fn."""

    def test_vocab_file_exists(self):
        path = os.path.join(ROOT, 'memory_pool',
                             'promise_description_quality_vocab.json')
        self.assertTrue(os.path.exists(path), f'vocab file missing: {path}')
        with open(path, 'r', encoding='utf-8') as f:
            v = json.load(f)
        self.assertIn('blacklist_descriptions', v)
        self.assertIn('exact_match', v['blacklist_descriptions'])
        self.assertIn('x', v['blacklist_descriptions']['exact_match'])
        self.assertIn('spam', v['blacklist_descriptions']['exact_match'])
        self.assertIn('[testcase]', v['blacklist_descriptions']['prefix_match'])
        self.assertEqual(v.get('behavior_on_violation'), 'reject_silent')

    def test_check_description_quality_blacklist(self):
        from jarvis_promise_log import _check_description_quality as qc
        for bad in ('x', 'spam', 'TODO', '', '...', '123', '[testcase] foo'):
            rejected, reason, mode = qc(bad)
            self.assertTrue(rejected, f'should reject {bad!r}, got reason={reason}')

    def test_check_description_quality_accept_real(self):
        from jarvis_promise_log import _check_description_quality as qc
        for good in ('do laundry', '吃饭看书',
                      'I will check the keyrouter health',
                      'pomodoro 25min'):  # 字面合理, 通过 (author 过滤是另条路)
            rejected, reason, _ = qc(good)
            self.assertFalse(rejected, f'should accept {good!r}, got reason={reason}')


class TestPromiseRegisterReject(unittest.TestCase):
    """register() 调 quality check 真退化."""

    def test_register_reject_returns_empty(self):
        # 用临时 path 防污染真 ledger
        from jarvis_promise_log import PromiseExecutionLog
        with tempfile.TemporaryDirectory() as tmp:
            log = PromiseExecutionLog(persist_path=os.path.join(tmp, 'p.json'))
            pid = log.register(description='x', kind='cyclic',
                                deadline_str='2026-12-31 12:00:00')
            self.assertEqual(pid, '', 'reject_silent should return empty id')
            self.assertEqual(len(log.promises), 0, 'no promise written')

    def test_register_accept_real_returns_id(self):
        from jarvis_promise_log import PromiseExecutionLog
        with tempfile.TemporaryDirectory() as tmp:
            log = PromiseExecutionLog(persist_path=os.path.join(tmp, 'p.json'))
            pid = log.register(description='I will check keyrouter health',
                                kind='soft', jarvis_reply='I will check')
            self.assertTrue(pid.startswith('p_'), f'should accept, got id={pid!r}')
            self.assertEqual(len(log.promises), 1)


class TestCommitmentWatcherFilter(unittest.TestCase):
    """_load_pending_from_promise_log() 过滤脏 description + 注入 author."""

    def test_filter_skips_blacklist_desc(self):
        # 直接测 quality fn 工作正确 + 验 commitment_watcher 导入正常
        from jarvis_commitment_watcher import CommitmentWatcher  # noqa: F401
        from jarvis_promise_log import _check_description_quality
        rej, _, _ = _check_description_quality('x')
        self.assertTrue(rej, 'CW 内部 _qc 必须能拒 x')
        rej_ok, _, _ = _check_description_quality('pomodoro 25min')
        self.assertFalse(rej_ok, 'pomodoro 25min 是字面合理, 不靠 quality 过滤; 靠 author 字段下游 LLM 自决')

    def test_commitments_dict_has_author_field(self):
        # 检查源码确保 author/who_promised 字段进 commitments dict
        cw_path = os.path.join(ROOT, 'jarvis_commitment_watcher.py')
        with open(cw_path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn("'author': getattr(p, 'author', '') or 'jarvis'", src,
                       'commitments dict must include author field for downstream LLM filter')
        self.assertIn("'who_promised':", src,
                       'commitments dict must include who_promised field')


class TestPromiseLogResetQualityFilter(unittest.TestCase):
    """promise_log_reset.py --quality-filter flag."""

    def test_quality_filter_flag_in_help(self):
        # 不调 subprocess (Windows gbk encode 中文 help 有问题), 直接 grep 源码
        path = os.path.join(ROOT, 'scripts', 'promise_log_reset.py')
        with open(path, 'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('--quality-filter', src,
                       'scripts/promise_log_reset.py must have --quality-filter')
        self.assertIn('--only-author-jarvis', src,
                       'scripts/promise_log_reset.py must have --only-author-jarvis')
        self.assertIn('_check_description_quality', src,
                       'should import _check_description_quality')


if __name__ == '__main__':
    unittest.main(verbosity=2)
