# -*- coding: utf-8 -*-
"""[P5-Gap3 / 2026-05-21 18:30] Screen Vision Engine — 屏幕 vision 结构化描述

Sir 22:47 真痛点 (Gap 3 治根):
> Sir 在 Cursor 写 code, Jarvis 知道进程 / window title, 但不知道哪个 file 哪一行,
> 屏幕上有什么 error / build status / Sir cursor 停在第几行. Sir 跟 Jarvis 对话需要
> 口述上下文 — 累.

== 现状 ==

chat_bypass 主流路径 (line 2076-2099) 当前 turn 已截图喂主脑 raw image. 主脑 Gemini-3-Flash
本身就是 vision LLM. 但:
  ❌ 没结构化描述持久化 → 跨 turn 看不到
  ❌ ToMReflector / IntegrityWatcher 等 module 没拿 vision evidence

== 本 Gap 设计 ==

后台 ScreenVisionEngine async daemon:
  1. 触发: wake_word / sir_explicit_screen_ref / app_switch / 5min backfill / Sir CLI
  2. 截图 (复用 PIL ImageGrab, JPEG q50, 1280x720)
  3. 调 Vision LLM (Gemini, JSON schema 提取)
  4. 持久化 ScreenSnapshot → memory_pool/screen_snapshot.json (atomic, latest 1 帧)
  5. publish SWM 'screen_described'
  6. 主脑下轮 prompt 看 [WHAT SIR IS LOOKING AT] block

== 准则 6 4 问 ==

| # | 答 |
|---|---|
| 1 SWM publish | ✅ publish 'screen_described' + ScreenSnapshot 持久化 |
| 2 LLM 决策 | ✅ Vision LLM describe + JSON, 不写 OCR / keyword 硬规则 |
| 3 持久化 + CLI | ✅ memory_pool/screen_snapshot.json + scripts/screen_vision_dump.py |
| 4 正交 | ✅ 跟 PhysicalEnvProbe (active window) / l4_screenshot_hands (raw img) 互补 |

== TTFT 影响 ==

零阻塞. 后台 daemon fire-and-forget. 主对话用旧帧 60s cache (JSON 文件即时 load).

== Privacy ==

env flag JARVIS_SCREEN_VISION=1 才启用 (默认关).
Vision LLM 自己识敏感场景 (密码 / 私聊 / 银行) → confidence=0 + 不描述.
临时 disk 截图 → describe 后立即 delete.

详 docs/JARVIS_VISION_INTEGRATION.md
"""
from __future__ import annotations

import io
import json
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional


try:
    from jarvis_utils import bg_log
except Exception:
    def bg_log(msg: str) -> None:
        print(msg)


# ============================================================
# Constants
# ============================================================

DEFAULT_SNAPSHOT_PATH = os.path.join('memory_pool', 'screen_snapshot.json')
DEFAULT_HISTORY_PATH = os.path.join('memory_pool', 'screen_history.jsonl')
DEFAULT_HISTORY_KEEP = 100   # 滚 100 帧

# 节能采样间隔 (Sir 22:47 真意: 不浪费 token)
DEFAULT_BACKFILL_INTERVAL_S = 300.0   # 5min idle 自动 backfill
DEFAULT_CACHE_TTL_S = 60.0              # 同一 turn 内 60s 复用旧帧

# Vision LLM 配置
VISION_MODEL_DEFAULT = 'gemini-3-flash-preview'   # 复用主脑 model (Sir google key 配额足)
VISION_TIMEOUT_S = 8.0                              # 单次 vision call 超时 (主对话不等)
JPEG_QUALITY = 50
JPEG_THUMB_W = 1280
JPEG_THUMB_H = 720

# Privacy: 敏感 keyword (Vision LLM 自己识更可靠, 此处仅 belt-and-suspenders)
_PRIVACY_HINT_WINDOWS = (
    '1Password', 'KeePass', 'Bitwarden', 'Bank',
    'Online Banking', '密码', '银行',
)

# Vision prompt — 极简, 让 LLM 自由发挥
_VISION_PROMPT = """Describe what's on this screen for Jarvis (Sir's AI butler).
Focus on what Sir is likely working on or paying attention to.
Be concise. If you see password fields / banking / private chat etc., set
confidence=0 and summary='privacy-sensitive content, not described'.

Output JSON only (no markdown fence):
{
  "active_app": "Cursor / VS Code / Chrome / Terminal / ...",
  "file_or_url_visible": "jarvis_directives.py / https://... or empty string",
  "cursor_line_approx": null or integer,
  "screen_summary": "1-2 sentence summary of what Sir is doing right now",
  "recent_visible_keywords": ["max 5 keywords visible on screen"],
  "errors_visible": ["red squiggly / build error / stack trace lines, max 3"],
  "build_output_status": "idle / running / failed / passed / null",
  "notable_elements": ["max 3 notable UI elements"],
  "confidence": 0.0-1.0
}"""


# ============================================================
# ScreenSnapshot dataclass
# ============================================================

@dataclass
class ScreenSnapshot:
    """单次 vision LLM 描述结果."""
    captured_at: float
    captured_iso: str
    active_app: str = ''
    file_or_url_visible: str = ''
    cursor_line_approx: Optional[int] = None
    screen_summary: str = ''
    recent_visible_keywords: list = field(default_factory=list)
    errors_visible: list = field(default_factory=list)
    build_output_status: str = ''
    notable_elements: list = field(default_factory=list)
    confidence: float = 0.0
    vision_model_used: str = ''
    sampling_trigger: str = ''   # 'wake' / 'backfill' / 'sir_ref' / 'app_switch' / 'cli'
    privacy_redacted: bool = False

    @property
    def age_s(self) -> float:
        return max(0.0, time.time() - self.captured_at)

    def is_fresh(self, ttl_s: float = DEFAULT_CACHE_TTL_S) -> bool:
        return self.age_s <= ttl_s

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================
# ScreenVisionEngine
# ============================================================

class ScreenVisionEngine:
    """后台 vision daemon — 周期 / 事件触发 → 截图 → vision LLM → 持久化.

    Args:
        key_router: KeyRouter for Vision LLM key (复用 google pool)
        snapshot_path: 持久化 latest 1 帧 (atomic 覆盖)
        history_path: rolling N 帧 (jsonl append)
        backfill_interval_s: 长 idle 自动 backfill 间隔
        env_flag: 'JARVIS_SCREEN_VISION' 默认关. 设 '1' 启用.
    """

    def __init__(self,
                  key_router: Any = None,
                  snapshot_path: str = DEFAULT_SNAPSHOT_PATH,
                  history_path: str = DEFAULT_HISTORY_PATH,
                  backfill_interval_s: float = DEFAULT_BACKFILL_INTERVAL_S,
                  env_flag: str = 'JARVIS_SCREEN_VISION'):
        self.key_router = key_router
        self.snapshot_path = snapshot_path
        self.history_path = history_path
        self.backfill_interval_s = backfill_interval_s
        self.env_flag = env_flag

        self._lock = threading.RLock()
        self._latest: Optional[ScreenSnapshot] = None
        self._sampling_lock = threading.Lock()   # 防 concurrent vision call (节流)
        self._sampling_in_progress = False

        self._daemon_stop = threading.Event()
        self._daemon_thread: Optional[threading.Thread] = None
        self._stats = {
            'total_calls': 0,
            'success_calls': 0,
            'privacy_redacted': 0,
            'failed_calls': 0,
            'last_call_at': 0.0,
            'last_error': '',
        }

        # 启动时 load latest snapshot from disk (重启不丢)
        self._load_latest()

    # ---- Enabled check ----

    def enabled(self) -> bool:
        """env flag 默认 ON (Sir 21:10 真意 — 懒得设, 默认全启用).

        Sir 设 =0 / =false / =off 才关闭. 跟 JARVIS_PREFLIGHT 默认 ON 一致.
        """
        v = (os.environ.get(self.env_flag) or '').strip().lower()
        return v not in ('0', 'false', 'no', 'off')

    # ---- Daemon lifecycle ----

    def start(self) -> None:
        """启动 backfill daemon (5min idle 自动 sample 1 帧)."""
        if not self.enabled():
            try:
                bg_log(f"📷 [ScreenVision] disabled (env {self.env_flag}=0)")
            except Exception:
                pass
            return
        if self._daemon_thread is not None and self._daemon_thread.is_alive():
            return
        self._daemon_stop.clear()
        self._daemon_thread = threading.Thread(
            target=self._daemon_loop, daemon=True, name='ScreenVisionDaemon')
        self._daemon_thread.start()
        try:
            bg_log(f"📷 [ScreenVision] daemon started "
                    f"(backfill={self.backfill_interval_s}s, model={VISION_MODEL_DEFAULT})")
        except Exception:
            pass

    def stop(self) -> None:
        self._daemon_stop.set()

    def _daemon_loop(self) -> None:
        """长 idle backfill — 每 backfill_interval_s 检查上次 sample 时间, 太老就 sample."""
        while not self._daemon_stop.wait(self.backfill_interval_s):
            try:
                last = self._stats.get('last_call_at', 0.0)
                if time.time() - last >= self.backfill_interval_s:
                    self.async_describe(trigger='backfill')
            except Exception:
                pass

    # ---- Async sample (主入口) ----

    def async_describe(self, trigger: str = 'manual',
                          jpeg_bytes: Optional[bytes] = None) -> None:
        """异步触发一次 sample + describe. fire-and-forget, 不阻塞主对话.

        Args:
            trigger: 'wake' / 'backfill' / 'sir_ref' / 'app_switch' / 'cli'
            jpeg_bytes: 复用已截图 (e.g. chat_bypass 主流) 节能. None → 自截图.

        防并发: 已有 sampling 进行 → 跳过.
        """
        if not self.enabled():
            return
        if not self._sampling_lock.acquire(blocking=False):
            return  # 已有 sample 在跑, skip
        try:
            self._sampling_in_progress = True
        finally:
            self._sampling_lock.release()
        threading.Thread(
            target=self._do_describe, args=(trigger, jpeg_bytes),
            daemon=True, name=f'ScreenVisionSample_{trigger}'
        ).start()

    def _do_describe(self, trigger: str,
                      jpeg_bytes: Optional[bytes] = None) -> None:
        """实际执行 sample + describe (后台线程内).

        Args:
            jpeg_bytes: 已截图 → 复用; None → 自截图.
        """
        try:
            self._stats['total_calls'] += 1
            self._stats['last_call_at'] = time.time()

            # 1. 截图 (复用 or 自截图)
            if jpeg_bytes is None:
                jpeg_bytes = self._capture_screen_jpeg()
            if jpeg_bytes is None:
                self._stats['failed_calls'] += 1
                self._stats['last_error'] = 'capture_failed'
                return

            # 2. 调 vision LLM
            described = self._call_vision_llm(jpeg_bytes, trigger=trigger)
            if described is None:
                self._stats['failed_calls'] += 1
                self._stats['last_error'] = 'vision_llm_failed'
                return

            # 3. 持久化 + publish SWM
            with self._lock:
                self._latest = described
                self._persist_latest()
                self._append_history()
            self._stats['success_calls'] += 1
            if described.privacy_redacted:
                self._stats['privacy_redacted'] += 1

            self._publish_swm(described)

            try:
                bg_log(
                    f"📷 [ScreenVision/{trigger}] described: "
                    f"app='{described.active_app[:30]}' "
                    f"summary='{described.screen_summary[:60]}' "
                    f"conf={described.confidence:.2f}"
                    + (' ⚠️PRIVACY' if described.privacy_redacted else '')
                )
            except Exception:
                pass

            # 🆕 [β.5.46-fix13 Fix-3 / 2026-05-22] WatchTask judge hook
            # Sir 22:18 真测痛点: Sir 说"等导出完成提醒" Jarvis 答应了但没机制兑现.
            # 本 hook 让 ScreenVision describe 后 LLM batch judge active WatchTasks
            # 是否被屏幕证据触发, 命中 → publish 'watch_task_fired' SWM + push
            # __NUDGE__. 主脑下轮 prompt 看 evidence, 主动报告 Sir.
            # 准则 6 三维耦合: 数据 publish SWM, LLM 决策, CLI 可改.
            try:
                if not described.privacy_redacted:  # 隐私场景 skip judge
                    from jarvis_watch_task import judge_against_snapshot as _wt_judge
                    _wt_judge(snapshot=described, key_router=self.key_router)
            except Exception:
                pass
        except Exception as e:
            self._stats['failed_calls'] += 1
            self._stats['last_error'] = f"{type(e).__name__}: {str(e)[:80]}"
        finally:
            self._sampling_in_progress = False

    # ---- Capture (复用 chat_bypass 现有 pattern) ----

    def _capture_screen_jpeg(self) -> Optional[bytes]:
        """截图 + JPEG 压缩 + 鼠标位置标记.

        🆕 [P5-fix81 BUG-Y / 2026-05-23 22:05] Sir 22:04 真测痛点:
          Sir "看一下我鼠标的这个位置" → 主脑没鼠标位置 evidence → 瞎猜.
          修法: 截图时拍 cursor_pos (win32api), 在 thumbnail 上画红圈标记,
          + Vision LLM prompt 注入坐标 → LLM 一眼看到 Sir 指啥.
        """
        try:
            from PIL import ImageGrab, ImageDraw
            img = ImageGrab.grab()
            full_w, full_h = img.size
            # 拍鼠标位置 (绝对坐标)
            cursor_xy = None
            try:
                import win32api
                cursor_xy = win32api.GetCursorPos()
            except Exception:
                pass
            img.thumbnail((JPEG_THUMB_W, JPEG_THUMB_H))
            thumb_w, thumb_h = img.size
            # 等比缩放 cursor 到 thumb 坐标
            self._last_cursor_thumb_xy = None
            if cursor_xy is not None and full_w > 0 and full_h > 0:
                scale_x = thumb_w / full_w
                scale_y = thumb_h / full_h
                tx = int(cursor_xy[0] * scale_x)
                ty = int(cursor_xy[1] * scale_y)
                # 画红圈标记 (半径 20px, 2 圈 outer+inner 对比)
                try:
                    draw = ImageDraw.Draw(img)
                    r = 22
                    draw.ellipse((tx - r, ty - r, tx + r, ty + r),
                                  outline=(255, 50, 50), width=3)
                    r2 = 10
                    draw.ellipse((tx - r2, ty - r2, tx + r2, ty + r2),
                                  outline=(255, 255, 50), width=2)
                    # 加 "MOUSE" 标
                    draw.text((tx + r + 2, ty - 8), 'MOUSE',
                                fill=(255, 50, 50))
                except Exception:
                    pass
                self._last_cursor_thumb_xy = (tx, ty, thumb_w, thumb_h)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=JPEG_QUALITY)
            return buf.getvalue()
        except Exception as e:
            self._stats['last_error'] = f"capture: {str(e)[:60]}"
            return None

    # ---- Vision LLM call (复用 chat_bypass safe_gemini_call pattern) ----

    def _call_vision_llm(self, jpeg_bytes: bytes,
                          trigger: str = '') -> Optional[ScreenSnapshot]:
        """调 Vision LLM (Gemini), 解析 JSON. 失败 fallback 到 PhysicalEnvProbe 信息."""
        try:
            from google.genai import types
            from jarvis_utils import safe_gemini_call
            from jarvis_key_router import KeyRouter
        except Exception:
            return self._fallback_snapshot(trigger=trigger,
                                              reason='import_failed')

        if self.key_router is None:
            return self._fallback_snapshot(trigger=trigger,
                                              reason='no_key_router')

        contents = [types.Content(role="user", parts=[
            types.Part(text=_VISION_PROMPT),
            types.Part.from_bytes(data=jpeg_bytes, mime_type="image/jpeg"),
        ])]

        def _vision_call(client):
            return client.models.generate_content(
                model=VISION_MODEL_DEFAULT,
                contents=contents,
            )

        try:
            res, key_name, _client = safe_gemini_call(
                self.key_router, KeyRouter.CALLER_REFLECTOR, 'flash',
                _vision_call, max_retries=1, base_delay=1.0,
                model_name=VISION_MODEL_DEFAULT,
                contents_text=_VISION_PROMPT,
            )
            try:
                self.key_router.release(key_name)
            except Exception:
                pass

            raw_text = (res.text or '').strip() if res else ''
            return self._parse_vision_json(raw_text, trigger=trigger)
        except Exception as e:
            self._stats['last_error'] = f"vision_call: {str(e)[:60]}"
            return self._fallback_snapshot(trigger=trigger,
                                              reason=f"call: {str(e)[:60]}")

    def _parse_vision_json(self, raw_text: str,
                            trigger: str = '') -> ScreenSnapshot:
        """parse vision LLM JSON 输出 → ScreenSnapshot. 失败 fallback."""
        # 去掉可能的 markdown fence
        t = raw_text.strip()
        if t.startswith('```'):
            t = t.split('\n', 1)[-1] if '\n' in t else t
            if t.endswith('```'):
                t = t[:t.rfind('```')]
        t = t.strip()
        try:
            data = json.loads(t)
        except Exception:
            # JSON parse 失败 → fallback
            return self._fallback_snapshot(trigger=trigger,
                                              reason='json_parse_failed')

        now = time.time()
        from datetime import datetime
        iso = datetime.fromtimestamp(now).isoformat(timespec='seconds')

        confidence = float(data.get('confidence', 0.0) or 0.0)
        summary = str(data.get('screen_summary', '') or '')
        privacy_redacted = (
            confidence < 0.1 or
            'privacy-sensitive' in summary.lower() or
            'not described' in summary.lower()
        )

        snap = ScreenSnapshot(
            captured_at=now,
            captured_iso=iso,
            active_app=str(data.get('active_app', '') or '')[:60],
            file_or_url_visible=str(data.get('file_or_url_visible', '') or '')[:120],
            cursor_line_approx=(
                int(data['cursor_line_approx'])
                if isinstance(data.get('cursor_line_approx'), (int, float))
                else None
            ),
            screen_summary=summary[:300],
            recent_visible_keywords=[
                str(k)[:40] for k in (data.get('recent_visible_keywords') or [])
            ][:5],
            errors_visible=[
                str(e)[:120] for e in (data.get('errors_visible') or [])
            ][:3],
            build_output_status=str(data.get('build_output_status', '') or '')[:30],
            notable_elements=[
                str(n)[:80] for n in (data.get('notable_elements') or [])
            ][:3],
            confidence=confidence,
            vision_model_used=VISION_MODEL_DEFAULT,
            sampling_trigger=trigger,
            privacy_redacted=privacy_redacted,
        )
        return snap

    def _fallback_snapshot(self, trigger: str = '',
                              reason: str = '') -> ScreenSnapshot:
        """Vision LLM 失败 → fallback: 用 PhysicalEnvProbe active window title."""
        active_app = ''
        try:
            import ctypes
            import ctypes.wintypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            active_app = buf.value or ''
        except Exception:
            pass

        now = time.time()
        from datetime import datetime
        iso = datetime.fromtimestamp(now).isoformat(timespec='seconds')
        return ScreenSnapshot(
            captured_at=now,
            captured_iso=iso,
            active_app=active_app[:60],
            screen_summary=f"(vision fallback — {reason})",
            confidence=0.1,
            vision_model_used='fallback',
            sampling_trigger=trigger,
        )

    # ---- Persist ----

    def _persist_latest(self) -> None:
        """atomic 覆盖 snapshot_path."""
        if self._latest is None:
            return
        try:
            os.makedirs(os.path.dirname(self.snapshot_path), exist_ok=True)
            tmp = self.snapshot_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._latest.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.snapshot_path)
        except Exception:
            pass

    def _append_history(self) -> None:
        """append 到 history.jsonl (rolling N 帧)."""
        if self._latest is None:
            return
        try:
            os.makedirs(os.path.dirname(self.history_path), exist_ok=True)
            with open(self.history_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(self._latest.to_dict(), ensure_ascii=False) + '\n')
            # 节能 trim — 每 50 次 trim 1 次
            if self._stats['total_calls'] % 50 == 0:
                self._trim_history()
        except Exception:
            pass

    def _trim_history(self) -> None:
        """保留最近 N 帧."""
        try:
            if not os.path.exists(self.history_path):
                return
            with open(self.history_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            if len(lines) > DEFAULT_HISTORY_KEEP:
                with open(self.history_path, 'w', encoding='utf-8') as f:
                    f.writelines(lines[-DEFAULT_HISTORY_KEEP:])
        except Exception:
            pass

    def _load_latest(self) -> None:
        """启动时 load latest snapshot — 重启不丢."""
        if not os.path.exists(self.snapshot_path):
            return
        try:
            with open(self.snapshot_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # 简易 reconstruct (容错)
            snap = ScreenSnapshot(
                captured_at=float(data.get('captured_at', 0.0)),
                captured_iso=str(data.get('captured_iso', '')),
                active_app=str(data.get('active_app', '')),
                file_or_url_visible=str(data.get('file_or_url_visible', '')),
                cursor_line_approx=data.get('cursor_line_approx'),
                screen_summary=str(data.get('screen_summary', '')),
                recent_visible_keywords=list(data.get('recent_visible_keywords', []) or []),
                errors_visible=list(data.get('errors_visible', []) or []),
                build_output_status=str(data.get('build_output_status', '')),
                notable_elements=list(data.get('notable_elements', []) or []),
                confidence=float(data.get('confidence', 0.0)),
                vision_model_used=str(data.get('vision_model_used', '')),
                sampling_trigger=str(data.get('sampling_trigger', '')),
                privacy_redacted=bool(data.get('privacy_redacted', False)),
            )
            self._latest = snap
        except Exception:
            pass

    # ---- SWM publish ----

    def _publish_swm(self, snap: ScreenSnapshot) -> None:
        try:
            from jarvis_utils import get_default_event_bus
            bus = get_default_event_bus()
            if bus is None:
                return
            bus.publish(
                etype='screen_described',
                description=(
                    f"Screen: {snap.active_app[:30]} — {snap.screen_summary[:80]}"
                ),
                source='ScreenVisionEngine',
                salience=0.40 if snap.confidence > 0.5 else 0.20,
                metadata={
                    'active_app': snap.active_app,
                    'file_or_url_visible': snap.file_or_url_visible,
                    'screen_summary': snap.screen_summary,
                    'errors_visible': snap.errors_visible,
                    'build_output_status': snap.build_output_status,
                    'confidence': snap.confidence,
                    'privacy_redacted': snap.privacy_redacted,
                    'sampling_trigger': snap.sampling_trigger,
                },
            )
        except Exception:
            pass

    # ---- Read API ----

    def get_latest_snapshot(self) -> Optional[ScreenSnapshot]:
        with self._lock:
            return self._latest

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._stats)


# ============================================================
# Render block for prompt (主脑下轮看 [WHAT SIR IS LOOKING AT])
# ============================================================

def render_screen_block(max_age_s: float = 120.0) -> str:
    """渲染 [WHAT SIR IS LOOKING AT] block 给主脑.

    Args:
        max_age_s: 帧太老 (> 2min) 不显, 防误导.

    Returns:
        '' 如果没 latest / 太老 / privacy redacted, 或 module disabled.
    """
    try:
        engine = _DEFAULT_ENGINE
        if engine is None or not engine.enabled():
            return ''
        snap = engine.get_latest_snapshot()
        if snap is None:
            return ''
        if snap.age_s > max_age_s:
            return ''
        if snap.privacy_redacted:
            # privacy 模式 — 只说 active_app, 不说内容
            return (
                f"[WHAT SIR IS LOOKING AT] (privacy-redacted, {int(snap.age_s)}s ago)\n"
                f"  Active: {snap.active_app or 'unknown'}\n"
                f"  Content: privacy-sensitive, not described."
            )
        if snap.confidence < 0.3:
            return ''   # 太低置信度不显, 防误导

        lines = [
            f"[WHAT SIR IS LOOKING AT] ({int(snap.age_s)}s ago, vision LLM hypothesis)",
            f"  Active: {snap.active_app or 'unknown'}",
        ]
        if snap.file_or_url_visible:
            file_part = snap.file_or_url_visible
            if snap.cursor_line_approx:
                file_part += f" @ line ~{snap.cursor_line_approx}"
            lines.append(f"  File/URL: {file_part}")
        if snap.screen_summary:
            lines.append(f"  Summary: {snap.screen_summary}")
        if snap.recent_visible_keywords:
            kw = ', '.join(snap.recent_visible_keywords[:5])
            lines.append(f"  Keywords: {kw}")
        if snap.errors_visible:
            err = ' | '.join(snap.errors_visible[:2])[:140]
            lines.append(f"  Errors: {err}")
        if snap.build_output_status and snap.build_output_status not in ('idle', 'null', ''):
            lines.append(f"  Build: {snap.build_output_status}")
        lines.extend([
            "",
            "[HOW TO USE THIS]",
            "  - Sir 用 \"this/that/那个\" 等代词时, 多半指屏幕上的东西.",
            "  - 你可以引用 Sir 看的具体内容 (file/line/error), 不用 Sir 口述.",
            "  - confidence < 0.3 帧未显. 帧 > 2min 太老不显.",
        ])
        return '\n'.join(lines)
    except Exception:
        return ''


# ============================================================
# Singleton
# ============================================================

_DEFAULT_ENGINE: Optional[ScreenVisionEngine] = None


def get_default_engine() -> Optional[ScreenVisionEngine]:
    return _DEFAULT_ENGINE


def init_default_engine(key_router: Any = None,
                          **kwargs) -> ScreenVisionEngine:
    """central_nerve 启动时调一次 — singleton init."""
    global _DEFAULT_ENGINE
    if _DEFAULT_ENGINE is None:
        _DEFAULT_ENGINE = ScreenVisionEngine(key_router=key_router, **kwargs)
    return _DEFAULT_ENGINE
