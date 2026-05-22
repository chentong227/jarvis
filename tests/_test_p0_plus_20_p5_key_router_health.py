# -*- coding: utf-8 -*-
"""[P5-fix20-A1+A2 / 2026-05-22] KeyRouter health snapshot + reset CLI 测试.

Sir 14:32 真测痛点修: OpenRouter 全挂 + Google 池 429 → 主脑能开口但
IntentResolver/Vision/Hippocampus 全降级 → "嘴上说没真做".

测试覆盖 (~12 条):
  A: KeyRouter.get_stats() schema 扩展 (cooldown / permanent_dead / pools / overall_health)
  B: KeyRouter.reset_cooldown / reset_permanent_death / reset_all
  C: _write_health_snapshot 写 disk
  D: _poll_reset_request → 执行 reset → 标 consumed → 写 audit
  E: dashboard /api/key_health 返 snapshot
  F: dashboard /api/key_reset 写 request 文件
  G: dashboard 主页 mini card + header banner 渲染
  H: CLI scripts/key_router_dump.py --show / --reset-all / --audit
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _make_router(google_keys=None, or_keys=None, isolated_state=True):
    """Build a KeyRouter with fake keys for unit test.

    isolated_state=True: 用 tmp 路径覆盖 _STATE_FILE_PATH +
    _HEALTH_SNAPSHOT_PATH + _RESET_REQUEST_PATH + _RESET_AUDIT_PATH,
    避免污染 / 被污染 (e.g. disk 上有真实的 permanent_death 状态).
    """
    from jarvis_key_router import KeyRouter
    g = google_keys if google_keys is not None else ['AIzaSyFAKE_G1', 'AIzaSyFAKE_G2']
    o = or_keys if or_keys is not None else ['sk-or-v1-fake1', 'sk-or-v1-fake2']
    if isolated_state:
        # patch class attribute → __init__ 走的是 isolated 路径, 不读真实 state
        tmp_dir = tempfile.mkdtemp(prefix='kr_test_')
        KeyRouter._STATE_FILE_PATH = os.path.join(tmp_dir, 'state.json')
        KeyRouter._HEALTH_SNAPSHOT_PATH = os.path.join(tmp_dir, 'health.json')
        KeyRouter._RESET_REQUEST_PATH = os.path.join(tmp_dir, 'req.json')
        KeyRouter._RESET_AUDIT_PATH = os.path.join(tmp_dir, 'audit.jsonl')
    kr = KeyRouter(
        main_brain_key='sk-or-v1-mainbrain-fake',
        google_keys=g,
        openrouter_keys=o,
    )
    # 测试里关 snapshot daemon, 避免与 _write_health_snapshot 竞争 (Windows
    # PermissionError on os.replace).
    try:
        kr._snapshot_stop.set()
        if hasattr(kr, '_snapshot_thread'):
            kr._snapshot_thread.join(timeout=2.0)
    except Exception:
        pass
    return kr


class TestA_StatsSchema(unittest.TestCase):
    """A: get_stats() 扩展 schema 含 cooldown / pools / overall_health."""

    def test_stats_has_pools(self):
        kr = _make_router()
        s = kr.get_stats()
        self.assertIn('pools', s)
        self.assertIn('main_brain', s['pools'])
        self.assertIn('google', s['pools'])
        self.assertIn('openrouter', s['pools'])
        # 每池都有 total/healthy/permanent_dead/in_cooldown
        for name in ('main_brain', 'google', 'openrouter'):
            for k in ('total', 'healthy', 'permanent_dead', 'in_cooldown'):
                self.assertIn(k, s['pools'][name],
                              f"pool {name} 缺 key {k}")

    def test_stats_has_overall_health(self):
        kr = _make_router()
        s = kr.get_stats()
        self.assertIn('overall_health', s)
        # 全新 router 应是 ok
        self.assertEqual(s['overall_health'], 'ok')

    def test_stats_overall_crit_when_pool_dead(self):
        """OpenRouter 全挂 → overall=crit."""
        kr = _make_router()
        # 标 OpenRouter 全部 dead (含 main_brain)
        with kr._lock:
            for k, v in kr._key_status.items():
                if v['provider'] == 'openrouter':
                    v['healthy'] = False
                    v['permanently_dead'] = True
        s = kr.get_stats()
        # main_brain pool + openrouter pool 都全挂
        self.assertEqual(s['overall_health'], 'crit')

    def test_stats_key_status_has_cooldown_fields(self):
        kr = _make_router()
        s = kr.get_stats()
        for label, st in s['key_status'].items():
            self.assertIn('cooldown_remaining_s', st)
            self.assertIn('in_cooldown', st)
            self.assertIn('permanently_dead', st)
            self.assertIn('last_error', st)


class TestB_ResetMethods(unittest.TestCase):
    """B: reset_cooldown / reset_permanent_death / reset_all."""

    def test_reset_cooldown(self):
        kr = _make_router()
        # 模拟 google_1 进入 cooldown
        with kr._lock:
            for k, v in kr._key_status.items():
                if v['label'] == 'google_1':
                    v['healthy'] = False
                    v['error_count'] = 3
                    v['last_error'] = '429 quota'
                    v['last_error_time'] = time.time()
                    break
        # 调 reset_cooldown
        ok = kr.reset_cooldown('google_1')
        self.assertTrue(ok)
        # 验证 google_1 healthy 回 True
        for k, v in kr._key_status.items():
            if v['label'] == 'google_1':
                self.assertTrue(v['healthy'])
                self.assertEqual(v['error_count'], 0)
                break

    def test_reset_cooldown_permanent_dead_fails(self):
        kr = _make_router()
        with kr._lock:
            for k, v in kr._key_status.items():
                if v['label'] == 'google_1':
                    v['healthy'] = False
                    v['permanently_dead'] = True
                    break
        ok = kr.reset_cooldown('google_1')
        self.assertFalse(ok, "permanent_dead 应该 fail (要走 reset_permanent_death)")

    def test_reset_all(self):
        kr = _make_router()
        # 标 google_1 cooldown, google_2 permanent_dead
        with kr._lock:
            for k, v in kr._key_status.items():
                if v['label'] == 'google_1':
                    v['healthy'] = False
                    v['last_error_time'] = time.time()
                elif v['label'] == 'google_2':
                    v['healthy'] = False
                    v['permanently_dead'] = True
        out = kr.reset_all()
        self.assertIn('google_1', out['reset_cooldown'])
        self.assertIn('google_2', out['reset_permanent'])


class TestC_HealthSnapshot(unittest.TestCase):
    """C: _write_health_snapshot 写 disk."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.snapshot = os.path.join(self.tmp, 'health.json')

    def tearDown(self):
        import shutil
        try:
            shutil.rmtree(self.tmp)
        except Exception:
            pass

    def test_snapshot_written(self):
        kr = _make_router()
        # 暂时 patch path 让它写到 tmp
        kr._HEALTH_SNAPSHOT_PATH = self.snapshot
        kr._write_health_snapshot()
        self.assertTrue(os.path.exists(self.snapshot))
        with open(self.snapshot, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('pools', data)
        self.assertIn('overall_health', data)
        self.assertIn('_snapshot_ts', data)
        self.assertIn('_snapshot_iso', data)


class TestD_PollResetRequest(unittest.TestCase):
    """D: _poll_reset_request 执行 reset → 标 consumed → 写 audit."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.req_path = os.path.join(self.tmp, 'reset_req.json')
        self.audit_path = os.path.join(self.tmp, 'audit.jsonl')
        self.snapshot = os.path.join(self.tmp, 'health.json')

    def tearDown(self):
        import shutil
        try:
            shutil.rmtree(self.tmp)
        except Exception:
            pass

    def _build_router(self):
        kr = _make_router()
        kr._RESET_REQUEST_PATH = self.req_path
        kr._RESET_AUDIT_PATH = self.audit_path
        kr._HEALTH_SNAPSHOT_PATH = self.snapshot
        return kr

    def _write_req(self, action, label=''):
        req = {
            'action': action, 'label': label, 'source': 'test',
            'requested_at': time.time(),
            'requested_iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'consumed': False,
        }
        with open(self.req_path, 'w', encoding='utf-8') as f:
            json.dump(req, f)
        return req

    def test_poll_reset_all(self):
        kr = self._build_router()
        # 标 google_1 cooldown
        with kr._lock:
            for k, v in kr._key_status.items():
                if v['label'] == 'google_1':
                    v['healthy'] = False
                    v['last_error_time'] = time.time()
        self._write_req('all')
        kr._poll_reset_request()
        # 验证 consumed
        with open(self.req_path, 'r', encoding='utf-8') as f:
            req = json.load(f)
        self.assertTrue(req['consumed'])
        self.assertIn('result', req)
        self.assertEqual(req['result']['outcome'], 'ok')
        # 验证 google_1 healthy 回 True
        for k, v in kr._key_status.items():
            if v['label'] == 'google_1':
                self.assertTrue(v['healthy'])
                break
        # 验证 audit 写了
        self.assertTrue(os.path.exists(self.audit_path))
        with open(self.audit_path, 'r', encoding='utf-8') as f:
            line = f.readline().strip()
        entry = json.loads(line)
        self.assertEqual(entry['result']['action'], 'all')

    def test_poll_idempotent_consumed(self):
        """consumed=True 的请求不应被重复执行."""
        kr = self._build_router()
        req = self._write_req('all')
        req['consumed'] = True
        with open(self.req_path, 'w', encoding='utf-8') as f:
            json.dump(req, f)
        kr._poll_reset_request()
        # audit 应该是空 / 不存在 (没新 entry)
        if os.path.exists(self.audit_path):
            self.assertEqual(os.path.getsize(self.audit_path), 0,
                             'consumed=True 不该再写 audit')

    def test_poll_no_request_file(self):
        """无 request 文件不应 crash."""
        kr = self._build_router()
        # 没写 req 文件
        kr._poll_reset_request()  # should not raise


class TestE_DashboardKeyHealthApi(unittest.TestCase):
    """E: dashboard /api/key_health 返回 snapshot."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.snapshot_path = os.path.join(self.tmp_dir, 'key_router_health.json')
        snap = {
            '_snapshot_ts': time.time(),
            '_snapshot_iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'overall_health': 'crit',
            'pools': {
                'main_brain': {'total': 1, 'healthy': 0, 'unhealthy': 1,
                                'permanent_dead': 1, 'in_cooldown': 0},
                'google': {'total': 2, 'healthy': 1, 'unhealthy': 1,
                            'permanent_dead': 0, 'in_cooldown': 1},
                'openrouter': {'total': 2, 'healthy': 0, 'unhealthy': 2,
                                'permanent_dead': 2, 'in_cooldown': 0},
            },
            'key_status': {
                'main_brain': {'healthy': False, 'permanently_dead': True,
                                 'in_cooldown': False, 'last_error': '401',
                                 'cooldown_remaining_s': 0, 'errors': 5},
                'google_1': {'healthy': True, 'permanently_dead': False,
                              'in_cooldown': False, 'last_error': '',
                              'cooldown_remaining_s': 0, 'errors': 0},
            },
            'openrouter_calls_today': 42,
        }
        with open(self.snapshot_path, 'w', encoding='utf-8') as f:
            json.dump(snap, f)
        # patch dashboard module _read_key_health to read tmp file
        sys.path.insert(0, os.path.join(ROOT, 'scripts'))
        import importlib
        if 'jarvis_dashboard_web' in sys.modules:
            self._mod = sys.modules['jarvis_dashboard_web']
        else:
            self._mod = importlib.import_module('jarvis_dashboard_web')
        self._orig_read = self._mod._read_key_health

        snap_path = self.snapshot_path

        def patched_read():
            if not os.path.exists(snap_path):
                return {'available': False}
            with open(snap_path, 'r', encoding='utf-8') as f:
                stats = json.load(f)
            age_s = max(0, int(time.time() - stats.get('_snapshot_ts', 0)))
            return {
                'available': True,
                'overall': stats.get('overall_health'),
                'health_msg': '❌ openrouter 池全挂 (0/2)',
                'pools': stats.get('pools', {}),
                'key_status': stats.get('key_status', {}),
                'openrouter_calls_today': stats.get('openrouter_calls_today', 0),
                'snapshot_age_s': age_s,
                'snapshot_iso': stats.get('_snapshot_iso', ''),
            }
        self._mod._read_key_health = patched_read

    def tearDown(self):
        try:
            if hasattr(self, '_mod') and hasattr(self, '_orig_read'):
                self._mod._read_key_health = self._orig_read
        except Exception:
            pass
        import shutil
        try:
            shutil.rmtree(self.tmp_dir)
        except Exception:
            pass

    def test_api_key_health_returns_data(self):
        with self._mod.app.test_client() as c:
            r = c.get('/api/key_health')
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data['ok'])
        self.assertIn('data', data)
        d = data['data']
        self.assertEqual(d['overall'], 'crit')
        self.assertIn('pools', d)
        self.assertIn('openrouter', d['pools'])


class TestF_DashboardKeyResetApi(unittest.TestCase):
    """F: /api/key_reset 写 request 文件."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.req_path_expected = os.path.join(
            ROOT, 'memory_pool', 'key_router_reset_request.json')

    def tearDown(self):
        import shutil
        try:
            shutil.rmtree(self.tmp_dir)
        except Exception:
            pass

    def _get_app(self):
        sys.path.insert(0, os.path.join(ROOT, 'scripts'))
        import importlib
        if 'jarvis_dashboard_web' in sys.modules:
            mod = importlib.reload(sys.modules['jarvis_dashboard_web'])
        else:
            mod = importlib.import_module('jarvis_dashboard_web')
        return mod.app

    def test_post_reset_all_writes_request(self):
        app = self._get_app()
        # 备份现有的 reset request 文件 (如果存在), 测后还原
        backup = None
        if os.path.exists(self.req_path_expected):
            with open(self.req_path_expected, 'r', encoding='utf-8') as f:
                backup = f.read()
        try:
            with app.test_client() as c:
                r = c.post('/api/key_reset',
                              json={'action': 'all', 'source': 'test'})
            self.assertEqual(r.status_code, 200)
            d = r.get_json()
            self.assertTrue(d['ok'])
            # 验证文件写了
            self.assertTrue(os.path.exists(self.req_path_expected))
            with open(self.req_path_expected, 'r', encoding='utf-8') as f:
                req = json.load(f)
            self.assertEqual(req['action'], 'all')
            self.assertEqual(req['source'], 'test')
            self.assertFalse(req['consumed'])
        finally:
            if backup is not None:
                with open(self.req_path_expected, 'w', encoding='utf-8') as f:
                    f.write(backup)

    def test_post_reset_invalid_action(self):
        app = self._get_app()
        with app.test_client() as c:
            r = c.post('/api/key_reset', json={'action': 'XXX'})
        self.assertEqual(r.status_code, 400)
        d = r.get_json()
        self.assertFalse(d['ok'])

    def test_post_reset_cooldown_requires_label(self):
        app = self._get_app()
        with app.test_client() as c:
            r = c.post('/api/key_reset', json={'action': 'cooldown'})
        self.assertEqual(r.status_code, 400)


class TestG_DashboardUI(unittest.TestCase):
    """G: 主页 mini card + header banner 渲染."""

    def _get_app(self):
        sys.path.insert(0, os.path.join(ROOT, 'scripts'))
        import importlib
        if 'jarvis_dashboard_web' in sys.modules:
            mod = importlib.reload(sys.modules['jarvis_dashboard_web'])
        else:
            mod = importlib.import_module('jarvis_dashboard_web')
        return mod.app

    def test_home_has_key_health_card(self):
        app = self._get_app()
        with app.test_client() as c:
            r = c.get('/')
        body = r.data.decode('utf-8')
        self.assertIn('API Key 池健康', body, '主页应有 key 池 mini card 标题')
        self.assertIn('data-key-card', body, 'mini card 应有 data-key-card anchor')

    def test_home_has_crit_banner(self):
        app = self._get_app()
        with app.test_client() as c:
            r = c.get('/')
        body = r.data.decode('utf-8')
        # banner 仅当 keyHealth.overall === 'crit' 时显示, 但 HTML 模板里要存在
        self.assertIn('API Key 池雪崩', body, 'header 应有 crit banner 文本')

    def test_api_all_has_key_health(self):
        """/api/all 应含 keyHealth 字段供主页渲染."""
        app = self._get_app()
        with app.test_client() as c:
            r = c.get('/api/all')
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn('keyHealth', data,
                      '/api/all 应返回 keyHealth 字段供主页 mini card 渲染')


class TestH_CLI(unittest.TestCase):
    """H: scripts/key_router_dump.py CLI."""

    def setUp(self):
        self.cli = os.path.join(ROOT, 'scripts', 'key_router_dump.py')

    def test_cli_exists(self):
        self.assertTrue(os.path.exists(self.cli))

    def test_cli_help(self):
        r = subprocess.run([sys.executable, self.cli, '--help'],
                            capture_output=True, text=True, encoding='utf-8',
                            errors='replace')
        self.assertEqual(r.returncode, 0)
        self.assertIn('--show', r.stdout)
        self.assertIn('--reset-all', r.stdout)

    def test_cli_show_no_snapshot(self):
        """无 snapshot 时 --show 应给提示退码 1."""
        # 备份 snapshot (如果存在)
        snap = os.path.join(ROOT, 'memory_pool', 'key_router_health.json')
        backup = None
        if os.path.exists(snap):
            with open(snap, 'rb') as f:
                backup = f.read()
            os.unlink(snap)
        try:
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            env['PYTHONUTF8'] = '1'
            r = subprocess.run([sys.executable, self.cli, '--show'],
                                capture_output=True, text=True, encoding='utf-8',
                                errors='replace', env=env)
            self.assertEqual(r.returncode, 1, f"stdout={r.stdout!r} stderr={r.stderr!r}")
            self.assertIn('key_router_health.json', r.stdout,
                            f"stdout={r.stdout!r}")
        finally:
            if backup is not None:
                with open(snap, 'wb') as f:
                    f.write(backup)


class TestI_Marker(unittest.TestCase):
    """I: marker P5-fix20-A1/A2 出现在源码."""

    def test_marker_in_key_router(self):
        with open(os.path.join(ROOT, 'jarvis_key_router.py'),
                  'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('P5-fix20-A1', src)
        self.assertIn('P5-fix20-A2', src)

    def test_marker_in_dashboard(self):
        with open(os.path.join(ROOT, 'scripts', 'jarvis_dashboard_web.py'),
                  'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('P5-fix20-A1', src)
        self.assertIn('P5-fix20-A2', src)

    def test_marker_in_cli(self):
        with open(os.path.join(ROOT, 'scripts', 'key_router_dump.py'),
                  'r', encoding='utf-8') as f:
            src = f.read()
        self.assertIn('P5-fix20-A2', src)


if __name__ == '__main__':
    unittest.main(verbosity=2)
