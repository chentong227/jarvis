"""tests/_test_fix50_sir_20260528_screen_watch_clarify.py — Screen Watch fix50 单测

[Sir 2026-05-28 23:36 fix50 / 5 改动覆盖]

测什么:
  - 改动 4 (vocab): watch_task_config.json 含 vague_trigger_phrases_zh/en
  - 改动 1 (Registrar vague branch):
      _has_vague_phrase 命中 vs 不命中
      _parse_llm_json 处理 verdict='vague'/'concrete'/'not_a_watch'/老 schema
      _publish_vague_clarify SWM event 真发
      _register_blocking 分支正确分流 (concrete/vague/vague_phrase_fallback/skip)
      render_vague_clarify_block 真渲染 block 给主脑
  - 改动 3 (inner_thought tick + ScreenVision advice):
      _check_active_watch_task_and_publish_vision_refresh: 有 active task → publish
      ScreenVisionEngine._compute_effective_backfill_s: 有 advice → 短; 无 → baseline
  - 改动 5 (mirror screen mock):
      get_mirror_screen_path / read_latest_mirror_screen / append_mirror_screen
      ScreenVisionEngine._do_describe_from_fake: fake → ScreenSnapshot → publish + judge
  - CLI scripts/watch_task_dump.py vague-phrases subcommand

不测 (要 subprocess + 时间, 留 mirror 真测):
  - jarvis_central_nerve._assemble_prompt 真接入 vague_clarify block (静态 import 验)
  - mirror 真启 subprocess + 6 场景 (留 scripts/jarvis_mirror_run_screen_scenarios.py)

Sir 真测:
  pytest tests/_test_fix50_sir_20260528_screen_watch_clarify.py -v
"""
from __future__ import annotations

import json
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jarvis_mirror_mode as mm  # noqa: E402
import jarvis_screen_vision as sv  # noqa: E402
import jarvis_watch_task as wt  # noqa: E402


# ============================================================
# fixtures
# ============================================================

@pytest.fixture
def isolated_watch_paths(monkeypatch, tmp_path):
    """切 tasks/config 到 tmp_path. config 写 vague_trigger_phrases 完整 schema."""
    tasks_p = tmp_path / "watch_tasks.json"
    config_p = tmp_path / "watch_task_config.json"
    config_data = {
        'enabled': True,
        'max_active_tasks': 10,
        'default_poll_via_screen_vision': True,
        'default_expires_in_s': 14400,
        'min_judge_interval_s': 0.0,  # test 不限 judge 间隔
        'registrar_trigger_phrases_zh': ['等', '提醒我'],
        'registrar_trigger_phrases_en': ['remind me when'],
        'vague_clarify': {
            'enabled': True,
            'max_recent_show': 3,
            'prompt_block_age_s': 600.0,
            'dedup_window_s': 30.0,
        },
        'vague_trigger_phrases_zh': ['盯一下', '盯下', '看着', '看一下', '帮我盯'],
        'vague_trigger_phrases_en': ['keep an eye on', 'watch for'],
        'vision_refresh_advice': {
            'enabled': True,
            'active_watch_backfill_s': 30.0,
            'advice_ttl_s': 120.0,
            'advice_salience': 0.6,
            'dedup_window_s': 5.0,
        },
        'registrar': {'min_sir_chars': 4},
    }
    config_p.write_text(json.dumps(config_data), encoding='utf-8')
    monkeypatch.setattr(wt, 'DEFAULT_TASKS_PATH', str(tasks_p))
    monkeypatch.setattr(wt, 'DEFAULT_CONFIG_PATH', str(config_p))
    # 重置 Registrar / Judge singleton 防上 test 残留
    monkeypatch.setattr(wt, '_DEFAULT_REGISTRAR', None)
    monkeypatch.setattr(wt, '_DEFAULT_JUDGE', None)
    yield {'tasks': tasks_p, 'config': config_p, 'data': config_data}


@pytest.fixture
def fake_event_bus(monkeypatch):
    """fake event bus 抓 publish calls + 模拟 recent_events."""
    bus = MagicMock()
    bus.published = []  # records (etype, description, source, salience, ttl, metadata)
    bus.fake_events = []  # 测试可注入 fake events

    def _publish(etype, description='', source='', salience=0.5, ttl=300.0,
                  metadata=None, evidence_chain=None):
        bus.published.append({
            'etype': etype,
            'description': description,
            'source': source,
            'salience': salience,
            'ttl': ttl,
            'metadata': metadata or {},
            'ts': time.time(),
        })
        bus.fake_events.append({
            'etype': etype,
            'description': description,
            'metadata': metadata or {},
            'ts': time.time(),
        })
        return f'ev_{len(bus.published)}'

    def _recent_events(within_seconds=300.0, types=None):
        now = time.time()
        out = []
        for ev in bus.fake_events:
            if now - ev['ts'] > within_seconds:
                continue
            if types and ev['etype'] not in types:
                continue
            out.append(ev)
        return out

    bus.publish.side_effect = _publish
    bus.recent_events.side_effect = _recent_events
    monkeypatch.setattr('jarvis_utils.get_event_bus', lambda: bus)
    monkeypatch.setattr('jarvis_utils.get_default_event_bus', lambda: bus)
    yield bus


# ============================================================
# 改动 4: vocab 持久化
# ============================================================

def test_vocab_config_has_vague_trigger_phrases():
    """prod config 必含 vague_trigger_phrases_zh + en (准则 6 持久化)."""
    cfg_path = wt.DEFAULT_CONFIG_PATH
    assert os.path.exists(cfg_path), f"prod config 必须存在: {cfg_path}"
    with open(cfg_path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    assert 'vague_trigger_phrases_zh' in cfg
    assert 'vague_trigger_phrases_en' in cfg
    assert len(cfg['vague_trigger_phrases_zh']) >= 5
    assert len(cfg['vague_trigger_phrases_en']) >= 3
    # 关键 phrase 必含
    assert any('盯' in p for p in cfg['vague_trigger_phrases_zh'])
    assert any('eye' in p.lower() for p in cfg['vague_trigger_phrases_en'])
    # 配套 config dict
    assert 'vague_clarify' in cfg
    assert cfg['vague_clarify'].get('enabled') is True
    assert 'vision_refresh_advice' in cfg
    assert cfg['vision_refresh_advice'].get('enabled') is True


# ============================================================
# 改动 1: Registrar _has_vague_phrase
# ============================================================

def test_has_vague_phrase_hit_zh(isolated_watch_paths):
    r = wt.WatchTaskRegistrar()
    assert r._has_vague_phrase('盯一下这个直播') is True
    assert r._has_vague_phrase('帮我盯着 Cursor') is True
    assert r._has_vague_phrase('看一下') is True


def test_has_vague_phrase_hit_en(isolated_watch_paths):
    r = wt.WatchTaskRegistrar()
    assert r._has_vague_phrase('Keep an eye on Cascade') is True
    assert r._has_vague_phrase('please watch for errors') is True


def test_has_vague_phrase_miss(isolated_watch_paths):
    r = wt.WatchTaskRegistrar()
    assert r._has_vague_phrase('What time is it') is False
    assert r._has_vague_phrase('提醒我 5 分钟后吃药') is False  # registrar 路径, 不 vague


# ============================================================
# 改动 1: _parse_llm_json verdict 三分类
# ============================================================

def test_parse_llm_json_concrete_with_verdict(isolated_watch_paths):
    r = wt.WatchTaskRegistrar()
    raw = json.dumps({
        'verdict': 'concrete',
        'watch': {
            'what_to_watch': 'Adobe Media Encoder export',
            'trigger_evidence': 'progress 100%',
            'notify_msg_en': 'Sir, done.',
            'notify_msg_zh': '先生, 完成了.',
            'rationale': 'clear export event',
        },
    })
    out = r._parse_llm_json(raw, 'sir text', 'jarvis reply')
    assert out is not None
    assert out['_verdict'] == 'concrete'
    assert out['what_to_watch'] == 'Adobe Media Encoder export'
    assert out['trigger_evidence'] == 'progress 100%'


def test_parse_llm_json_vague_with_verdict(isolated_watch_paths):
    r = wt.WatchTaskRegistrar()
    raw = json.dumps({
        'verdict': 'vague',
        'watch': None,
        'vague_topic': '直播间',
        'clarify_question': '盯主播啥具体动作?',
    })
    out = r._parse_llm_json(raw, 'sir text', 'jarvis reply')
    assert out is not None
    assert out['_verdict'] == 'vague'
    assert out['_vague_topic'] == '直播间'
    assert out['_clarify_question'] == '盯主播啥具体动作?'


def test_parse_llm_json_not_a_watch_with_verdict(isolated_watch_paths):
    r = wt.WatchTaskRegistrar()
    raw = json.dumps({'verdict': 'not_a_watch', 'watch': None})
    out = r._parse_llm_json(raw, 'sir text', 'jarvis reply')
    assert out is None


def test_parse_llm_json_old_schema_concrete(isolated_watch_paths):
    """老 LLM 无 verdict 字段, watch 完整 → 当 concrete (向后兼容)."""
    r = wt.WatchTaskRegistrar()
    raw = json.dumps({
        'watch': {
            'what_to_watch': 'build',
            'trigger_evidence': 'green check',
        },
    })
    out = r._parse_llm_json(raw, 'sir text', 'jarvis reply')
    assert out is not None
    assert out['_verdict'] == 'concrete'
    assert out['what_to_watch'] == 'build'


def test_parse_llm_json_old_schema_null(isolated_watch_paths):
    """老 LLM 返 {watch: null} → None."""
    r = wt.WatchTaskRegistrar()
    raw = json.dumps({'watch': None})
    assert r._parse_llm_json(raw, 's', 'r') is None


def test_parse_llm_json_markdown_fence(isolated_watch_paths):
    """LLM 包了 markdown fence 也能 parse."""
    r = wt.WatchTaskRegistrar()
    raw = (
        '```json\n'
        + json.dumps({'verdict': 'vague', 'vague_topic': 'x',
                       'clarify_question': 'y'})
        + '\n```'
    )
    out = r._parse_llm_json(raw, 's', 'r')
    assert out is not None
    assert out['_verdict'] == 'vague'


def test_parse_llm_json_bad_json(isolated_watch_paths):
    """LLM 返垃圾 → fallback (None)."""
    r = wt.WatchTaskRegistrar()
    assert r._parse_llm_json('not json at all', 's', 'r') is None


# ============================================================
# 改动 1: _publish_vague_clarify
# ============================================================

def test_publish_vague_clarify_sends_swm(isolated_watch_paths, fake_event_bus):
    r = wt.WatchTaskRegistrar()
    r._publish_vague_clarify(
        sir_text='盯一下直播',
        jarvis_reply='ok sir',
        turn_id='t1',
        vague_topic='直播间',
        clarify_question='盯啥具体?',
        source_reason='llm_verdict_vague',
    )
    published = [p for p in fake_event_bus.published
                  if p['etype'] == 'watch_task_vague_clarify']
    assert len(published) == 1
    p = published[0]
    assert p['salience'] >= 0.5  # 高 salience 主脑必看
    assert p['metadata']['vague_topic'] == '直播间'
    assert p['metadata']['clarify_question'] == '盯啥具体?'
    assert p['metadata']['source_reason'] == 'llm_verdict_vague'


# ============================================================
# 改动 1: _register_blocking 分流
# ============================================================

def test_register_blocking_vague_branch(isolated_watch_paths, fake_event_bus):
    """LLM 返 verdict=vague → publish watch_task_vague_clarify, 不真注册."""
    r = wt.WatchTaskRegistrar()
    fake_extracted = {
        '_verdict': 'vague',
        '_vague_topic': '直播间',
        '_clarify_question': '盯啥?',
    }
    with patch.object(r, '_call_registrar_llm', return_value=fake_extracted):
        r._register_blocking('盯下直播', 'ok sir', 'turn_v1', key_router=None)
    # 验 publish
    vague = [p for p in fake_event_bus.published
              if p['etype'] == 'watch_task_vague_clarify']
    assert len(vague) == 1
    assert vague[0]['metadata']['source_reason'] == 'llm_verdict_vague'
    # 验 watch_tasks.json 没新 task (vague 不真注册)
    tasks = wt._load_tasks()
    assert len(tasks) == 0


def test_register_blocking_concrete_branch(isolated_watch_paths,
                                              fake_event_bus):
    """LLM 返 verdict=concrete → 真注册 + publish watch_task_registered."""
    r = wt.WatchTaskRegistrar()
    fake = {
        '_verdict': 'concrete',
        'what_to_watch': 'build',
        'trigger_evidence': 'green check',
        'notify_msg_en': 'Sir, build done',
        'notify_msg_zh': '先生, build 完成',
        'rationale': 'clear event',
    }
    with patch.object(r, '_call_registrar_llm', return_value=fake):
        r._register_blocking('等 build 完叫我', 'ok', 'turn_c1', key_router=None)
    tasks = wt._load_tasks()
    assert len(tasks) == 1
    assert tasks[0].what_to_watch == 'build'
    assert tasks[0].state == 'active'
    registered = [p for p in fake_event_bus.published
                   if p['etype'] == 'watch_task_registered']
    assert len(registered) == 1


def test_register_blocking_vague_phrase_fallback(isolated_watch_paths,
                                                    fake_event_bus):
    """vague phrase 命中但 LLM 返 None (e.g. not_a_watch) → 兜底 publish vague_clarify."""
    r = wt.WatchTaskRegistrar()
    with patch.object(r, '_call_registrar_llm', return_value=None):
        r._register_blocking('盯一下 Cursor', 'ok', 'turn_f1', key_router=None)
    vague = [p for p in fake_event_bus.published
              if p['etype'] == 'watch_task_vague_clarify']
    assert len(vague) == 1
    assert vague[0]['metadata']['source_reason'] == 'vague_phrase_fallback'


def test_register_blocking_no_match_skip(isolated_watch_paths,
                                            fake_event_bus):
    """既无 phrase 也无 vague_phrase 且 LLM None → 不 publish 任何 event, skip."""
    r = wt.WatchTaskRegistrar()
    with patch.object(r, '_call_registrar_llm', return_value=None):
        r._register_blocking('Just talking weather', 'ok', 'turn_s1',
                              key_router=None)
    relevant = [p for p in fake_event_bus.published
                if p['etype'] in {
                    'watch_task_register_fail', 'watch_task_vague_clarify',
                    'watch_task_registered',
                }]
    assert len(relevant) == 0


def test_register_blocking_phrase_hit_llm_fail(isolated_watch_paths,
                                                  fake_event_bus):
    """registrar phrase 命中 ('等', '提醒我') 但 LLM None → publish register_fail
    (不是 vague_clarify, 因为 Sir 真要 watch 但 LLM 挂了)."""
    r = wt.WatchTaskRegistrar()
    with patch.object(r, '_call_registrar_llm', return_value=None):
        r._register_blocking('等导出完提醒我', 'ok', 'turn_pf1', key_router=None)
    fail = [p for p in fake_event_bus.published
             if p['etype'] == 'watch_task_register_fail']
    assert len(fail) == 1


# ============================================================
# 改动 1: render_vague_clarify_block
# ============================================================

def test_render_vague_clarify_block_with_events(isolated_watch_paths,
                                                    fake_event_bus):
    """有近期 vague_clarify event → 渲染 block 含 sir_text + clarify_question."""
    # 先 publish 1 个 fake event
    fake_event_bus.publish(
        etype='watch_task_vague_clarify',
        source='WatchTaskRegistrar', salience=0.85, ttl=600.0,
        metadata={
            'sir_text': '盯一下这个直播',
            'jarvis_reply_excerpt': 'ok sir',
            'turn_id': 'turn_demo',
            'vague_topic': '直播间',
            'clarify_question': '盯主播啥具体? 唱歌? 礼物?',
            'source_reason': 'llm_verdict_vague',
            'ts': time.time(),
        },
    )
    block = wt.render_vague_clarify_block()
    assert '[WATCH TASK VAGUE CLARIFY' in block
    assert '盯一下这个直播' in block
    assert '盯主播啥具体' in block
    assert '直播间' in block


def test_render_vague_clarify_block_empty(isolated_watch_paths,
                                              fake_event_bus):
    """没 event → 返 ''."""
    assert wt.render_vague_clarify_block() == ''


def test_render_vague_clarify_block_dedup(isolated_watch_paths,
                                              fake_event_bus):
    """同 sir_text 重复 publish → block 只显 1 条 (de-dup by head)."""
    same_text = '盯下直播'
    for i in range(3):
        fake_event_bus.publish(
            etype='watch_task_vague_clarify', source='WatchTaskRegistrar',
            salience=0.85, ttl=600.0,
            metadata={
                'sir_text': same_text, 'jarvis_reply_excerpt': 'ok',
                'turn_id': f't{i}', 'vague_topic': 't',
                'clarify_question': 'q', 'source_reason': 'x',
                'ts': time.time(),
            },
        )
    block = wt.render_vague_clarify_block()
    assert block.count('turn=t') == 1  # de-dup: 只显第一个 turn


def test_render_vague_clarify_block_disabled(isolated_watch_paths,
                                                 fake_event_bus):
    """vague_clarify.enabled=False → 不渲染."""
    cfg = isolated_watch_paths['data']
    cfg['vague_clarify']['enabled'] = False
    isolated_watch_paths['config'].write_text(json.dumps(cfg), encoding='utf-8')
    # publish 1 event
    fake_event_bus.publish(
        etype='watch_task_vague_clarify', source='WatchTaskRegistrar',
        salience=0.85, ttl=600.0,
        metadata={'sir_text': 'x', 'ts': time.time()},
    )
    assert wt.render_vague_clarify_block() == ''


# ============================================================
# 改动 3: InnerThoughtDaemon _check_active_watch_task_and_publish_vision_refresh
# ============================================================

def test_inner_thought_check_active_publishes(isolated_watch_paths,
                                                   fake_event_bus):
    """有 1 个 active WatchTask → publish proactive_vision_refresh_advice."""
    # 注入 1 active task
    fake = {
        '_verdict': 'concrete',
        'what_to_watch': 'live', 'trigger_evidence': 'singing',
        'notify_msg_en': 'a', 'notify_msg_zh': 'b', 'rationale': 'c',
    }
    r = wt.WatchTaskRegistrar()
    with patch.object(r, '_call_registrar_llm', return_value=fake):
        r._register_blocking('盯下直播 主播唱歌就喊我', 'ok', 't_active',
                              key_router=None)
    assert len(wt.list_active_tasks()) == 1
    fake_event_bus.published.clear()  # 清掉 register publish, 只看 inner_thought

    # mock InnerThoughtDaemon 走 method (避免 init 整个 daemon)
    import jarvis_inner_thought_daemon as itd
    d = itd.InnerThoughtDaemon.__new__(itd.InnerThoughtDaemon)
    d._last_vision_refresh_publish_ts = 0.0
    d._vision_refresh_publish_count = 0
    d._check_active_watch_task_and_publish_vision_refresh()
    advice = [p for p in fake_event_bus.published
               if p['etype'] == 'proactive_vision_refresh_advice']
    assert len(advice) == 1
    assert advice[0]['metadata']['active_count'] == 1
    assert advice[0]['metadata']['recommended_backfill_s'] == 30.0


def test_inner_thought_no_active_no_publish(isolated_watch_paths,
                                                fake_event_bus):
    """没 active task → 不 publish."""
    import jarvis_inner_thought_daemon as itd
    d = itd.InnerThoughtDaemon.__new__(itd.InnerThoughtDaemon)
    d._last_vision_refresh_publish_ts = 0.0
    d._vision_refresh_publish_count = 0
    d._check_active_watch_task_and_publish_vision_refresh()
    advice = [p for p in fake_event_bus.published
               if p['etype'] == 'proactive_vision_refresh_advice']
    assert len(advice) == 0


def test_inner_thought_dedup_window_blocks_spam(isolated_watch_paths,
                                                    fake_event_bus):
    """dedup_window_s 内多次调 → 只 publish 1 次."""
    fake = {
        '_verdict': 'concrete', 'what_to_watch': 'x', 'trigger_evidence': 'y',
        'notify_msg_en': 'a', 'notify_msg_zh': 'b', 'rationale': 'c',
    }
    r = wt.WatchTaskRegistrar()
    with patch.object(r, '_call_registrar_llm', return_value=fake):
        r._register_blocking('盯下 X 完成提醒', 'ok', 't1', key_router=None)
    fake_event_bus.published.clear()

    import jarvis_inner_thought_daemon as itd
    d = itd.InnerThoughtDaemon.__new__(itd.InnerThoughtDaemon)
    d._last_vision_refresh_publish_ts = 0.0
    d._vision_refresh_publish_count = 0
    d._check_active_watch_task_and_publish_vision_refresh()
    d._check_active_watch_task_and_publish_vision_refresh()  # 立即再调
    d._check_active_watch_task_and_publish_vision_refresh()
    advice = [p for p in fake_event_bus.published
               if p['etype'] == 'proactive_vision_refresh_advice']
    # dedup_window_s=5.0, 3 次连调间隔 ~0s → 只 1 个 publish
    assert len(advice) == 1


# ============================================================
# 改动 3: ScreenVisionEngine._compute_effective_backfill_s
# ============================================================

def test_screen_vision_compute_backfill_baseline(fake_event_bus):
    """没 advice event → 返 baseline backfill_interval_s."""
    engine = sv.ScreenVisionEngine(key_router=None, backfill_interval_s=300.0)
    eff = engine._compute_effective_backfill_s()
    assert eff == 300.0


def test_screen_vision_compute_backfill_with_advice(fake_event_bus):
    """有近期 advice → 用 recommended_backfill_s."""
    engine = sv.ScreenVisionEngine(key_router=None, backfill_interval_s=300.0)
    fake_event_bus.publish(
        etype='proactive_vision_refresh_advice',
        source='InnerThoughtDaemon', salience=0.6, ttl=120.0,
        metadata={
            'active_count': 1, 'recommended_backfill_s': 30.0,
            'ts': time.time(),
        },
    )
    eff = engine._compute_effective_backfill_s()
    assert eff == 30.0


def test_screen_vision_compute_backfill_clamps_too_low(fake_event_bus):
    """advice 推荐 < 10s → 强制 clamp 到 10 (防过激)."""
    engine = sv.ScreenVisionEngine(key_router=None, backfill_interval_s=300.0)
    fake_event_bus.publish(
        etype='proactive_vision_refresh_advice',
        source='x', salience=0.6, ttl=120.0,
        metadata={'recommended_backfill_s': 2.0, 'ts': time.time()},
    )
    assert engine._compute_effective_backfill_s() == 10.0


# ============================================================
# 改动 5: mirror_mode fake screen helpers
# ============================================================

@pytest.fixture
def mirror_env(monkeypatch, tmp_path):
    monkeypatch.setenv('JARVIS_MIRROR', '1')
    monkeypatch.chdir(tmp_path)
    # 清 cache
    mm._MIRROR_SCREEN_CACHE['mtime'] = 0.0
    mm._MIRROR_SCREEN_CACHE['data'] = None
    yield tmp_path


@pytest.fixture
def non_mirror_env(monkeypatch, tmp_path):
    monkeypatch.delenv('JARVIS_MIRROR', raising=False)
    monkeypatch.chdir(tmp_path)
    yield tmp_path


def test_mirror_get_screen_path(mirror_env):
    assert mm.get_mirror_screen_path() == os.path.join(
        str(mirror_env), '_mirror_screen.jsonl')


def test_mirror_read_screen_returns_none_in_non_mirror(non_mirror_env):
    """主进程禁止读 mirror screen (return None)."""
    assert mm.read_latest_mirror_screen() is None


def test_mirror_read_screen_no_file(mirror_env):
    """mirror but file 不存在 → None."""
    assert mm.read_latest_mirror_screen() is None


def test_mirror_read_screen_empty_file(mirror_env):
    """mirror + file 空 → None."""
    p = os.path.join(str(mirror_env), '_mirror_screen.jsonl')
    open(p, 'w').close()
    assert mm.read_latest_mirror_screen() is None


def test_mirror_append_screen_writes(mirror_env):
    ok = mm.append_mirror_screen({
        'screen_summary': 'test',
        'active_app': 'Cursor',
        'confidence': 0.9,
    })
    assert ok is True
    p = os.path.join(str(mirror_env), '_mirror_screen.jsonl')
    assert os.path.exists(p)
    with open(p, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry['screen_summary'] == 'test'
    assert '_injected_at' in entry
    assert '_injected_iso' in entry


def test_mirror_append_screen_rejected_in_non_mirror(non_mirror_env):
    """主进程禁止写 (防 Cascade 误调污染主 Jarvis)."""
    assert mm.append_mirror_screen({'screen_summary': 'x'}) is False
    assert not os.path.exists(os.path.join(str(non_mirror_env),
                                              '_mirror_screen.jsonl'))


def test_mirror_read_returns_latest_line(mirror_env):
    """3 帧依次注入 → read_latest 返最新一帧."""
    for i in range(3):
        mm.append_mirror_screen({
            'screen_summary': f'frame_{i}',
            'active_app': f'app_{i}',
        })
    latest = mm.read_latest_mirror_screen()
    assert latest is not None
    assert latest['screen_summary'] == 'frame_2'
    assert latest['active_app'] == 'app_2'


def test_mirror_read_skips_bad_lines(mirror_env):
    """坏 JSON 行跳过, 返最近 valid 行."""
    p = os.path.join(str(mirror_env), '_mirror_screen.jsonl')
    with open(p, 'w', encoding='utf-8') as f:
        f.write('{"screen_summary": "first"}\n')
        f.write('not json at all\n')
        f.write('\n')  # 空行
        f.write('{"screen_summary": "second"}\n')
    latest = mm.read_latest_mirror_screen()
    assert latest is not None
    assert latest['screen_summary'] == 'second'


# ============================================================
# 改动 5: ScreenVisionEngine._do_describe_from_fake
# ============================================================

def test_screen_vision_do_describe_from_fake(mirror_env, fake_event_bus,
                                                 isolated_watch_paths):
    """fake_data → ScreenSnapshot 构造 + 持久化 + publish + judge 走 (judge mocked)."""
    snap_p = os.path.join(str(mirror_env), 'screen_snapshot.json')
    hist_p = os.path.join(str(mirror_env), 'screen_history.jsonl')
    engine = sv.ScreenVisionEngine(
        key_router=None,
        snapshot_path=snap_p,
        history_path=hist_p,
    )
    fake = {
        'active_app': 'Bilibili Live',
        'screen_summary': '主播唱歌中',
        'recent_visible_keywords': ['唱歌', '弹幕'],
        'notable_elements': ['主播张嘴'],
        'errors_visible': [],
        'confidence': 0.95,
    }
    # mock judge_against_snapshot 防真烧 LLM
    with patch('jarvis_watch_task.judge_against_snapshot',
                return_value=[]):
        engine._do_describe_from_fake(fake, trigger='mirror_fake_test')
    # 验 snapshot 持久化
    assert os.path.exists(snap_p)
    with open(snap_p, 'r', encoding='utf-8') as f:
        saved = json.load(f)
    assert saved['screen_summary'] == '主播唱歌中'
    assert saved['vision_model_used'] == 'mirror_fake'
    assert saved['sampling_trigger'] == 'mirror_fake_test'
    # 验 latest 字段
    assert engine._latest is not None
    assert engine._latest.active_app == 'Bilibili Live'
    # 验 SWM publish
    described = [p for p in fake_event_bus.published
                  if p['etype'] == 'screen_described']
    assert len(described) == 1
    # 验 mirror audit event
    mirror_audit_p = os.path.join(str(mirror_env), '_mirror_output.jsonl')
    assert os.path.exists(mirror_audit_p)
    with open(mirror_audit_p, 'r', encoding='utf-8') as f:
        events = [json.loads(ln) for ln in f if ln.strip()]
    fake_applied = [e for e in events if e.get('event') == 'mirror_screen_fake_applied']
    assert len(fake_applied) == 1
    assert fake_applied[0]['screen_summary'] == '主播唱歌中'


def test_screen_vision_do_describe_from_fake_calls_judge(
    mirror_env, fake_event_bus, isolated_watch_paths
):
    """fake snapshot → judge_against_snapshot 真被调 (验 fire 链)."""
    engine = sv.ScreenVisionEngine(
        key_router=None,
        snapshot_path=os.path.join(str(mirror_env), 'snap.json'),
        history_path=os.path.join(str(mirror_env), 'hist.jsonl'),
    )
    fake = {'screen_summary': 'test', 'confidence': 0.9}
    judge_mock = MagicMock(return_value=[])
    with patch('jarvis_watch_task.judge_against_snapshot', judge_mock):
        engine._do_describe_from_fake(fake)
    judge_mock.assert_called_once()
    # snapshot 参数应该是构造好的 ScreenSnapshot 实例
    call_kwargs = judge_mock.call_args.kwargs
    snap_arg = call_kwargs.get('snapshot') or judge_mock.call_args.args[0]
    assert snap_arg.screen_summary == 'test'
    assert snap_arg.vision_model_used == 'mirror_fake'


# ============================================================
# CLI smoke (subprocess) — vague-phrases list
# ============================================================

def test_cli_vague_phrases_list_runs():
    """CLI vague-phrases no-args 不报错且列出 zh/en lists."""
    import subprocess
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Windows GBK 默认炸 emoji + 中文, force utf-8
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    r = subprocess.run(
        [sys.executable, os.path.join('scripts', 'watch_task_dump.py'),
          'vague-phrases'],
        cwd=repo, capture_output=True, text=True, timeout=15,
        encoding='utf-8', errors='replace', env=env,
    )
    assert r.returncode == 0, f"CLI fail: stderr={r.stderr}"
    assert r.stdout is not None, f"stdout None — stderr={r.stderr}"
    assert 'vague_trigger_phrases' in r.stdout
    assert '盯' in r.stdout
    assert 'eye' in r.stdout.lower()


# ============================================================
# central_nerve 静态 import (验改动 2 没破)
# ============================================================

def test_central_nerve_imports_vague_clarify_helper():
    """jarvis_central_nerve.py 真 import render_vague_clarify_block.

    避免 init 整个 nerve, 只验 import (改动 2 没破)."""
    src_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'jarvis_central_nerve.py',
    )
    with open(src_path, 'r', encoding='utf-8') as f:
        src = f.read()
    assert 'render_vague_clarify_block' in src
    assert '_wt_vague' in src  # 我加的 alias


# ============================================================
# 🆕 [fix50.1 / 2026-05-29] 真测后修 2 BUG 防回归
# ============================================================

def test_registrar_prompt_ignores_jarvis_pushback():
    """[fix50.1 BUG#1] Registrar prompt 显式说 judge BY SIR INTENT ONLY, 不被
    Jarvis pushback ('outside my reach') 影响. 这是 0/6 fire 主因 — 主脑 reply
    pushback → Registrar LLM 误判 not_a_watch → 0 task 注册.
    """
    assert 'JUDGE BY SIR' in wt._REGISTRAR_PROMPT.upper() or \
            'SIR\'S INTENT ONLY' in wt._REGISTRAR_PROMPT
    # 必含明确 pushback 反例 + 教 LLM ignore
    assert 'outside my reach' in wt._REGISTRAR_PROMPT or \
            'DO NOT downgrade' in wt._REGISTRAR_PROMPT
    # JARVIS REPLY 必标 'context only, do not use as gate'
    assert 'context only' in wt._REGISTRAR_PROMPT.lower() or \
            'do not use as gate' in wt._REGISTRAR_PROMPT.lower()


def test_screen_vision_daemon_loop_reactive_wait(fake_event_bus):
    """[fix50.1 BUG#2] daemon_loop wait_s 永远 ≤ 30s, 即使 baseline backfill 5min.
    
    防回归 — 老 BUG: daemon_loop sleep 老 backfill_interval_s (300s) cycle, advice
    publish 后 daemon 仍在睡老周期, 35s scenarios wait 错过 trigger. 修法: wait
    至多 30s (min(eff, 30)).
    """
    # 直接 grep source (不能真跑 daemon_loop, 会 thread infinite)
    src_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'jarvis_screen_vision.py',
    )
    with open(src_path, 'r', encoding='utf-8') as f:
        src = f.read()
    # 必含 min(..., 30.0) 或 30 cap
    assert 'min(self._compute_effective_backfill_s(), 30' in src or \
            'min(..., 30' in src
    # 必含 reactive 注释 (设计意图)
    assert 'reactive' in src.lower() or 'fix50.1' in src
