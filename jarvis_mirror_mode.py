"""
jarvis_mirror_mode.py — Agent Mirror Testing 基础设施

[Sir 2026-05-28 22:00 fix49] Sir clarify 需求:
> "甚至可以理解成把贾维斯目录复制一份那种, 只是不需要测我说话, 转录这些, 相当于
>  你直接输入文字等同于我说话就可以了, 其他完全一致, 主要用于测试贾维斯的能力
>  是否能实现, 有没有实际使用的 BUG"

= 整个 d:\\Jarvis 复制一份到 D:\\jarvis_mirror_<ts>\\, 独立 subprocess 起完整 Jarvis
(主脑 / 思考脑 / sentinel / hub / promise / concerns / profile / hippocampus / ...)
+ skip 抢资源 (麦克风 / TTS GPU / dashboard port / UI window), Cascade 通过 file IPC
注入 "Sir 说什么", 收 reply + audit. 测完整盘 rm, 主 Jarvis 0 知觉.

设计准则 (准则 6 数据强耦合 + 准则 8 优雅):
  - 单一入口 `is_mirror_mode()` (env JARVIS_MIRROR=1 检测)
  - 4 个 hook 点 (jarvis_central_nerve VocalCord / jarvis_nerve VoiceListenThread /
    chat_bypass dashboard FAST_CALL / chat_bypass stream 末尾输出)
  - cwd 隔离 (镜像 subprocess cwd 已 chdir 到 mirror), 所有 __file__-based ROOT
    自然指镜像目录, 0 path leak (P1 audit 已证)
  - MockVocalCord / MirrorVoiceWorker 跟原 class API 100% 兼容, 下游 0 改

⚠️ 边界 (Sir 2026-05-28 23:25 确认, 准则 5 言出必行):
  Mirror = **软件层 sandbox**, 不是数字孪生. 能测 / 测不到见 docs §6.
  - ✅ 能测: 主脑 reply 逻辑 / 工具调链 / sentinel / prompt 拼接 / 准则 6 持久化 / IntentResolver
  - ❌ 测不到: ASR 转录 / VAD / wake_word / CosyVoice GPU OOM / TTS 音质 / UI Qt 卡顿 /
            TTFT 真实数据 / audio device 冲突 / 实时中断 / dashboard WebSocket / 时间敏感 daemon
            实时状态 / 真实环境干扰 (噪音/网络)
  - ⚠️ 副作用: LLM key 共享主进程 env → 真烧 OpenRouter/Gemini token (TODO --llm-mock)
  硬件链 BUG (麦克风 / ASR / TTS / UI / TTFT) 仍需 Sir 主程序真测, Cascade 替不了.

启动: 看 scripts/jarvis_mirror.py + docs/JARVIS_AGENT_MIRROR_TESTING.md
"""
import os
import json
import queue
import time
import threading
from typing import Optional


# ============================================================
# 入口 API — 4 行 + 4 path helper
# ============================================================

def is_mirror_mode() -> bool:
    """检 env JARVIS_MIRROR=1. 镜像启动脚本 set, 主进程永不 set."""
    return os.environ.get('JARVIS_MIRROR') == '1'


def get_mirror_root() -> str:
    """镜像根目录 (= cwd, 因为镜像 subprocess cwd 已 chdir 到 mirror).

    非 mirror mode 返回主 Jarvis cwd, 调用方应该先 is_mirror_mode() check.
    """
    return os.getcwd()


def get_mirror_input_path() -> str:
    """Cascade 写, 镜像 MirrorVoiceWorker 1s poll 读, emit text_ready signal."""
    return os.path.join(get_mirror_root(), '_mirror_input.jsonl')


def get_mirror_output_path() -> str:
    """镜像 chat_bypass / mock_tts / sentinel 写, Cascade tail 看实时进度."""
    return os.path.join(get_mirror_root(), '_mirror_output.jsonl')


def get_mirror_task() -> str:
    """Cascade 描述测试目的 (写 _mirror_meta.json 给后续 audit)."""
    return os.environ.get('JARVIS_MIRROR_TASK', '<no task description>')


def get_mirror_screen_path() -> str:
    """🆕 [fix50 / 2026-05-28] _mirror_screen.jsonl — Cascade 写 fake snapshot.

    Cascade 通过 scripts/jarvis_mirror_screen.py inject 注入屏幕场景 (文字/图标/图形/
    图像 + 直播/限速 6 类), ScreenVisionEngine _do_describe 顶部读最新一行 fake →
    bypass 截图 + 真 vision LLM, 直接构造 ScreenSnapshot 走持久化+publish+judge 全链.
    主进程非 mirror → 不读不写, 0 影响.
    """
    return os.path.join(get_mirror_root(), '_mirror_screen.jsonl')


# 🆕 [fix50] mtime cache 防 daemon 每 30s 真 disk read
_MIRROR_SCREEN_CACHE: dict = {'mtime': 0.0, 'data': None, 'line_count': 0}
_MIRROR_SCREEN_LOCK = threading.Lock()


def read_latest_mirror_screen() -> Optional[dict]:
    """🆕 [fix50 / 2026-05-28] 读 _mirror_screen.jsonl 最新一行 fake snapshot.

    Returns:
        dict (含 screen_summary / active_app / errors_visible / notable_elements /
              recent_visible_keywords / confidence / ...) or None (file 不存在/空/坏行).

    主进程 (非 mirror) 永远返 None, 不读 disk. mtime cache 避免 daemon 每 30s
    真 disk read (mirror screen 改动罕见, file 静止时 cache 命中).
    """
    if not is_mirror_mode():
        return None
    path = get_mirror_screen_path()
    if not os.path.exists(path):
        return None
    try:
        mtime = os.path.getmtime(path)
        if mtime == _MIRROR_SCREEN_CACHE['mtime'] and _MIRROR_SCREEN_CACHE['data'] is not None:
            return _MIRROR_SCREEN_CACHE['data']
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        if not lines:
            return None
        # 找最新一行 valid JSON (反向遍历, 跳过空行 / 坏行)
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            _MIRROR_SCREEN_CACHE['mtime'] = mtime
            _MIRROR_SCREEN_CACHE['data'] = data
            _MIRROR_SCREEN_CACHE['line_count'] = len(lines)
            return data
        return None
    except Exception as e:
        print(f"[mirror_mode] read_latest_mirror_screen fail: {e}")
        return None


def append_mirror_screen(snapshot_dict: dict) -> bool:
    """🆕 [fix50 / 2026-05-28] Cascade 调 (通过 scripts/jarvis_mirror_screen.py) 注入 1 帧.

    snapshot_dict 至少含 'screen_summary'. 完整 schema 参考 ScreenSnapshot:
      active_app / file_or_url_visible / cursor_line_approx / screen_summary /
      recent_visible_keywords (list) / errors_visible (list) / build_output_status /
      notable_elements (list) / confidence (float 0-1) / privacy_redacted (bool)

    自动加 _injected_at / _injected_iso.
    """
    if not is_mirror_mode():
        # 主进程禁止写, 防 Cascade 误调污染主 Jarvis
        return False
    try:
        path = get_mirror_screen_path()
        payload = dict(snapshot_dict)
        payload.setdefault('_injected_at', time.time())
        payload.setdefault('_injected_iso', time.strftime('%Y-%m-%dT%H:%M:%S'))
        with _MIRROR_SCREEN_LOCK:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(payload, ensure_ascii=False) + '\n')
            # invalidate cache (下次 read 立即看新 frame)
            _MIRROR_SCREEN_CACHE['mtime'] = 0.0
            _MIRROR_SCREEN_CACHE['data'] = None
        return True
    except Exception as e:
        print(f"[mirror_mode] append_mirror_screen fail: {e}")
        return False


# ============================================================
# 输出 — chat_bypass / inner_thought / mock_tts / sentinel 末尾调
# ============================================================

_OUTPUT_LOCK = threading.Lock()


def append_mirror_output(payload: dict) -> None:
    """镜像里任何事件 (turn 完成 / 思考脑发声 / mock_tts / mutation 触发 / ...)
    都可调这写 _mirror_output.jsonl 一行.

    Cascade tail 看实时进度. 非 mirror mode → noop (主进程调也安全, 0 IO).

    payload 必含 'event' 字段 (= 'turn_complete' / 'mock_tts' /
    'sir_input_received' / 'inner_thought_speak' / 'mutation_skipped' / ...).
    ts / ts_iso 自动注入.
    """
    if not is_mirror_mode():
        return
    try:
        payload = dict(payload)
        payload.setdefault('ts', time.time())
        payload.setdefault('ts_iso', time.strftime('%Y-%m-%dT%H:%M:%S'))
        with _OUTPUT_LOCK:
            with open(get_mirror_output_path(), 'a', encoding='utf-8') as f:
                f.write(json.dumps(payload, ensure_ascii=False) + '\n')
    except Exception as e:
        # mirror 输出 fail 不能影响主 chain
        print(f"[mirror_mode] append_mirror_output fail: {e}")


# ============================================================
# MockVocalCord — 替 jarvis_vocal_cord.VocalCord (GPU/audio skip)
# ============================================================

class MockVocalCord:
    """镜像 mode 替真 VocalCord, 不 init CosyVoice-300M GPU model, 不抢 audio device.

    speak() 不真出声, 改成 _mirror_output.jsonl 写一行 event=mock_tts. 主脑 / 思考脑 /
    chat_bypass 全 chain 不感知差异 (API 100% 兼容: speak / stop_immediately /
    _split_long_sentence / get_render_stats / _is_speaking / _jarvis_spk_id /
    _render_count). Cascade tail output 看到 mock_tts 行就知道镜像 "说" 了什么.
    """

    def __init__(self):
        self._is_speaking = False
        self._jarvis_spk_id = 'mirror_mock'
        self._render_count = 0
        # 兼容 vocal_cord 的属性 (chat_bypass / nerve 可能 access)
        self.cosyvoice = None
        self.prompt_text = ''
        self.prompt_speech_16k = None
        self._last_render_text = ''
        print("🪞 [MockVocalCord] mirror mode active — real CosyVoice GPU + audio device skipped")

    def speak(self, text: str, retry: int = 1, **kwargs):
        """跟真 VocalCord.speak 同签名, 不出声, 写 mock_tts 给 Cascade audit."""
        if not text or not str(text).strip():
            return
        self._is_speaking = True
        try:
            append_mirror_output({
                'event': 'mock_tts',
                'text': str(text),
                'len_chars': len(str(text)),
                'render_count': self._render_count + 1,
            })
            print(f"🪞 [MockVocalCord] would speak ({len(str(text))} chars): {str(text)[:120]}...")
        finally:
            self._is_speaking = False
            self._render_count += 1

    def say(self, text: str):
        self.speak(text)

    def render_only(self, text: str, retry: int = 2):
        if not text or not str(text).strip():
            return b''
        self._is_speaking = True
        self._last_render_text = str(text)
        self._render_count += 1
        try:
            append_mirror_output({
                'event': 'mock_tts_render',
                'text': self._last_render_text,
                'len_chars': len(self._last_render_text),
                'render_count': self._render_count,
                'retry': retry,
            })
        finally:
            self._is_speaking = False
        return b'\x00\x00' * 2205

    def play_only(self, audio_bytes: bytes):
        append_mirror_output({
            'event': 'mock_audio_play',
            'byte_len': len(audio_bytes or b''),
            'text': self._last_render_text,
        })

    def stop(self):
        self.stop_immediately()

    def stop_immediately(self):
        """真 VocalCord 用来打断当前 TTS render. Mock 直接 flip flag + log."""
        was_speaking = self._is_speaking
        self._is_speaking = False
        if was_speaking:
            append_mirror_output({'event': 'mock_tts_stop'})

    def _split_long_sentence(self, text: str, max_len: int = 200) -> list:
        """跟真 _split_long_sentence 同签名 (chat_bypass 调). Mock 简化."""
        if len(text) <= max_len:
            return [text]
        return [text[i:i + max_len] for i in range(0, len(text), max_len)]

    def get_render_stats(self) -> dict:
        return {
            'render_count': self._render_count,
            'is_speaking': self._is_speaking,
            'mirror_mode': True,
        }


class MirrorSubtitleQueue(queue.Queue):
    """镜像字幕队列：保留 Queue API, 同时把所有字幕/UI 事件写 mirror JSONL."""

    def put(self, item, block=True, timeout=None):
        try:
            lang, text = item if isinstance(item, tuple) and len(item) == 2 else ('raw', item)
            append_mirror_output({
                'event': 'mirror_subtitle',
                'channel': lang,
                'text': text,
            })
        except Exception:
            pass
        return super().put(item, block=block, timeout=timeout)


class MirrorBreathingLightUI:
    """镜像 UI no-op：不创建 OpenGL 窗口，只记录状态变化。"""

    def __init__(self):
        self.state = 'IDLE'
        self.is_awake = False
        append_mirror_output({'event': 'mirror_ui_started'})

    def show(self):
        append_mirror_output({'event': 'mirror_ui_show_noop'})

    def change_state(self, new_state: str):
        self.state = new_state
        append_mirror_output({'event': 'mirror_ui_state', 'state': new_state})

    def set_awake_status(self, status: bool):
        self.is_awake = bool(status)
        append_mirror_output({'event': 'mirror_ui_awake', 'awake': self.is_awake})

    def flash_pulse(self, kind: str = 'gold'):
        append_mirror_output({'event': 'mirror_ui_visual_pulse', 'kind': kind})


class MirrorSubtitleOverlay:
    """镜像字幕层 no-op：只暴露 subtitle_queue, 下游无需分支。"""

    def __init__(self, orb_widget=None):
        self.orb = orb_widget
        self.subtitle_queue = MirrorSubtitleQueue()
        append_mirror_output({'event': 'mirror_subtitle_overlay_started'})


# ============================================================
# MirrorVoiceWorker — 替 jarvis_worker.VoiceListenThread (麦克风 skip)
# ============================================================
#
# 注意: 这里**只**在 mirror mode 下 import PyQt5 (避免主进程 unused import).
# 真实例化在 jarvis_nerve.py 时才发生.

def create_mirror_voice_worker(poll_interval: float = 1.0):
    """factory, mirror 启动时 jarvis_nerve.py 调.

    返一个 QThread, API 跟 VoiceListenThread 兼容:
      - text_ready signal (str) — 模拟 Sir 说话 → jarvis_worker.push_command
      - interrupt_signal signal () — 兼容 (mirror 不用)
      - awake_signal signal (bool) — 兼容
      - return_sentinel attr — 下游 wire
      - _subtitle_queue / state / _local_in_active_conv / _attention_slot — 兼容
      - set_speaking_state(bool) method — 兼容
      - start() / stop() — 启停 daemon

    内部跑 1s poll _mirror_input.jsonl, 看到新行 → emit text_ready.
    """
    from PyQt5.QtCore import QThread, pyqtSignal
    # [Sir 2026-05-28 23:17 fix49 BUG#3] 复用 VoiceListenThread class-level
    # 常量 (DISMISS_*/STOP_WORDS/PAUSE_ONLY_WORDS/DEBUG_ASR), Sir 改主版镜像
    # 自动同步, 不需要双维护. 纯 import 不实例化 → 不触发麦克风初始化.
    from jarvis_voice_listen_thread import VoiceListenThread as _RealVLT

    class MirrorVoiceWorker(QThread):
        text_ready = pyqtSignal(str)
        interrupt_signal = pyqtSignal()
        awake_signal = pyqtSignal(bool)

        # —— class-level 词表/常量: 100% 镜像主版, 主版改自动同步 ——
        PAUSE_ONLY_WORDS = _RealVLT.PAUSE_ONLY_WORDS
        STRICT_STOP_WORDS = _RealVLT.STRICT_STOP_WORDS
        SOFT_STOP_WORDS = _RealVLT.SOFT_STOP_WORDS
        STOP_WORDS = _RealVLT.STOP_WORDS
        DISMISS_EXCLUSIVE = _RealVLT.DISMISS_EXCLUSIVE
        DISMISS_POLITE = _RealVLT.DISMISS_POLITE
        DISMISS_WORDS = _RealVLT.DISMISS_WORDS
        DEBUG_ASR = _RealVLT.DEBUG_ASR

        def __init__(self):
            super().__init__()
            self.poll_interval = poll_interval
            self._last_read_line_count = 0
            self._stop_event = threading.Event()
            # 兼容 VoiceListenThread 下游属性
            self.return_sentinel = None
            self._subtitle_queue = None
            self.state = None
            self._local_in_active_conv = False
            self._attention_slot = None
            self.is_jarvis_speaking = False
            self.last_interaction_time = 0
            self.last_user_speech_time = 0
            self.mute_until = 0.0
            self.last_conversation_end_time = 0
            self.last_dismissal_reason = None
            self._suppress_wave = False
            # [Phase 6 audio_to_brain] 主版有 _last_audio_* 字段, mirror 无麦
            # 全置 None/0, get_recent_audio_for_brain 永远返 (b'', 0.0)
            self._last_audio_wav_bytes = b''
            self._last_audio_ts = 0.0
            self._last_audio_duration_sec = 0.0
            self.quiet_exit_until = 0.0
            # [β.5.35-C struggle] mirror 不跑 struggle 检测, 占位防 AttributeError
            self.last_struggle_match = None
            self.last_struggle_severity = ''
            self.last_struggle_ts = 0.0

        # === Phase 6 audio_to_brain: mirror 无音频, 永远返空 ===
        def get_recent_audio_for_brain(self, max_age_sec: float = 30.0) -> tuple:
            return (b'', 0.0)

        # === β.5.35-C struggle: mirror 永远 no-match ===
        def _detect_sir_struggle(self, cmd: str) -> bool:
            return False

        def _publish_listening_done(self):
            # mirror 不显 Listening… 指示, no-op
            return

        @property
        def in_active_conversation(self) -> bool:
            state = self.state
            if state is None:
                return self._local_in_active_conv
            return bool(getattr(state, 'active_conversation', False))

        @in_active_conversation.setter
        def in_active_conversation(self, value):
            value = bool(value)
            self._local_in_active_conv = value
            state = self.state
            if state is not None:
                try:
                    state.set_active_conversation(
                        value, reason='mirror_voice_worker', source='mirror_mode'
                    )
                except Exception:
                    pass

        def run(self):
            path = get_mirror_input_path()
            print(f"🪞 [MirrorVoiceWorker] polling {path} every {self.poll_interval}s")
            append_mirror_output({
                'event': 'mirror_voice_worker_started',
                'input_path': path,
                'poll_interval_s': self.poll_interval,
            })
            while not self._stop_event.is_set():
                try:
                    if os.path.exists(path):
                        with open(path, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                        new_lines = lines[self._last_read_line_count:]
                        for line in new_lines:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                entry = json.loads(line)
                                text = entry.get('text', '').strip()
                                if text:
                                    print(f"🪞 [MirrorVoiceWorker] emit text_ready: {text[:80]}")
                                    self.in_active_conversation = True
                                    self.last_interaction_time = time.time()
                                    self.last_user_speech_time = self.last_interaction_time
                                    # 🪞 [mirror-turn-fix / 2026-06-08] 对齐真实语音路径
                                    # (jarvis_voice_listen_thread.py:922): emit text_ready 前
                                    # 开新对话轮, 让本轮 bg_log + writeback touch 拿到真实
                                    # turn_id (修上次 turn_id 空致 canonical touch_refs=0)。
                                    # 仅镜像验收工具改动, 不碰产品代码。
                                    try:
                                        from jarvis_utils import TraceContext
                                        TraceContext.new_turn()
                                    except Exception:
                                        pass
                                    append_mirror_output({
                                        'event': 'sir_input_received',
                                        'text': text,
                                        'input_entry': entry,
                                    })
                                    self.awake_signal.emit(True)
                                    # 跟 VoiceListenThread 完全一样 emit
                                    self.text_ready.emit(text)
                            except json.JSONDecodeError as e:
                                print(f"[MirrorVoiceWorker] bad input line: {line[:80]} ({e})")
                        self._last_read_line_count = len(lines)
                except Exception as e:
                    print(f"[MirrorVoiceWorker] poll fail: {e}")
                self._stop_event.wait(self.poll_interval)

        def stop(self):
            self._stop_event.set()
            self.quit()
            self.wait(2000)

        def set_speaking_state(self, *args, **kwargs):
            # 兼容 VoiceListenThread.set_speaking_state, mirror 不用
            state = str(args[0]) if args else ''
            self.is_jarvis_speaking = state.upper() == 'EXECUTING'

    return MirrorVoiceWorker()


# ============================================================
# Meta writer — mirror 启动时记录 task / pid / start_time
# ============================================================

def write_mirror_meta() -> None:
    """镜像 jarvis_nerve.py 启动初记一次 meta, Cascade 看 _mirror_meta.json 知道镜像就绪.

    [Sir 2026-05-28 23:00 BUG #2 fix] 不再 overwrite launcher 已写的 meta 防 task 乱码 (Windows GBK env
    vs Python UTF-8). 子进程优先 merge: 保留 launcher 写的 task, 只补 pid/start_ts 这些子进程才知道的字段.
    """
    if not is_mirror_mode():
        return
    try:
        meta_path = os.path.join(get_mirror_root(), '_mirror_meta.json')
        existing = {}
        if os.path.exists(meta_path):
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    existing = json.load(f) or {}
            except Exception:
                existing = {}

        # task 优先用 launcher 已写的 (launcher 直接 file write 不过 env, 编码正确),
        # 没有 才 fallback 到 env get_mirror_task (可能 GBK 乱码).
        task = existing.get('task') or get_mirror_task()

        meta = {
            'pid': os.getpid(),
            'mirror_root': get_mirror_root(),
            'task': task,
            'start_ts': time.time(),
            'start_iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'subprocess_started_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
        # merge: 保留 launcher 写的别的 key (例: launcher_pid)
        for _k, _v in existing.items():
            if _k not in meta:
                meta[_k] = _v

        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"🪞 [mirror_mode] meta written: {meta_path}")
    except Exception as e:
        print(f"[mirror_mode] write_mirror_meta fail: {e}")


# ============================================================
# ChatBypass monkey-patch — cover 13 个 return path
# ============================================================
# [Sir 2026-05-28 23:00 BUG #3+#4 fix] stream_chat 有 ~13 return path (本地 fallback / 早返 /
# 异常 / circuit broken / happy path), stream_nudge 也独立 method, 原 L6132-6160 一处 hook 只
# 覆盖 happy path. 镜像 audit 看不到 90% 主脑回复.
#
# 准则 8 优雅修法: 在 ChatBypass.__init__ 末 monkey-patch 三 method, try/finally 写 event,
# 无论早返/正常/raise 都触发 1 行 turn_complete (or nudge_complete) 进 _mirror_output.jsonl.
# 0 改 chat_bypass 内部 13 个 return, 只在 mirror gate True 时 patch.

def patch_chat_bypass_for_mirror(chat_bypass) -> None:
    """[BUG #3+#4 fix] mirror gate. wrap stream_chat / stream_chat_local / stream_nudge
    三 method, try/finally 写 turn_complete / nudge_complete event 覆盖所有 return path.

    chat_bypass.__init__ 末 mirror gate 调一次即可, 主进程不调 (is_mirror_mode short circuit).
    """
    if not is_mirror_mode():
        return

    import functools as _ft
    import time as _t

    def _extract_user_input(method_name, args, kwargs):
        try:
            if method_name == 'stream_chat_local':
                return args[0] if args else kwargs.get('user_input', '')
            if method_name == 'stream_chat':
                # stream_chat(prompt, user_input='', clean_intent=None, ...)
                return kwargs.get('user_input', '') or (args[1] if len(args) > 1 else '')
            if method_name == 'stream_nudge':
                ctx = args[0] if args else kwargs.get('nudge_context', {})
                if isinstance(ctx, dict):
                    return f"<nudge:{ctx.get('nudge_type', '?')}>"
                return '<nudge>'
        except Exception:
            return ''
        return ''

    def _extract_reply(ret_value):
        try:
            if isinstance(ret_value, tuple) and len(ret_value) >= 2:
                return str(ret_value[1] or '')
            if isinstance(ret_value, str):
                return ret_value
        except Exception:
            return ''
        return ''

    def _wrap(method_name, channel):
        original = getattr(chat_bypass, method_name, None)
        if original is None:
            return

        @_ft.wraps(original)
        def wrapper(*args, **kwargs):
            _t0 = _t.time()
            _user_input = _extract_user_input(method_name, args, kwargs)
            _final_reply = ''
            _exc_repr = None
            _ret_value = None
            try:
                _ret_value = original(*args, **kwargs)
                _final_reply = _extract_reply(_ret_value)
                return _ret_value
            except Exception as _e:
                _exc_repr = repr(_e)[:200]
                raise
            finally:
                try:
                    _dur = _t.time() - _t0
                    _tool_results = []
                    try:
                        for _tr in (getattr(chat_bypass, '_last_tool_results', []) or [])[:10]:
                            if isinstance(_tr, dict):
                                _tool_results.append({
                                    'organ': _tr.get('organ'),
                                    'command': _tr.get('command'),
                                    'success': _tr.get('success'),
                                    'result_excerpt': str(_tr.get('result', ''))[:200],
                                })
                    except Exception:
                        pass

                    _evt = 'nudge_complete' if channel == 'nudge' else 'turn_complete'
                    append_mirror_output({
                        'event': _evt,
                        'channel': channel,
                        'method': method_name,
                        'sir_utterance': str(_user_input or '')[:400],
                        'final_reply': str(_final_reply or '')[:1600],
                        'reply_len_chars': len(_final_reply or ''),
                        'duration_sec': float(_dur),
                        'tool_results': _tool_results,
                        'circuit_broken_reason': getattr(chat_bypass, '_last_circuit_broken_reason', None),
                        'exception_repr': _exc_repr,
                        'return_type': type(_ret_value).__name__ if _ret_value is not None else 'None',
                    })
                except Exception:
                    pass

        setattr(chat_bypass, method_name, wrapper)

    _wrap('stream_chat', 'main_chat')
    _wrap('stream_chat_local', 'main_chat_local')
    _wrap('stream_nudge', 'nudge')

    try:
        append_mirror_output({
            'event': 'mirror_chat_bypass_patched',
            'methods': ['stream_chat', 'stream_chat_local', 'stream_nudge'],
        })
    except Exception:
        pass
