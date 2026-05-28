"""tests/_test_fix49_sir_20260528_mirror_mode.py — mirror mode 基础 + hook 单元测试

[Sir 2026-05-28 22:00 fix49 mirror P3 test]

测什么:
  - env JARVIS_MIRROR=1 / 0 切换正确
  - get_mirror_input_path / get_mirror_output_path / get_mirror_root 在 mirror 模式返当前 cwd
  - append_mirror_output: 非 mirror = noop; mirror = 写一行 JSON 到 _mirror_output.jsonl
  - MockVocalCord: speak / say / render_only / play_only / stop / stop_immediately /
      _split_long_sentence / get_render_stats API 兼容 + 各写一行 event 到 mirror_output
  - MirrorSubtitleQueue / MirrorBreathingLightUI / MirrorSubtitleOverlay no-op + 写事件
  - MirrorVoiceWorker (PyQt5 QThread): in_active_conversation property + set_speaking_state
  - write_mirror_meta: 写 _mirror_meta.json 含 pid/task/start_ts

不测 (要 subprocess + 时间, 留 manual 真测):
  - jarvis_nerve.py 启动整链
  - chat_bypass hook 真触发 turn_complete (要主脑 LLM call)

Sir 真测 cheat sheet:
  pytest tests/_test_fix49_sir_20260528_mirror_mode.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time

import pytest

# 保证 import 主项目 module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jarvis_mirror_mode as mm  # noqa: E402


# ============================================================
# fixtures
# ============================================================

@pytest.fixture
def mirror_env(monkeypatch, tmp_path):
    """fixture: set JARVIS_MIRROR=1, chdir 到 tmp_path (= mirror_root)."""
    monkeypatch.setenv('JARVIS_MIRROR', '1')
    monkeypatch.setenv('JARVIS_MIRROR_TASK', 'unit_test')
    monkeypatch.chdir(tmp_path)
    yield tmp_path


@pytest.fixture
def non_mirror_env(monkeypatch, tmp_path):
    """fixture: 显式 unset JARVIS_MIRROR, 模拟主进程."""
    monkeypatch.delenv('JARVIS_MIRROR', raising=False)
    monkeypatch.chdir(tmp_path)
    yield tmp_path


def _read_output_lines(mirror_root) -> list:
    """读 _mirror_output.jsonl 全部 JSON 行."""
    p = os.path.join(str(mirror_root), '_mirror_output.jsonl')
    if not os.path.exists(p):
        return []
    out = []
    with open(p, 'r', encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                out.append(json.loads(ln))
    return out


# ============================================================
# 1. env gate
# ============================================================

def test_is_mirror_mode_true(mirror_env):
    assert mm.is_mirror_mode() is True


def test_is_mirror_mode_false(non_mirror_env):
    assert mm.is_mirror_mode() is False


def test_get_mirror_root_returns_cwd(mirror_env):
    assert mm.get_mirror_root() == str(mirror_env)


def test_get_mirror_input_path(mirror_env):
    expected = os.path.join(str(mirror_env), '_mirror_input.jsonl')
    assert mm.get_mirror_input_path() == expected


def test_get_mirror_output_path(mirror_env):
    expected = os.path.join(str(mirror_env), '_mirror_output.jsonl')
    assert mm.get_mirror_output_path() == expected


def test_get_mirror_task_default(monkeypatch, tmp_path):
    monkeypatch.delenv('JARVIS_MIRROR_TASK', raising=False)
    assert mm.get_mirror_task() == '<no task description>'


def test_get_mirror_task_set(monkeypatch):
    monkeypatch.setenv('JARVIS_MIRROR_TASK', 'fix49 真测')
    assert mm.get_mirror_task() == 'fix49 真测'


# ============================================================
# 2. append_mirror_output
# ============================================================

def test_append_mirror_output_noop_in_non_mirror(non_mirror_env):
    mm.append_mirror_output({'event': 'should_not_write'})
    # 非 mirror 不应有任何文件被创建
    assert not os.path.exists(os.path.join(str(non_mirror_env), '_mirror_output.jsonl'))


def test_append_mirror_output_writes_in_mirror(mirror_env):
    mm.append_mirror_output({'event': 'unit_test_evt', 'foo': 'bar'})
    lines = _read_output_lines(mirror_env)
    assert len(lines) == 1
    assert lines[0]['event'] == 'unit_test_evt'
    assert lines[0]['foo'] == 'bar'
    assert 'ts' in lines[0]
    assert 'ts_iso' in lines[0]


def test_append_mirror_output_multi(mirror_env):
    for i in range(5):
        mm.append_mirror_output({'event': 'evt', 'i': i})
    lines = _read_output_lines(mirror_env)
    assert len(lines) == 5
    assert [l['i'] for l in lines] == [0, 1, 2, 3, 4]


def test_append_mirror_output_explicit_ts_preserved(mirror_env):
    mm.append_mirror_output({'event': 'x', 'ts': 12345.0, 'ts_iso': 'custom'})
    lines = _read_output_lines(mirror_env)
    assert lines[0]['ts'] == 12345.0
    assert lines[0]['ts_iso'] == 'custom'


# ============================================================
# 3. MockVocalCord — API 兼容 + 写 mirror_output
# ============================================================

def test_mock_vocal_cord_init(mirror_env):
    v = mm.MockVocalCord()
    assert v._is_speaking is False
    assert v._render_count == 0
    assert v.cosyvoice is None
    assert v._jarvis_spk_id == 'mirror_mock'


def test_mock_vocal_cord_speak(mirror_env):
    v = mm.MockVocalCord()
    v.speak('Hello Sir')
    lines = _read_output_lines(mirror_env)
    tts_lines = [l for l in lines if l['event'] == 'mock_tts']
    assert len(tts_lines) == 1
    assert tts_lines[0]['text'] == 'Hello Sir'
    assert tts_lines[0]['len_chars'] == 9
    assert v._render_count == 1
    assert v._is_speaking is False  # speak 完归 False


def test_mock_vocal_cord_speak_empty_noop(mirror_env):
    v = mm.MockVocalCord()
    v.speak('')
    v.speak('   ')
    lines = _read_output_lines(mirror_env)
    assert all(l['event'] != 'mock_tts' for l in lines)


def test_mock_vocal_cord_say_proxies_to_speak(mirror_env):
    v = mm.MockVocalCord()
    v.say('via_say')
    lines = _read_output_lines(mirror_env)
    tts = [l for l in lines if l['event'] == 'mock_tts']
    assert len(tts) == 1
    assert tts[0]['text'] == 'via_say'


def test_mock_vocal_cord_render_only(mirror_env):
    v = mm.MockVocalCord()
    audio = v.render_only('render me', retry=3)
    assert isinstance(audio, bytes)
    assert len(audio) > 0
    lines = _read_output_lines(mirror_env)
    rend = [l for l in lines if l['event'] == 'mock_tts_render']
    assert len(rend) == 1
    assert rend[0]['text'] == 'render me'
    assert rend[0]['retry'] == 3


def test_mock_vocal_cord_render_only_empty(mirror_env):
    v = mm.MockVocalCord()
    audio = v.render_only('')
    assert audio == b''


def test_mock_vocal_cord_play_only(mirror_env):
    v = mm.MockVocalCord()
    v.play_only(b'\x00' * 100)
    lines = _read_output_lines(mirror_env)
    play = [l for l in lines if l['event'] == 'mock_audio_play']
    assert len(play) == 1
    assert play[0]['byte_len'] == 100


def test_mock_vocal_cord_stop_when_speaking(mirror_env):
    v = mm.MockVocalCord()
    v._is_speaking = True
    v.stop_immediately()
    lines = _read_output_lines(mirror_env)
    stops = [l for l in lines if l['event'] == 'mock_tts_stop']
    assert len(stops) == 1
    assert v._is_speaking is False


def test_mock_vocal_cord_stop_noop_when_idle(mirror_env):
    v = mm.MockVocalCord()
    v.stop_immediately()
    lines = _read_output_lines(mirror_env)
    stops = [l for l in lines if l['event'] == 'mock_tts_stop']
    assert len(stops) == 0


def test_mock_vocal_cord_stop_alias(mirror_env):
    v = mm.MockVocalCord()
    v._is_speaking = True
    v.stop()  # alias for stop_immediately
    lines = _read_output_lines(mirror_env)
    assert any(l['event'] == 'mock_tts_stop' for l in lines)


def test_mock_vocal_cord_split_long_sentence():
    v = mm.MockVocalCord()
    short = v._split_long_sentence('short', max_len=200)
    assert short == ['short']
    long = v._split_long_sentence('a' * 450, max_len=200)
    assert len(long) == 3  # 200 + 200 + 50
    assert ''.join(long) == 'a' * 450


def test_mock_vocal_cord_get_render_stats(mirror_env):
    v = mm.MockVocalCord()
    v.speak('x')
    v.speak('y')
    stats = v.get_render_stats()
    assert stats['render_count'] == 2
    assert stats['is_speaking'] is False
    assert stats['mirror_mode'] is True


# ============================================================
# 4. MirrorSubtitleQueue / UI / SubtitleOverlay
# ============================================================

def test_mirror_subtitle_queue(mirror_env):
    q = mm.MirrorSubtitleQueue()
    q.put(('en', 'Hello'))
    q.put(('zh', '你好'))
    lines = _read_output_lines(mirror_env)
    subs = [l for l in lines if l['event'] == 'mirror_subtitle']
    assert len(subs) == 2
    assert subs[0]['channel'] == 'en'
    assert subs[0]['text'] == 'Hello'
    assert subs[1]['channel'] == 'zh'
    assert subs[1]['text'] == '你好'


def test_mirror_subtitle_queue_raw_payload(mirror_env):
    q = mm.MirrorSubtitleQueue()
    q.put('plain string')  # 非 tuple, 走 fallback channel
    lines = _read_output_lines(mirror_env)
    subs = [l for l in lines if l['event'] == 'mirror_subtitle']
    assert len(subs) == 1
    assert subs[0]['channel'] == 'raw'


def test_mirror_breathing_light_ui(mirror_env):
    ui = mm.MirrorBreathingLightUI()
    ui.show()
    ui.change_state('THINKING')
    ui.set_awake_status(True)
    ui.flash_pulse('gold')
    lines = _read_output_lines(mirror_env)
    by_event = {l['event']: l for l in lines}
    assert 'mirror_ui_started' in by_event
    assert 'mirror_ui_show_noop' in by_event
    assert by_event['mirror_ui_state']['state'] == 'THINKING'
    assert by_event['mirror_ui_awake']['awake'] is True
    assert by_event['mirror_ui_visual_pulse']['kind'] == 'gold'
    assert ui.state == 'THINKING'
    assert ui.is_awake is True


def test_mirror_subtitle_overlay(mirror_env):
    ui = mm.MirrorBreathingLightUI()
    overlay = mm.MirrorSubtitleOverlay(ui)
    assert isinstance(overlay.subtitle_queue, mm.MirrorSubtitleQueue)
    overlay.subtitle_queue.put(('en', 'overlay'))
    lines = _read_output_lines(mirror_env)
    assert any(l.get('event') == 'mirror_subtitle_overlay_started' for l in lines)
    assert any(l.get('text') == 'overlay' for l in lines)


# ============================================================
# 5. MirrorVoiceWorker (factory + 基础 API; 不真启动 QThread.run)
# ============================================================

def test_create_mirror_voice_worker_api(mirror_env):
    """factory 返一个跟 VoiceListenThread API 兼容的对象."""
    try:
        from PyQt5.QtCore import QThread  # noqa: F401
    except ImportError:
        pytest.skip("PyQt5 not installed in this env")

    w = mm.create_mirror_voice_worker(poll_interval=0.5)

    # 基础信号 (跟 VoiceListenThread 同 attr)
    assert hasattr(w, 'text_ready')
    assert hasattr(w, 'interrupt_signal')
    assert hasattr(w, 'awake_signal')

    # 兼容属性
    assert w.return_sentinel is None
    assert w._subtitle_queue is None
    assert w.state is None
    assert w._local_in_active_conv is False
    assert w._attention_slot is None
    assert w.is_jarvis_speaking is False
    assert w._suppress_wave is False

    # in_active_conversation property
    assert w.in_active_conversation is False
    w.in_active_conversation = True
    assert w._local_in_active_conv is True

    # set_speaking_state
    w.set_speaking_state('EXECUTING')
    assert w.is_jarvis_speaking is True
    w.set_speaking_state('IDLE')
    assert w.is_jarvis_speaking is False

    # stop (不真启动 run, stop 应安全 noop)
    w.stop()  # 不应该 raise


# ============================================================
# 6. write_mirror_meta
# ============================================================

def test_write_mirror_meta(mirror_env):
    mm.write_mirror_meta()
    meta_path = os.path.join(str(mirror_env), '_mirror_meta.json')
    assert os.path.exists(meta_path)
    with open(meta_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    assert meta['mirror_root'] == str(mirror_env)
    assert meta['task'] == 'unit_test'  # fixture 设的
    assert isinstance(meta['pid'], int)
    assert meta['pid'] == os.getpid()
    assert 'start_ts' in meta
    assert 'start_iso' in meta


def test_write_mirror_meta_noop_in_non_mirror(non_mirror_env):
    mm.write_mirror_meta()
    meta_path = os.path.join(str(non_mirror_env), '_mirror_meta.json')
    assert not os.path.exists(meta_path)


# ============================================================
# 7. 集成: speak → output JSONL → tail script 能 parse 出 fmt_event
# ============================================================

def test_tail_script_can_parse_mirror_output(mirror_env, monkeypatch):
    """integration: vocal speak + ui events 全写完后, tail script fmt_event 应不 raise."""
    v = mm.MockVocalCord()
    v.speak('hello')
    v.render_only('world')
    v.play_only(b'\x00' * 50)
    v.stop()  # noop (not speaking)
    v._is_speaking = True
    v.stop()  # 真 stop
    overlay = mm.MirrorSubtitleOverlay(mm.MirrorBreathingLightUI())
    overlay.subtitle_queue.put(('en', 'integration'))
    mm.append_mirror_output({'event': 'sir_input_received', 'text': 'test'})
    mm.append_mirror_output({
        'event': 'turn_complete', 'channel': 'main_chat', 'turn_id': 't1',
        'sir_utterance': 'test', 'final_reply': 'reply', 'reply_len_chars': 5,
        'duration_sec': 1.23, 'tool_results': [], 'circuit_broken_reason': None,
    })
    mm.append_mirror_output({
        'event': 'fast_call_attempt', 'organ': 'memory', 'command': 'recall',
        'params_excerpt': {'q': 'sir wants...'},
    })

    # 现在 import tail script 并跑 fmt_event 不 raise
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
    import importlib
    if 'jarvis_mirror_tail' in sys.modules:
        importlib.reload(sys.modules['jarvis_mirror_tail'])
    import jarvis_mirror_tail as tail_mod  # noqa: E402

    lines = _read_output_lines(mirror_env)
    assert len(lines) > 5
    for entry in lines:
        s = tail_mod.fmt_event(entry)
        assert isinstance(s, str)
        assert len(s) > 0
