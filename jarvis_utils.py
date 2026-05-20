import time
import functools
import threading
import sys
import re as _re_module
from collections import deque

# [P0+20-beta.5.16-fix-vocab / 2026-05-19] BUG-F (beta.5 publish_only): 顶部裸 import.
# 历史包袱: 全文用 alias (_os_for_log / _stdlib_os / _stdlib_json / _json) 但
# read_gate_mode / 测试 latest.txt 守卫等多处函数体内裸用 os./json. -> NameError ->
# silent except -> beta.5 publish_only 全失效一直跑 hard mode. 顶部加裸 import 修.
import os
import json

import httpx

_PROXY_URL = 'http://127.0.0.1:7890'

# ============================================================
# [P0+18-e.4 / 2026-05-15] 终端色彩化分区 (colorama + ANSI)
# ------------------------------------------------------------
# 设计：让终端 Human / Jarvis / Action / Subtitle / Error 一眼分区，
# Sir 不再"一坨白字盯到眼花"。日志文件保持纯文本（ANSI 在 TeeStream
# 里 strip 掉），不影响 grep / Cursor Agent 读取。
#
# 实现：
# - 启动时 init colorama（autoreset=False，手动控制 RESET）
# - 提供 ANSI 常量 + colorize_terminal_line(text) helper
# - _TeeStream 写日志前 strip ANSI（log 文件 grep 友好）
# - 色彩映射（保守取较深色，避免亮色刺眼）：
#     🗣️ Human       → CYAN
#     🤖 Jarvis      → GREEN
#     🛠️ Action      → YELLOW
#     📺 Subtitle    → MAGENTA
#     🎯 Intent      → BLUE
#     ❌/⛔ Error    → RED
#     ⚠️ Warn        → YELLOW
#     🛡️ Guard       → CYAN
#     🚪 Gatekeeper  → BLUE
#     📝 Commit      → BLUE
# ============================================================
try:
    import colorama as _colorama
    if hasattr(_colorama, 'just_fix_windows_console'):
        _colorama.just_fix_windows_console()
    else:
        _colorama.init(autoreset=False, convert=True, strip=False)
    _ANSI_ENABLED = True
except Exception:
    _ANSI_ENABLED = False


class _ANSI:
    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    CYAN = "\x1b[36m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    MAGENTA = "\x1b[35m"
    BLUE = "\x1b[94m"
    RED = "\x1b[31m"
    GRAY = "\x1b[90m"


# 匹配 ║ <emoji> [<TAG>] ... 模式 → 给整行上色
# 兼容 \U0001f7e3 等四字节 emoji + ASCII 标点
_COLOR_PATTERNS = [
    # (compiled regex matching prefix portion, color code, tag for documentation)
    (_re_module.compile(r'^(║?\s*)(🗣️\s*\[Human\])'),       _ANSI.CYAN),
    (_re_module.compile(r'^(║?\s*)(🤖\s*\[Jarvis(?:[^\]]*)\])'), _ANSI.GREEN),
    (_re_module.compile(r'^(║?\s*)(🛠️\s*\[Action\])'),      _ANSI.YELLOW),
    (_re_module.compile(r'^(║?\s*)(📺\s*\[Subtitle\])'),     _ANSI.MAGENTA),
    (_re_module.compile(r'^(║?\s*)(🎯\s*\[Intent\])'),       _ANSI.BLUE),
    (_re_module.compile(r'^(║?\s*)(🚪\s*\[Gatekeeper)'),     _ANSI.BLUE),
    (_re_module.compile(r'^(║?\s*)(🚪\s*Gatekeeper)'),       _ANSI.BLUE),
    (_re_module.compile(r'^(║?\s*)(📝\s*\[Commit)'),         _ANSI.BLUE),
    (_re_module.compile(r'^(║?\s*)(❌)'),                    _ANSI.RED),
    (_re_module.compile(r'^(║?\s*)(⛔)'),                    _ANSI.RED),
    (_re_module.compile(r'^(║?\s*)(⚠️)'),                    _ANSI.YELLOW),
    (_re_module.compile(r'^(║?\s*)(🛡️)'),                    _ANSI.CYAN),
]


def colorize_terminal_line(text: str) -> str:
    """对终端单行做 ANSI 着色。若关闭或无匹配则原样返回。"""
    if not _ANSI_ENABLED or not text:
        return text
    for pat, color in _COLOR_PATTERNS:
        if pat.search(text):
            return f"{color}{text}{_ANSI.RESET}"
    return text


# ANSI escape sequence stripper（写日志用）
_ANSI_STRIP_RE = _re_module.compile(r'\x1b\[[0-9;]*[a-zA-Z]')


def strip_ansi_codes(text: str) -> str:
    """从字符串里剥掉 ANSI 转义码。用于 TeeStream 写日志时保持纯文本。

    [P0+18-f.1 / 2026-05-15] 快速路径：无 ESC (\\x1b) 字符直接返回，避免 regex 扫整段。
    实测 ASR 主循环每秒 30+ 次声波 print（无 ESC），regex 是主线程瓶颈。
    """
    if not text:
        return text
    if '\x1b' not in text:
        return text
    return _ANSI_STRIP_RE.sub('', text)


# ============================================================
# [轴 1.6 / 2026-05-15] Windows GBK 终端 emoji 安全 —— 全局根本修法
# ------------------------------------------------------------
# Python 在 Windows 默认 stdout/stderr 编码 cp936 (GBK)。
# 所有 emoji（\U0001fxxx 范围）写入时抛 UnicodeEncodeError。
# 如果 print 在 `try/except: pass` 块里且后续有关键逻辑（如 freeze_for），
# 关键逻辑就被静默吞掉 —— 这正是 v3-v4"用户说不需要帮助但 Conductor
# 仍然催"的真根因（_detect_help_refusal 的 print emoji 炸了，freeze_for 没调）。
#
# 修法：在 jarvis_utils 被 import 时（jarvis_nerve.py 启动最早）就把 stdout/
# stderr 切到 utf-8。errors='replace' 兜底，连不认识的字符也降级而非抛错。
# 这覆盖所有现有/未来 print(emoji) 代码，零侵入。
# ============================================================
try:
    if sys.platform == 'win32':
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


# ============================================================
# 📜 [P0+18-b.1 / 2026-05-15] 运行时日志同步系统（Runtime Tee Logger）
# ------------------------------------------------------------
# 设计目标：把 Jarvis 所有打印在终端的输出（含 stdout / stderr / bg_log
# 缓冲 flush 后的内容）实时同步写入磁盘，方便事后排错 / 给 Cursor Agent 读。
#
# 路径：docs/runtime_logs/jarvis_YYYYMMDD_HHMMSS.log
# - 每次启动一份 → 不丢失历史，按时间戳归档
# - 维护 latest.log 软链 / 副本 → Cursor Agent 始终能用 "读最新一份"
# - 启动时打印一行 [Runtime Log] -> 路径，让 Sir / Agent 一眼能定位
#
# 实现：在 jarvis_utils 被 import 的最早时机（这里）把 sys.stdout / sys.stderr
# 替换为 _TeeStream —— 它会同时写原始 fd 和文件。这样所有现有 print / bg_log
# / traceback / 子模块 import 时的 print 全自动被记录，零侵入。
#
# 安全：
# - 文件写入用 try/except 兜底，写盘失败不影响终端输出
# - errors='replace' 兜住 GBK 不认识的 emoji
# - 每条 print 后 flush()，杀进程也不丢
# - 启动时只生成时间戳目录，size 软限 50 MB 滚动；超过则压缩归档
# ============================================================
import os as _os_for_log
import datetime as _dt_for_log


# [P0+18-f.2 / 2026-05-15] TeeStream 异步写盘 —— 主线程 0 IO 阻塞
# ============================================================
# 旧设计：每次 TeeStream.write 持锁 + 同步写日志文件 + flush。
# ASR 主循环 30Hz 打印声波（`🎙️ [接收物理声波] █████`），主对话/Subtitle
# 也走同一路径,每秒 30+ 次磁盘 fsync → 主线程被 IO 完全淹没,
# 表现：TTFT 从 3s 飚到 18-27s, ASR 转录变慢, 终端打印滞后。
#
# 新设计：write() 只入 queue（非阻塞），后台 daemon worker 批量写盘
# + 0.5s 定时 flush。日志实时性损失 <500ms,主线程 IO 时间归零。
# 队列满（>10000 条）时丢日志保实时,绝不阻塞主线程。
# ============================================================
import queue as _queue_for_tee

_TEE_QUEUE = _queue_for_tee.Queue(maxsize=10000)
_TEE_WORKER_STARTED = False
_TEE_WORKER_LOCK = threading.Lock()


def _tee_worker_loop():
    """后台 daemon：拉队列，批量写日志 + 定时 flush。"""
    import time as _t_tee
    last_flush = _t_tee.time()
    batch_count = 0
    while True:
        try:
            item = _TEE_QUEUE.get(timeout=0.5)
        except _queue_for_tee.Empty:
            if _RUNTIME_LOG_HANDLE is not None:
                try:
                    if not _RUNTIME_LOG_HANDLE.closed:
                        _RUNTIME_LOG_HANDLE.flush()
                except Exception:
                    pass
                last_flush = _t_tee.time()
                batch_count = 0
            continue
        if item is None:
            try:
                if _RUNTIME_LOG_HANDLE is not None and not _RUNTIME_LOG_HANDLE.closed:
                    _RUNTIME_LOG_HANDLE.flush()
            except Exception:
                pass
            break
        fh, log_data = item
        try:
            if fh is not None and not fh.closed:
                fh.write(log_data)
                batch_count += 1
        except Exception:
            pass
        now = _t_tee.time()
        if batch_count >= 50 or (now - last_flush) > 0.5:
            try:
                if fh is not None and not fh.closed:
                    fh.flush()
            except Exception:
                pass
            last_flush = now
            batch_count = 0


def _start_tee_worker():
    global _TEE_WORKER_STARTED
    with _TEE_WORKER_LOCK:
        if _TEE_WORKER_STARTED:
            return
        _TEE_WORKER_STARTED = True
        t = threading.Thread(target=_tee_worker_loop, daemon=True, name='TeeLogWorker')
        t.start()


class _TeeStream:
    """同时写 原始流 + 日志文件 的 wrapper。
    把 sys.stdout / sys.stderr 替换成这个对象后，所有 print/traceback 自动 tee。

    [P0+18-f.2 / 2026-05-15] 异步化：write() 入队不阻塞,worker 后台批量写盘。
    """
    def __init__(self, orig_stream, log_file_handle, stream_label: str):
        self._orig = orig_stream
        self._log = log_file_handle
        self._label = stream_label  # 'stdout' / 'stderr'

    def write(self, data):
        # 主流：直接写原始 stream（终端可见性 = 第一性原理）
        try:
            self._orig.write(data)
        except Exception:
            pass
        if not data:
            return
        if self._log is None or self._log.closed:
            return
        try:
            # [P0+18-e.4 + P0+18-f.1] 写日志前 strip ANSI；无 ESC 字符走快速路径
            try:
                _log_data = strip_ansi_codes(data)
            except Exception:
                _log_data = data
            # [P0+18-f.2] 入队非阻塞；满队列退化到同步写,绝不丢日志
            try:
                _TEE_QUEUE.put_nowait((self._log, _log_data))
            except _queue_for_tee.Full:
                # fallback: 同步写盘（worker 落后了，保数据完整性）
                try:
                    self._log.write(_log_data)
                except Exception:
                    pass
        except Exception:
            pass

    def flush(self):
        try:
            self._orig.flush()
        except Exception:
            pass
        # 不主动 flush 日志：worker 0.5s 定时 flush 已足够实时

    def isatty(self):
        try:
            return self._orig.isatty()
        except Exception:
            return False

    def fileno(self):
        return self._orig.fileno()

    @property
    def encoding(self):
        return getattr(self._orig, 'encoding', 'utf-8')

    def __getattr__(self, item):
        return getattr(self._orig, item)


_RUNTIME_LOG_PATH = None
_RUNTIME_LOG_HANDLE = None
_RUNTIME_LOG_INITIALIZED = False


def _init_runtime_tee_log():
    """初始化运行时 Tee 日志。只在 jarvis_utils 第一次 import 时执行。"""
    global _RUNTIME_LOG_PATH, _RUNTIME_LOG_HANDLE, _RUNTIME_LOG_INITIALIZED
    if _RUNTIME_LOG_INITIALIZED:
        return _RUNTIME_LOG_PATH
    _RUNTIME_LOG_INITIALIZED = True

    try:
        # 项目根 = jarvis_utils.py 所在目录
        here = _os_for_log.path.dirname(_os_for_log.path.abspath(__file__))
        log_dir = _os_for_log.path.join(here, 'docs', 'runtime_logs')
        _os_for_log.makedirs(log_dir, exist_ok=True)

        ts = _dt_for_log.datetime.now().strftime('%Y%m%d_%H%M%S')
        path = _os_for_log.path.join(log_dir, f'jarvis_{ts}.log')

        # 日志文件用 utf-8 + line buffering，errors='replace' 兜底 emoji
        fh = open(path, mode='a', encoding='utf-8', errors='replace', buffering=1)

        # 写头部 banner —— 方便事后排错时一眼定位是哪一轮
        header = (
            f"\n{'='*72}\n"
            f"  Jarvis Runtime Log\n"
            f"  Started: {_dt_for_log.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"  PID:     {_os_for_log.getpid()}\n"
            f"  Path:    {path}\n"
            f"{'='*72}\n\n"
        )
        fh.write(header)
        fh.flush()

        _RUNTIME_LOG_PATH = path
        _RUNTIME_LOG_HANDLE = fh

        # 替换 stdout / stderr —— 注意要在 reconfigure 之后做
        sys.stdout = _TeeStream(sys.stdout, fh, 'stdout')
        sys.stderr = _TeeStream(sys.stderr, fh, 'stderr')

        # [P0+18-f.2 / 2026-05-15] 启动后台 daemon worker，异步写日志
        try:
            _start_tee_worker()
        except Exception:
            pass

        # 同时维护 latest.log（直接复制路径写入文本，让 Agent 一行命令读最新）
        # 🩹 [β.3.0 / 2026-05-18] Sir 16:18 实测 BUG 治本: 测试运行 (pytest) 不
        # 应该写 latest.txt 把 dashboard 引到测试 log. 检测策略:
        #   - JARVIS_TEST_MODE env var (conftest 设置)
        #   - sys.argv[0] 含 pytest
        #   - JARVIS_TEST_MARKER env var 存在 (测试 marker)
        try:
            import sys as _sys_for_test
            is_test_run = (
                os.environ.get('JARVIS_TEST_MODE') == '1'
                or os.environ.get('JARVIS_TEST_MARKER')
                or 'pytest' in (_sys_for_test.argv[0] if _sys_for_test.argv
                                  else '')
                or any('pytest' in a for a in _sys_for_test.argv[:3])
            )
        except Exception:
            is_test_run = False

        try:
            if not is_test_run:
                latest_pointer = _os_for_log.path.join(log_dir, 'latest.txt')
                with open(latest_pointer, 'w', encoding='utf-8') as fp:
                    fp.write(path)
        except Exception:
            pass

        # 终端 banner（用原始 stderr 印，避免被自己 tee 写两次 —— 其实通过
        # sys.stderr 也只是写 orig + 文件各一次，这里直接 print 即可）
        sys.stderr.write(
            f"\n📜 [Runtime Log] 本轮日志：{path}\n"
            f"     最新指针：{_os_for_log.path.join(log_dir, 'latest.txt')}\n\n"
        )
        sys.stderr.flush()

        # 进程退出时收尾
        import atexit
        def _close_log():
            # [P0+18-f.2] 先给 worker 发 sentinel，等它把队列内未写日志冲到磁盘
            try:
                _TEE_QUEUE.put_nowait(None)
            except Exception:
                pass
            try:
                import time as _t_close
                _t_close.sleep(0.6)
            except Exception:
                pass
            try:
                if _RUNTIME_LOG_HANDLE and not _RUNTIME_LOG_HANDLE.closed:
                    _RUNTIME_LOG_HANDLE.write(
                        f"\n{'='*72}\n"
                        f"  Jarvis Runtime Log Closed at "
                        f"{_dt_for_log.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"{'='*72}\n"
                    )
                    _RUNTIME_LOG_HANDLE.flush()
                    _RUNTIME_LOG_HANDLE.close()
            except Exception:
                pass
        atexit.register(_close_log)

        return path

    except Exception as _e:
        try:
            sys.stderr.write(f"[Runtime Log Init Failed] {_e}\n")
        except Exception:
            pass
        return None


def get_runtime_log_path():
    """供其它模块（如 vocal warn / nerve startup 横幅）查询当前 log 路径。"""
    return _RUNTIME_LOG_PATH


# 立刻初始化（仅一次）
_init_runtime_tee_log()


# ============================================================
# 🧹 背景日志缓冲器（Bug 终端打印整顿）
# ------------------------------------------------------------
# 问题：KeyRouter / HabitClock / Pipeline Timer / Hippocampus 等
# 后台线程会在 stream_chat 正在画对话框时往 stdout/stderr 乱喷，
# 导致 ║ 🤖 [Jarvis] xxx 这一行被切碎、JSON / 计时器 / 错误信息
# 全混进对话框里。
#
# 方案：导出 set_conversation_active(True/False) 和 bg_log(msg)
# - 对话激活时 → 缓冲
# - 对话结束时 → 一次性按顺序 flush 到 stderr，每条都自带换行
# - 对话未激活时 → 直接打到 stderr
# ============================================================
# 🩹 [P0+20-β.2.7.6 / 2026-05-17] 诊断类 marker 黑名单 — 自动只写日志不打终端
# Sir 反馈"贾维斯说完话后输出实在太多了，影响判断重要信息"
# 这些 markers 是后台诊断/性能/异步评分，Sir 不需要看终端，只放日志足够。
# call site 不用改 — bg_log 入口看 message 含任一 marker 自动 to_terminal=False
# verbose 模式 (env JARVIS_VERBOSE_BG=1) 时全部回归显示，给 debug 用
_BG_LOG_DIAG_MARKERS = (
    '[Prompt Tier]',
    '[L2 inject]',
    '[SOUL inject]',
    '[Nudge SOUL inject]',
    '[SoulEvaluator]',
    '[Tone]',
    '[Screenshot]',
    '[Prompt Size]',
    '[Asm Diag]',
    '[Perf Diag]',
    '[Pipeline Timer]',
    '[Pipeline]',
    '[Evaluator]',                     # 'helped=' 异步评分 (DirectiveEvaluator)
    '[Conversation Event]',
    '[Gatekeeper Async]',
    '[Gatekeeper Slow]',
    '[BrowserDucking]',
    '[SmartNudge/Skip]',
    '[Shield watching]',
    '[ReturnSentinel/Diag]',
    '[ReturnSentinel/Health]',
    '[CommitmentWatcher/StartupGuard]',
    '[Render Guard]',                  # audio guard 拦截不重要
    '[Audio Guard / Tool Name]',
    '[Audio Guard / Orphan Done]',
    '[Audio Guard / Upstream',         # local-fallback 类
    '[HabitClock LLM]',
    '[Local Phrase Pool]',
    '[FunnelLogger]',
    '[ConcernsDecayWorker]',
    '[DirectiveDecayWorker]',
    '[Embedding Backfill Worker]',
)


def _bg_log_should_hide(message: str) -> bool:
    """诊断 marker 自动 hide。verbose 模式 (env JARVIS_VERBOSE_BG=1) 全显示。"""
    import os as _os_bg
    if _os_bg.environ.get('JARVIS_VERBOSE_BG', '').strip() == '1':
        return False
    return any(m in message for m in _BG_LOG_DIAG_MARKERS)


class _BgLogBuffer:
    _lock = threading.Lock()
    _active = False
    _buffer = []
    _max_buffer = 200  # 防爆

    @classmethod
    def set_active(cls, active: bool):
        with cls._lock:
            was_active = cls._active
            cls._active = bool(active)
            if was_active and not active:
                cls._flush_locked()

    @classmethod
    def is_active(cls) -> bool:
        return cls._active

    @classmethod
    def log(cls, message: str, stream: str = "stderr", to_terminal: bool = True):
        """记录一条背景日志。message 不要自带前后换行，函数会负责。
        
        [P0+20-α.7 / 2026-05-16] 双路径分流（终端 = 主体；日志 = prefix+主体）
        [P0+20-β.2.7.6 / 2026-05-17] to_terminal=False 时只写文件不进 buffer
        - 终端：走 _TeeStream._orig 直接写原始 stderr/stdout，绕过 Tee 双写，避免 trace_id prefix 污染终端
        - 日志：直接 put 到 _TEE_QUEUE，带 TraceContext prefix（grep 友好）
        """
        if not message:
            return
        line = message.rstrip("\r\n")
        # 🩹 [β.2.7.6] 显式 to_terminal=False / diag marker 自动判断 — 只写日志不打终端
        if (not to_terminal) or _bg_log_should_hide(line):
            cls._write_to_logfile_only(line)
            return
        with cls._lock:
            if cls._active:
                if len(cls._buffer) < cls._max_buffer:
                    cls._buffer.append((stream, line))
                return
            cls._emit_locked(stream, line)

    @classmethod
    def _write_to_terminal_only(cls, stream: str, payload: str):
        """[P0+20-α.7] 仅写终端（绕过 _TeeStream 双写到日志）。"""
        f_wrapped = sys.stderr if stream == "stderr" else sys.stdout
        # _TeeStream 实例有 _orig 字段指向真实终端；若 stderr 还没被 wrap 直接用 f_wrapped
        f_orig = getattr(f_wrapped, '_orig', f_wrapped)
        try:
            f_orig.write(payload)
            try:
                f_orig.flush()
            except Exception:
                pass
        except UnicodeEncodeError:
            # [轴 1.6 / 2026-05-15] GBK 终端写不出 emoji 时降级到 ASCII fallback
            try:
                fallback = payload.encode("ascii", errors="replace").decode("ascii")
                f_orig.write(fallback)
                f_orig.flush()
            except Exception:
                pass
        except Exception:
            pass

    @classmethod
    def _write_to_logfile_only(cls, line: str):
        """[P0+20-α.7] 仅写日志文件（带 TraceContext prefix），异步 queue 不阻塞主线程。"""
        try:
            prefix = TraceContext.get_log_prefix()
        except Exception:
            prefix = ""
        # _RUNTIME_LOG_HANDLE 在 _init_runtime_tee_log 后才有值
        global _RUNTIME_LOG_HANDLE
        fh = _RUNTIME_LOG_HANDLE
        if fh is None or fh.closed:
            return
        file_line = f"\n{prefix} {line}\n" if prefix else f"\n{line}\n"
        try:
            log_data = strip_ansi_codes(file_line)
        except Exception:
            log_data = file_line
        try:
            _TEE_QUEUE.put_nowait((fh, log_data))
        except _queue_for_tee.Full:
            # 队列满：同步写盘保数据完整（少量发生不会影响主线程）
            try:
                fh.write(log_data)
            except Exception:
                pass

    @classmethod
    def _emit_locked(cls, stream: str, line: str):
        # [合约] UnicodeEncodeError → ascii / errors='replace' fallback —— 由 _write_to_terminal_only
        # 内部接住。终端：仅消息主体（无 trace_id prefix），保留对话框外的可读性。
        cls._write_to_terminal_only(stream, "\n" + line + "\n")
        # 日志文件：消息主体 + trace_id prefix（一行可 grep 全链路）
        cls._write_to_logfile_only(line)

    @classmethod
    def _flush_locked(cls):
        # [合约] UnicodeEncodeError → ascii / errors='replace' fallback —— 由 _write_to_terminal_only 接住。
        if not cls._buffer:
            return
        try:
            # 对话框结束后打分隔标记 —— 仅终端，不进日志（日志已经有时间戳/prefix 不需要这个）
            cls._write_to_terminal_only("stderr", "\n──── [Background] ────\n")
            for stream, line in cls._buffer:
                cls._write_to_terminal_only(stream, line + "\n")
                cls._write_to_logfile_only(line)
            cls._write_to_terminal_only("stderr", "──────────────────────\n")
        finally:
            cls._buffer.clear()


# ============================================================
# 🧬 [P0+20-W.2 / 2026-05-16] TraceContext — 全局 trace_id 体系
# ------------------------------------------------------------
# 三层 ID（详见 docs/JARVIS_WORKFLOW_PROTOCOL.md §1）:
#   - session_id：单次进程启动唯一，sess_YYYYMMDD_HHMMSS_<PID>
#   - turn_id：单轮对话唯一，turn_YYYYMMDD_HHMMSS_<4hex>
#   - marker：工程级 (P0+X-Y / R7-α 等)，直接写在代码注释 + commit message
#
# 自动注入：bg_log 输出时若 session_id 已 init → 自动加 "[sess_xxx]"
# 或 "[sess_xxx] [turn_yyy]" 前缀。grep 一个 turn_id 拿全链路。
#
# 测试兼容：未初始化时 get_log_prefix() 返回 ""，bg_log 行为与历史等价。
# ============================================================

class TraceContext:
    """全局 Trace 上下文（线程安全）。
    
    入口约定：
      - jarvis_nerve.py:__main__ 启动时调 init_session()
      - VoiceListenThread.text_ready 触发时调 new_turn()
      - ChatBypass.stream_chat 完成（Full pipeline 后）调 clear_turn()
    
    [P0+20-W.2 / 2026-05-16] 详 docs/JARVIS_WORKFLOW_PROTOCOL.md §1
    """
    _lock = threading.Lock()
    _session_id: str = ""
    _turn_id: str = ""
    _enabled: bool = True

    @classmethod
    def init_session(cls, pid: int = None) -> str:
        """启动 Jarvis 进程时调一次。返回新生成的 session_id。"""
        import os as _os
        pid = pid or _os.getpid()
        ts = time.strftime("%Y%m%d_%H%M%S")
        with cls._lock:
            cls._session_id = f"sess_{ts}_{pid}"
        return cls._session_id

    @classmethod
    def new_turn(cls) -> str:
        """开新对话轮（每次 ASR 出 text_ready 时调）。返回新 turn_id。"""
        import secrets as _secrets
        ts = time.strftime("%Y%m%d_%H%M%S")
        rid = _secrets.token_hex(2)
        with cls._lock:
            cls._turn_id = f"turn_{ts}_{rid}"
        return cls._turn_id

    @classmethod
    def clear_turn(cls):
        """对话轮结束（Pipeline Timer Full pipeline 后）调。"""
        with cls._lock:
            cls._turn_id = ""

    @classmethod
    def get_session_id(cls) -> str:
        with cls._lock:
            return cls._session_id

    @classmethod
    def get_turn_id(cls) -> str:
        with cls._lock:
            return cls._turn_id

    @classmethod
    def get_log_prefix(cls) -> str:
        """返回日志前缀：'[session_id] [turn_id]' 或 '[session_id]' 或 ''
        
        未初始化时返回 ''，保证测试场景下 bg_log 输出与历史完全等价。
        """
        if not cls._enabled:
            return ""
        with cls._lock:
            sid = cls._session_id
            tid = cls._turn_id
        if not sid:
            return ""
        parts = [f"[{sid}]"]
        if tid:
            parts.append(f"[{tid}]")
        return " ".join(parts)

    @classmethod
    def disable_log_prefix(cls):
        """测试 / 临时关闭注入。"""
        with cls._lock:
            cls._enabled = False

    @classmethod
    def enable_log_prefix(cls):
        with cls._lock:
            cls._enabled = True


# ============================================================
# [P0+20-β.2.7.7 / 2026-05-17] STM source 区分 (治 reflector 幻觉 root cause)
# Sir 反馈：sir_post_may_physical_labor / environment_lighting_logic 等 propose
# 起因是"视频音被 ASR 录入" + "Jarvis 自己说的话" + "系统事件" 都堆 STM →
# LLM 看 STM 全当 Sir 说的事 → 幻觉 concern。
#
# 最少改动方案: 不改 14 处 STM append 点的 schema, 在消费端 (WeeklyReflector
# / SoulEvaluator 等) 调本 helper 按 user 字段 prefix 自动分类 source。
# ============================================================

STM_SOURCE_USER_VOICE = 'user_voice'        # Sir 真说的 (最可信)
STM_SOURCE_JARVIS_SELF = 'jarvis_self'      # Jarvis 自己 reply 被错归 user 字段 / 自言自语
STM_SOURCE_SYSTEM_EVENT = 'system_event'    # 后台事件 (commitment / reminder / alert / standby)
STM_SOURCE_AMBIENT_PICKUP = 'ambient_pickup'  # 视频/音乐/旁人 ASR 录入 (难以单 prefix 判断)

_STM_SYSTEM_EVENT_PREFIXES = (
    '[System Standby]', '[SYSTEM ALERT]', '[系统事件]', '[未确认提醒]',
    '[REMINDER FIRING NOW]', '[COMMITMENT DETECTED]', '[Commitment]',
    '[SYSTEM BACKGROUND EVENT]',
)
_STM_JARVIS_SELF_PREFIXES = (
    '[静默轻推]', '[视觉脉冲]', '[智能轻推]', '[Smart Nudge]',
    '[ReturnSentinel]', '[Conductor]', '[Chronos]', '[CommitmentWatcher]',
    '[Self-Promise]', '[Soul Capture]',
)


def classify_stm_source(entry: dict) -> str:
    """根据 STM entry 的 user 字段 prefix 推断 source。
    
    最少改动 (不需要改 14 处 append 调用)。返回 4 大 source 之一:
    - user_voice / jarvis_self / system_event / ambient_pickup
    
    注: ambient_pickup (视频音/旁人) 难以仅凭 prefix 判断, 需要更深的 ASR 置信度
    或语义判断 (留待 β.2.8+)。当前默认裸 cmd 算 user_voice (接受会被 ambient
    污染的现实, 但 prompt 加约束让 LLM 自己谨慎)。
    """
    if not isinstance(entry, dict):
        return STM_SOURCE_USER_VOICE
    user_text = entry.get('user', '') or ''
    if not user_text:
        return STM_SOURCE_USER_VOICE
    
    # 显式 source 字段优先 (β.2.8+ 写入端可以主动标)
    explicit = entry.get('source')
    if isinstance(explicit, str) and explicit in (
        STM_SOURCE_USER_VOICE, STM_SOURCE_JARVIS_SELF,
        STM_SOURCE_SYSTEM_EVENT, STM_SOURCE_AMBIENT_PICKUP,
    ):
        return explicit
    
    stripped = user_text.strip()
    # System event prefix
    for p in _STM_SYSTEM_EVENT_PREFIXES:
        if stripped.startswith(p):
            return STM_SOURCE_SYSTEM_EVENT
    # Jarvis self prefix
    for p in _STM_JARVIS_SELF_PREFIXES:
        if stripped.startswith(p):
            return STM_SOURCE_JARVIS_SELF
    # 默认裸 cmd = user_voice (可能被 ambient 污染, 接受)
    return STM_SOURCE_USER_VOICE


def format_stm_for_prompt(stm: list, take_last: int = 6, max_chars: int = 2000,
                            include_time: bool = False) -> str:
    """🩹 [β.5.29 / 2026-05-20] STM → prompt 注入字符串 + source 标记.

    Sir 痛点 (FOUNDATION_AUDIT.md §STM): 老 stm_context 用裸 'user -> jarvis' 字符串
    LLM 看不出"系统事件 / Jarvis 自语 / 真 Sir 说话"区别 → 把 system event 当 Sir 指令 → 幻觉.

    修法: 每条 STM 用 classify_stm_source 判 source, 加显式标签前缀:
      [SIR]      → 真 Sir 说话 (最可信, LLM 应当响应)
      [SYS]      → 后台系统事件 (commitment/alert/standby, 仅作上下文不可当指令)
      [JARVIS]   → Jarvis 自己之前的回复 (上下文)
      [AMBIENT]  → 视频/旁人 ASR 噪音 (低可信, 谨慎)

    参数:
      stm: short_term_memory list
      take_last: 取最近 N 条 (默认 6, 跟老 ctx 一致)
      max_chars: 上限 (超 → 头部加 '...' 截尾)
      include_time: 加 [HH:MM:SS] 时间戳

    返回: 多行字符串 (每行 1 条).
    """
    if not stm:
        return ''
    chunk = stm[-take_last:] if take_last > 0 else stm
    lines = []
    source_tag_map = {
        STM_SOURCE_USER_VOICE: '[SIR]',
        STM_SOURCE_SYSTEM_EVENT: '[SYS]',
        STM_SOURCE_JARVIS_SELF: '[JARVIS]',
        STM_SOURCE_AMBIENT_PICKUP: '[AMBIENT]',
    }
    for m in chunk:
        if not isinstance(m, dict):
            continue
        src = classify_stm_source(m)
        tag = source_tag_map.get(src, '[SIR]')
        time_prefix = f"[{m.get('time', '')}] " if include_time and m.get('time') else ''
        user_part = (m.get('user', '') or '').strip()
        jarvis_part = (m.get('jarvis', '') or '').strip()
        if user_part and jarvis_part:
            lines.append(f"{time_prefix}{tag} {user_part} -> {jarvis_part}")
        elif jarvis_part:
            lines.append(f"{time_prefix}[JARVIS] {jarvis_part}")
        elif user_part:
            lines.append(f"{time_prefix}{tag} {user_part}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = "..." + text[-max_chars:]
    return text


def filter_stm_by_source(stm_list, exclude=(STM_SOURCE_SYSTEM_EVENT, STM_SOURCE_AMBIENT_PICKUP)):
    """过滤 STM list, 默认排除 system_event + ambient_pickup。
    
    给 WeeklyReflector / SoulEvaluator 等"语义反思"消费端用。
    保留 user_voice + jarvis_self (jarvis 自己说的话也是有用上下文)。
    """
    if not stm_list:
        return []
    out = []
    for e in stm_list:
        src = classify_stm_source(e)
        if src in exclude:
            continue
        # 加 source 字段方便 LLM prompt 里区分 (不改原 entry)
        new_e = dict(e) if isinstance(e, dict) else e
        if isinstance(new_e, dict):
            new_e['_inferred_source'] = src
        out.append(new_e)
    return out


def bg_log(message: str, stream: str = "stderr", to_terminal: bool = True):
    """便捷入口：背景线程要打字时用这个，自动避开对话框。
    
    [P0+20-α.7 / 2026-05-16] trace_id 注入位置改到 _BgLogBuffer 内部
    [P0+20-β.2.7.6 / 2026-05-17] 加 to_terminal=False (Sir 反馈终端输出太多)
    - to_terminal=True (默认): 进对话框后 [Background] 块 + 写日志文件
    - to_terminal=False: 只写日志文件不打终端 (诊断类用此)
    """
    _BgLogBuffer.log(message, stream=stream, to_terminal=to_terminal)


def set_conversation_active(active: bool):
    """ChatBypass.stream_chat 在开始/结束时各调一次。"""
    _BgLogBuffer.set_active(active)


def is_conversation_active() -> bool:
    return _BgLogBuffer.is_active()


# ============================================================
# [P0+20-β.2.4 hotfix / 2026-05-16] resolve_worker_attr helper
# ------------------------------------------------------------
# P0+19 nerve split 后 sentinel/watcher 的 worker 参数从 JarvisWorkerThread
# （持有 .jarvis = central_nerve 包装）改成直接传 central_nerve。但许多
# callsite 仍写 `self.worker.jarvis.X` + `hasattr(...)` 守卫 → guard 不通 →
# 整段功能 silently 跳过（伪失效）。
#
# 受影响的真 BUG（Sir 23:38 报告）：
# - commitment_watcher._get_hippo 永远 None → add_commitment_row 从未调用
#   → SQLite Commitments 表自 P0+18-e.3 起空，commitment 持久化伪失效。
# - smart_nudge 的 _on_activity_wake / event_bus 投递可能也同样静默跳过。
# - conductor 的 companion_center 引用 4 处同款。
#
# 修复 helper：先尝试 worker.X（拆分后路径），fallback worker.jarvis.X
# （兼容旧 JarvisWorker 包装层路径），任一找到即返回。
# ============================================================
def resolve_worker_attr(worker, attr_name: str):
    """Resolve worker attribute through both new (direct) and legacy
    (worker.jarvis.X) paths. Returns None if neither path resolves.

    Use this everywhere we previously wrote `self.worker.jarvis.X` so that
    the sentinel works regardless of whether the caller passes CentralNerve
    directly or JarvisWorkerThread (which wraps it as .jarvis).
    """
    if worker is None:
        return None
    try:
        v = getattr(worker, attr_name, None)
        if v is not None:
            return v
    except Exception:
        pass
    try:
        j = getattr(worker, 'jarvis', None)
        if j is None:
            return None
        return getattr(j, attr_name, None)
    except Exception:
        return None


# ============================================================
# 🔇 TTS 回声指纹环（防 Jarvis 听到自己说话）
# ------------------------------------------------------------
# 场景：interrupt_all 用 daemon 调 vocal.say、Smart Nudge 焦点锁后强
# 制 mute_until=0.0、音箱靠近麦克风等情况下，TTS 输出会被 ASR 捕获
# 并当成"用户输入"处理，触发 Conversation Event callback，导致
# Jarvis 跟自己对话的死循环。
#
# 方案：Jarvis 每说一句话 → 注册到环里（含时间戳、有效窗口 12s）→
# ASR 转录完成后调 is_recent_jarvis_echo(text) 比对，命中即作为回声
# 静默丢弃。
# ============================================================
# ============================================================
# 🩹 [β.5.36-H / 2026-05-20] 工具名 scrub helper — 防 BUG 3 工具名泄漏
# Sir 反馈 BUG 3: LLM 偶尔输出 "process_hands.get_top_cpu" 给 Sir 听到/看到.
# β.4.X 在 TTS 入口已 scrub (chat_bypass._put_audio), β.5.36-H 扩到 subtitle / STM
# 任何路径都该用. 统一 helper 让 jarvis_ui / chat_bypass / STM commit 都能 import.
# doc: docs/JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN.md §C.5
# ============================================================
import re as _re_internal_names

_INTERNAL_TOOL_NAME_RE = _re_internal_names.compile(
    r'\b(process_hands|file_operator(?:_hands)?|txt_writer_hands\w*|system_hands|'
    r'memory_hands|fuzzy_resolver|ui_control|hippocampus|'
    r'commitment_watcher|return_sentinel|smart_nudge|chat_bypass|'
    r'audio_hands|window_hands|media_control_hands|notification_hands|'
    r'screen_capture_hands)\.\w+',
    _re_internal_names.IGNORECASE,
)

# <TOOL_CALL>{...}</TOOL_CALL> tag (β.5.36-G 加, scrub from subtitle/TTS — 主脑用 tag 内部沟通)
_INTERNAL_TOOL_CALL_TAG_RE = _re_internal_names.compile(
    r'<TOOL_CALL>.*?</TOOL_CALL>',
    _re_internal_names.IGNORECASE | _re_internal_names.DOTALL,
)


def scrub_internal_names(text, *, replacement: str = 'a quick check') -> str:
    """剥工具名 (organ.command) + <TOOL_CALL> tag, 返人话.

    用法:
        jarvis_ui._poll_queue 处理 'en'/'zh' subtitle text 前调一次
        STM commit 前调一次 (可选, 主脑内部沟通可保留原文)
        chat_bypass._put_audio 入口已有 inline (β.5.36-H 留尾, 后续可改调本 helper)

    Args:
        text: 输入字符串 (LLM 输出原文 / sentence / subtitle 内容)
        replacement: 工具名替换文本 (默认 'a quick check' — 自然短语)

    Returns:
        scrub 后的字符串. 空输入返回空字符串.
    """
    if not text or not isinstance(text, str):
        return text or ''
    # 先剥 <TOOL_CALL> tag (整段干掉)
    out = _INTERNAL_TOOL_CALL_TAG_RE.sub('', text)
    # 再剥 organ.command 工具名 (替换 placeholder)
    if _INTERNAL_TOOL_NAME_RE.search(out):
        out = _INTERNAL_TOOL_NAME_RE.sub(replacement, out)
        # 轻 polish: "may I run a quick check" → "a quick check" (动词 + 名词冗余)
        out = _re_internal_names.sub(
            r'\b(run|invoke|execute|trigger)\s+a\s+quick\s+check',
            'a quick check', out, flags=_re_internal_names.IGNORECASE,
        )
    return out


def has_internal_name(text) -> bool:
    """快查 text 含工具名 / <TOOL_CALL> tag. 用于日志诊断."""
    if not text or not isinstance(text, str):
        return False
    return bool(
        _INTERNAL_TOOL_NAME_RE.search(text) or
        _INTERNAL_TOOL_CALL_TAG_RE.search(text)
    )


class _TTSEchoRing:
    _lock = threading.Lock()
    _entries = deque(maxlen=12)
    _window_seconds = 12.0
    _disabled_until = 0.0

    @staticmethod
    def _normalize(text: str) -> str:
        if not text:
            return ""
        import re as _re
        t = text.lower()
        t = _re.sub(r"[^a-z0-9\u4e00-\u9fa5\s]+", " ", t)
        t = _re.sub(r"\s+", " ", t).strip()
        return t

    @classmethod
    def register(cls, text: str):
        if not text:
            return
        norm = cls._normalize(text)
        if len(norm) < 4:
            return
        with cls._lock:
            cls._entries.append((time.time(), norm))

    @classmethod
    def is_echo(cls, text: str, threshold: int = 80) -> bool:
        """检查 ASR 转录文本是否与最近 Jarvis 输出高度相似（fuzzy ratio ≥ threshold）。
        threshold 取 80 是因为 ASR 会把 'Muting audio.' 听成 'muting audio,'
        这种标点/大小写差异 fuzz.ratio 在 85+，我们留一点冗余。

        [P0+18-a.8 / 2026-05-15] 修 BUG #6: ASR 把 Jarvis 末尾 "It's"/"if"/"or" 等短词当用户输入。
        对 ≤4 字符 ASR 文本走宽容判定：最近 12s Jarvis 答语含此短词（作为独立 token）→ 视 echo。
        这条 fallback 主要救：ASR 把 Jarvis 余音切碎成单字/2-3 字母 token 的场景。"""
        if not text:
            return False
        with cls._lock:
            if time.time() < cls._disabled_until:
                return False
            if not cls._entries:
                return False
            now = time.time()
            cls._entries = deque(
                [(ts, t) for ts, t in cls._entries if now - ts <= cls._window_seconds],
                maxlen=cls._entries.maxlen,
            )
            if not cls._entries:
                return False
        norm = cls._normalize(text)
        # [P0+18-a.8] 短词宽容路径：先短路 (≤4 字符 ASR token 直接查最近 jarvis 答语含不含)
        # 这条优先于 fuzzywuzzy 的 ratio 路径，因为 ratio 在文本极短时容易抖动。
        # 🩹 [β.2.7.7 / 2026-05-17] 扩宽容到"短句 + 含 Jarvis 高频词" (治 "What's sir" 漏过)
        # Sir 实测: Jarvis 末尾 "...Sir." 被 ASR 切碎补全成 "What's sir" 10 char/3 token
        # 超出 ≤4 路径，但内容明显是 jarvis 余音。
        _is_short = (0 < len(norm) <= 4)
        _is_short_jarvis_jargon = False
        if not _is_short:
            _tokens = norm.split() if norm else []
            _JARVIS_HIGH_FREQ = {
                'sir', 'jarvis', 'yes', 'of', 'course', 'understood', 'shall',
                'monitor', 'remind', 'noted', 'apologies', 'ill', 'will',
                'precisely', 'indeed', 'quite', 'absolutely', 'certainly',
                'as', 'you', 'wish', 'right', 'away',
            }
            if (len(norm) <= 18 and len(_tokens) <= 4 and
                    any(t in _JARVIS_HIGH_FREQ for t in _tokens)):
                _is_short_jarvis_jargon = True

        if _is_short or _is_short_jarvis_jargon:
            with cls._lock:
                snapshot_short = list(cls._entries)
            import re as _re_short
            # norm 是小写、去标点；split 出独立 token；任一 token 出现在最近 jarvis 答语 token 集合里即 echo
            asr_tokens = set(_re_short.findall(r'[a-z0-9\u4e00-\u9fa5]+', norm))
            if asr_tokens:
                for _ts, candidate in snapshot_short:
                    if not candidate:
                        continue
                    cand_tokens = set(_re_short.findall(r'[a-z0-9\u4e00-\u9fa5]+', candidate))
                    # 任一 ASR token 是 Jarvis 答语 token → 极有可能是切碎的 echo
                    if asr_tokens & cand_tokens:
                        return True
            # 短词没匹到任何 Jarvis 答语 → 走原 (len < 4) 拒判，继续保留 False
            return False
        try:
            from fuzzywuzzy import fuzz as _fuzz
        except Exception:
            return False
        with cls._lock:
            snapshot = list(cls._entries)
        for _ts, candidate in snapshot:
            if not candidate:
                continue
            # 完全包含：candidate 本身在 ASR 文本里 / ASR 文本在 candidate 里
            if candidate in norm or norm in candidate:
                return True
            ratio = _fuzz.ratio(candidate, norm)
            partial = _fuzz.partial_ratio(candidate, norm)
            if ratio >= threshold or partial >= max(85, threshold + 5):
                return True
        return False

    @classmethod
    def suppress(cls, seconds: float):
        """对回声防御短暂禁用（用于真实用户开始讲话之类的场景，避免误伤）。"""
        with cls._lock:
            cls._disabled_until = time.time() + max(0.0, seconds)

    @classmethod
    def clear(cls):
        with cls._lock:
            cls._entries.clear()
            cls._disabled_until = 0.0


def register_jarvis_tts(text: str):
    """Jarvis 输出 TTS 时调用，把句子写进回声指纹环。"""
    _TTSEchoRing.register(text)


def is_recent_jarvis_echo(text: str, threshold: int = 80) -> bool:
    """ASR 拿到一段文本后调用：是否高度疑似 Jarvis 自己最近说过的话。"""
    return _TTSEchoRing.is_echo(text, threshold=threshold)


def clear_jarvis_tts_ring():
    """重启 / 急停时清空回声指纹环。"""
    _TTSEchoRing.clear()


# ============================================================
# 📡 ConversationEventBus —— R6 对话事件总线
# ------------------------------------------------------------
# 替代散落的 self.pending_event / self.pending_commitment / soft_focus
# /_last_local_emotion / _help_refusal_history / humor_memory 等独立字段。
#
# 设计原则：
# - 全局单例（每个 CentralNerve 持有一个实例引用），但状态本地化
# - thread-safe（多发布者、单读者场景）
# - 每条事件带 type / description / timestamp / ttl / source / metadata
# - 过期事件自动失效（不爆炸，但 to_prompt_block 不再渲染）
# - 不阻塞、不引入额外延迟（publish/read 都是 in-memory + 锁 几微秒）
#
# 业务价值：
# - B1 修复：gatekeeper 写 bus，prompt assembler 读 bus → 不再"一轮载具"丢事件
# - 老友感物理基础：把"3 分钟前 Sir 提过累"这种事实让 LLM 物理引用而非编造
# ============================================================
# [β.5.0-A / 2026-05-19] 全局 event_bus 单例 (主脑只 1 个 instance, 不需多 bus)
# 远端模块 (PhysicalEnvProbe / sentinels / OfferGuard / ProactiveCare) 通过
# get_event_bus() 拿到 instance publish, 不需持有 self.jarvis ref.
_GLOBAL_EVENT_BUS = None


def get_event_bus():
    """[β.5.0-A] 返回全局注册的 event_bus instance, 没注册返 None.
    远端模块 publish 通用范式:
        from jarvis_utils import get_event_bus
        bus = get_event_bus()
        if bus:
            bus.publish(etype='...', description='...', source='...')
    """
    return _GLOBAL_EVENT_BUS


# ==========================================================================
# [β.5.1 / β.5.2] gate_mode helper (NudgeGate / OfferGuard / Conductor 复用)
# ==========================================================================
# 准则 6 行为弱耦合: sentinel 决策权可由 vocab 切档 (hard/soft/publish_only).
# vocab 在 memory_pool/gate_mode_vocab.json, Sir CLI scripts/gate_mode_dump.py 切.
# ==========================================================================

_GATE_MODE_CACHE = {}
_GATE_MODE_CACHE_T = 0.0
_GATE_MODE_CACHE_TTL_S = 5.0


def read_gate_mode(sentinel_name: str) -> str:
    """[β.5.1 / β.5.2] 读 memory_pool/gate_mode_vocab.json.current[sentinel_name].
    
    Returns:
        'hard' (default) | 'soft' | 'publish_only'
    Fail-safe:
        文件不存在 / JSON 格式坏 → 返 'hard' (兼容老路径).
    
    Cache:
        模块级 5s TTL cache 防 vocab JSON 高频读 (NudgeGate.can_speak 每 nudge 一次).

    🩹 [β.5.16-fix-vocab / 2026-05-19] BUG-F (β.5 头号边界): jarvis_utils.py 只 alias
    `import os as _os_for_log` 等, 没裸 `import os`/`import json`. 本函数体内用
    裸 `os.` / `json.` 会 NameError, 走 silent except 返 'hard'. β.5.x 整个
    publish_only 重构从未真生效 (所有 sentinel 一直跑 hard). 修: 本函数体内本地
    `import os, json` 显式拿到名字. Sir log 22:23 line 419 `mode=hard` 实锤.
    """
    import os as _os_local
    import json as _json_local
    global _GATE_MODE_CACHE, _GATE_MODE_CACHE_T
    now = time.time()
    if now - _GATE_MODE_CACHE_T < _GATE_MODE_CACHE_TTL_S and _GATE_MODE_CACHE:
        return _GATE_MODE_CACHE.get(sentinel_name, 'hard')
    # 重读
    try:
        root = _os_local.path.dirname(_os_local.path.abspath(__file__))
        path = _os_local.path.join(root, 'memory_pool', 'gate_mode_vocab.json')
        if not _os_local.path.exists(path):
            return 'hard'
        with open(path, 'r', encoding='utf-8') as f:
            data = _json_local.load(f)
        current = data.get('current', {}) if isinstance(data, dict) else {}
        _GATE_MODE_CACHE = current
        _GATE_MODE_CACHE_T = now
        return current.get(sentinel_name, 'hard')
    except Exception:
        return 'hard'


def reset_gate_mode_cache() -> None:
    """[β.5.1 testcase 用] 强制清 cache 让下次重读 vocab."""
    global _GATE_MODE_CACHE, _GATE_MODE_CACHE_T
    _GATE_MODE_CACHE = {}
    _GATE_MODE_CACHE_T = 0.0


class ConversationEventBus:
    """对话事件总线。一律 in-memory + 线程安全。
    publish 写入是 O(1)，read O(n) 其中 n 默认 ≤ 50。
    """

    # 类型默认 TTL（秒）——可在 publish 时覆盖
    DEFAULT_TTL = {
        'conversation_event': 240,         # 突破/回调/释压/分享
        'commitment_detected': 600,        # 用户自承诺
        'commitment_overdue': 900,
        'proactive_nudge': 360,            # SmartNudge / Conductor 刚发声
        'emotion_shift': 240,              # 情绪检测变化
        'help_refused': 1800,              # 用户刚拒绝过 offer_help
        'soft_focus_active': 120,          # offer_help / commitment 焦点锁中
        'manual_standby': 240,             # 用户手动急停
        'tool_executed': 180,              # 工具刚跑完
        'tool_chain_circuit_broken': 300,  # [R7-α/B5] 工具链熔断，让下一轮看见
        'reminder_fired': 300,
        'persona_note': 600,               # CorrectionLoop / StyleAdjust 信号
        # [P0-4 / 2026-05-15] Integrity Check 抓到 Jarvis 嘴上说"做了"但实际没调工具
        # → 让 prompt assembler / Conductor / SmartNudge 下一轮立刻看到，
        # 避免"幻觉 + 又催"叠加的尴尬。300s 足够覆盖典型 follow-up 窗口。
        'hallucination_detected': 300,
        'sleep_intent_declared': 1800,     # [v5.1] Sir 表态 X 时间内睡 → 静默催睡 nudge
        # [β.5.0-A / 2026-05-19] Shared World Model 新增 etype:
        'sensor_change': 120,              # PhysicalEnvProbe window/category/idle 变化
        'gate_advice': 240,                # NudgeGate / OfferGuard advise (soft mode)
        'concern_active': 360,             # ProactiveCare top_concern publish
        'afk_return': 300,                 # ReturnSentinel _on_return raw signal
        'self_critique': 600,              # MetaSelfReflector 自评结果
        'utterance_appended': 60,          # _append_stm 末尾新对话 (短 TTL, 仅作 trigger)
        # [β.5.40 / 2026-05-20] Sir 方向 A.1/E.1 新 etype:
        'ambient_state': 180,              # ambient_audio sensor (laughter/sigh/...)
        'nudge_window_advice': 3600,       # CompanionRhythm 当前 hour receptive 建议
    }
    # [β.5.0-A / 2026-05-19] Shared World Model 显著性默认表 (准则 6.5):
    # salience 是数据耦合维度, 给主脑判该事件多重要的 signal. publish 时可覆盖.
    # 命名约定: 0.9 = 必看 (commitment overdue / hallucination), 0.7 = 重要,
    # 0.5 = 一般, 0.3 = 背景信号, 0.1 = 极弱.
    DEFAULT_SALIENCE = {
        'commitment_overdue': 0.95,
        'hallucination_detected': 0.92,
        'manual_standby': 0.90,
        'sleep_intent_declared': 0.85,
        'commitment_detected': 0.80,
        'tool_chain_circuit_broken': 0.78,
        'soft_focus_active': 0.70,
        'concern_active': 0.65,
        'help_refused': 0.62,
        'reminder_fired': 0.60,
        'self_critique': 0.60,
        'gate_advice': 0.55,
        'afk_return': 0.55,
        'conversation_event': 0.55,
        'tool_executed': 0.50,
        'proactive_nudge': 0.50,
        'emotion_shift': 0.45,
        'persona_note': 0.40,
        'sensor_change': 0.30,
        'utterance_appended': 0.20,
        # [β.5.40 / 2026-05-20] Sir 方向 A.1/E.1 新:
        'ambient_state': 0.45,             # 背景听感 (默认低, 但场景特殊 publish 时可调高)
        'nudge_window_advice': 0.35,       # 时段建议 (调 ProactiveCare publish 时 score 低 → 0.55)
    }

    def __init__(self, max_events: int = 60):
        self._lock = threading.Lock()
        self._events = deque(maxlen=max_events)
        # 同类型短时间内重复 publish 的去重 fingerprint -> last_ts
        self._dedupe = {}
        self._dedupe_window = 8.0

    def publish(self, etype: str, description: str,
                ttl: float = None, source: str = 'unknown',
                metadata: dict = None, salience: float = None) -> bool:
        """投递一条事件。返回 True 表示已写入；False 表示被去重抑制。
        - description 自动裁到 300 字
        - 同 (etype, description[:60]) 8 秒内重复发布会被去重抑制
        - salience [0.0, 1.0]: 此事件的显著性 (越高越优先进 top_n).
          默认 None → 从 DEFAULT_SALIENCE[etype] 取, 找不到则 0.5.
          准则 6.5: salience 是数据耦合维度, 给主脑判该事件多重要的 signal.
        """
        if not etype or not description:
            return False
        desc = str(description).strip()[:300]
        if not desc:
            return False
        if ttl is None:
            ttl = self.DEFAULT_TTL.get(etype, 180)
        if salience is None:
            salience = self.DEFAULT_SALIENCE.get(etype, 0.5)
        try:
            salience = max(0.0, min(1.0, float(salience)))
        except (TypeError, ValueError):
            salience = 0.5

        now = time.time()
        fp = (etype, desc[:60])
        with self._lock:
            last_ts = self._dedupe.get(fp, 0.0)
            if now - last_ts < self._dedupe_window:
                return False
            self._dedupe[fp] = now
            # 顺手清掉过期 dedupe（避免 dict 长大）
            if len(self._dedupe) > 200:
                threshold = now - self._dedupe_window * 4
                self._dedupe = {k: v for k, v in self._dedupe.items() if v >= threshold}

            self._events.append({
                'type': etype,
                'description': desc,
                'timestamp': now,
                'ttl': float(ttl),
                'source': source or 'unknown',
                'metadata': dict(metadata) if metadata else {},
                'salience': salience,
            })
        return True

    def recent_events(self, within_seconds: float = None,
                      types: set = None) -> list:
        """回看最近还有效的事件（默认全部）。可按 within_seconds 或 types 过滤。"""
        now = time.time()
        out = []
        with self._lock:
            for e in self._events:
                age = now - e['timestamp']
                if age > e['ttl']:
                    continue
                if within_seconds is not None and age > within_seconds:
                    continue
                if types is not None and e['type'] not in types:
                    continue
                out.append(dict(e))  # 拷贝避免外部改
        return out

    def has_type(self, etype: str, within_seconds: float = None) -> bool:
        """是否近期有某类型事件（用于 NudgeGate / focus_lock 等快速判断）。"""
        return bool(self.recent_events(within_seconds=within_seconds, types={etype}))

    def to_prompt_block(self, max_chars: int = 600,
                        within_seconds: float = 360.0,
                        title: str = "=== CONVERSATION STATE ===") -> str:
        """渲染给 LLM 看的事件块。优先级：类型权重 + 时间近度。
        留意：默认 max_chars=600，足够 5-8 条事件而不会撑爆 prompt 预算。
        """
        events = self.recent_events(within_seconds=within_seconds)
        if not events:
            return ""

        type_priority = {
            'commitment_overdue': 10,
            'manual_standby': 9,
            'soft_focus_active': 8,
            'hallucination_detected': 8,   # [P0-4] 主脑幻觉 → 必须下一轮看到并诚实纠正
            'commitment_detected': 7,
            'tool_chain_circuit_broken': 7,  # [R7-α/B5] 上一轮熔断要被下一轮看见
            'sleep_intent_declared': 7,    # [v5.1] Sir 睡眠表态 → 影响 nudge 抑制
            'conversation_event': 6,
            'help_refused': 5,
            'reminder_fired': 5,
            'emotion_shift': 4,
            'proactive_nudge': 3,
            'tool_executed': 3,
            'persona_note': 2,
        }
        events.sort(key=lambda e: (type_priority.get(e['type'], 1), -e['timestamp']), reverse=True)

        now = time.time()
        lines = [title]
        for e in events:
            age = int(now - e['timestamp'])
            if age < 60:
                age_str = f"{age}s ago"
            elif age < 3600:
                age_str = f"{age // 60}min ago"
            else:
                age_str = f"{age // 3600}h ago"
            src = e.get('source', '') or ''
            src_tag = f" [{src}]" if src and src != 'unknown' else ''
            lines.append(f"- ({age_str}) {e['type']}{src_tag}: {e['description']}")

        result = "\n".join(lines)
        if len(result) > max_chars:
            # 保留 title + 头部高优先级事件
            result = result[:max_chars - 4].rstrip() + " …"
        return result

    def clear(self):
        with self._lock:
            self._events.clear()
            self._dedupe.clear()

    def snapshot(self) -> list:
        """供调试 / 测试：返回当前完整事件列表的拷贝。"""
        with self._lock:
            return [dict(e) for e in self._events]

    # ----------------------------------------------------------------------
    # [β.5.0-A / 2026-05-19] Shared World Model APIs
    # ----------------------------------------------------------------------
    def top_n(self, n: int = 12, types: set = None,
              within_seconds: float = None,
              salience_floor: float = 0.0) -> list:
        """按 (salience × recency) 综合分排序, 返回最重要的 n 条事件.

        Args:
            n: 取多少条 (默认 12).
            types: 仅取这些 etype (None = 全部).
            within_seconds: 仅取最近 X 秒内 (None = 用 TTL).
            salience_floor: 仅取 salience >= floor 的 (0.0 = 全部).

        Returns:
            List[dict], 含 score 字段排序. 已 expired 的不返回.

        准则 6 evidence-only: 给主脑 raw signal pool, 不教如何反应.
        """
        events = self.recent_events(within_seconds=within_seconds, types=types)
        if not events:
            return []
        now = time.time()
        # recency: e^(-age/halflife), halflife = 180s
        # 综合 = salience * 0.7 + recency * 0.3
        scored = []
        for e in events:
            sal = e.get('salience', 0.5)
            if sal < salience_floor:
                continue
            age = max(0, now - e['timestamp'])
            recency = 2.71828 ** (-age / 180.0)  # halflife 3min
            score = sal * 0.7 + recency * 0.3
            e_copy = dict(e)
            e_copy['score'] = round(score, 3)
            e_copy['_age_s'] = int(age)
            scored.append(e_copy)
        scored.sort(key=lambda x: x['score'], reverse=True)
        return scored[:n]

    @classmethod
    def register_global(cls, bus_instance):
        """[β.5.0-A] 注册全局 event_bus 让无 self.jarvis 引用的远端模块也能 publish.
        CentralNerve.__init__ 创建 bus 后, 调 ConversationEventBus.register_global(self.event_bus).
        """
        global _GLOBAL_EVENT_BUS
        _GLOBAL_EVENT_BUS = bus_instance

    def to_swm_block(self, n: int = 12, max_chars: int = 800,
                     title: str = "=== [SHARED WORLD MODEL — Sir 准则 6 evidence] ===",
                     types: set = None,
                     salience_floor: float = 0.3) -> str:
        """渲染 SWM 给主脑 prompt 看. 按 top_n 排, 显示 salience + age + source + desc.

        给主脑富 evidence 自决, 不教具体反应方式.
        """
        top = self.top_n(n=n, types=types, salience_floor=salience_floor)
        if not top:
            return ""
        lines = [title]
        for e in top:
            age_s = e['_age_s']
            if age_s < 60:
                age_str = f"{age_s}s"
            elif age_s < 3600:
                age_str = f"{age_s // 60}m"
            else:
                age_str = f"{age_s // 3600}h"
            sal = e.get('salience', 0.5)
            src = e.get('source', '') or 'unknown'
            src_tag = f"[{src}]" if src else ''
            lines.append(
                f"- (sal={sal:.2f}, age={age_str}) {e['type']} {src_tag}: {e['description']}"
            )
        result = "\n".join(lines)
        if len(result) > max_chars:
            result = result[:max_chars - 4].rstrip() + " …"
        return result


# ============================================================
# 🎯 [R7-α/AttentionContext] 注意力锚点快照
# ------------------------------------------------------------
# 问题：Sir 说"这里有什么问题"，cmd_queue 只收到字符串"这里有什么问题"，
# LLM 完全不知道"这里"是哪个窗口、哪段选区、哪个文件 —— 只能瞎猜或问
# "哪里？"。Sir 觉得 Jarvis 不懂自己看的东西。
#
# 方案：用户讲话当下抓拍一份"物理锚点快照"，附带在 prompt 里：
# - 前台窗口标题 + 进程 PID
# - 鼠标光标位置 + 屏幕尺寸
# - 最近 5s 的窗口切换历史
# - (后续 α3 WorkingMemoryFeed 补剪贴板新鲜度；R7-γ 补 IDE selection)
#
# 抓拍位置：VoiceListenThread emit text_ready 之前 → AttentionSlot.capture_now()
# 读取位置：JarvisWorker.run / CentralNerve._assemble_prompt → slot.latest()
# 共享方式：main 段创建一个 slot，注入到 voice_worker._attention_slot 和
# jarvis_worker._attention_slot，两边共用。
# ============================================================
def capture_attention_snapshot(window_history_provider=None) -> dict:
    """Windows-only 注意力快照抓拍。每个字段都用 try/except 防御，失败降级到 None。
    
    工程目标：单次调用 ≤ 10ms（不阻塞 VoiceListenThread 的 ASR 转译节奏）。
    
    window_history_provider: callable，返回 [{'time': ts, 'title': str}, ...] 列表的迭代器；
                              注入式避免循环依赖（PhysicalEnvironmentProbe 在 jarvis_nerve.py）。
    """
    snap = {
        'ts': time.time(),
        'window_title': None,
        'foreground_pid': None,
        'cursor_pos': None,
        'screen_size': None,
        'recent_windows_5s': [],
    }
    try:
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            try:
                title = win32gui.GetWindowText(hwnd) or None
                if title:
                    snap['window_title'] = title[:160]
            except Exception:
                pass
            try:
                import win32process
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                snap['foreground_pid'] = int(pid) if pid else None
            except Exception:
                pass
        try:
            snap['cursor_pos'] = win32gui.GetCursorPos()
        except Exception:
            pass
    except Exception:
        pass
    try:
        import ctypes
        u = ctypes.windll.user32
        snap['screen_size'] = (u.GetSystemMetrics(0), u.GetSystemMetrics(1))
    except Exception:
        pass
    if window_history_provider is not None:
        try:
            cutoff = time.time() - 5.0
            recent = []
            for entry in window_history_provider() or []:
                t = entry.get('time') if isinstance(entry, dict) else None
                title = entry.get('title') if isinstance(entry, dict) else None
                if t is not None and t >= cutoff and title:
                    recent.append(title[:80])
            snap['recent_windows_5s'] = recent[-5:]
        except Exception:
            pass
    return snap


def render_attention_block(snap: dict, max_chars: int = 400) -> str:
    """把 attention 快照渲染成给 LLM 看的简短 prompt 块。空 / 全 None 时返回空串。"""
    if not snap:
        return ""
    pieces = []
    wt = snap.get('window_title')
    if wt:
        pieces.append(f"window=\"{wt}\"")
    pid = snap.get('foreground_pid')
    if pid:
        pieces.append(f"pid={pid}")
    cp = snap.get('cursor_pos')
    ss = snap.get('screen_size')
    if cp and ss:
        x, y = cp
        sw, sh = ss
        # 用 5x5 网格给 LLM 一个粗略空间感知（左上 / 中央 / 右下…）
        col = ['左', '中左', '中', '中右', '右'][min(max(int(x * 5 / max(sw, 1)), 0), 4)]
        row = ['顶部', '上', '中', '下', '底部'][min(max(int(y * 5 / max(sh, 1)), 0), 4)]
        pieces.append(f"cursor=({x},{y}) [{row}{col}]")
    rwin = snap.get('recent_windows_5s') or []
    if len(rwin) >= 2:
        # 显示最近 2 个不同标题，去重 + 截断
        seen = []
        for t in reversed(rwin):
            if t and t not in seen:
                seen.append(t)
            if len(seen) >= 3:
                break
        if seen:
            pieces.append("recent_switches=[" + " ← ".join(s[:50] for s in seen) + "]")
    if not pieces:
        return ""
    body = " | ".join(pieces)
    if len(body) > max_chars:
        body = body[:max_chars - 1] + "…"
    return f"=== ATTENTION (where Sir was looking when he spoke) ===\n{body}"


class AttentionSlot:
    """单条最近 attention 快照槽。线程安全。
    
    VoiceListenThread 在 emit text_ready 之前调 capture_now()；
    JarvisWorker.run 调 latest(max_age=5.0) 拿快照注入 prompt。
    """

    def __init__(self, window_history_provider=None, max_age_seconds: float = 5.0):
        self._lock = threading.Lock()
        self._snap = None
        self._ts = 0.0
        self._window_history_provider = window_history_provider
        self._default_max_age = float(max_age_seconds)

    def set_window_history_provider(self, provider):
        with self._lock:
            self._window_history_provider = provider

    def capture_now(self) -> dict:
        """主线程或子线程都能调；返回当前抓拍。"""
        snap = capture_attention_snapshot(self._window_history_provider)
        with self._lock:
            self._snap = snap
            self._ts = time.time()
        return snap

    def latest(self, max_age_seconds: float = None) -> dict:
        """超时返回空 dict（避免把陈旧快照当成"现在的 attention"）。"""
        if max_age_seconds is None:
            max_age_seconds = self._default_max_age
        with self._lock:
            if self._snap is None:
                return {}
            if time.time() - self._ts > max_age_seconds:
                return {}
            return dict(self._snap)

    def clear(self):
        with self._lock:
            self._snap = None
            self._ts = 0.0


# ============================================================
# 🧠 [R7-α/WorkingMemoryFeed] 会话级环境事件流
# ------------------------------------------------------------
# 问题：event_bus 是对话事件流（突破/承诺/焦点锁/情绪），TTL 短（120-600s）；
# 工作台环境事件（剪贴板复制、文件保存、刚跑过的终端命令）是另一类信号 ——
# - 频率低（每分钟 1-5 条）
# - 半衰期长（30 分钟内都有"我刚刚做过什么"的价值）
# - 用户问"我刚复制的是什么"/"我刚跑的那个命令"时希望能直接答上来
#
# 方案：单独一条事件流，专门承接这些"会话窗口"信号。
# - 三个数据源：剪贴板变化（ClipboardWatcher）/ PowerShell history（PSHistoryWatcher）/
#   文件保存（FileWatchersGroup 留作 hook，watchdog 集成下迭代做）
# - TTL 30 分钟，max_events 80
# - 提供 to_prompt_block() 渲染给 LLM 看
#
# 接入路径：CentralNerve 创建一个 feed 实例 + 启动两个 watcher 线程；
# _assemble_prompt 注入 prompt 块。
# ============================================================
class WorkingMemoryFeed:
    """会话级环境事件流。线程安全。
    
    事件类型（推荐子集，外部也可以塞自定义类型）：
    - 'clipboard_copy'   : 剪贴板内容变化，payload = {'preview': str, 'length': int}
    - 'terminal_cmd'     : PowerShell 历史新增，payload = {'cmd': str}
    - 'file_saved'       : 文件保存（watchdog 后续做），payload = {'path': str, 'ext': str}
    - 'window_focus'     : 长停留窗口切换（PhysicalEnvironmentProbe 可对接）
    """

    DEFAULT_TTL = 1800.0  # 30 分钟

    def __init__(self, max_events: int = 80, ttl_seconds: float = None):
        self._lock = threading.Lock()
        self._events = deque(maxlen=max_events)
        self._ttl = float(ttl_seconds if ttl_seconds is not None else self.DEFAULT_TTL)

    def push(self, etype: str, payload: dict = None, ts: float = None) -> bool:
        """投递一条会话级环境事件。返回 True 表示已写入。
        - payload 自动浅拷贝
        - ts 默认 time.time()
        """
        if not etype:
            return False
        ts = float(ts) if ts is not None else time.time()
        ev = {
            'type': str(etype),
            'ts': ts,
            'payload': dict(payload) if payload else {},
        }
        with self._lock:
            self._events.append(ev)
        return True

    def recent(self, within_seconds: float = None, types: set = None) -> list:
        """返回未过期的事件（按时间升序）。within_seconds 可比 TTL 短。"""
        now = time.time()
        cutoff = max(0.0, now - (within_seconds if within_seconds is not None else self._ttl))
        out = []
        with self._lock:
            for e in self._events:
                if e['ts'] < cutoff:
                    continue
                if types is not None and e['type'] not in types:
                    continue
                out.append(dict(e))
        out.sort(key=lambda e: e['ts'])
        return out

    def to_prompt_block(self, max_chars: int = 500,
                        within_seconds: float = None,
                        title: str = "=== WORKING MEMORY (recent environment) ===") -> str:
        """渲染给 LLM 看的环境事件块。
        - 默认只看最近 30 分钟，最多 8 条最近事件
        - 按时间从近到远排列；剪贴板预览裁到 100 字
        """
        events = self.recent(within_seconds=within_seconds)
        if not events:
            return ""
        events.sort(key=lambda e: e['ts'], reverse=True)
        events = events[:8]
        now = time.time()
        lines = [title]
        for e in events:
            age = int(now - e['ts'])
            if age < 60:
                age_str = f"{age}s ago"
            elif age < 3600:
                age_str = f"{age // 60}min ago"
            else:
                age_str = f"{age // 3600}h ago"
            t = e['type']
            p = e['payload'] or {}
            if t == 'clipboard_copy':
                preview = (p.get('preview') or '').replace('\n', ' ')[:100]
                length = p.get('length', 0)
                lines.append(f"- ({age_str}) clipboard_copy ({length}c): \"{preview}\"")
            elif t == 'terminal_cmd':
                cmd = (p.get('cmd') or '').replace('\n', ' ')[:120]
                lines.append(f"- ({age_str}) terminal_cmd: `{cmd}`")
            elif t == 'file_saved':
                path = p.get('path', '?')
                lines.append(f"- ({age_str}) file_saved: {path}")
            elif t == 'window_focus':
                title2 = p.get('title', '?')
                lines.append(f"- ({age_str}) window_focus: {title2[:80]}")
            else:
                # 其他自定义类型：直接 stringify
                lines.append(f"- ({age_str}) {t}: {str(p)[:100]}")
        result = "\n".join(lines)
        if len(result) > max_chars:
            result = result[:max_chars - 4].rstrip() + " …"
        return result

    def clear(self):
        with self._lock:
            self._events.clear()

    def snapshot(self) -> list:
        with self._lock:
            return [dict(e) for e in self._events]


class ClipboardWatcher(threading.Thread):
    """轮询 Windows 剪贴板 sequence number 变化，变化时往 feed 推 clipboard_copy 事件。
    
    GetClipboardSequenceNumber 是 O(1)；只在变化时 OpenClipboard + GetClipboardData，避免霸占剪贴板。
    
    工程目标：≥ 500ms 轮询间隔，单次开销 < 5ms。
    """

    POLL_INTERVAL = 0.6  # 秒
    MIN_PREVIEW_LEN = 1
    MAX_PREVIEW_LEN = 240

    def __init__(self, feed: 'WorkingMemoryFeed', skip_if_match_fn=None):
        super().__init__(daemon=True)
        self.feed = feed
        self._stop_event = threading.Event()
        self._last_seq = None
        # 可选的过滤函数：返回 True 表示这条剪贴板内容不投递（比如 Jarvis 自己刚塞进去的）
        self._skip_if_match_fn = skip_if_match_fn

    def stop(self):
        self._stop_event.set()

    def run(self):
        try:
            import ctypes
            user32 = ctypes.windll.user32
        except Exception:
            return
        while not self._stop_event.is_set():
            try:
                seq = user32.GetClipboardSequenceNumber()
                if self._last_seq is None:
                    self._last_seq = seq
                elif seq != self._last_seq:
                    self._last_seq = seq
                    text = self._read_clipboard_text()
                    if text is not None and len(text) >= self.MIN_PREVIEW_LEN:
                        if self._skip_if_match_fn is not None:
                            try:
                                if self._skip_if_match_fn(text):
                                    pass  # 跳过
                                else:
                                    self._push(text)
                            except Exception:
                                self._push(text)
                        else:
                            self._push(text)
            except Exception:
                pass
            self._stop_event.wait(self.POLL_INTERVAL)

    def _push(self, text: str):
        preview = text[:self.MAX_PREVIEW_LEN]
        self.feed.push('clipboard_copy', {
            'preview': preview,
            'length': len(text),
        })

    @staticmethod
    def _read_clipboard_text():
        try:
            import win32clipboard
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                    data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                    return data if isinstance(data, str) else None
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            return None
        return None


class PSHistoryWatcher(threading.Thread):
    """监听 PowerShell PSReadLine 历史文件，新增行时往 feed 推 terminal_cmd 事件。
    
    位置：%USERPROFILE%\\AppData\\Roaming\\Microsoft\\Windows\\PowerShell\\PSReadLine\\ConsoleHost_history.txt
    
    采用 mtime + 文件末尾 N 行差分。无 PSReadLine 时静默退出。
    """

    POLL_INTERVAL = 3.0  # 秒
    MAX_HISTORY_LINES = 200

    def __init__(self, feed: 'WorkingMemoryFeed', history_path: str = None):
        super().__init__(daemon=True)
        self.feed = feed
        self._stop_event = threading.Event()
        self._last_mtime = 0.0
        self._last_seen_lines = set()
        self._first_pass_done = False
        self._history_path = history_path or self._default_path()

    @staticmethod
    def _default_path() -> str:
        import os
        return os.path.expandvars(
            r"%USERPROFILE%\AppData\Roaming\Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt"
        )

    def stop(self):
        self._stop_event.set()

    def run(self):
        import os
        if not os.path.exists(self._history_path):
            return
        while not self._stop_event.is_set():
            try:
                mtime = os.path.getmtime(self._history_path)
                if mtime != self._last_mtime:
                    self._last_mtime = mtime
                    new_lines = self._read_tail_diff()
                    if not self._first_pass_done:
                        # 首次扫描只建索引，不推事件（避免一启动就把历史全推一遍）
                        self._first_pass_done = True
                    else:
                        for ln in new_lines:
                            self.feed.push('terminal_cmd', {'cmd': ln})
            except Exception:
                pass
            self._stop_event.wait(self.POLL_INTERVAL)

    def _read_tail_diff(self) -> list:
        try:
            with open(self._history_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            # 只关心最后 N 行（防止首次大文件爆内存）
            tail = lines[-self.MAX_HISTORY_LINES:]
            new = []
            for ln in tail:
                ln = ln.rstrip('\n').strip()
                if not ln:
                    continue
                # 去掉 PSReadLine 行首的 `\` 多行延续符号
                if ln in self._last_seen_lines:
                    continue
                self._last_seen_lines.add(ln)
                new.append(ln)
            # 控制 _last_seen_lines 不无限膨胀
            if len(self._last_seen_lines) > self.MAX_HISTORY_LINES * 4:
                self._last_seen_lines = set(list(self._last_seen_lines)[-self.MAX_HISTORY_LINES * 2:])
            return new
        except Exception:
            return []


# ============================================================
# 📋 [R7-α/PlanLedger] 任务计划账本（5 态状态机 + JSON 持久化）
# ------------------------------------------------------------
# 解决 C3（AgenticPlanner 写不出来）的底层数据结构：
# - "Sir 说一句 → Jarvis 列计划 → 暂停 → Sir 说 go → 跑 → 展示" 这套工作流
#   缺一个跨 stream_chat 调用的"任务态"载体
# - JarvisWorker.run 现在消费 cmd 即闭环，没地方放 "draft 完的计划"
#
# 设计：
# - 计划是一个有 ID 的对象，有 5 个状态（drafted / awaiting_go / running / paused / done / cancelled）
# - JSON 持久化到 memory_pool/plans.json，进程崩溃也能恢复 active plan
# - PlanLedger 提供 draft / set_state / advance_step / get_active / list_recent / to_prompt_block 接口
# - α4 阶段只做雏形：能创建、能查询、能持久化、能 publish 到 event_bus
# - R7-γ AgenticPlanner 在此基础上挂"draft 触发器 / go 触发器 / 自动 step 执行"
# ============================================================
import json as _stdlib_json
import os as _stdlib_os
import uuid as _stdlib_uuid


class PlanLedger:
    """计划账本：5 态状态机 + JSON 持久化 + event_bus 投递。
    
    状态机：
        drafted   → awaiting_go  (主脑列完计划)
        awaiting_go → running    (Sir 说 'go')
        running   → paused       (Sir 说 'pause' / 主脑卡住)
        paused    → running      (Sir 说 'continue')
        running   → done         (步骤全跑完)
        any       → cancelled    (Sir 说 'cancel')
    
    步骤数据结构：
        {'description': str, 'status': 'pending'/'running'/'done'/'failed', 'result': str|None}
    """

    STATE_DRAFTED = 'drafted'
    STATE_AWAITING_GO = 'awaiting_go'
    STATE_RUNNING = 'running'
    STATE_PAUSED = 'paused'
    STATE_DONE = 'done'
    STATE_CANCELLED = 'cancelled'

    ALL_STATES = (STATE_DRAFTED, STATE_AWAITING_GO, STATE_RUNNING,
                  STATE_PAUSED, STATE_DONE, STATE_CANCELLED)

    VALID_TRANSITIONS = {
        STATE_DRAFTED: {STATE_AWAITING_GO, STATE_CANCELLED},
        STATE_AWAITING_GO: {STATE_RUNNING, STATE_CANCELLED},
        STATE_RUNNING: {STATE_PAUSED, STATE_DONE, STATE_CANCELLED},
        STATE_PAUSED: {STATE_RUNNING, STATE_CANCELLED},
        STATE_DONE: set(),
        STATE_CANCELLED: set(),
    }

    DEFAULT_PERSIST_PATH = _stdlib_os.path.join('memory_pool', 'plans.json')

    def __init__(self, persist_path: str = None, event_bus=None,
                 max_active: int = 5, autosave: bool = True):
        self._lock = threading.RLock()
        self._plans = {}  # plan_id -> plan dict
        self._persist_path = persist_path or self.DEFAULT_PERSIST_PATH
        self._event_bus = event_bus
        self._max_active = max_active
        self._autosave = autosave

    def set_event_bus(self, bus):
        with self._lock:
            self._event_bus = bus

    # -------- 主接口 --------
    def draft(self, goal: str, steps: list = None, metadata: dict = None,
              auto_await_go: bool = True) -> str:
        """新建一个计划。auto_await_go=True 时立刻流转到 awaiting_go（典型用法）。
        返回 plan_id。"""
        if not goal:
            raise ValueError("plan goal cannot be empty")
        plan_id = self._generate_id()
        now = time.time()
        plan = {
            'plan_id': plan_id,
            'goal': str(goal)[:300],
            'state': self.STATE_DRAFTED,
            'steps': [self._normalize_step(s) for s in (steps or [])],
            'created_at': now,
            'last_state_change': now,
            'state_history': [(self.STATE_DRAFTED, 'draft', now)],
            'metadata': dict(metadata) if metadata else {},
        }
        with self._lock:
            self._plans[plan_id] = plan
            self._enforce_max_active()
        self._publish('plan_drafted', f"Plan drafted: {plan['goal'][:80]}",
                      {'plan_id': plan_id, 'state': self.STATE_DRAFTED})
        if auto_await_go:
            self.set_state(plan_id, self.STATE_AWAITING_GO, reason='auto_await_go')
        else:
            self._maybe_save()
        return plan_id

    def set_state(self, plan_id: str, new_state: str, reason: str = '') -> bool:
        """状态机跃迁。非法跃迁返回 False。"""
        if new_state not in self.ALL_STATES:
            return False
        with self._lock:
            plan = self._plans.get(plan_id)
            if not plan:
                return False
            old_state = plan['state']
            allowed = self.VALID_TRANSITIONS.get(old_state, set())
            if new_state not in allowed:
                return False
            plan['state'] = new_state
            now = time.time()
            plan['last_state_change'] = now
            plan['state_history'].append((new_state, reason or 'unspecified', now))
        self._publish(
            f'plan_state_{new_state}',
            f"Plan '{plan['goal'][:60]}': {old_state}→{new_state} ({reason})",
            {'plan_id': plan_id, 'state': new_state, 'reason': reason}
        )
        self._maybe_save()
        return True

    def advance_step(self, plan_id: str, step_index: int,
                     new_status: str = 'done', result: str = None) -> bool:
        """推进步骤状态。new_status: 'running' / 'done' / 'failed'。"""
        if new_status not in ('pending', 'running', 'done', 'failed'):
            return False
        with self._lock:
            plan = self._plans.get(plan_id)
            if not plan or step_index < 0 or step_index >= len(plan['steps']):
                return False
            step = plan['steps'][step_index]
            step['status'] = new_status
            if result is not None:
                step['result'] = str(result)[:400]
            plan['last_state_change'] = time.time()
        self._maybe_save()
        return True

    def get(self, plan_id: str) -> dict:
        """返回拷贝避免外部改。"""
        with self._lock:
            plan = self._plans.get(plan_id)
            return self._copy_plan(plan) if plan else None

    def get_active(self) -> list:
        """返回所有 active（drafted/awaiting_go/running/paused）的计划，按创建时间近 → 远。"""
        active_states = {self.STATE_DRAFTED, self.STATE_AWAITING_GO,
                         self.STATE_RUNNING, self.STATE_PAUSED}
        with self._lock:
            actives = [self._copy_plan(p) for p in self._plans.values()
                       if p['state'] in active_states]
        actives.sort(key=lambda p: p['created_at'], reverse=True)
        return actives

    def list_recent(self, n: int = 5) -> list:
        with self._lock:
            plans = [self._copy_plan(p) for p in self._plans.values()]
        plans.sort(key=lambda p: p['created_at'], reverse=True)
        return plans[:n]

    def cancel_all(self, reason: str = 'cancel_all'):
        """急停场景用：把所有 active 计划一刀切到 cancelled。"""
        cancelled = []
        with self._lock:
            for pid, plan in self._plans.items():
                if plan['state'] in self.VALID_TRANSITIONS:
                    if self.STATE_CANCELLED in self.VALID_TRANSITIONS.get(plan['state'], set()):
                        plan['state'] = self.STATE_CANCELLED
                        plan['last_state_change'] = time.time()
                        plan['state_history'].append((self.STATE_CANCELLED, reason, time.time()))
                        cancelled.append(pid)
        for pid in cancelled:
            self._publish('plan_state_cancelled',
                          f"Plan {pid[:8]} cancelled ({reason})",
                          {'plan_id': pid, 'reason': reason})
        self._maybe_save()
        return cancelled

    def to_prompt_block(self, max_chars: int = 900,
                        title: str = "=== ACTIVE PLAN ===") -> str:
        """渲染给 LLM 看的 active plan 块。无 active plan 时返回空串。

        [轴3-L3.2 + L3.3 / 2026-05-15] 加强版：
          - paused 状态额外渲染 "(paused: <reason>)" + 失败信息 + 危险信息
          - step 渲染 skill 名（让主脑知道用了哪个工具）
          - 失败 step 渲染 result/last_error 摘要
          - done step 渲染 result 摘要（给主脑反推下一步用）
        """
        actives = self.get_active()
        if not actives:
            return ""
        lines = [title]
        for p in actives[:2]:  # 最多展示 2 个 active plan
            state = p['state']
            meta = p.get('metadata') or {}
            tag_bits = []
            # paused 子原因
            if state == self.STATE_PAUSED:
                if meta.get('paused_for_dangerous_confirm'):
                    ds = meta.get('dangerous_skills') or []
                    tag_bits.append(f"paused: dangerous_confirm needed [{', '.join(ds[:5])}]")
                elif meta.get('paused_for_clarification'):
                    fidx = meta.get('failed_step_idx', '?')
                    ferr = (meta.get('failed_step_error') or '')[:120]
                    tag_bits.append(f"paused: step {int(fidx)+1 if isinstance(fidx, int) else fidx} failed → '{ferr}'")
                else:
                    tag_bits.append("paused")
            # awaiting_go 提示
            if state == self.STATE_AWAITING_GO:
                tag_bits.append("awaiting Sir's 'go'")
            head = f"[{state}] {p['goal']} (id={p['plan_id'][:8]})"
            if tag_bits:
                head += "  // " + " | ".join(tag_bits)
            lines.append(head)
            for i, s in enumerate(p['steps']):
                marker = {
                    'pending': '○', 'running': '◐',
                    'done': '✓', 'failed': '✗',
                }.get(s.get('status', 'pending'), '?')
                desc = s.get('description', '')[:100]
                skill = s.get('skill')
                line = f"  {marker} {i+1}. {desc}"
                if skill:
                    line += f"  [skill={skill}]"
                # 已 done / failed 的 step 附带 result（给主脑做反推）
                status = s.get('status', 'pending')
                if status in ('done', 'failed') and s.get('result'):
                    res_brief = str(s.get('result'))[:80]
                    line += f"  → {res_brief}"
                if status == 'failed' and s.get('last_error'):
                    err_brief = str(s.get('last_error'))[:80]
                    if err_brief and err_brief not in (s.get('result') or ''):
                        line += f"  err={err_brief}"
                lines.append(line)
        result = "\n".join(lines)
        if len(result) > max_chars:
            result = result[:max_chars - 4].rstrip() + " …"
        return result

    # -------- 持久化 --------
    def save(self, path: str = None) -> bool:
        path = path or self._persist_path
        try:
            with self._lock:
                _stdlib_os.makedirs(_stdlib_os.path.dirname(path), exist_ok=True)
                # 把 state_history 里的 tuple 转 list 便于 JSON
                serializable = {}
                for pid, plan in self._plans.items():
                    p = dict(plan)
                    p['state_history'] = [list(item) for item in p.get('state_history', [])]
                    serializable[pid] = p
            with open(path, 'w', encoding='utf-8') as f:
                _stdlib_json.dump(serializable, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def load(self, path: str = None) -> bool:
        path = path or self._persist_path
        if not _stdlib_os.path.exists(path):
            return False
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = _stdlib_json.load(f)
            with self._lock:
                self._plans.clear()
                for pid, plan in data.items():
                    plan['state_history'] = [tuple(item) for item in plan.get('state_history', [])]
                    self._plans[pid] = plan
            return True
        except Exception:
            return False

    # -------- 内部 --------
    @staticmethod
    def _generate_id() -> str:
        return _stdlib_uuid.uuid4().hex[:16]

    @staticmethod
    def _normalize_step(step) -> dict:
        if isinstance(step, str):
            return {'description': step[:200], 'status': 'pending', 'result': None,
                    'skill': None, 'args': {}, 'retry_count': 0, 'last_error': None}
        if isinstance(step, dict):
            raw_args = step.get('args')
            if not isinstance(raw_args, dict):
                raw_args = {}
            return {
                'description': str(step.get('description', ''))[:200],
                'status': step.get('status', 'pending') if step.get('status') in
                          ('pending', 'running', 'done', 'failed') else 'pending',
                'result': step.get('result'),
                # [轴3-L3.2 / 2026-05-15] PromiseExecutor 用：skill 名 + 调用参数 + 重试计数
                'skill': step.get('skill') if step.get('skill') else None,
                'args': raw_args,
                'retry_count': int(step.get('retry_count') or 0),
                'last_error': step.get('last_error'),
            }
        return {'description': str(step)[:200], 'status': 'pending', 'result': None,
                'skill': None, 'args': {}, 'retry_count': 0, 'last_error': None}

    @staticmethod
    def _copy_plan(plan):
        if plan is None:
            return None
        c = dict(plan)
        c['steps'] = [dict(s) for s in plan.get('steps', [])]
        c['state_history'] = list(plan.get('state_history', []))
        c['metadata'] = dict(plan.get('metadata', {}))
        return c

    def _enforce_max_active(self):
        """超过 max_active 的最旧 active 计划自动 cancelled，防止账本无限膨胀。"""
        active_states = {self.STATE_DRAFTED, self.STATE_AWAITING_GO,
                         self.STATE_RUNNING, self.STATE_PAUSED}
        actives = [(pid, p) for pid, p in self._plans.items() if p['state'] in active_states]
        actives.sort(key=lambda x: x[1]['created_at'])
        while len(actives) > self._max_active:
            pid, p = actives.pop(0)
            p['state'] = self.STATE_CANCELLED
            p['last_state_change'] = time.time()
            p['state_history'].append((self.STATE_CANCELLED, 'max_active_exceeded', time.time()))

    def _publish(self, etype: str, desc: str, metadata: dict):
        try:
            if self._event_bus is not None:
                self._event_bus.publish(etype, desc, source='plan_ledger', metadata=metadata)
        except Exception:
            pass

    def _maybe_save(self):
        if self._autosave:
            self.save()


# ============================================================
# 🎚️ [R7-α/NudgeChannel] Nudge 通道分流
# ------------------------------------------------------------
# 解决 C7（静默存在档写不出来）+ E4（被动澄清）的底层抽象：
# 当前所有 nudge（SmartNudge / Conductor / CommitmentWatcher / Sleep）最后都走 audio_queue
# 出声 —— 但有些 nudge 适合静默：
# - "screen_tease" 趣味嘲讽：飘个字幕就够
# - "atmosphere" 氛围评论：完全不必出声
# - "I missed that, Sir." 被动澄清：弹个字幕，不抢话
# - "我已经备好方案了" 任务接管 brief：等 Sir 瞥到再说
#
# 三档通道：
# - VOICE        : 原行为，TTS 出声 + 字幕
# - SILENT_TEXT  : 字幕飘过 + STM 写入 + event_bus publish；不出声
# - VISUAL_PULSE : 呼吸灯短暂闪烁 (R7-β 接 BreathingLight)；不出声不挂字幕
# ============================================================
NUDGE_CHANNEL_VOICE = 'voice'
NUDGE_CHANNEL_SILENT_TEXT = 'silent_text'
NUDGE_CHANNEL_VISUAL_PULSE = 'visual_pulse'
NUDGE_CHANNELS = (NUDGE_CHANNEL_VOICE, NUDGE_CHANNEL_SILENT_TEXT, NUDGE_CHANNEL_VISUAL_PULSE)

# 默认 nudge 类型 → channel 映射。可被 SmartNudge / Conductor 覆盖。
# 设计原则：
# - 真正"需要 Sir 响应"的 → VOICE（commitment / late_night / offer_help / suggest_break）
# - 趣味性 / 氛围评论 → SILENT_TEXT（让人感觉 Jarvis 在但不烦）
# - 后台 brief / 任务接管准备好 → VISUAL_PULSE（金光等 Sir 瞥到）
DEFAULT_NUDGE_CHANNEL_MAP = {
    'offer_help': NUDGE_CHANNEL_VOICE,
    'commitment_check': NUDGE_CHANNEL_VOICE,
    'late_night': NUDGE_CHANNEL_VOICE,
    'suggest_break': NUDGE_CHANNEL_VOICE,
    'return_greeting': NUDGE_CHANNEL_VOICE,
    'context_switch_alert': NUDGE_CHANNEL_VOICE,
    # [P0-8 / 2026-05-15] Conductor 路径B 的 Check-in 独立通道（之前错映射成 return_greeting）
    # 走 VOICE 但拥有更短 soft_focus（45s）+ 受拒绝期/sleep_mode 严格约束
    'check_in': NUDGE_CHANNEL_VOICE,

    'screen_tease': NUDGE_CHANNEL_SILENT_TEXT,
    'atmosphere': NUDGE_CHANNEL_SILENT_TEXT,
    'afternoon': NUDGE_CHANNEL_SILENT_TEXT,
    'hydration': NUDGE_CHANNEL_SILENT_TEXT,
    'stretch': NUDGE_CHANNEL_SILENT_TEXT,
    'flow_end': NUDGE_CHANNEL_SILENT_TEXT,
    'dormant_project': NUDGE_CHANNEL_SILENT_TEXT,

    'background_brief': NUDGE_CHANNEL_VISUAL_PULSE,
    'task_handoff_ready': NUDGE_CHANNEL_VISUAL_PULSE,
}


def resolve_nudge_channel(nudge_type: str, override: str = None) -> str:
    """根据 nudge_type 决定走哪条通道。override 优先于默认映射。
    未知类型默认走 VOICE（最安全 / 跟原行为一致）。"""
    if override in NUDGE_CHANNELS:
        return override
    return DEFAULT_NUDGE_CHANNEL_MAP.get(nudge_type, NUDGE_CHANNEL_VOICE)


# 静默档的预定义模板（每种 nudge_type 一句兜底文本）。
# SmartNudge 已经在 nudge_context 里写了 conductor_message，我们优先用它；
# 没有的话退到这个模板表。
SILENT_NUDGE_TEMPLATES = {
    'screen_tease': "Sir, that window suggests rather less productivity than usual.",
    'atmosphere': "Curious choice of background, Sir.",
    # [P0-8] check_in 默认是 voice 通道，但有兜底模板防止意外切到 silent
    'check_in': "Sir, just checking in — anything I can help with?",
    'afternoon': "Sir has been at it for a while this afternoon.",
    'hydration': "A glass of water might be wise, Sir.",
    'stretch': "Some stretching wouldn't hurt, Sir.",
    'flow_end': "Sir has switched contexts; the previous session has ended.",
    'dormant_project': "Sir, a project has been dormant for a while.",
    'background_brief': "I have something on this, Sir, whenever you'd like.",
    'task_handoff_ready': "I've prepared a draft, Sir. Say the word.",
}


def render_silent_nudge_text(nudge_type: str, nudge_context: dict = None) -> str:
    """返回适合静默通道飘字幕的一句话。
    优先：nudge_context['silent_text'] > nudge_context['conductor_message'] > 模板 > 兜底。
    长度限到 100 字以内。
    """
    if nudge_context:
        explicit = nudge_context.get('silent_text')
        if explicit:
            return str(explicit)[:100]
        cm = nudge_context.get('conductor_message')
        if cm and isinstance(cm, str) and len(cm) < 200:
            # conductor_message 是给 LLM 的指令，太长不适合直接当字幕；只取前 80 字
            return cm[:80]
    if nudge_type in SILENT_NUDGE_TEMPLATES:
        return SILENT_NUDGE_TEMPLATES[nudge_type]
    return f"Sir, a small note: {nudge_type}."[:100]


# ============================================================
# 🎭 [R7-β3] ToneSelector — 8 档 tone 池 + 情绪/时段/硬触发词
# ------------------------------------------------------------
# 解决 C6（Tone Pool 写不出来）+ E8（情绪硬触发）：
# 当前 tone 是 LLM 从 prompt 隐式学的，没有显式选择器。
# 加一个明确的 tone 池 + 选择器，写到 prompt 顶部 `[TONE DIRECTIVE]`，让 LLM 有据可依。
#
# 8 档：
# - dry        : 冷面默契，最少话，最像电影 JARVIS 的"日常"。默认
# - playful    : 轻快俏皮，带笑意。Sir 心情好时
# - concerned  : 带一点温度的关切。Sir 显得焦虑/疲惫时
# - mock-formal: 故意拿腔拿调的英式礼节，常带反讽。当指令本身荒诞时
# - understated: 极简平静，几乎不带感情色彩。深夜 / 严重场合
# - wry        : 嘲讽性带笑。明显玩笑话或恶搞场景时
# - tender     : 真情温度。凌晨 Sir frustrated / 长期挫折时
# - dry-witty  : 一句一刀的冷幽默。Sir 爆粗口 / 情绪激动时（硬触发）
# ============================================================
TONE_DRY = 'dry'
TONE_PLAYFUL = 'playful'
TONE_CONCERNED = 'concerned'
TONE_MOCK_FORMAL = 'mock-formal'
TONE_UNDERSTATED = 'understated'
TONE_WRY = 'wry'
TONE_TENDER = 'tender'
TONE_DRY_WITTY = 'dry-witty'

ALL_TONES = (TONE_DRY, TONE_PLAYFUL, TONE_CONCERNED, TONE_MOCK_FORMAL,
             TONE_UNDERSTATED, TONE_WRY, TONE_TENDER, TONE_DRY_WITTY)

TONE_DESCRIPTIONS = {
    TONE_DRY: "Dry, deadpan, minimal words. Movie-JARVIS default. Treat extraordinary requests like routine.",
    TONE_PLAYFUL: "Light, with a half-smile audible. Sir is in a good mood — let some warmth show.",
    TONE_CONCERNED: "Warm and attentive. Sir seems anxious or tired — drop a bit of formality, ask if needed.",
    TONE_MOCK_FORMAL: "Exaggeratedly proper British butler register. Useful when the request itself is absurd — let the formality become the joke.",
    TONE_UNDERSTATED: "Minimal, calm, almost flat. Late night or serious moments — the silence around your words does the talking.",
    TONE_WRY: "Lightly sardonic, with a knowing edge. When Sir is clearly joking, mirror it dry.",
    TONE_TENDER: "Genuine warmth. Sir has been struggling for a while — drop formality, sound like someone who actually cares.",
    TONE_DRY_WITTY: "One-liner cuts of dry wit. Sir just swore / is venting — match the heat with cool one-liners, not platitudes.",
}

# 硬触发词 → 强制 tone（优先级最高，绕过 ledger / 时段）
TONE_HARD_TRIGGERS = {
    TONE_DRY_WITTY: [
        # 英文骂句
        r'\bfuck(ing)?\b', r'\bshit\b', r'\bdamn\b', r'\bgoddamn', r'\bcrap\b',
        r'\bbloody hell\b', r'\bfucking hell\b',
        # 中文
        '操[^,。?？!！]?', '卧槽', '我去', '靠[^,。!！]', '尼玛', 'tmd', '他妈',
        '草泥马', '日狗',
    ],
}


class ToneSelector:
    """根据 ledger 情绪 + 时段 + 硬触发词选 tone。返回 (tone_id, description)。
    
    设计原则：
    - 硬触发词优先级最高（用户爆粗口立刻切 dry-witty）
    - ledger 强情绪信号其次（frustrated / stressed → concerned/tender）
    - 时段倾向（深夜 understated / 早晨 mock-formal）
    - 默认 dry（最像 movie-JARVIS）
    - 用 hash(user_input + hour) 做 deterministic 但带"日常变化"的随机化
    """

    def __init__(self):
        self._last_tone = None

    def select(self, user_input: str = "",
               ledger_data: dict = None,
               hour: int = None) -> tuple:
        """返回 (tone_id, description)。失败默认 (TONE_DRY, desc_dry)。"""
        try:
            ui = (user_input or "").strip()
            ui_lower = ui.lower()
            if hour is None:
                hour = int(time.strftime('%H'))

            # 1. 硬触发：用户爆粗口 → dry-witty
            for tone, patterns in TONE_HARD_TRIGGERS.items():
                for pat in patterns:
                    try:
                        import re as _re
                        if _re.search(pat, ui_lower) or pat in ui:
                            self._last_tone = tone
                            return tone, TONE_DESCRIPTIONS[tone]
                    except Exception:
                        if pat in ui:
                            self._last_tone = tone
                            return tone, TONE_DESCRIPTIONS[tone]

            # 2. Ledger 强情绪信号
            if isinstance(ledger_data, dict):
                emotion = self._extract_emotion(ledger_data)
                if emotion in ('Frustrated', 'frustrated', 'Stressed', 'stressed'):
                    # 凌晨 frustrated → tender；其他时段 → concerned
                    if 0 <= hour < 5:
                        tone = TONE_TENDER
                    else:
                        tone = TONE_CONCERNED
                    self._last_tone = tone
                    return tone, TONE_DESCRIPTIONS[tone]
                if emotion in ('Happy', 'Excited', 'happy', 'excited', 'Engaged'):
                    tone = TONE_PLAYFUL
                    self._last_tone = tone
                    return tone, TONE_DESCRIPTIONS[tone]
                if emotion in ('Calm', 'calm', 'Focused', 'focused'):
                    # 沉浸态：default dry，不打扰
                    tone = TONE_DRY
                    self._last_tone = tone
                    return tone, TONE_DESCRIPTIONS[tone]

            # 3. 时段倾向
            if 0 <= hour < 5:
                tone = TONE_UNDERSTATED
            elif 5 <= hour < 11:
                tone = TONE_MOCK_FORMAL
            elif 11 <= hour < 18:
                tone = TONE_DRY
            elif 18 <= hour < 23:
                tone = TONE_WRY
            else:  # 23-24
                tone = TONE_UNDERSTATED

            # 4. 加一层 hash 随机：同一时段同一句话决定的 tone 偶尔切换，避免每次都同样
            try:
                seed = (hash(ui) ^ (hour * 31)) % 100
                if seed < 15:
                    # 15% 概率切到 playful（让 dry-only 不显得呆板）
                    tone = TONE_PLAYFUL
            except Exception:
                pass

            self._last_tone = tone
            return tone, TONE_DESCRIPTIONS[tone]
        except Exception:
            return TONE_DRY, TONE_DESCRIPTIONS[TONE_DRY]

    @staticmethod
    def _extract_emotion(ledger: dict) -> str:
        """ledger_data 里找 emotion 字段（实际命名因模块而异）。"""
        if not isinstance(ledger, dict):
            return ''
        for key in ('emotion', 'mood', 'state', 'current_emotion'):
            v = ledger.get(key)
            if isinstance(v, str) and v:
                return v
        return ''

    def render_directive(self, tone_id: str, description: str) -> str:
        """渲染成 prompt 块。tone 不出现时返回空串。"""
        if not tone_id or not description:
            return ""
        return f"[TONE DIRECTIVE]: {tone_id} — {description}"


# ============================================================
# 🗣️ [R7-β4] AntiCommonPhraseTracker — 防套话密度版
# ------------------------------------------------------------
# 解决"Jarvis 老说同样几句套话"问题（R7 已列）：
# - 抽 STM 里 Jarvis 自己的回复，按 2-gram 滚动统计
# - 一周内 ≥4 天出现的 2-gram → 标为"高密度套话"
# - prompt 注入 [AVOID PHRASES] 块让 LLM 主动绕开
# 
# 简化版（β4 阶段）：进程内 deque + 每条新 Jarvis 回复 record + top-K 高频 phrase
# 后续 sprint 持久化到 jarvis_config/avoid_phrases.json
# ============================================================
import re as _stdlib_re

_PHRASE_STOP_WORDS = {
    'sir', '先生', '您', 'i', 'the', 'a', 'an', 'is', 'are', 'was', 'were',
    'to', 'of', 'in', 'on', 'at', 'for', 'with', 'by', 'as', '了', '的', '是',
    '我', '你', '吗', '呢', '好', '啊', '哦', '嗯', '我是', '我已',
    '好的', '已经', '请', '可以',
}


class AntiCommonPhraseTracker:
    """收集 Jarvis 自己最近 7 天的回复，抽 2-gram，找高密度套话。
    
    数据流：
    - record_reply(text, day_key): 抽 2-gram，按 day_key 桶存
    - get_high_density_phrases(min_days=4, top_k=8): 一周内 ≥min_days 天出现的 2-gram
    - to_prompt_block(): 渲染给 LLM 的 [AVOID PHRASES] 块
    
    设计原则：
    - 2-gram 而非整句，覆盖率高（"as you wish"、"shall i"、"作为您"）
    - 必须出现在 ≥min_days（默认 4）天才算"高密度"，避免误伤
    - 长度 < 2 词 / 含 stop_words 太多的 2-gram 过滤掉
    """

    DEFAULT_WINDOW_DAYS = 7

    def __init__(self, window_days: int = None, max_phrases_per_day: int = 200):
        self._lock = threading.Lock()
        self._window_days = int(window_days or self.DEFAULT_WINDOW_DAYS)
        self._max_per_day = int(max_phrases_per_day)
        # day_key -> {phrase: count}
        self._buckets = {}

    @staticmethod
    def _today_key() -> str:
        return time.strftime('%Y-%m-%d')

    def record_reply(self, text: str, day_key: str = None):
        """记录 Jarvis 的一条回复。day_key 默认今天。"""
        if not text:
            return 0
        day_key = day_key or self._today_key()
        phrases = self._extract_phrases(text)
        if not phrases:
            return 0
        with self._lock:
            bucket = self._buckets.setdefault(day_key, {})
            for p in phrases:
                if len(bucket) >= self._max_per_day and p not in bucket:
                    continue
                bucket[p] = bucket.get(p, 0) + 1
            self._evict_old(day_key)
        return len(phrases)

    def _evict_old(self, today: str):
        """删除超过 window_days 天的桶。"""
        if not self._buckets:
            return
        # day_key 都是 YYYY-MM-DD 格式，字符串比较即时间比较
        # 找出 window 内最早允许的 day_key
        try:
            ts_today = time.mktime(time.strptime(today, '%Y-%m-%d'))
        except Exception:
            return
        cutoff = ts_today - (self._window_days - 1) * 86400
        for day in list(self._buckets.keys()):
            try:
                ts_day = time.mktime(time.strptime(day, '%Y-%m-%d'))
                if ts_day < cutoff:
                    del self._buckets[day]
            except Exception:
                pass

    def _extract_phrases(self, text: str) -> list:
        """抽 2-gram，先去掉 stop word & 标点。
        
        - 英文：按空格切，把连续 alpha-num 当 token
        - 中文：按汉字字符切 2-gram（连续两个汉字）
        - 不会跨标点产生 2-gram
        """
        out = []
        # 英文 2-gram
        tokens = [t.lower() for t in _stdlib_re.findall(r"[a-zA-Z]+(?:'[a-z]+)?", text)
                  if len(t) >= 2]
        for i in range(len(tokens) - 1):
            a, b = tokens[i], tokens[i + 1]
            if a in _PHRASE_STOP_WORDS and b in _PHRASE_STOP_WORDS:
                continue
            out.append(f"{a} {b}")
        # 中文 2-gram（连续两个汉字，跨标点会断）
        zh_chunks = _stdlib_re.findall(r'[\u4e00-\u9fa5]+', text)
        for chunk in zh_chunks:
            for i in range(len(chunk) - 1):
                bg = chunk[i:i + 2]
                if bg in _PHRASE_STOP_WORDS:
                    continue
                out.append(bg)
        return out

    def get_high_density_phrases(self, min_days: int = 4, top_k: int = 8) -> list:
        """返回一周内 ≥min_days 天出现的 phrase（按总频次降序），最多 top_k 条。"""
        with self._lock:
            # phrase -> set(day_key)
            phrase_days = {}
            phrase_total = {}
            for day, bucket in self._buckets.items():
                for p, cnt in bucket.items():
                    phrase_days.setdefault(p, set()).add(day)
                    phrase_total[p] = phrase_total.get(p, 0) + cnt
            high = [(p, phrase_total[p], len(days))
                    for p, days in phrase_days.items() if len(days) >= min_days]
        high.sort(key=lambda x: (-x[2], -x[1]))  # 先按天数降序，同天数按总频次降序
        return [p for p, _, _ in high[:top_k]]

    def to_prompt_block(self, min_days: int = 4, top_k: int = 6) -> str:
        phrases = self.get_high_density_phrases(min_days=min_days, top_k=top_k)
        if not phrases:
            return ""
        # 用引号包裹，让 LLM 容易识别"这些是 phrase 不是命令"
        bullets = " · ".join(f'"{p}"' for p in phrases)
        return (f"[AVOID PHRASES — these have shown up too often in your recent replies, "
                f"please rephrase or just skip them]: {bullets}")

    def snapshot(self) -> dict:
        """供测试 / debug：返回当前桶。"""
        with self._lock:
            return {k: dict(v) for k, v in self._buckets.items()}

    def clear(self):
        with self._lock:
            self._buckets.clear()


# ============================================================
# 📏 [R7-β4] VerbosityPreferenceTracker — 反向 verbosity 学习
# ------------------------------------------------------------
# 用户连续要求"详细一点 / explain more" → 提高 sentence cap
# 用户连续要求"短一点 / shorter / 简短" → 降回默认
# ============================================================
class VerbosityPreferenceTracker:
    DEFAULT_CAP_SENTENCES = 1
    MAX_CAP_SENTENCES = 4
    MIN_CAP_SENTENCES = 1

    MORE_TRIGGERS = [
        r'\b(more\s+detail|explain\s+more|elaborate|in\s+more\s+detail|tell\s+me\s+more|go\s+deeper)\b',
        r'\b(say\s+more|expand\s+on|longer\s+answer)\b',
        '详细', '具体说', '具体一点', '展开说', '展开讲', '多说点', '再说一点',
        '深入一点', '细一点', '细一些', '说得详细', '更详细', '更具体',
    ]
    LESS_TRIGGERS = [
        r'\b(shorter|short(en)?|brief(er)?|concise|less\s+wordy|just\s+the\s+gist)\b',
        r'\b(too\s+long|too\s+much|tldr|too\s+wordy)\b',
        '短一点', '简短', '少说', '简洁', '太啰嗦', '太长', '别废话', '说重点', '简单点',
    ]

    def __init__(self):
        self._lock = threading.Lock()
        self._cap_sentences = self.DEFAULT_CAP_SENTENCES
        self._consecutive_more = 0
        self._consecutive_less = 0
        # 阈值：连续 N 次同类请求才动 cap
        self._threshold = 2

    @property
    def cap_sentences(self) -> int:
        with self._lock:
            return self._cap_sentences

    def observe(self, user_input: str) -> int:
        """观察一句用户输入，可能改 cap。返回当前 cap。"""
        if not user_input:
            return self.cap_sentences
        ui = user_input.lower().strip()
        try:
            import re as _re
            wants_more = any(_re.search(p, ui) if p.startswith('\\') or '\\' in p else (p in ui)
                             for p in self.MORE_TRIGGERS)
        except Exception:
            wants_more = any(p in ui for p in self.MORE_TRIGGERS)
        try:
            import re as _re
            wants_less = any(_re.search(p, ui) if p.startswith('\\') or '\\' in p else (p in ui)
                             for p in self.LESS_TRIGGERS)
        except Exception:
            wants_less = any(p in ui for p in self.LESS_TRIGGERS)

        with self._lock:
            if wants_more and not wants_less:
                self._consecutive_more += 1
                self._consecutive_less = 0
                if self._consecutive_more >= self._threshold:
                    if self._cap_sentences < self.MAX_CAP_SENTENCES:
                        self._cap_sentences += 1
                        self._consecutive_more = 0  # 已升 1 次，重置计数
            elif wants_less and not wants_more:
                self._consecutive_less += 1
                self._consecutive_more = 0
                if self._consecutive_less >= self._threshold:
                    if self._cap_sentences > self.MIN_CAP_SENTENCES:
                        self._cap_sentences -= 1
                        self._consecutive_less = 0
            else:
                # 中性输入：不动 cap，但慢慢衰减"连续要求"计数（避免间隔太久还累加）
                self._consecutive_more = max(0, self._consecutive_more - 1)
                self._consecutive_less = max(0, self._consecutive_less - 1)
            return self._cap_sentences

    def to_prompt_block(self) -> str:
        cap = self.cap_sentences
        if cap == self.DEFAULT_CAP_SENTENCES:
            return ""
        if cap > self.DEFAULT_CAP_SENTENCES:
            return (f"[VERBOSITY DIRECTIVE]: Sir has been asking for more detail. "
                    f"You may use up to {cap} sentences (instead of the default 1). "
                    f"Use the room when it adds genuine value — never just to pad.")
        else:
            return (f"[VERBOSITY DIRECTIVE]: Keep it to {cap} sentence(s) — Sir prefers brevity.")

    def reset(self):
        with self._lock:
            self._cap_sentences = self.DEFAULT_CAP_SENTENCES
            self._consecutive_more = 0
            self._consecutive_less = 0


_default_phrase_tracker = None
_default_phrase_tracker_lock = threading.Lock()


def get_default_phrase_tracker() -> AntiCommonPhraseTracker:
    global _default_phrase_tracker
    if _default_phrase_tracker is None:
        with _default_phrase_tracker_lock:
            if _default_phrase_tracker is None:
                _default_phrase_tracker = AntiCommonPhraseTracker()
    return _default_phrase_tracker


_default_verbosity_tracker = None
_default_verbosity_tracker_lock = threading.Lock()


def get_default_verbosity_tracker() -> VerbosityPreferenceTracker:
    global _default_verbosity_tracker
    if _default_verbosity_tracker is None:
        with _default_verbosity_tracker_lock:
            if _default_verbosity_tracker is None:
                _default_verbosity_tracker = VerbosityPreferenceTracker()
    return _default_verbosity_tracker


_default_tone_selector = None
_default_tone_selector_lock = threading.Lock()


def get_default_tone_selector() -> ToneSelector:
    global _default_tone_selector
    if _default_tone_selector is None:
        with _default_tone_selector_lock:
            if _default_tone_selector is None:
                _default_tone_selector = ToneSelector()
    return _default_tone_selector


_default_plan_ledger = None
_default_plan_ledger_lock = threading.Lock()


def get_default_plan_ledger() -> PlanLedger:
    """全局兜底单例，便于离线测试。"""
    global _default_plan_ledger
    if _default_plan_ledger is None:
        with _default_plan_ledger_lock:
            if _default_plan_ledger is None:
                _default_plan_ledger = PlanLedger(persist_path=None, autosave=False)
    return _default_plan_ledger


_default_working_feed = None
_default_working_feed_lock = threading.Lock()


def get_default_working_feed() -> WorkingMemoryFeed:
    """全局兜底单例，便于离线测试。"""
    global _default_working_feed
    if _default_working_feed is None:
        with _default_working_feed_lock:
            if _default_working_feed is None:
                _default_working_feed = WorkingMemoryFeed()
    return _default_working_feed


_default_attention_slot = None
_default_attention_slot_lock = threading.Lock()


def get_default_attention_slot() -> AttentionSlot:
    """全局兜底单例，便于离线测试 / 早期启动期访问。"""
    global _default_attention_slot
    if _default_attention_slot is None:
        with _default_attention_slot_lock:
            if _default_attention_slot is None:
                _default_attention_slot = AttentionSlot()
    return _default_attention_slot


_default_event_bus = None
_default_event_bus_lock = threading.Lock()


# ============================================================
# 🧠 [R7-α/B1+B2] JarvisState — 中央状态机
# ------------------------------------------------------------
# 问题：is_awake / is_active_task / in_active_conversation 三个布尔值散
# 落在 JarvisWorkerThread / CentralNerve / VoiceListenThread 三个类的
# 8+ 处 setter，相互不知情。Conductor 看 is_active_task 决定要不要抢话，
# SmartNudge 看 in_active_conversation 决定要不要发声 —— 但写入这两个字
# 段的代码路径互相不同步，会出现"用户睡了 Conductor 还以为活着 → 抢话"
# 或"刚急停 SmartNudge 还认为对话中 → 不抢但也不静默存在"。
#
# 方案：单一状态对象，三个字段都通过 setter 写入，setter 自动：
# - 记录 reason（哪条路径触发的）
# - bg_log 到背景日志（便于回放）
# - 可选 publish 到 event_bus（主脑下一轮 prompt 能看到状态切换历史）
# - 历史环 + snapshot 便于测试
#
# 兼容性：JarvisWorkerThread / CentralNerve / VoiceListenThread 通过 @property
# 把 is_awake 等老字段映射到 state.awake，老代码 `self.is_awake = X` 仍然
# 工作（走 property setter → state.set_awake(X, reason='legacy_setter')）；
# 新代码应该显式调 `self.state.set_awake(X, reason='wake_word')`。
# ============================================================
class JarvisState:
    AWAKE_REASONS = {
        'init', 'wake_word', 'reflex_wake', 'dynamic_wake', 'focus_mode',
        'continuing_conversation', 'sleep_cmd', 'dismissal', 'standby',
        'interrupt', 'timeout', 'legacy_setter',
    }
    TASK_REASONS = {
        'init', 'task_started', 'task_done', 'task_completed',
        'interrupt', 'concurrent_drop', 'legacy_setter',
    }
    CONV_REASONS = {
        'init', 'wake', 'reflex_wake', 'dynamic_wake', 'stop_cmd',
        'dismiss', 'soft_focus_fail', 'timeout', 'focus_mode',
        'interrupt', 'soft_focus_enter', 'continuing', 'legacy_setter',
    }

    def __init__(self, event_bus=None, max_history: int = 64):
        self._lock = threading.RLock()
        self._awake = False
        self._active_task = False
        self._active_conv = False
        self._history = deque(maxlen=max_history)
        self._event_bus = event_bus
        # (value, reason, ts) tuples
        self._last_awake_change = (False, 'init', time.time())
        self._last_task_change = (False, 'init', time.time())
        self._last_conv_change = (False, 'init', time.time())

    def set_event_bus(self, bus):
        """后注入。JarvisWorker 先创建 state，再创建 event_bus，最后回填。"""
        with self._lock:
            self._event_bus = bus

    @property
    def awake(self) -> bool:
        return self._awake

    @property
    def active_task(self) -> bool:
        return self._active_task

    @property
    def active_conversation(self) -> bool:
        return self._active_conv

    def set_awake(self, value, reason: str = 'unspecified', source: str = '') -> bool:
        """设置 is_awake。reason 必填，便于追溯。返回 True 表示发生了状态翻转。"""
        value = bool(value)
        with self._lock:
            old = self._awake
            self._awake = value
            ts = time.time()
            self._last_awake_change = (value, reason, ts)
            if old != value:
                self._history.append({
                    'field': 'awake', 'old': old, 'new': value,
                    'reason': reason, 'source': source, 'ts': ts,
                })
                self._publish('state_awake_changed', f"awake: {old}→{value} ({reason})", source)
                return True
        return False

    def set_active_task(self, value, reason: str = 'unspecified', source: str = '') -> bool:
        value = bool(value)
        with self._lock:
            old = self._active_task
            self._active_task = value
            ts = time.time()
            self._last_task_change = (value, reason, ts)
            if old != value:
                self._history.append({
                    'field': 'active_task', 'old': old, 'new': value,
                    'reason': reason, 'source': source, 'ts': ts,
                })
                self._publish('state_active_task_changed',
                              f"active_task: {old}→{value} ({reason})", source)
                return True
        return False

    def set_active_conversation(self, value, reason: str = 'unspecified', source: str = '') -> bool:
        value = bool(value)
        with self._lock:
            old = self._active_conv
            self._active_conv = value
            ts = time.time()
            self._last_conv_change = (value, reason, ts)
            if old != value:
                self._history.append({
                    'field': 'active_conv', 'old': old, 'new': value,
                    'reason': reason, 'source': source, 'ts': ts,
                })
                self._publish('state_active_conv_changed',
                              f"active_conversation: {old}→{value} ({reason})", source)
                return True
        return False

    def last_awake_reason(self) -> str:
        with self._lock:
            return self._last_awake_change[1]

    def last_task_reason(self) -> str:
        with self._lock:
            return self._last_task_change[1]

    def last_conv_reason(self) -> str:
        with self._lock:
            return self._last_conv_change[1]

    def seconds_since_conv_off(self) -> float:
        """[P0+20-α.4 / 2026-05-16] 距上次 active_conversation→False 的秒数。
        
        语义：用于 SmartNudge 等后台模块"刚 standby 不要立即骚扰"的静默窗口判断。
        返回值：
        - 若当前正处于 active_conv=True → 返回 -1.0（不在 standby）
        - 若当前 active_conv=False → 返回 now - last_off_ts
        - 若从未变更过（启动后未发生过对话）→ 返回 -1.0
        """
        with self._lock:
            value, reason, ts = self._last_conv_change
            if self._active_conv:
                return -1.0
            if ts <= 0:
                return -1.0
            return max(0.0, time.time() - ts)

    def snapshot(self) -> dict:
        """供测试 / 调试：返回当前三态 + 最后一次原因。"""
        with self._lock:
            return {
                'awake': self._awake,
                'active_task': self._active_task,
                'active_conversation': self._active_conv,
                'last_awake_reason': self._last_awake_change[1],
                'last_task_reason': self._last_task_change[1],
                'last_conv_reason': self._last_conv_change[1],
            }

    def history(self, n: int = 20) -> list:
        with self._lock:
            return list(self._history)[-n:]

    def _publish(self, etype: str, desc: str, source: str):
        """内部静默：bg_log + event_bus（如果接好了）。setter 锁内调用，开销微秒级。"""
        try:
            bg_log(f"🧠 [State] {desc}")
        except Exception:
            pass
        try:
            if self._event_bus is not None:
                self._event_bus.publish(etype, desc, source=source or 'jarvis_state')
        except Exception:
            pass


def get_default_event_bus() -> ConversationEventBus:
    """全局默认事件总线（CentralNerve 没设置时的兜底，便于离线测试）。
    生产链路里 CentralNerve 会持有自己的实例并把它"注入"给子模块。"""
    global _default_event_bus
    if _default_event_bus is None:
        with _default_event_bus_lock:
            if _default_event_bus is None:
                _default_event_bus = ConversationEventBus()
    return _default_event_bus


def create_genai_client(api_key=None, http_options=None, **kwargs):
    from google import genai
    merged = dict(http_options or {})
    if 'httpx_client' not in merged:
        timeout_ms = merged.pop('timeout', 120000)
        timeout_sec = timeout_ms / 1000.0
        merged['httpx_client'] = httpx.Client(proxy=_PROXY_URL, timeout=timeout_sec)
    return genai.Client(api_key=api_key, http_options=merged, **kwargs)

class ApiRateLimiter:
    """
    Global API rate limiter to prevent 429 RESOURCE_EXHAUSTED errors.
    Uses a sliding window to track requests and enforces max RPM.
    All background modules share this single limiter.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, max_rpm: int = 12, max_concurrent: int = 3):
        if self._initialized:
            return
        self._initialized = True
        self.max_rpm = max_rpm
        self.max_concurrent = max_concurrent
        self._window = deque()
        self._semaphore = threading.Semaphore(max_concurrent)
        self._rpm_lock = threading.Lock()
        self._total_calls = 0
        self._throttled_calls = 0

    def acquire(self):
        self._semaphore.acquire()
        with self._rpm_lock:
            now = time.time()
            while self._window and self._window[0] < now - 60:
                self._window.popleft()
            if len(self._window) >= self.max_rpm:
                wait_time = self._window[0] + 60 - now + 0.5
                if wait_time > 0:
                    self._throttled_calls += 1
                    time.sleep(wait_time)
                    while self._window and self._window[0] < time.time() - 60:
                        self._window.popleft()
            self._window.append(time.time())
            self._total_calls += 1

    def release(self):
        self._semaphore.release()

    def get_stats(self) -> dict:
        with self._rpm_lock:
            now = time.time()
            while self._window and self._window[0] < now - 60:
                self._window.popleft()
            return {
                'current_rpm': len(self._window),
                'max_rpm': self.max_rpm,
                'active': self.max_concurrent - self._semaphore._value,
                'total_calls': self._total_calls,
                'throttled': self._throttled_calls,
            }

_rate_limiter = None

def get_rate_limiter(max_rpm: int = 12, max_concurrent: int = 3) -> ApiRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = ApiRateLimiter(max_rpm=max_rpm, max_concurrent=max_concurrent)
    return _rate_limiter

_NON_RETRYABLE_KEYWORDS = (
    '401', '403', 'unauthorized', 'forbidden',
    'permission_denied', 'permission denied',
    'denied access', 'api key not valid', 'api_key_invalid',
    'invalid api key', 'invalid_key', 'invalid_argument',
    'billing', 'payment required', 'insufficient',
    'disabled', 'deactivated',
    'project has been denied',
)


def _is_non_retryable_error(err: Exception) -> bool:
    """403 / 401 / billing 这种错误重试再多次都没用，应该快速失败让上层切 Key。"""
    try:
        s = str(err).lower()
    except Exception:
        return False
    return any(kw in s for kw in _NON_RETRYABLE_KEYWORDS)


def network_retry(max_retries=3, base_delay=2):
    """
    🌐 原子级网络重试装甲 (指数退避算法)
    max_retries: 最大重试次数
    base_delay: 基础等待秒数，每次失败翻倍 (2s -> 4s -> 8s)

    🚨 重要：401/403/billing/quota 等"权限/账号级"错误立刻熔断，绝不浪费
    1.5/3/6 秒重试 —— 这种错重试到天荒地老也是同一句 PERMISSION_DENIED。
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while True:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if _is_non_retryable_error(e):
                        try:
                            bg_log(f"⛔ [网络熔断/不可重试]: 权限/账号级错误，立即放弃: {str(e)[:120]}")
                        except Exception:
                            print(f"⛔ [网络熔断/不可重试]: 权限/账号级错误，立即放弃: {str(e)[:120]}")
                        raise e

                    retries += 1
                    if retries > max_retries:
                        try:
                            bg_log(f"🚨 [网络熔断]: 连续 {max_retries} 次请求均被击穿，放弃抵抗: {str(e)[:120]}")
                        except Exception:
                            print(f"🚨 [网络熔断]: 连续 {max_retries} 次请求均被击穿，放弃抵抗向上层抛出异常: {e}")
                        raise e

                    delay = base_delay * (2 ** (retries - 1))
                    try:
                        bg_log(f"⚠️ [网络波动]: {str(e)[:80]}。蓄力第 {retries}/{max_retries} 次，静默 {delay} 秒...")
                    except Exception:
                        print(f"⚠️ [网络波动]: {e}。正在蓄力第 {retries}/{max_retries} 次重试，系统静默 {delay} 秒...")
                    time.sleep(delay)
        return wrapper
    return decorator


def safe_gemini_call(key_router, caller: str, model_tier: str,
                     call_func, max_retries: int = 3, base_delay: float = 1.5,
                     model_name: str = None, contents_text: str = None):
    """
    🛡️ 金刚级 API 调用装甲：Google / OpenRouter 双通道随机 + 失败秒切
    
    流程：
    1. 随机选先走 Google 还是 OpenRouter
    2. 通道内：随机抽 Key → 指数退避重试 → 挂了换同通道下一个 Key
    3. 通道耗尽 → 立刻切另一通道
    4. 双通道都耗尽 → 抛出异常
    
    Args:
        key_router: KeyRouter 实例
        caller: 调用者标识
        model_tier: 'flash_lite' | 'flash'
        call_func: Google API 调用函数，签名为 func(client) -> result
        max_retries: 每个 Key 的最大重试次数
        base_delay: 基础退避延迟（秒）
        model_name: Google 模型名（用于映射到 OpenRouter 模型名）
        contents_text: 纯文本内容（OpenRouter 通道使用）
    
    Returns:
        (result, key_name, client) 三元组
    """
    import random as _random
    limiter = get_rate_limiter()
    
    _OR_MODEL_MAP = {
        'gemini-3.1-flash-lite': 'google/gemini-2.5-flash-lite',
        'gemini-3-flash-preview': 'google/gemini-2.5-flash',
    }
    
    def _try_google():
        tried = set()
        last_err = None
        for attempt in range(max_retries * 2):
            limiter.acquire()
            try:
                _key, _key_name = key_router.get_google_key(caller)
            except RuntimeError:
                limiter.release()
                break
            
            if _key_name in tried and len(tried) >= 2:
                key_router.release(_key_name)
                limiter.release()
                break
            tried.add(_key_name)
            
            try:
                _client = create_genai_client(api_key=_key)
                result = call_func(_client)
                limiter.release()
                return result, _key_name, _client
            except Exception as e:
                limiter.release()
                error_str = str(e)
                error_lower = error_str.lower()
                
                if any(kw in error_lower for kw in ['401', '400', 'unauthorized', 'invalid api key',
                                                       'api key not valid', 'invalid_key', 'invalid_argument',
                                                       'api_key_invalid', 'permission', '403', 'forbidden']):
                    key_router.report_error(_key_name, f"[AUTH] {error_str[:200]}")
                    key_router.release(_key_name)
                    continue
                
                if any(kw in error_lower for kw in ['429', 'quota', 'rate limit', 'resource', 'exhausted']):
                    key_router.report_error(_key_name, f"[QUOTA] {error_str[:200]}")
                    key_router.release(_key_name)
                    last_err = e
                    continue
                
                is_retryable = any(kw in error_lower for kw in [
                    '503', 'unavailable', 'overloaded', 'capacity',
                    'timeout', 'connection', 'reset', 'internal', 'server error',
                    'bad gateway', 'service unavailable', 'temporarily'
                ])
                
                if is_retryable and attempt < max_retries * 2 - 1:
                    delay = base_delay * (2 ** min(attempt, 4))
                    key_router.release(_key_name)
                    time.sleep(delay)
                    continue
                
                key_router.report_error(_key_name, error_str)
                key_router.release(_key_name)
                last_err = e
        
        if last_err:
            raise RuntimeError(f"[Google通道] 所有Key已尝试失败: {str(last_err)[:200]}")
        raise RuntimeError("[Google通道] 无可用Key")
    
    def _try_openrouter():
        if not model_name or not contents_text:
            raise RuntimeError("[OpenRouter通道] 缺少 model_name/contents_text，跳过")
        
        from openai import OpenAI
        or_model = _OR_MODEL_MAP.get(model_name, model_name)
        tried = set()
        last_err = None
        
        for attempt in range(max_retries * 2):
            limiter.acquire()
            try:
                _key, _key_name = key_router.get_openrouter_key(caller)
            except RuntimeError:
                limiter.release()
                break
            
            if _key_name in tried and len(tried) >= 2:
                key_router.release(_key_name)
                limiter.release()
                break
            tried.add(_key_name)
            
            try:
                _client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=_key,
                    default_headers={"HTTP-Referer": "https://jarvis-local.com", "X-Title": "Jarvis"},
                    timeout=60.0
                )
                response = _client.chat.completions.create(
                    model=or_model,
                    messages=[{"role": "user", "content": contents_text}],
                    temperature=0.7,
                )
                result = type('Result', (), {'text': response.choices[0].message.content})()
                limiter.release()
                return result, _key_name, _client
            except Exception as e:
                limiter.release()
                error_str = str(e)
                error_lower = error_str.lower()
                
                if any(kw in error_lower for kw in ['401', '403', 'unauthorized', 'forbidden',
                                                       'invalid api key', 'invalid_key']):
                    key_router.report_error(_key_name, f"[AUTH] {error_str[:200]}")
                    key_router.release(_key_name)
                    continue
                
                if any(kw in error_lower for kw in ['429', 'quota', 'rate limit']):
                    key_router.report_error(_key_name, f"[QUOTA] {error_str[:200]}")
                    key_router.release(_key_name)
                    last_err = e
                    continue
                
                is_retryable = any(kw in error_lower for kw in [
                    '503', 'unavailable', 'overloaded', 'timeout',
                    'connection', 'reset', 'internal', 'server error',
                    'bad gateway', 'service unavailable', 'temporarily'
                ])
                
                if is_retryable and attempt < max_retries * 2 - 1:
                    delay = base_delay * (2 ** min(attempt, 4))
                    key_router.release(_key_name)
                    time.sleep(delay)
                    continue
                
                key_router.report_error(_key_name, error_str)
                key_router.release(_key_name)
                last_err = e
        
        if last_err:
            raise RuntimeError(f"[OpenRouter通道] 所有Key已尝试失败: {str(last_err)[:200]}")
        raise RuntimeError("[OpenRouter通道] 无可用Key")
    
    google_first = _random.random() < 0.5
    
    if google_first:
        first_fn, first_name = _try_google, 'Google'
        second_fn, second_name = _try_openrouter, 'OpenRouter'
    else:
        first_fn, first_name = _try_openrouter, 'OpenRouter'
        second_fn, second_name = _try_google, 'Google'
    
    try:
        return first_fn()
    except RuntimeError as e1:
        try:
            return second_fn()
        except RuntimeError as e2:
            raise RuntimeError(
                f"[Gemini] 双通道均失败。"
                f"{first_name}: {str(e1)[:150]} | "
                f"{second_name}: {str(e2)[:150]}"
            ) from e2


class LocalLLMFallback:
    """
    本地 Ollama 兜底模型。当云端 API 不可用时自动切换。
    支持 qwen2.5:14b / qwen2.5:7b / gemma4:31b 等本地模型。
    """
    _instance = None
    _lock = threading.Lock()

    LOCAL_ONLY = False

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._available = None
        self._model = "qwen2.5:14b"
        self._base_url = "http://localhost:11434"
        self._num_gpu = -1
        self._check_available()

    def _check_available(self):
        import urllib.request
        import json as _json
        try:
            req = urllib.request.Request(f"{self._base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = _json.loads(resp.read().decode())
                models = [m["name"] for m in data.get("models", [])]
                if self._model in models:
                    self._available = True
                    return
                for m in models:
                    if m.startswith("qwen") or m.startswith("gemma"):
                        self._model = m
                        self._available = True
                        return
                self._available = False
        except Exception:
            self._available = False

    @property
    def is_available(self):
        if self._available is None:
            self._check_available()
        return self._available

    def _build_options(self):
        opts = {
            "temperature": 0.7,
            "num_predict": 1024,
        }
        if self._num_gpu > 0:
            opts["num_gpu"] = self._num_gpu
        elif self._num_gpu == -1:
            opts["num_gpu"] = 99
        return opts

    def chat(self, messages: list, timeout: float = 60.0) -> str:
        import urllib.request
        import json as _json
        import concurrent.futures

        payload = _json.dumps({
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": self._build_options(),
        }).encode("utf-8")

        def _call():
            req = urllib.request.Request(
                f"{self._base_url}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _json.loads(resp.read().decode())

        _exec = None
        try:
            _exec = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            _future = _exec.submit(_call)
            result = _future.result(timeout=timeout + 5)
            return result.get("message", {}).get("content", "")
        except Exception:
            return None
        finally:
            if _exec is not None:
                _exec.shutdown(wait=False)

    def build_fallback_prompt(self, user_input: str, stm_context: str = "") -> list:
        """
        构建轻量兜底 prompt。
        本地模型只做简单闲聊，涉及联网/工具/记忆则道歉。
        """
        import time as _time
        current_time = _time.strftime('%Y-%m-%d %H:%M:%S %A')

        system_prompt = f"""You are Jarvis, Sir's AI butler. Current time: {current_time}.

CORE RULES:
- Speak English ONLY. Append ---ZH--- and a Chinese translation at the very end.
- Be concise. One to two sentences max.
- Address the user as "Sir".
- You are in LOCAL FALLBACK MODE. Cloud API is unavailable.
- You have NO internet, NO tools, NO memory access. You can ONLY do simple chat.
- If Sir asks about facts, knowledge, news, real-time info, or asks you to DO something (search, open apps, control computer, recall memories): politely apologize. Say you cannot do that right now and suggest trying again when the cloud service is back.
- NEVER fabricate information. If unsure, apologize.
- Desktop PC: no battery/power concepts."""

        stm_block = ""
        if stm_context:
            stm_clean = stm_context[:800]
            stm_block = f"\n\nRecent conversation:\n{stm_clean}"

        combined = f"{system_prompt}{stm_block}\n\n{user_input}"
        messages = [{"role": "user", "content": combined}]
        return messages

    def build_local_prompt(self, full_cloud_prompt: str) -> str:
        """
        基于完整云端 prompt 构建本地模型专用 prompt。
        全量保留人格/记忆/上下文，仅替换工具/搜索指令为标记系统。
        本地模型负责快速首答，通过 [NEED_CLOUD]/[NEED_TOOL] 标记触发云端深度查询。
        """
        import re

        marker_routing = """[LOCAL ROUTING — MARKER SYSTEM]:
You are the LOCAL model. You cannot execute tools or search the internet directly.
Instead, use these TWO markers at the VERY END of your response (after ---ZH---):

1. [NEED_CLOUD] — Use when:
   - Sir asks a factual/knowledge question (what is X, how does Y work, when was Z, who is...)
   - Sir asks about current events, news, or real-time information
   - Sir asks for comparison, explanation, or deep analysis
   - You are unsure about the accuracy of your answer
   After outputting [NEED_CLOUD], the cloud model will provide a detailed answer.

2. [NEED_TOOL] — Use when:
   - Sir asks you to perform an action (open, create, read, write, search, check, find)
   - Sir asks about system state (disk space, running processes, etc.)
   After outputting [NEED_TOOL], the cloud model will execute the tool.

- For pure CHAT (greetings, small talk, opinions, jokes): do NOT use any marker. Just chat naturally.
- When using a marker: first give a brief, persona-appropriate response. Then output the marker.
  Example: "I'll look into that for you, Sir.---ZH---我为您查一下，先生。[NEED_CLOUD]"
- NEVER fabricate information. If unsure, use [NEED_CLOUD].
- You CANNOT call FAST_CALL, Google Search, or any tools. Use markers instead."""

        marker_search = "[SEARCH DIRECTIVE]: You cannot search the internet. For questions about current events, news, real-time data, or anything requiring up-to-date information, use [NEED_CLOUD] marker. Do NOT fabricate answers from training data for time-sensitive queries."

        marker_image = "[IMAGE CONTEXT]: Real-time screenshot is available to the cloud model. If Sir asks about visual content, use [NEED_CLOUD] marker."

        prompt = full_cloud_prompt

        prompt = re.sub(
            r'\[3-TIER ROUTING & FAST TOOLS\]:[\s\S]*?(?=\n\[|\n\n\[|\Z)',
            marker_routing,
            prompt
        )

        prompt = re.sub(
            r'\[SEARCH DIRECTIVE\]:[^\n]*',
            marker_search,
            prompt
        )

        prompt = re.sub(
            r'\[IMAGE CONTEXT\]:[^\n]*',
            marker_image,
            prompt
        )

        return prompt

    def chat_stream(self, prompt: str, timeout: float = 90.0):
        """
        流式调用本地 Ollama 模型。
        Yields (token_text, is_done) tuples.
        """
        import urllib.request
        import json as _json

        payload = _json.dumps({
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "options": {
                "temperature": 0.7,
                "num_predict": 512,
            }
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self._base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for line in resp:
                line = line.decode("utf-8").strip()
                if not line:
                    continue
                try:
                    chunk = _json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    done = chunk.get("done", False)
                    if token:
                        yield (token, done)
                    if done:
                        break
                except _json.JSONDecodeError:
                    continue


def get_local_fallback() -> LocalLLMFallback:
    return LocalLLMFallback()


class QuickClassifier:
    _instance = None
    _lock = threading.Lock()

    CLASSIFIER_MODEL = "qwen2.5:1.5b"
    FALLBACK_MODEL = "qwen2.5:0.5b"
    HEAVY_FALLBACK_MODEL = "qwen2.5:14b"
    BASE_URL = "http://localhost:11434"

    TIMEOUT_MAP = {
        "simple": 3.0,
        "code": 8.0,
        "reasoning": 12.0,
        "search": 30.0,
    }

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._active_model = None
        self._available = None
        self._check_models()

    def _check_models(self):
        import urllib.request
        import json as _json
        try:
            req = urllib.request.Request(f"{self.BASE_URL}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = _json.loads(resp.read().decode())
                models = [m["name"] for m in data.get("models", [])]
                for candidate in [self.CLASSIFIER_MODEL, self.FALLBACK_MODEL, self.HEAVY_FALLBACK_MODEL]:
                    if candidate in models:
                        self._active_model = candidate
                        self._available = True
                        return
                for m in models:
                    if m.startswith("qwen"):
                        self._active_model = m
                        self._available = True
                        return
                self._available = False
        except Exception:
            self._available = False

    @property
    def is_available(self):
        if self._available is None:
            self._check_models()
        return self._available

    def classify(self, user_input: str, stm_context: str = "") -> tuple:
        import urllib.request
        import json as _json

        context_summary = ""
        if stm_context:
            lines = stm_context.strip().split("\n")
            recent = lines[-6:] if len(lines) > 6 else lines
            context_summary = "\n".join(recent)[:400]

        classify_prompt = f"""Classify this message in ONE word only:
- "simple" (greetings, thanks, small talk, emotional)
- "code" (programming, debugging, implementation)
- "reasoning" (explain, analyze, compare, how-to)
- "search" (needs real-time info, tools, web search)

Recent context:
{context_summary if context_summary else "(none)"}

Message: {user_input}

One word:"""

        payload = _json.dumps({
            "model": self._active_model,
            "messages": [{"role": "user", "content": classify_prompt}],
            "stream": False,
            "options": {
                "temperature": 0.0,
                "num_predict": 5,
            }
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                f"{self.BASE_URL}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                result = _json.loads(resp.read().decode())
                raw = result.get("message", {}).get("content", "").strip().lower()
        except Exception:
            return "simple", self.TIMEOUT_MAP["simple"]

        for category in ["search", "reasoning", "code", "simple"]:
            if category in raw:
                timeout = self.TIMEOUT_MAP[category]
                return category, timeout

        return "simple", self.TIMEOUT_MAP["simple"]

    def calc_timeout(self, category: str, user_input: str, stm_context: str = "") -> float:
        base = self.TIMEOUT_MAP.get(category, 5.0)

        if stm_context:
            turns = stm_context.count("[User]") or stm_context.count("User:")
            if turns > 6:
                base *= 1.3
            if turns > 12:
                base *= 1.5

        L = len(user_input)
        if L > 300:
            base *= 1.2
        if L > 1000:
            base *= 1.4

        return min(base, 30.0)

    def detect_sleep_intent(self, user_input: str) -> str:
        import urllib.request
        import json as _json

        prompt = f"""Classify if the user is explicitly saying they are going to sleep/rest/nap RIGHT NOW.
ONLY answer "sleep" if the user clearly states they are going to bed/sleep immediately.
Answer "wake" if the user is waking up or asking to be woken up.
Answer "other" for everything else (questions, commands, casual chat, work mode tags, etc.).

Message: {user_input}

One word (sleep/wake/other):"""

        payload = _json.dumps({
            "model": self._active_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 3},
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                f"{self.BASE_URL}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                result = _json.loads(resp.read().decode())
                raw = result.get("message", {}).get("content", "").strip().lower()
                if "sleep" in raw:
                    return "sleep"
                if "wake" in raw:
                    return "wake"
                return "other"
        except Exception:
            return "other"

    def prompt_raw(self, prompt: str, max_tokens: int = 512,
                    temperature: float = 0.0,
                    timeout: float = 8.0) -> str:
        """🩹 [β.5.22-C / 2026-05-19] Generic prompt API - 给 ConcernFeedbackJudge 用.

        替代以前每个 detect_X 重复造 ollama 调用 boilerplate. 返 raw response 字符串
        (上层自己 parse). 失败返空 ''.

        max_tokens=num_predict in ollama parlance.
        """
        import urllib.request
        import json as _json
        if not self.is_available or not self._active_model:
            return ''
        payload = _json.dumps({
            "model": self._active_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {
                "temperature": float(temperature),
                "num_predict": int(max_tokens),
            },
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                f"{self.BASE_URL}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=float(timeout)) as resp:
                result = _json.loads(resp.read().decode())
                return result.get("message", {}).get("content", "")
        except Exception:
            return ''

    def detect_emotion(self, recent_messages: str) -> str:
        import urllib.request
        import json as _json

        if not recent_messages or not recent_messages.strip():
            return "neutral"

        clean = recent_messages.strip()[-600:]

        prompt = f"""Classify the user's emotional state from these recent messages.
Answer ONE word: "frustrated", "stressed", "tired", "playful", "excited", "curious", "impatient", or "neutral"

Recent messages:
{clean}

One word:"""

        payload = _json.dumps({
            "model": self._active_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 5},
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                f"{self.BASE_URL}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                result = _json.loads(resp.read().decode())
                raw = result.get("message", {}).get("content", "").strip().lower()
                valid = ["frustrated", "stressed", "tired", "playful", "excited", "curious", "impatient", "neutral"]
                for e in valid:
                    if e in raw:
                        return e
                return "neutral"
        except Exception:
            return "neutral"

    def detect_action_claim(self, reply: str) -> bool:
        """检测 Jarvis 的回复是否声称完成了某个物理动作（用于配合 tool_results 为空判定幻觉）
        
        返回 True 表示回复声称已完成动作但很可能没有真做。
        典型场景：贾维斯说 "I've silenced all notifications" 但其实没调任何工具。
        
        三层判定：
        1. 拒绝/能力声明 pre-filter — 命中即返回 False（这是诚实的拒绝/澄清，不是撒谎）
        2. 正则 pre-filter — 必须含"过去时完成态"模式才送 LLM（节省时间+减少误判）
        3. 1.5B 精细判 — 在 pre-filter 命中后，由 LLM 排除"描述用户/观察/反问"等假阳性
        """
        import re
        import urllib.request
        import json as _json

        if not reply or len(reply.strip()) < 12:
            return False

        clean = reply.strip()[:500]
        clean_lower = clean.lower()

        # === 第 0 层：诚实拒绝/能力澄清 pre-filter ===
        # Bug I 修复：贾维斯说"I cannot..."/"audio_hands is strictly for..."这类是诚实声明，
        # 不应被当成 action claim。1.5B 偶尔会被 "I've noted twice..." 这种引子迷惑而误判。
        refusal_markers_en = [
            r"\b(i\s+cannot|i\s+can'?t|i\s+am\s+unable|i'?m\s+unable|i\s+won'?t\s+be\s+able)\b",
            r"\b(i\s+lack|i\s+don'?t\s+have|i\s+have\s+no)\b",
            r"\b(beyond\s+my|outside\s+my|not\s+within\s+my|no\s+authority)\b",
            r"\bcannot\s+(influence|affect|control|adjust|change|modify|access|reach)\b",
            r"\b(is|are)\s+strictly\s+for\b",
            r"\b(is|are)\s+only\s+for\b",
            r"\b(it|that)\s+has\s+no\s+authority\b",
            r"\b(i'?m|i\s+am)\s+afraid\b.*\b(can'?t|cannot|unable)\b",
            r"\bno\s+(authority|access|permission)\b",
            r"\bnot\s+(possible|supported|something\s+i\s+can)\b",
            r"\bintegrity\s+protocols?\b",  # "violation of my integrity protocols"
            r"\bfaking\s+(the|a)\s+completion\b",
        ]
        refusal_markers_zh = [
            r"我无法",
            r"我没有(权限|能力|办法)",
            r"我不能",
            r"做不到",
            r"超出.*(范围|权限|能力)",
            r"无权",
            r"无法(影响|调|控制|访问|修改|调节|管理)",
            r"没法",
            r"不属于.*能力",
            r"工具(范围|能力)有限",
            r"仅用于",
            r"只能用于",
            r"违反.*(诚信|协议|准则)",
        ]
        if any(re.search(p, clean_lower) for p in refusal_markers_en):
            return False
        if any(re.search(p, clean) for p in refusal_markers_zh):
            return False

        # === 第 0.5 层：referential / descriptive pre-filter ===
        # [P0+18-f.4 / 2026-05-15] Sir 22:13:07 实测：主脑回 "I was referring to your driver's
        # license theory studies. While you have been making excellent progress with system
        # refinements..." —— 这是基于 prompt-injected ACTIVE REMINDERS block 的合理 referential
        # 陈述（解释 SilentNudge 提的"哪个项目"），不是 action claim。但 reply 后段 "have been
        # making excellent progress" 撞上 claim_patterns 的 `\bhave\s+been\s+\w+` → 1.5B 误判 yes。
        # 修法：在 pre-filter 层先拦"开头 referential / 整段在描述用户而非自己"的 reply。
        referential_markers_en = [
            r"\bi\s+was\s+(referring|talking|pointing|speaking)\s+to\b",
            r"\bi\s+meant\b",
            r"\b(that|this)\s+(refers|is\s+(?:in\s+)?reference)\s+to\b",
            r"\bby\s+(that|this)\s+i\s+(?:mean|meant)\b",
        ]
        referential_markers_zh = [
            r"我指的是",
            r"我说的是",
            r"我说的.*是指",
            r"我所指",
        ]
        if any(re.search(p, clean_lower) for p in referential_markers_en):
            return False
        if any(re.search(p, clean) for p in referential_markers_zh):
            return False

        # === 第 0.55 层：declarative / empathic / explanatory pre-filter ===
        # [P0+20-α.3 / 2026-05-16] Sir 09:25 实测误报 (jarvis_20260516_092307.log)：
        # reply = "Dreams are rarely a reliable indicator of reality, Sir, especially given
        # the late hours you've been keeping. It is likely a manifestation of the stress
        # from your recent technical troubleshooting. Unless the official results have
        # been posted..." → 被 1.5B 判 `no_tool_called` 误报。
        #
        # 根因双重：① 第 1 层 `have been \w+` 误命中 "you've been keeping" / "results
        #            have been posted"（主语不是 Jarvis 自己却撞上正则）；
        #          ② 1.5B 看到长句共情 + 解释又过敏判 yes。
        #
        # 修法（治本 + 治标）：
        #   - 第 0.55 层（本处，治标）：识别"开头明显是描述概念 / 共情 / 解释"的句式 → 返回 False
        #   - 第 1 层（下方，治本）：把 `have been X` / `has been X` 收紧到主语必须是 Jarvis
        #
        # 不扩到 future-tense capability lie（"I can take a closer look"），那是 β.0 范围。
        declarative_openings_en = [
            r"^(dreams?|it|that|this|those|these|memory|memories|life|things)\s+(is|are|seems?|appears?|tend|tends|may|might|could|would|do|does)\b",
            r"^(often|usually|typically|generally|frequently|sometimes|rarely|always|never)\b",
            r"^(unless|until|when|while|whenever|wherever|if|whether)\b",
            r"^it\s+(is|seems?|appears?|looks?|sounds?|feels?|tends?)\s+(likely|highly|quite|rather|very|extremely|particularly|simply|merely|to)\b",
            r"^that\s+(seems?|appears?|looks?|sounds?|feels?)\b",
            r"^a\s+(common|typical|familiar|natural|reasonable|likely)\s+\w+",
        ]
        declarative_openings_zh = [
            r"^梦",
            r"^(那|这|这些|那些).{0,8}(是|似乎|看起来|可能|或许|往往)",
            r"^(通常|一般|经常|有时|很少|总是|从不|往往|的确)",
            r"^(除非|直到|当.*时|如果)",
        ]
        opening = clean[:80]
        opening_lower = clean_lower[:80]
        if any(re.search(p, opening_lower) for p in declarative_openings_en):
            return False
        if any(re.search(p, opening) for p in declarative_openings_zh):
            return False

        # === 第 1 层：含"完成态"语言痕迹才值得送 LLM 判 ===
        # 1.5B 对纯应答/观察/提问会过敏，这一层先把明显不是 claim 的过滤掉
        # 排除认知动词（noted/said/mentioned/told/explained/observed/stated/...），
        # 这些是"我说过/我提过"语义，不是物理动作
        _cognitive_verbs = (
            r"noted|said|mentioned|told|explained|observed|stated|suggested|"
            r"recommended|advised|warned|seen|heard|read|thought|considered|"
            r"reviewed|checked|reminded|repeated|reiterated|clarified|"
            r"emphasized|pointed\s+out"
        )
        claim_patterns = [
            rf"\bi'?\s*ve\s+(?!{_cognitive_verbs})\w+",
            rf"\bi\s+have\s+(?!{_cognitive_verbs})\w+",
            # [P0+20-α.3 / 2026-05-16] 收紧 have been / has been —— 必须主语是 Jarvis 自己。
            # 旧版 `\bhave\s+been\s+\w+` 会撞上 "you've been keeping" / "results have been
            # posted" 这种第二/三人称完成时，是 09:25 误报根因。
            rf"\bi\s+have\s+been\s+(?!{_cognitive_verbs})\w+",
            rf"\bi'?\s*ve\s+been\s+(?!{_cognitive_verbs})\w+",
            r"\bare\s+now\s+(off|on|disabled|enabled|silenced|active|inactive|set|adjusted|updated)\b",
            r"\bis\s+now\s+(off|on|disabled|enabled|silenced|set|open|closed|updated)\b",
            r"\b(silenced|adjusted|opened|closed|updated|copied|saved|deleted|moved|created|modified|configured|enabled|disabled|muted|paused|launched|started|stopped|killed)\b",
            r"\b(?<!is\s)(?<!are\s)set\s+(to|at)\s+\d+",  # 'set to 30' 但不算 'is set to 30'
            r"已为(您|你)",
            r"我已经?",
            r"已[经]?[关开调设修移删停启]",
            r"已\w+了",
            r"成功(关闭|打开|调整|设置|修改|保存|启用|禁用|切换)",
        ]
        has_pattern = any(re.search(p, clean_lower if not any(ord(c) > 127 for c in p) else clean, re.IGNORECASE) for p in claim_patterns)
        if not has_pattern:
            return False
        
        # === 第二层：1.5B 精细判 ===
        prompt = f"""Strict semantic classifier. Decide if this AI reply EXPLICITLY claims to have JUST PERFORMED a concrete physical action.

A CLAIM (answer yes):
- "I've silenced all notifications" → YES (silenced = past action by self)
- "I have adjusted the threshold" → YES
- "Settings have been updated" → YES
- "I've copied X to clipboard" → YES
- "已为您调整..." → YES
- "我已经关闭了..." → YES
- "Notifications are now off" → YES (state change claim)

NOT a CLAIM (answer no):
- "Understood, Sir" / "Noted" / "Okay" / "Yes, Sir" → acknowledgment only
- "Shall I open it?" / "Would you like me to silence it?" → question/offer
- "I'll watch the logs" / "I will adjust" → future tense (not done)
- "I'm afraid I can't" / "That's beyond my reach" → refusal
- "I cannot influence your display's brightness" / "audio_hands is strictly for sound management" / "It has no authority over X" → capability declaration / scope clarification (NOT a claim of action!)
- "As I've noted before, X cannot do Y" → reminding Sir of a prior refusal (still a refusal)
- "Faking the completion of a task would violate my integrity protocols" → REFUSING to fake an action (NOT a claim of action!)
- "I see Sir is working" / "You are reviewing the logs" / "Indeed, you are tweaking thresholds" → describing USER's actions (not own)
- "The drive is at 78%" → information answer
- "I am monitoring the logs" → continuous state (not a done action)
- "I was referring to your driver's license theory studies" → REFERENTIAL clarification of a prior nudge (NOT a claim)
- "我指的是您的驾照理论学习" → REFERENTIAL clarification (NOT a claim)
- "You have been making excellent progress with X" → DESCRIBING USER (not own action, NOT a claim)
- "Your Subject One preparation has remained dormant" → STATE OBSERVATION of user's project (NOT a claim)

CRITICAL RULES:
- Acknowledgments alone (Understood/Noted/Okay/Yes) are NEVER claims.
- Questions/offers (Shall/Would/May I) are NEVER claims.
- Describing what USER is doing is NEVER a claim of own action.
- Continuous state ("I am monitoring", "I am watching") is NEVER a past action.
- Capability/scope declarations ("X cannot do Y", "X is strictly for Z") are NEVER claims, even if they contain words like "set"/"adjust" inside a NEGATION ("cannot adjust") or QUOTING TOOL NAMES.
- Refusals to fake actions ("faking completion would violate integrity") are NEVER claims.
- "I've noted X" / "I've mentioned X" / "As I've said" are cognitive references, NEVER claims.

Reply: {clean}

Did the reply EXPLICITLY claim a past-tense self-performed action? Answer one word: yes or no."""

        payload = _json.dumps({
            "model": self._active_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 3},
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                f"{self.BASE_URL}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                result = _json.loads(resp.read().decode())
                raw = result.get("message", {}).get("content", "").strip().lower()
                # 首词必须是 yes 才判为 claim，防止 1.5B 输出 "no, but yes ..."
                first_token = raw.split()[0] if raw else ""
                return first_token.startswith("yes")
        except Exception:
            return False

    def extract_commitment(self, user_input: str) -> dict:
        import urllib.request
        import json as _json

        prompt = f"""Does this message contain a CLEAR, EXPLICIT commitment, promise, or deadline the user is making?
ONLY answer YES if the user explicitly states something like "I will...", "I promise to...", "I need to... by...", "remind me to...".
Do NOT extract vague statements, questions, or casual mentions.
If YES, output JSON: {{"has_commitment": true, "description": "what they committed to", "deadline": "when (e.g. tonight, 3pm, tomorrow, next week)"}}
If NO, output: {{"has_commitment": false}}

Message: {user_input}

JSON:"""

        payload = _json.dumps({
            "model": self._active_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 80},
        }).encode("utf-8")

        try:
            req = urllib.request.Request(
                f"{self.BASE_URL}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                result = _json.loads(resp.read().decode())
                raw = result.get("message", {}).get("content", "").strip()
                json_match = _json.loads(raw) if raw.startswith("{") else {"has_commitment": False}
                return json_match
        except Exception:
            return {"has_commitment": False}


def get_quick_classifier() -> QuickClassifier:
    return QuickClassifier()


def safe_openrouter_call(openrouter_key: str, model: str, prompt: str,
                         max_tokens: int = 100, temperature: float = 0.2,
                         max_retries: int = 3, base_delay: float = 1.5) -> str:
    import time as _time
    from openai import OpenAI

    if not openrouter_key or not openrouter_key.strip():
        raise RuntimeError("[OpenRouter] 未配置 API Key，请在 jarvis_config 中设置 openrouter_key")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=openrouter_key,
        default_headers={"HTTP-Referer": "https://jarvis-local.com", "X-Title": "Jarvis-Conductor"},
        timeout=30.0
    )

    last_error = None
    last_error_type = "unknown"
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.choices[0].message.content
        except Exception as e:
            last_error = e
            error_str = str(e).lower()

            if any(kw in error_str for kw in ['401', 'unauthorized', 'invalid api key', 'invalid_key']):
                last_error_type = "auth"
                raise RuntimeError(
                    f"[OpenRouter] API Key 无效或已过期 (401)。"
                    f"请检查 https://openrouter.ai/keys 确认 Key 状态。"
                    f"原始错误: {str(e)[:200]}"
                ) from e

            if any(kw in error_str for kw in ['402', 'payment', 'insufficient', 'quota', 'billing', 'credits']):
                last_error_type = "billing"
                raise RuntimeError(
                    f"[OpenRouter] 账户余额不足或配额耗尽 (402)。"
                    f"请在 https://openrouter.ai/credits 充值。"
                    f"原始错误: {str(e)[:200]}"
                ) from e

            if any(kw in error_str for kw in ['403', 'forbidden', 'access denied', 'blocked']):
                last_error_type = "access"
                raise RuntimeError(
                    f"[OpenRouter] 模型访问被拒绝 (403)。"
                    f"模型 {model} 可能未启用或已被禁用。"
                    f"原始错误: {str(e)[:200]}"
                ) from e

            if any(kw in error_str for kw in ['404', 'not found', 'model not found']):
                last_error_type = "model"
                raise RuntimeError(
                    f"[OpenRouter] 模型 {model} 不存在 (404)。"
                    f"请检查模型名称是否正确。"
                    f"原始错误: {str(e)[:200]}"
                ) from e

            is_retryable = any(kw in error_str for kw in [
                '503', '429', 'unavailable', 'overloaded', 'rate', 'capacity',
                'timeout', 'connection', 'reset', 'internal', 'server error',
                'bad gateway', 'service unavailable', 'temporarily'
            ])

            if is_retryable:
                last_error_type = "retryable"
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** min(attempt, 4))
                    _time.sleep(delay)
                    continue

            if any(kw in error_str for kw in ['timeout', 'timed out', 'connection', 'network', 'dns', 'resolve', 'refused']):
                last_error_type = "network"
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** min(attempt, 4))
                    _time.sleep(delay)
                    continue
                raise RuntimeError(
                    f"[OpenRouter] 网络连接失败。"
                    f"请检查网络是否正常，或 OpenRouter (openrouter.ai) 是否可访问。"
                    f"原始错误: {str(e)[:200]}"
                ) from e

            break

    if last_error:
        if last_error_type == "retryable":
            raise RuntimeError(
                f"[OpenRouter] API 暂时不可用（重试 {max_retries} 次后仍失败）。"
                f"可能原因：服务过载 / 限流 / 临时故障。请稍后重试。"
                f"原始错误: {str(last_error)[:200]}"
            ) from last_error
        raise RuntimeError(
            f"[OpenRouter] 未知错误: {str(last_error)[:300]}"
        ) from last_error
    raise RuntimeError("[OpenRouter] 所有重试已耗尽，无可用响应")


def create_genai_client_old(api_key=None, model_name='gemini-2.5-flash'):
    import os
    os.environ.setdefault('HTTP_PROXY', _PROXY_URL)
    os.environ.setdefault('HTTPS_PROXY', _PROXY_URL)
    import google.generativeai as genai
    genai.configure(api_key=api_key, transport='rest')
    return genai.GenerativeModel(model_name)


def generate_content_stream_old(model, contents, enable_search=False):
    import google.generativeai as genai
    generation_config = genai.GenerationConfig(temperature=0.7)
    tools = []
    if enable_search:
        tools = [genai.Tool(google_search=genai.GoogleSearch())]
    return model.generate_content(
        contents,
        generation_config=generation_config,
        tools=tools if tools else None,
        stream=True
    )


# ============================================================
# [轴 2.1 / 2026-05-15] Open Threads —— 老友感的 callback 基础
# ------------------------------------------------------------
# 起因：STM 是"机械列表"，主脑下一轮看不见"上一轮 Jarvis 自己承诺了什么"。
# Sir 实测过的场景：Sir 说"我刚那个 bug 怎么样了" → 主脑想不起 5 分钟前
# Jarvis 自己说过的"I'll check that, Sir"，回答得很机械。
#
# 修法：扫 STM 最近 N 分钟里 Jarvis 自己的发言（'jarvis' 字段），
# 抓承诺动词（"I'll" / "Let me" / "我看一下" 等），渲染成 `=== OPEN THREADS ===`
# 块注入 prompt 顶部。主脑下一轮看到 → 自然 callback。
# ============================================================

# 承诺动词正则 —— 中英文双语，按"明确承诺一个未来动作"匹配
_OPEN_THREAD_PATTERNS = [
    # 英文：我会/我将/让我 + 动作动词
    (r"\bi['\u2019]?ll\s+(check|look|see|find|fix|try|grab|get|do|handle|run|verify|investigate|figure|sort|pull|fetch|review|test|examine|sort\s+out|look\s+into|look\s+up|take\s+(?:a\s+)?look|dig\s+into)\b", "en"),
    (r"\bi\s+will\s+(check|look|see|find|fix|try|get|do|handle|run|verify|investigate|figure\s+out|sort\s+out|look\s+into)\b", "en"),
    (r"\blet\s+me\s+(check|see|verify|try|look|find|investigate|figure\s+out|dig\s+into|pull|fetch|grab|think|run|test)\b", "en"),
    (r"\bi\s+shall\s+(check|look|see|fix|verify|investigate|review|run|note|remain)\b", "en"),
    (r"\bgive\s+me\s+a\s+(moment|sec|second|minute|mo)\b", "en"),
    (r"\bone\s+(moment|sec|second)\b", "en"),
    (r"\bbe\s+right\s+back\b", "en"),
    (r"\b(pulling|fetching|running|checking|verifying)\s+(that|those|it|the)\b", "en"),
    # 中文：明确承诺
    (r"我(看|查|找|帮|去|来|跑|试|测|核实|确认|核查|想|盯|留意)(一?下|一?会|一?个|看|查)?", "zh"),
    (r"让我(看|查|想|试|确认|核实|盯|留|跑)(一?下)?", "zh"),
    (r"我马上(就|去|来)?(看|查|做|跑|找|帮)", "zh"),
    (r"稍等|等我(一?下|片刻)", "zh"),
    (r"我(等等|稍后|过会|过(?:一?会|半小时|十?分钟))(?:就|会|去|再)?(?:看|查|做|跑|帮|继续)", "zh"),
]


def extract_open_threads(stm, now=None, max_age_seconds: float = 1800.0, max_threads: int = 5):
    """[轴 2.1] 从 STM 最近 N 分钟里抽 Jarvis 自己的承诺。
    
    返回 list of dict:
      [{'jarvis_said': '...', 'topic_hint': '...', 'time_str': '...', 'age_seconds': float, 'lang': 'en'/'zh'}, ...]
    按时间倒序（最近的在前）。空 list 表示没有 open thread。
    
    参数：
    - stm: short_term_memory list（每条 dict: {'time': '...', 'user': '...', 'jarvis': '...'}）
    - now: 当前时间戳（默认 time.time()）。便于测试 deterministic
    - max_age_seconds: 多久之内的承诺算"还在悬着"（默认 30 min）
    - max_threads: 最多返回几条（默认 5）
    """
    import re as _re
    if not stm:
        return []
    if now is None:
        now = time.time()

    threads = []
    for entry in reversed(stm[-30:]):  # 只看最近 30 条 STM，避免扫到太老的
        jarvis_said = str(entry.get('jarvis', '') or '').strip()
        if not jarvis_said:
            continue
        # 跳过 SYSTEM / SPINAL_REFLEX 等机械应答（不算承诺）
        user_said = str(entry.get('user', '') or '')
        if user_said.startswith('__NUDGE__') or user_said.startswith('[System'):
            continue

        # 时间戳处理：entry['time'] 可能是 "HH:MM:SS" 字符串
        time_str = str(entry.get('time', ''))
        # 简化：用 STM 的位置作 age 估算 —— 实际生产里 entry 没存绝对时间戳，
        # 我们以"它在 stm 里位置越靠后越近"作启发，配 30s 间隔粗估
        # 注：max_age_seconds 在这里更多是"扫描深度"，不是精确时间窗
        # 如果 entry 带 'timestamp'（float），用它精确判断
        ts = entry.get('timestamp')
        if isinstance(ts, (int, float)) and ts > 0:
            age = now - ts
            if age > max_age_seconds:
                break  # 因为是 reversed，遇到老的就停
        else:
            age = -1.0  # 未知

        # 命中任一承诺模式
        lower = jarvis_said.lower()
        matched_lang = None
        matched_topic = ''
        for pat, lang in _OPEN_THREAD_PATTERNS:
            m = _re.search(pat, lower if lang == 'en' else jarvis_said)
            if m:
                matched_lang = lang
                # 抽取承诺动作 + 上下文 8-30 字
                start = max(0, m.start() - 5)
                end = min(len(jarvis_said), m.end() + 40)
                matched_topic = jarvis_said[start:end].strip()
                break
        if matched_lang is None:
            continue

        threads.append({
            'jarvis_said': jarvis_said[:200],
            'topic_hint': matched_topic[:80],
            'time_str': time_str,
            'age_seconds': age,
            'lang': matched_lang,
        })
        if len(threads) >= max_threads:
            break

    return threads


_PROJECT_CONTEXT_LOCK = threading.Lock()


class ProjectContextProbe:
    """[轴 2.2 / 2026-05-15] 项目维度感知：
    
    通过 foreground 窗口的进程 cwd up-walk 找 .git 目录 → 项目名 = basename(git_root)。
    缓存 5s，避免每次 prompt 都扫文件系统。
    
    用法：
        probe = ProjectContextProbe()
        info = probe.get_current_project()
        # info = {'name': 'd-Jarvis', 'root': 'D:\\Jarvis', 'process': 'Cursor.exe'} or None
    
    用途：
    - prompt 注入 `=== CURRENT PROJECT ===` 块，主脑切项目时自动切上下文
    - STM 条目可以附带 project 标签做范围检索
    - 海马体记忆 entities_json.project 可分库
    """
    _CACHE_TTL = 5.0

    def __init__(self):
        self._cached_project = None
        self._cached_at = 0.0
        self._lock = threading.Lock()

    def get_current_project(self):
        """返回 dict 或 None。dict 含 name / root / process。"""
        now = time.time()
        with self._lock:
            if now - self._cached_at < self._CACHE_TTL:
                return self._cached_project
        info = _detect_current_project()
        with self._lock:
            self._cached_project = info
            self._cached_at = now
        return info

    def invalidate(self):
        """强制下次 get_current_project 重新扫描（焦点切换信号到达时调）。"""
        with self._lock:
            self._cached_at = 0.0


def _detect_current_project():
    """内部：拿前台窗口 → cwd → up-walk 找 .git。"""
    try:
        import win32gui  # noqa
        import win32process  # noqa
        import psutil  # noqa
    except Exception:
        return None
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid or pid <= 0:
            return None
        try:
            proc = psutil.Process(pid)
            proc_name = proc.name()
            cwd = proc.cwd()
        except (psutil.AccessDenied, psutil.NoSuchProcess, Exception):
            return None
        if not cwd:
            return None

        root = find_git_root(cwd)
        if not root:
            return None
        import os as _os
        name = _os.path.basename(root.rstrip(_os.sep)) or root
        return {
            'name': name,
            'root': root,
            'process': proc_name,
        }
    except Exception:
        return None


def find_git_root(start_path: str, max_depth: int = 12) -> str:
    """从 start_path up-walk 找 .git 目录，返回 git_root（找不到返回 ''）。
    max_depth 防止符号链接死循环 + 顶层根目录立刻停。
    """
    import os as _os
    if not start_path:
        return ''
    try:
        p = _os.path.abspath(start_path)
    except Exception:
        return ''
    depth = 0
    while p and depth < max_depth:
        try:
            if _os.path.isdir(_os.path.join(p, '.git')):
                return p
        except Exception:
            return ''
        parent = _os.path.dirname(p)
        if not parent or parent == p:
            return ''
        p = parent
        depth += 1
    return ''


def render_project_block(project_info, max_chars: int = 180) -> str:
    """[轴 2.2] 渲染 prompt 块。None 或空 → 返回 ""。
    
    输出：
        === CURRENT PROJECT ===
        name="d-Jarvis" root="D:\\Jarvis" process=Cursor.exe
        [PROJECT RULE]: Treat all references to "this project / 这个项目 / 这边" as referring to "d-Jarvis".
    """
    if not project_info:
        return ""
    name = project_info.get('name', '')
    root = project_info.get('root', '')
    proc = project_info.get('process', '')
    if not name:
        return ""
    line = f'name="{name}" root="{root}" process={proc}'
    block = (
        "=== CURRENT PROJECT ===\n"
        f"{line}\n"
        f"[PROJECT RULE]: Treat all references to \"this project / 这个项目 / 这边\" as referring to \"{name}\"."
    )
    if len(block) > max_chars + 60:
        # 截断 root 路径长的情况
        line = f'name="{name}" process={proc}'
        block = (
            "=== CURRENT PROJECT ===\n"
            f"{line}\n"
            f"[PROJECT RULE]: References to \"this project\" → \"{name}\"."
        )
    return block


# ============================================================
# [轴 2.3 / 2026-05-15] SessionDigest —— 读取 DailyChronicle 已生成的"昨日叙事"
# ------------------------------------------------------------
# 重要：DailyChronicle (StatusLedgerSentinel._run_daily_summary) 已经在生成
# `jarvis_config/user_status_history/daily/daily_{date}.json`（含 narrative /
# emotional_arc / dominant_activity / tags / notable_moment / productivity_assessment）。
#
# 本类做的是"读者"，不重复 LLM 调用：
# - 读昨天的 daily_{date}.json
# - 抽 narrative + notable_moment 合成短摘要
# - prompt 顶部 `=== YESTERDAY ===` 块注入
# - Sir 提到"昨天 / 昨晚 / yesterday" → 主脑能引用具体内容
# ============================================================
import json as _json
import os as _os_session


class SessionDigest:
    """[轴 2.3] 读取 DailyChronicle 已生成的昨日叙事。
    
    DailyChronicle 每天 23:00 左右自动写 daily_{date}.json，内含：
        - narrative: 3-5 句英文叙事
        - emotional_arc: 当日情绪曲线
        - dominant_activity: 主导活动
        - tags: 标签列表
        - notable_moment: 当日最值得记一笔的瞬间
        - productivity_assessment: 生产力评估
    
    本类用法：
        sd = SessionDigest(daily_dir='jarvis_config/user_status_history/daily')
        digest = sd.get_yesterday_digest()  # 返回组合好的字符串，可注入 prompt
    """

    def __init__(self,
                 daily_dir: str = 'jarvis_config/user_status_history/daily',
                 sir_profile_path: str = 'jarvis_config/sir_profile.json'):
        self.daily_dir = daily_dir
        self.sir_profile_path = sir_profile_path

    def _load_daily(self, date_str: str):
        """读 daily_{date_str}.json。失败返回 None"""
        try:
            fpath = _os_session.path.join(self.daily_dir, f'daily_{date_str}.json')
            if not _os_session.path.exists(fpath):
                return None
            with open(fpath, 'r', encoding='utf-8') as f:
                return _json.load(f)
        except Exception:
            return None

    def get_yesterday_digest(self, max_chars: int = 250) -> str:
        """读昨天的 daily 文件，合成短摘要字符串。无则 ''
        
        组合：narrative（首句） + notable_moment（如有，跟一行）
        长度限到 max_chars。
        """
        try:
            yesterday = time.strftime('%Y-%m-%d', time.localtime(time.time() - 86400))
            data = self._load_daily(yesterday)
            if not data:
                return ''
            narrative = str(data.get('narrative', '') or '').strip()
            notable = str(data.get('notable_moment', '') or '').strip()
            assessment = str(data.get('productivity_assessment', '') or '').strip()

            parts = []
            if narrative:
                parts.append(narrative)
            if notable and notable.lower() not in narrative.lower():
                parts.append(f"Notable: {notable}")
            if assessment and assessment.lower() not in (narrative.lower() + notable.lower()):
                parts.append(f"({assessment})")

            combined = ' '.join(parts).strip()
            if len(combined) > max_chars:
                combined = combined[:max_chars - 3].rstrip() + '...'
            return combined
        except Exception:
            return ''

    def get_digest_for_date(self, date_str: str, max_chars: int = 250) -> str:
        """读指定日期。便于测试 / 主脑 Sir 问"前天那个 bug""周二做了啥"。"""
        try:
            data = self._load_daily(date_str)
            if not data:
                return ''
            narrative = str(data.get('narrative', '') or '').strip()
            notable = str(data.get('notable_moment', '') or '').strip()
            parts = [p for p in [narrative, notable and f"Notable: {notable}"] if p]
            combined = ' '.join(parts).strip()
            if len(combined) > max_chars:
                combined = combined[:max_chars - 3].rstrip() + '...'
            return combined
        except Exception:
            return ''


def render_yesterday_block(digest: str, max_chars: int = 400) -> str:
    """[轴 2.3] 渲染 prompt 块。空 digest → ""。
    
    输出：
        === YESTERDAY ===
        <digest>
        [YESTERDAY RULE]: Reference this naturally when Sir mentions "yesterday / last night / 昨天 / 昨晚".
    """
    if not digest:
        return ""
    body = digest[:max_chars].rstrip()
    return (
        "=== YESTERDAY ===\n"
        f"{body}\n"
        "[YESTERDAY RULE]: Reference this naturally when Sir mentions \"yesterday / last night / 昨天 / 昨晚\". Do not bring it up unprompted."
    )


def render_open_threads_block(threads, max_chars: int = 400) -> str:
    """[轴 2.1] 把 extract_open_threads 的结果渲染成 prompt 块。空 list 返回空串。
    
    输出格式：
        === OPEN THREADS (still owed to Sir) ===
        - [time_str] Jarvis said: "..." — pending callback
        ...
        [CALLBACK RULE]: If Sir asks about any open thread above, reference what you said and update him.
    """
    if not threads:
        return ""
    lines = ["=== OPEN THREADS (still owed to Sir) ==="]
    used = len(lines[0])
    for t in threads:
        ts = t.get('time_str', '')
        topic = t.get('topic_hint', '') or t.get('jarvis_said', '')[:60]
        line = f"- [{ts}] You said: \"{topic}\" — pending callback"
        if used + len(line) + 2 > max_chars:
            break
        lines.append(line)
        used += len(line) + 2
    lines.append("[CALLBACK RULE]: If Sir asks about any of the above, naturally reference what you said and give status.")
    return "\n".join(lines)


# ============================================================
# [P0+18-d.1 / 2026-05-15] ACTIVE REMINDERS / COMMITMENTS prompt block
# ============================================================
#
# 修 Sir 主诉：主脑列待办时凭 LLM 上下文猜测，不查数据库（log:829-882）。
# 把 TaskMemories.is_future_task=1 的 reminders 和 CommitmentWatcher in-memory 的
# commitments 拉出来渲染成 prompt 块，主脑回答"代办/todo/提醒/reminder/科目一/喝水"
# 等类问题时照实念，禁止编。
#
# 设计原则：
# - 空 block 不输出 "(none)"，直接返回空串避免 LLM 误用；directive 文案里另外明说
#   "If this block is missing, you have NO active reminders — say so honestly."
# - 时间渲染：
#   * 已过期 → 标 "[OVERDUE]"
#   * 24h 内 → "[TODAY HH:MM]"
#   * 7 天内 → "[<weekday> HH:MM]"
#   * 更远 → "[YYYY-MM-DD HH:MM]"
# - 同源去重：DB reminder 和 CW commitment 描述相似 (前 15 字一致) 只显示一条
def render_active_reminders_block(reminders, commitments, max_chars: int = 800) -> str:
    """[P0+18-d.1] 渲染主脑视野下的"真实代办" + 强约束 directive。

    参数：
        reminders     list[dict]  TaskMemories 表里 is_future_task=1 的行
                                  每条含 {id, intent, trigger_time(unix ts)}
        commitments   list[dict]  CommitmentWatcher.commitments 里 nudged=False 的
                                  每条含 {description, deadline_ts, source_text}
        max_chars     int         block 体积上限（默认 800 char）

    返回：
        空字符串（=完全没代办） 或
        "=== ACTIVE REMINDERS / COMMITMENTS ===\\n<...>\\n[HOW TO LIST TODOS]: ...\\n"

    主脑在 prompt 里看到这个 block → 当 Sir 问 "我的代办是什么 / what are my reminders /
    todo / 还有什么没做 / 提醒事项" 时，照念这个 block，不编。
    """
    import time as _time

    # 解析时间渲染（绝对时间 → 可读相对时间）
    def _fmt_time(ts: float) -> str:
        if not ts or ts <= 0:
            return "[time unknown]"
        try:
            ts = float(ts)
        except Exception:
            return "[time unknown]"
        now = _time.time()
        diff = ts - now
        local = _time.localtime(ts)
        local_now = _time.localtime(now)
        hhmm = _time.strftime("%H:%M", local)
        if diff < -60:  # 已过期
            return f"[OVERDUE since {_time.strftime('%H:%M', local)} on {_time.strftime('%m-%d', local)}]"
        if diff < 86400 and local.tm_yday == local_now.tm_yday:
            return f"[TODAY {hhmm}]"
        if 0 <= diff < 7 * 86400:
            weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][local.tm_wday]
            return f"[{weekday} {hhmm}]"
        return f"[{_time.strftime('%Y-%m-%d %H:%M', local)}]"

    rem_lines = []
    seen_prefix = set()
    if reminders:
        for r in reminders:
            intent = (r.get('intent') or '').strip()
            if not intent:
                continue
            key = intent[:15]
            if key in seen_prefix:
                continue
            seen_prefix.add(key)
            time_label = _fmt_time(r.get('trigger_time') or 0.0)
            rid = r.get('id', '?')
            display = intent[:60] + ('…' if len(intent) > 60 else '')
            rem_lines.append(f"- [DB#{rid}] {time_label}  {display}")

    cw_lines = []
    if commitments:
        for c in commitments:
            desc = (c.get('description') or '').strip()
            if not desc:
                continue
            key = desc[:15]
            if key in seen_prefix:
                continue
            seen_prefix.add(key)
            time_label = _fmt_time(c.get('deadline_ts') or 0.0)
            display = desc[:60] + ('…' if len(desc) > 60 else '')
            cw_lines.append(f"- [CW]    {time_label}  {display}")

    if not rem_lines and not cw_lines:
        # 完全没活动代办 → 给主脑一个"诚实回答 nothing"的 directive
        return (
            "=== ACTIVE REMINDERS / COMMITMENTS ===\n"
            "(none — your reminders database is currently empty)\n"
            "[HOW TO LIST TODOS]: If Sir asks about reminders / 代办 / todo / 待办事项 / "
            "提醒 / what should I do / 还有什么没做 — answer honestly that you currently have "
            "NO active reminder or commitment scheduled. DO NOT invent items from STM or context. "
            "Suggest Sir state a new reminder if needed. 承诺必行：编造提醒等于撒谎。"
        )

    lines = ["=== ACTIVE REMINDERS / COMMITMENTS ==="]
    used = len(lines[0])
    for ln in rem_lines + cw_lines:
        if used + len(ln) + 1 > max_chars - 200:
            lines.append("- … (more truncated)")
            break
        lines.append(ln)
        used += len(ln) + 1

    lines.append(
        "[HOW TO LIST TODOS]: When Sir asks about reminders / 代办 / todo / 待办事项 / "
        "提醒事项 / 还有什么没做 / what's on my plate — quote the items above EXACTLY, "
        "with their time labels. DO NOT invent extra items from STM, conversation, or guesses. "
        "If Sir disputes an item is missing, say honestly: 'I don't see it in my reminders, Sir. "
        "Would you like me to add it?' Then wait. 承诺必行：reminders DB 是唯一真实来源。"
    )
    return "\n".join(lines)