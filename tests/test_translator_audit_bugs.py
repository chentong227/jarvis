# -*- coding: utf-8 -*-
"""[Sir 2026-05-24 22:57 audit] 主动审计 6 个 BUG / 盲点 regression test.

源 BUG (我自审):
  #1 🔴 真 BUG: vocab.json 并发写 race (reflector propose + translator flush 各自 RMW)
     → 后写覆盖前写, 一边工作丢失
  #2 🟡 alias 被 reject 后 hit_buffer 仍 bump → flush 时 bump 死 alias
  #3 🟡 /api/translator/<alias_id>/<action> 无 input validation
  #4 🟡 _put_audio META guard 只 cover '[META]' 字面, 不 cover [Meta]/【META】
  #5 🟡 reflector config 负数 / 0 / 极值无 validate
  #6 ⚪ nerve shutdown 不 stop TranslatorHitFlush daemon (atexit hook)

修法:
  #1 加 jarvis_translator_vocab_io.py 集中 IO + module-level RLock + read_then_mutate
  #2 flush_hit_updates 跳过非 active alias
  #3 alias_id 必须 match `alias_\d{1,8}` regex
  #4 META guard regex case-insensitive + 中英括号 [meta] / 【meta】
  #5 _load_config 加 _MIN_VALUES 边界, 越界 fallback 默认
  #6 nerve atexit hook: 退出前 flush + stop daemon event
"""
import os
import json
import time
import tempfile
import shutil
import threading
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


# ============================================================
# BUG #1: vocab.json 并发写 race
# ============================================================

class TestBug1VocabConcurrentWriteRace(unittest.TestCase):
    """vocab_io.read_then_mutate 保证并发 RMW 不丢数据."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._tmp_vocab = os.path.join(self._tmpdir, 'vocab.json')
        # seed empty vocab
        with open(self._tmp_vocab, 'w', encoding='utf-8') as f:
            json.dump({'schema_version': 1, 'aliases': []}, f)

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_vocab_io_module_exists(self):
        from jarvis_translator_vocab_io import (
            load_vocab, save_vocab, read_then_mutate, get_lock
        )
        self.assertTrue(callable(load_vocab))
        self.assertTrue(callable(save_vocab))
        self.assertTrue(callable(read_then_mutate))
        self.assertIsInstance(get_lock(), type(threading.RLock()))

    def test_concurrent_mutate_no_data_loss(self):
        """20 个 thread 同时调 read_then_mutate append alias, 全部应 persist."""
        from jarvis_translator_vocab_io import read_then_mutate

        N_THREADS = 20

        def _add_one(i):
            def _mutator(vocab):
                vocab.setdefault('aliases', []).append({'id': f'alias_{i:03d}'})
                return True
            read_then_mutate(self._tmp_vocab, _mutator)

        threads = [threading.Thread(target=_add_one, args=(i,)) for i in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # 验全部 persist
        with open(self._tmp_vocab, 'r', encoding='utf-8') as f:
            final = json.load(f)
        ids = {a['id'] for a in final['aliases']}
        self.assertEqual(len(ids), N_THREADS, '20 个 thread 同时写, 全部应 persist')

    def test_concurrent_translator_flush_and_reflector_propose(self):
        """模拟 translator.flush + reflector.propose 并发, 不互相覆盖."""
        from jarvis_translator_vocab_io import read_then_mutate

        # seed 1 个 active alias (translator flush 会 bump 它)
        with open(self._tmp_vocab, 'w', encoding='utf-8') as f:
            json.dump({
                'schema_version': 1,
                'aliases': [{'id': 'alias_001', 'kind': 'organ',
                              'from': 'a', 'to': 'b', 'status': 'active',
                              'hit_count': 0}],
            }, f)

        def _flush_bump(_n):
            """模拟 translator flush: bump hit_count."""
            def _m(vocab):
                for a in vocab['aliases']:
                    if a['id'] == 'alias_001':
                        a['hit_count'] = a.get('hit_count', 0) + 1
                return True
            read_then_mutate(self._tmp_vocab, _m)

        def _propose_new(i):
            """模拟 reflector propose: 加新 alias."""
            def _m(vocab):
                vocab['aliases'].append({'id': f'alias_pro_{i:03d}',
                                          'from': 'x', 'to': 'y',
                                          'status': 'review'})
                return True
            read_then_mutate(self._tmp_vocab, _m)

        threads = []
        for i in range(10):
            threads.append(threading.Thread(target=_flush_bump, args=(i,)))
            threads.append(threading.Thread(target=_propose_new, args=(i,)))
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        with open(self._tmp_vocab, 'r', encoding='utf-8') as f:
            final = json.load(f)
        # 验 hit_count = 10 (10 次 flush)
        alias_001 = next(a for a in final['aliases'] if a['id'] == 'alias_001')
        self.assertEqual(alias_001['hit_count'], 10, 'flush 10 次应全 persist')
        # 验 10 个 propose 全 persist
        proposed = [a for a in final['aliases'] if a['id'].startswith('alias_pro_')]
        self.assertEqual(len(proposed), 10, 'propose 10 次应全 persist')


# ============================================================
# BUG #2: alias reject 后 hit_buffer 仍 bump → flush 时跳过
# ============================================================

class TestBug2RejectAliasNotBumped(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._tmp_vocab = os.path.join(self._tmpdir, 'vocab.json')
        import jarvis_translator as t
        self._orig = t._ALIAS_VOCAB_PATH
        t._ALIAS_VOCAB_PATH = self._tmp_vocab

    def tearDown(self):
        import jarvis_translator as t
        t._ALIAS_VOCAB_PATH = self._orig
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_flush_skips_rejected_alias(self):
        """alias 已被 reject → flush 时不 bump hit_count."""
        with open(self._tmp_vocab, 'w', encoding='utf-8') as f:
            json.dump({
                'schema_version': 1,
                'aliases': [{'id': 'alias_001', 'kind': 'organ',
                              'from': 'a', 'to': 'b',
                              'status': 'rejected', 'hit_count': 5}],
            }, f)
        from jarvis_translator import Translator
        tr = Translator(hand_registry={'b': object})
        # 手 inject pending bump (模拟 reject 前已命中, flush 还没跑)
        with tr._hit_buffer_lock:
            tr._hit_buffer['alias_001'] = 3
            tr._hit_buffer_last_ts['alias_001'] = time.time()
        merged = tr.flush_hit_updates()
        self.assertEqual(merged, 0, 'rejected alias 不应被 bump')
        with open(self._tmp_vocab, 'r', encoding='utf-8') as f:
            v = json.load(f)
        self.assertEqual(v['aliases'][0]['hit_count'], 5, 'hit_count 应保持 5 不变')


# ============================================================
# BUG #3: dashboard alias_id input validation
# ============================================================

class TestBug3DashboardInputValidation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'scripts', 'jarvis_dashboard_web.py'),
                  'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_alias_id_regex_validation(self):
        """dashboard 应有 alias_id regex 校验."""
        self.assertIn(r"alias_\d{1,8}", self.src,
                      'alias_id 必须 match alias_\\d{1,8} regex')

    def test_invalid_alias_id_returns_400(self):
        """API 应返 400 + message_zh."""
        self.assertIn("'非法 alias 编号格式", self.src)


# ============================================================
# BUG #4: META guard case-insensitive + 中英括号
# ============================================================

class TestBug4MetaGuardCaseAndBracket(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_chat_bypass.py'),
                  'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_meta_guard_uses_regex(self):
        """_put_audio 的 META guard 应用 regex 不再硬编码 '[META]' in text."""
        # 必须 含 IGNORECASE + 中英括号 pattern
        self.assertIn('IGNORECASE', self.src,
                      'META guard 必须 case-insensitive')
        self.assertIn(r'[\[【]\s*meta\s*[\]】]', self.src,
                      'META guard regex 必须 cover 中英括号')


# ============================================================
# BUG #5: reflector config 值域 validate
# ============================================================

class TestBug5ConfigValueValidation(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._tmp_config = os.path.join(self._tmpdir, 'config.json')
        import jarvis_translator_reflector as trr
        self._orig = trr.CONFIG_PATH
        trr.CONFIG_PATH = self._tmp_config

    def tearDown(self):
        import jarvis_translator_reflector as trr
        trr.CONFIG_PATH = self._orig
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_negative_tick_interval_fallback_default(self):
        with open(self._tmp_config, 'w', encoding='utf-8') as f:
            json.dump({'tick_interval_s': -100}, f)
        from jarvis_translator_reflector import _load_config
        cfg = _load_config()
        self.assertEqual(cfg['tick_interval_s'], 1800.0,
                         '负数应 fallback 默认 1800')

    def test_zero_propose_threshold_fallback(self):
        with open(self._tmp_config, 'w', encoding='utf-8') as f:
            json.dump({'propose_threshold': 0}, f)
        from jarvis_translator_reflector import _load_config
        cfg = _load_config()
        self.assertEqual(cfg['propose_threshold'], 3,
                         '0 应 fallback 默认 3 (0 = 无脑 propose 灾难)')

    def test_too_small_tick_interval_fallback(self):
        """tick_interval < 10s 应 fallback (防过频 IO)."""
        with open(self._tmp_config, 'w', encoding='utf-8') as f:
            json.dump({'tick_interval_s': 5}, f)
        from jarvis_translator_reflector import _load_config
        cfg = _load_config()
        self.assertEqual(cfg['tick_interval_s'], 1800.0)

    def test_valid_values_accepted(self):
        with open(self._tmp_config, 'w', encoding='utf-8') as f:
            json.dump({
                'tick_interval_s': 60,
                'propose_threshold': 2,
                'scan_window_s': 3600,
            }, f)
        from jarvis_translator_reflector import _load_config
        cfg = _load_config()
        self.assertEqual(cfg['tick_interval_s'], 60.0)
        self.assertEqual(cfg['propose_threshold'], 2)
        self.assertEqual(cfg['scan_window_s'], 3600.0)


# ============================================================
# BUG #6: nerve atexit flush hook
# ============================================================

class TestBug6NerveAtexitFlush(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, 'jarvis_central_nerve.py'),
                  'r', encoding='utf-8') as f:
            cls.src = f.read()

    def test_atexit_registered_for_translator_flush(self):
        """nerve 应在 translator init 后 atexit register flush hook."""
        # 找 TranslatorHitFlush daemon 创建后, 应有 atexit register
        idx = self.src.find('TranslatorHitFlush')
        self.assertGreater(idx, 0)
        section = self.src[idx:idx + 2000]
        self.assertIn('atexit', section, 'TranslatorHitFlush 后必须 atexit register')
        self.assertIn('_translator_flush_stop.set()', section,
                      'atexit hook 必须 stop daemon event')
        self.assertIn('flush_hit_updates()', section,
                      'atexit hook 必须 final flush')


if __name__ == '__main__':
    unittest.main()
