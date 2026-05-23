# -*- coding: utf-8 -*-
"""[P0+19-9 / 2026-05-16] Jarvis UI — PyQt5 + OpenGL 视觉层

从 jarvis_nerve.py 拆出 2 个 UI 类：
  - SubtitleOverlay (413 行) — 字幕覆盖窗口
  - BreathingLightUI (279 行) — 呼吸灯 OpenGL 渲染窗口

依赖：
- PyQt5.QtWidgets.QWidget / QApplication
- PyQt5.QtCore: Qt / QTimer / pyqtSignal
- PyQt5.QtGui: QPainter / QColor / QRadialGradient
- PyQt5.QtOpenGL.QOpenGLWidget
- PyOpenGL (glVertex2f / glEnd / glUseProgram / 等)

向后兼容：jarvis_nerve.py 用 `from jarvis_ui import ...` 转发。
"""

from __future__ import annotations

# [P0+19-final fix 4 / 2026-05-16] 一次性补全标准库 + 第三方常用 import（防 NameError 暴露）
import os  # noqa: F401
import sys  # noqa: F401
import io  # noqa: F401
import re  # noqa: F401
import time  # noqa: F401
import json  # noqa: F401
import math  # noqa: F401
import random  # noqa: F401
import queue  # noqa: F401
import sqlite3  # noqa: F401
import hashlib  # noqa: F401
import threading  # noqa: F401
import collections  # noqa: F401
import importlib  # noqa: F401
import concurrent.futures  # noqa: F401
import multiprocessing  # noqa: F401
from collections import defaultdict, deque  # noqa: F401
from dataclasses import dataclass, field  # noqa: F401
from typing import List, Dict, Any, Optional, Tuple  # noqa: F401
try:
    from google.genai import types  # noqa: F401
except ImportError:
    pass


import math
import time
import queue

from PyQt5.QtWidgets import QWidget, QApplication  # noqa: F401
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRectF, QRect, QPointF, QPoint, QSize, QSizeF  # noqa: F401 [P0+19-final fix 3] QRectF 等绘图坐标类
from PyQt5.QtGui import QPainter, QColor, QRadialGradient, QFont, QPen, QBrush, QLinearGradient, QFontMetrics, QPolygonF  # noqa: F401 [P0+19-final fix] QFont 等字幕 UI 用

# QOpenGLWidget 跨版本 import 兼容
try:
    from PyQt5.QtOpenGL import QOpenGLWidget  # noqa: F401
except ImportError:
    try:
        from PyQt5.QtWidgets import QOpenGLWidget  # noqa: F401
    except ImportError:
        QOpenGLWidget = QWidget  # 退化

# OpenGL
try:
    from OpenGL.GL import *  # noqa: F401, F403
except ImportError:
    pass  # 没装 PyOpenGL 时 BreathingLightUI 会跑时报错

class SubtitleOverlay(QWidget):
    MAX_HEIGHT = 420
    MIN_HEIGHT = 60
    BASE_WIDTH = 560

    def __init__(self, orb_widget):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.orb = orb_widget
        self.subtitle_queue = queue.Queue()
        self._last_update = 0
        self._opacity = 0.0
        self._target_opacity = 0.0
        self._focus_mode = False

        self.subtitle_enabled = True
        self.orb_enabled = True

        self._zh_text = ""
        self._zh_scroll_offset = 0
        self._zh_scroll_max = 0
        self._zh_scroll_timer_active = False

        self._en_words = []
        self._en_reveal_count = 0
        self._word_timer_active = False

        self._user_text = ""
        self._user_text_time = 0

        self._en_font = QFont("Consolas", 11, QFont.Bold)
        self._zh_font = QFont("Microsoft YaHei", 12, QFont.Bold)
        self._user_font = QFont("Microsoft YaHei", 9)

        self._cached_height = self.MIN_HEIGHT
        self.setFixedSize(self.BASE_WIDTH, self.MIN_HEIGHT)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_queue)
        self._poll_timer.start(80)

        self._word_timer = QTimer(self)
        self._word_timer.timeout.connect(self._reveal_next_word)

        self._zh_scroll_timer = QTimer(self)
        self._zh_scroll_timer.timeout.connect(self._zh_scroll_step)

        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._fade_step)
        self._fade_timer.start(50)

        self._sync_pos()
        self.hide()

    def _sync_pos(self):
        orb_geo = self.orb.geometry()
        screen = QApplication.primaryScreen().geometry()
        x = orb_geo.x() + orb_geo.width() // 2 - self.width() // 2
        x = max(10, min(x, screen.width() - self.width() - 10))
        y = orb_geo.y() - self.height() + 40
        self.move(x, max(0, y))

    def set_focus_mode(self, active: bool):
        if active and not self._focus_mode:
            self._focus_mode = True
            self._target_opacity = 1.0
            self._sync_pos()
            self.show()
        elif not active and self._focus_mode:
            self._focus_mode = False
            self._target_opacity = 0.0
            self._zh_text = ""
            self._zh_scroll_offset = 0
            self._zh_scroll_max = 0
            self._en_words = []
            self._en_reveal_count = 0
            self._user_text = ""
            self._word_timer.stop()
            self._word_timer_active = False
            self._zh_scroll_timer.stop()
            self._zh_scroll_timer_active = False
            self._last_update = 0

    def show_user_speech(self, text: str):
        self._user_text = text
        self._user_text_time = time.time()
        self._last_update = time.time()
        self.update()

    def _poll_queue(self):
        changed = False
        try:
            while True:
                item = self.subtitle_queue.get_nowait()
                if not isinstance(item, tuple) or len(item) != 2:
                    continue
                lang, text = item
                if lang == "control":
                    if text == "subtitle_on":
                        self.subtitle_enabled = True
                        self._target_opacity = 1.0 if self._focus_mode else self._target_opacity
                        self._sync_pos()
                        self.show()
                        self.update()
                    elif text == "subtitle_off":
                        self.subtitle_enabled = False
                        self._target_opacity = 0.0
                    elif text == "orb_on":
                        self.orb_enabled = True
                        self.orb.show()
                    elif text == "orb_off":
                        self.orb_enabled = False
                        self.orb.hide()
                    continue
                if lang == "clear":
                    # [R7-β1/post-test v2] 不立即清空文本，先开启淡出动画
                    # 文本会在 _fade_step 检测到 _opacity ≤ 0 时才真正清空
                    # （视觉上是字幕"渐隐消失"，而非"瞬间空白"）
                    self._word_timer.stop()
                    self._word_timer_active = False
                    self._zh_scroll_timer.stop()
                    self._zh_scroll_timer_active = False
                    if not self._focus_mode:
                        self._target_opacity = 0.0
                        # 不重置 _last_update —— 让 _fade_step 立刻开始淡出
                        # （之前 _last_update = 0 会重置 fade 触发条件，导致动画路径异常）
                    else:
                        # 焦点模式下"clear" 通常配合 focus=False 一起来；
                        # 单独 clear 时把内容清掉但保持 opacity
                        self._zh_text = ""
                        self._zh_scroll_offset = 0
                        self._zh_scroll_max = 0
                        self._en_words = []
                        self._en_reveal_count = 0
                        self._last_update = 0
                    changed = False
                    break
                elif lang == "zh":
                    if not self.subtitle_enabled:
                        continue
                    # 🩹 [β.5.36-H / 2026-05-20] scrub 工具名 / <TOOL_CALL> tag 防漏给 Sir 看到
                    try:
                        from jarvis_utils import scrub_internal_names as _scrub
                        text = _scrub(text)
                    except Exception:
                        pass
                    self._zh_text = text
                    self._zh_scroll_offset = 0
                    self._zh_scroll_max = 0
                    self._zh_scroll_timer.stop()
                    self._zh_scroll_timer_active = False
                    changed = True
                elif lang == "en":
                    if not self.subtitle_enabled:
                        continue
                    # 🩹 [β.5.36-H / 2026-05-20] scrub 工具名 / <TOOL_CALL> tag 防漏给 Sir 看到
                    try:
                        from jarvis_utils import scrub_internal_names as _scrub
                        text = _scrub(text)
                    except Exception:
                        pass
                    # [R7-β post-test v3] 跨轮 / 距上次更新 > 8s 时，认为是新一轮回复，先清空再 extend
                    # 这是 Sir 实测吐槽"字是不断累加的"的根因 —— 多轮对话 / nudge 触发不会推 user 事件
                    # 导致 _en_words 一直长。这里用时间戳兜底：超过 8s 的间隔视作新轮。
                    # [v5 Sir 反馈"英文打印不完整"] 3.0 → 8.0：云端慢响应两句之间间隔可达 4-7s
                    # （CRITICAL / DEEP_QUERY 档常见），3s 阈值会把第一句"提前清掉"造成截断假象。
                    # 8s 仍然足够清"上一轮残留"（用户讲话间隔 / nudge 间隔通常 >> 8s）。
                    if self._last_update > 0 and time.time() - self._last_update > 8.0:
                        self._en_words = []
                        self._en_reveal_count = 0
                        self._zh_text = ""
                        self._zh_scroll_offset = 0
                        self._zh_scroll_max = 0
                    new_words = text.split()
                    self._en_words.extend(new_words)
                    if not self._word_timer_active:
                        self._word_timer_active = True
                        interval = max(40, min(100, 600 // max(len(new_words), 1)))
                        self._word_timer.start(interval)
                    changed = True
                elif lang == "user":
                    # [R7-β5] ASR 完成后的用户文本（替换 listening… 状态）
                    if self.subtitle_enabled:
                        # [R7-β1/post-test] 每次新一轮用户输入到来时，清空旧的英文/中文字幕，
                        # 避免连续对话时字幕一直累加（旧设计 _en_words.extend，没人清）
                        self._en_words = []
                        self._en_reveal_count = 0
                        self._zh_text = ""
                        self._zh_scroll_offset = 0
                        self._zh_scroll_max = 0
                        self._word_timer.stop()
                        self._word_timer_active = False
                        self._zh_scroll_timer.stop()
                        self._zh_scroll_timer_active = False
                        self.show_user_speech(text)
                        changed = True
                elif lang == "listening_start":
                    # [R7-β5] 用户刚开口（声波超阈值），显示听感状态条
                    if self.subtitle_enabled:
                        self.show_user_speech("Listening…")
                        changed = True
                elif lang == "listening_done":
                    # [R7-β5] ASR 完成或丢弃。如果 text 非空则保留（用户文本会接管），
                    # 空则清空 listening 状态。
                    if self.subtitle_enabled and not text:
                        self._user_text = ""
                        self.update()
                        changed = True
                elif lang == "focus":
                    # [R7-β5/兼容修] focus 模式切换信号（α5 之前未消费）
                    try:
                        self.set_focus_mode(bool(text))
                        changed = True
                    except Exception:
                        pass
                elif lang == "silent_nudge":
                    # [R7-β5/兼容修] α5 SILENT_TEXT 通道：飘字幕不出声
                    if self.subtitle_enabled and text:
                        # 用 user 通道把"轻推"展示出来，让 Sir 能看见
                        self.show_user_speech(f"💭 {text}")
                        changed = True
                elif lang == "visual_pulse":
                    # [轴 1.5 / 2026-05-15] α5 VISUAL_PULSE 通道终于接通：
                    # 之前是占位 pass（事件被静默丢）→ 现在调 orb.flash_pulse(nudge_type)
                    # 让 BreathingLightUI 真正金光呼吸 1.2s 再回基线
                    # text 就是 nudge_type 字符串（'background_brief' / 'task_handoff_ready' 等）
                    try:
                        orb = getattr(self, 'orb', None)
                        if orb is not None and hasattr(orb, 'flash_pulse'):
                            orb.flash_pulse(str(text) if text else 'gold')
                            try:
                                from jarvis_utils import bg_log
                                bg_log(f"✨ [VisualPulse] flash_pulse({text}) → BreathingLight 1.2s")
                            except Exception:
                                pass
                    except Exception:
                        pass
        except queue.Empty:
            pass
        if changed:
            self._last_update = time.time()
            self._target_opacity = 1.0
            self._sync_pos()
            self._recalc_height()
            self.show()
            self.update()

    def _reveal_next_word(self):
        if self._en_reveal_count < len(self._en_words):
            self._en_reveal_count += 1
            self._last_update = time.time()
            self._recalc_height()
            self.update()
        else:
            self._word_timer.stop()
            self._word_timer_active = False

    def _recalc_height(self):
        from PyQt5.QtGui import QFontMetrics
        pad_x = 16
        pad_y = 10
        total_h = 0

        if self._user_text and time.time() - self._user_text_time < 15.0:
            fm = QFontMetrics(self._user_font)
            rect = fm.boundingRect(0, 0, self.BASE_WIDTH - pad_x * 2, 80,
                                   Qt.AlignLeft | Qt.TextWordWrap, self._user_text)
            total_h += rect.height() + 4

        if self._zh_text:
            fm = QFontMetrics(self._zh_font)
            rect = fm.boundingRect(0, 0, self.BASE_WIDTH - pad_x * 2, 2000,
                                   Qt.AlignLeft | Qt.TextWordWrap, self._zh_text)
            zh_h = rect.height()
            if zh_h > 160:
                self._zh_scroll_max = zh_h - 140
                if not self._zh_scroll_timer_active:
                    self._zh_scroll_timer_active = True
                    self._zh_scroll_timer.start(2500)
                zh_h = 140
            else:
                self._zh_scroll_max = 0
                self._zh_scroll_timer.stop()
                self._zh_scroll_timer_active = False
            total_h += zh_h + 4

        if self._en_reveal_count > 0:
            fm = QFontMetrics(self._en_font)
            visible = " ".join(self._en_words[:self._en_reveal_count])
            rect = fm.boundingRect(0, 0, self.BASE_WIDTH - pad_x * 2, 2000,
                                   Qt.AlignLeft | Qt.TextWordWrap, visible)
            total_h += rect.height() + 4

        new_h = max(self.MIN_HEIGHT, min(self.MAX_HEIGHT, int(total_h + pad_y * 2 + 4)))
        if new_h != self._cached_height:
            self._cached_height = new_h
            self.setFixedSize(self.BASE_WIDTH, new_h)
            self._sync_pos()

    def _zh_scroll_step(self):
        if self._zh_scroll_max <= 0:
            self._zh_scroll_timer.stop()
            self._zh_scroll_timer_active = False
            return
        self._zh_scroll_offset += 1
        if self._zh_scroll_offset >= self._zh_scroll_max:
            self._zh_scroll_timer.stop()
            self._zh_scroll_timer_active = False
        self.update()

    def _fade_step(self):
        target = self._target_opacity
        if not self._focus_mode and self._last_update > 0 and time.time() - self._last_update > 6.0:
            target = 0.0

        if abs(self._opacity - target) < 0.005:
            self._opacity = target
            if self._opacity <= 0 and not self._focus_mode:
                self.hide()
                self._zh_text = ""
                self._zh_scroll_offset = 0
                self._zh_scroll_max = 0
                self._en_words = []
                self._en_reveal_count = 0
                self._user_text = ""
                self._last_update = 0
                self._zh_scroll_timer.stop()
                self._zh_scroll_timer_active = False
        else:
            if self._opacity < target:
                self._opacity = min(target, self._opacity + 0.04)
            else:
                self._opacity = max(target, self._opacity - 0.03)
            self.update()

    def paintEvent(self, event):
        if self._opacity <= 0.005:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        w, h = self.width(), self.height()
        pad_x = 16
        pad_y = 10
        y = pad_y

        lines = []

        if self._user_text and time.time() - self._user_text_time < 15.0:
            user_age = time.time() - self._user_text_time
            user_alpha = max(0.3, 1.0 - user_age / 15.0)
            lines.append(("user", self._user_text, user_alpha, 0))

        if self._zh_text:
            lines.append(("zh", self._zh_text, 1.0, self._zh_scroll_offset))

        if self._en_reveal_count > 0:
            visible = " ".join(self._en_words[:self._en_reveal_count])
            lines.append(("en", visible, 1.0, 0))

        if not lines:
            p.end()
            return

        line_heights = []
        total_h = 0
        for kind, text, alpha, scroll_offset in lines:
            if kind == "user":
                p.setFont(self._user_font)
            elif kind == "zh":
                p.setFont(self._zh_font)
            else:
                p.setFont(self._en_font)
            max_width = w - pad_x * 2
            rect = p.boundingRect(pad_x, 0, max_width, 2000,
                                  Qt.AlignLeft | Qt.TextWordWrap, text)
            full_h = rect.height()
            if kind == "zh" and self._zh_scroll_max > 0:
                display_h = min(full_h, 140)
            else:
                display_h = full_h
            line_heights.append(display_h)
            total_h += display_h + 4

        bg_h = total_h + pad_y * 2 - 4
        bg_rect = QRectF(4, 2, w - 8, bg_h)

        # 🆕 [P5-fix79 BUG-U / 2026-05-23 21:46] Sir 21:43 真测痛点:
        # 字幕在白色背景 (Windsurf 白文档) 完全看不清字 — user 绿/zh 浅灰白/en 青色
        # 都是浅色 + 背景 alpha 200/255 (78% 不够暗) → 白底透出 → 失对比.
        # 修法 (3 处): 背景 alpha 200→245 加深, 字色加饱和度, 所有字加 1px 黑色描边.
        p.setBrush(QColor(6, 8, 16, int(245 * self._opacity)))
        p.setPen(QPen(QColor(0, 180, 220, int(120 * self._opacity)), 1))
        p.drawRoundedRect(bg_rect, 8, 8)

        p.setPen(QPen(QColor(0, 180, 220, int(40 * self._opacity)), 1))
        p.drawLine(QPointF(pad_x, 2), QPointF(w - pad_x, 2))

        def _draw_text_outlined(painter, rect, flags, text_str, fill_color, outline_alpha=220):
            """画文字带 1px 黑色描边 (poor-man stroke)."""
            outline_qc = QColor(0, 0, 0, int(outline_alpha * self._opacity))
            painter.save()
            painter.setPen(outline_qc)
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1),
                            (-1, -1), (1, -1), (-1, 1), (1, 1)):
                shifted = QRectF(rect.x() + dx, rect.y() + dy,
                                  rect.width(), rect.height())
                painter.drawText(shifted, flags, text_str)
            painter.restore()
            painter.setPen(fill_color)
            painter.drawText(rect, flags, text_str)

        for i, (kind, text, alpha, scroll_offset) in enumerate(lines):
            if kind == "user":
                p.setFont(self._user_font)
                _fill = QColor(160, 240, 180, int(255 * self._opacity * alpha))
            elif kind == "zh":
                p.setFont(self._zh_font)
                _fill = QColor(245, 245, 250, int(255 * self._opacity))
            else:
                p.setFont(self._en_font)
                _fill = QColor(80, 230, 255, int(255 * self._opacity))

            display_h = line_heights[i]
            if kind == "zh" and self._zh_scroll_max > 0:
                p.save()
                clip_rect = QRectF(pad_x, y, w - pad_x * 2, display_h)
                p.setClipRect(clip_rect)
                text_rect = QRectF(pad_x, y - scroll_offset, w - pad_x * 2,
                                    display_h + self._zh_scroll_max + 20)
                _draw_text_outlined(p, text_rect, Qt.AlignLeft | Qt.TextWordWrap, text, _fill)
                p.restore()
            else:
                text_rect = QRectF(pad_x, y, w - pad_x * 2, display_h + 4)
                _draw_text_outlined(p, text_rect, Qt.AlignLeft | Qt.TextWordWrap, text, _fill)
            y += display_h + 4

        p.end()


class BreathingLightUI(QOpenGLWidget):
    def __init__(self):
        super().__init__()
        # 保持无边框、置顶、透明背景，并开启“鼠标物理穿透 (Mouse Passthrough)”
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(300, 300)
        self.move(1500, 750) 

        self.state = "IDLE"
        self.is_awake = False
        self.start_time = time.time()

        # 🚀 物理引擎：当前状态值 (初始化为绝对安静的 1/4 状态)
        self.current_scale = 0.15
        self.current_speed = 0.4
        self.current_color_mix = 0.0

        # 🎯 物理引擎：目标状态值
        self.target_scale = 0.15       # 1. 待机态：四分之一大小
        self.target_speed = 0.4
        self.target_color_mix = 0.0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(30) # 约 33fps 丝滑帧率

        self._debounce_until = 0.0
        self._pending_state = None
        self._pending_awake = None

        # [轴 1.5 / 2026-05-15] VISUAL_PULSE 通道实现 —— α5 设计的"金光呼吸"真正接通
        # 之前 BreathingLightUI 不读 subtitle_queue，subtitle_queue.put(("visual_pulse", ...)) 直接被丢
        # 现在 SubtitleOverlay._poll_queue 收到 visual_pulse 事件 → 调 orb.flash_pulse(kind)
        # 这是 R8 轴 4.2 后台测试守护 + 轴 3.x 任务接管就绪 的视觉前提
        self._pulse_active = False
        self._pulse_start_time = 0.0
        self._pulse_duration = 1.2
        self._pulse_target_scale = 0.40
        self._pulse_target_color_mix = 0.85
        self._pulse_target_speed = 1.4

    def flash_pulse(self, kind: str = 'gold'):
        """[轴 1.5] 触发一次 VISUAL_PULSE：1.2s 内 scale + color_mix + speed 临时 spike，自动回基线。
        
        kind 选项（来自 NudgeChannel 的 nudge_type）：
        - 'gold' / 'background_brief' / 'task_handoff_ready' → 暖金色（默认）
        - 'amber' → 偏橙色（紧急提示用）
        - 'lavender' → 浅紫（柔和提示用）
        
        线程安全：必须在 Qt 主线程调（SubtitleOverlay._poll_queue 由 QTimer 触发，符合）。
        与 paintGL 阻尼插值兼容：直接改 target_*，由 paintGL 渐进过渡，视觉柔和。
        """
        try:
            self._pulse_active = True
            self._pulse_start_time = time.time()

            if kind in ('gold', 'task_handoff_ready', 'background_brief', None, ''):
                self._pulse_target_scale = 0.42
                self._pulse_target_color_mix = 0.85
                self._pulse_target_speed = 1.4
            elif kind == 'amber':
                self._pulse_target_scale = 0.38
                self._pulse_target_color_mix = 0.95
                self._pulse_target_speed = 1.6
            elif kind == 'lavender':
                self._pulse_target_scale = 0.36
                self._pulse_target_color_mix = 0.65
                self._pulse_target_speed = 1.2
            else:
                # 未知 kind → 走默认暖金
                self._pulse_target_scale = 0.40
                self._pulse_target_color_mix = 0.80
                self._pulse_target_speed = 1.4

            # 直接顶高 target，由 paintGL 阻尼系数 0.005-0.01 渐进过渡
            self.target_scale = self._pulse_target_scale
            self.target_color_mix = self._pulse_target_color_mix
            self.target_speed = self._pulse_target_speed
        except Exception:
            pass

    def set_awake_status(self, status: bool):
        now = time.time()
        if now < self._debounce_until:
            self._pending_awake = status
            return
        self._debounce_until = now + 0.2
        self.is_awake = status
        self._update_targets()
        if self._pending_awake is not None and self._pending_awake != status:
            pending = self._pending_awake
            self._pending_state = None
            self._pending_awake = None
            self.is_awake = pending
            self._update_targets()

    def change_state(self, new_state: str):
        now = time.time()
        if now < self._debounce_until:
            self._pending_state = new_state
            return
        self._debounce_until = now + 0.2
        self.state = new_state
        self._update_targets()
        if self._pending_state and self._pending_state != new_state:
            pending = self._pending_state
            self._pending_state = None
            self._pending_awake = None
            self.state = pending
            self._update_targets()

    def _update_targets(self):
        """核心控制器：重构的极简比例尺"""
        # [轴 1.5 / 2026-05-15] VISUAL_PULSE 期间不被状态机覆盖
        # pulse 进行中（1.2s 内）保持 spike 目标值；超时后由 paintGL 重新调度
        if getattr(self, '_pulse_active', False):
            return

        if self.state == "IDLE":
            if self.is_awake:
                self.target_scale = 0.35
                self.target_speed = 1.2
                self.target_color_mix = 0.0
            else:
                self.target_scale = 0.15
                self.target_speed = 0.4
                self.target_color_mix = 0.0
        elif self.state == "MAIL_PENDING":
            self.target_scale = 0.18
            self.target_speed = 0.6
            self.target_color_mix = 0.4
            
        # 👇 核心新增：独立的 THINKING 状态！
        elif self.state == "THINKING":
            # 思考态：光球微微收缩，转速适中，呈现冷色与暖色的交界状态
            self.target_scale = 0.22        
            self.target_speed = 0.7         
            self.target_color_mix = 0.3     
            
        elif self.state == "RECOGNIZING":
            # 聆听态：稍大一点，转速变快，准备捕捉声音
            self.target_scale = 0.28
            self.target_speed = 1.5
            self.target_color_mix = 0.5
            
        else: # EXECUTING (说话态)
            self.target_scale = 0.35
            self.target_speed = 1.0
            self.target_color_mix = 1.0

    def initializeGL(self):
        # 顶点：只负责撑开一张画布，没有任何几何突起！
        VERTEX_SHADER = """
        #version 120
        void main() { gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex; }
        """
        # 片段：真正的纯平 Siri 流体魔法（琥珀色深邃版）
        FRAGMENT_SHADER = """
        #version 120
        uniform float iTime;
        uniform vec2 iResolution;
        uniform float uScale;
        uniform float uSpeed;
        uniform float uColorMix;

        void main() {
            // 坐标归一化并居中
            vec2 uv = (gl_FragCoord.xy - 0.5 * iResolution.xy) / min(iResolution.x, iResolution.y);
            uv /= uScale; 

            float radius = length(uv);
            
            // 🛡️ 将整体面具的羽化拉长，从 0.2 就开始变柔，边缘更加没有塑料感
            float mask = smoothstep(0.50, 0.20, radius); 

            if (mask <= 0.0) {
                gl_FragColor = vec4(0.0);
                return;
            }

            // 🌊 内部流体力学：保留你最喜欢的这套三层正弦波
            float wave1 = sin(uv.x * 5.0 + iTime * uSpeed) * 0.5 + 0.5;
            float wave2 = sin((uv.x + uv.y) * 4.0 - iTime * uSpeed * 0.8) * 0.5 + 0.5;
            float wave3 = sin((uv.x - uv.y) * 6.0 + iTime * uSpeed * 1.2) * 0.5 + 0.5;

            // 🎨 配色方案 A：贾维斯深邃蓝 (底色调暗、调深)
            vec3 colorBlue = vec3(0.0, 0.25, 0.9); // 更浓郁的深蓝
            vec3 colorCyan = vec3(0.0, 0.7, 1.0);
            vec3 finalIdle = mix(colorBlue, colorCyan, wave1);

            // 🎨 配色方案 B：全新 iOS 18 Siri 撞色 (琥珀色登场)
            vec3 speakColor1 = vec3(1.0, 0.0, 0.4); // 深洋红 (降低发白)
            vec3 speakColor2 = vec3(1.0, 0.6, 0.0); // 🌟 琥珀色 (Amber) 代替紫色
            vec3 speakColor3 = vec3(0.0, 0.9, 0.8); // 青绿色
            
            // 三色交织
            vec3 finalSpeak = mix(speakColor1, speakColor2, wave1);
            finalSpeak = mix(finalSpeak, speakColor3, wave2);

            // 🔄 Lerp 颜色混合
            vec3 finalColor = mix(finalIdle, finalSpeak, uColorMix);

            // 💡 核心手术点：向心能量衰减场 (Core Glow Falloff)
            float coreConstraint = smoothstep(0.40, 0.0, radius); 
            
            // 把波浪高光与向心衰减相乘
            float energy = (wave1 * wave2 * wave3) * 2.5 * coreConstraint; 
            
            // 🌑 深邃化处理：降低过曝的高光白度，让色彩本身更浓郁
            finalColor += finalColor * energy * 0.35; 

            // 稍微提升基础 Alpha 值，让深色部分依然有存在感
            float alpha = mask * (0.55 + energy * 0.45);

            gl_FragColor = vec4(finalColor, alpha);
        }
        """
        self.shader = shaders.compileProgram(
            shaders.compileShader(VERTEX_SHADER, GL_VERTEX_SHADER),
            shaders.compileShader(FRAGMENT_SHADER, GL_FRAGMENT_SHADER)
        )

    def paintGL(self):
        now = time.time()
        # [轴 1.5] VISUAL_PULSE 到期 → 解除 pulse + 回到状态机基线
        if getattr(self, '_pulse_active', False):
            if now - self._pulse_start_time >= self._pulse_duration:
                self._pulse_active = False
                # 重新走 _update_targets 拉回 state/awake 决定的基线
                self._update_targets()

        if now >= self._debounce_until and (self._pending_state is not None or self._pending_awake is not None):
            if self._pending_state is not None:
                self.state = self._pending_state
                self._pending_state = None
            if self._pending_awake is not None:
                self.is_awake = self._pending_awake
                self._pending_awake = None
            self._update_targets()

        glClearColor(0, 0, 0, 0)
        glClear(GL_COLOR_BUFFER_BIT)
        glEnable(GL_BLEND)
        # 使用原生 Alpha 混合，边缘更加纯净自然
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        # 🏎️ 阻尼插值引擎 (Lerp)：将阻尼系数调至极低，实现极其缓慢柔和的“粘滞”流体过渡
        self.current_scale += (self.target_scale - self.current_scale) * 0.01
        self.current_speed += (self.target_speed - self.current_speed) * 0.005
        self.current_color_mix += (self.target_color_mix - self.current_color_mix) * 0.01

        glUseProgram(self.shader)

        # 将物理参数送入 GPU
        time_loc = glGetUniformLocation(self.shader, "iTime")
        glUniform1f(time_loc, time.time() - self.start_time)

        res_loc = glGetUniformLocation(self.shader, "iResolution")
        glUniform2f(res_loc, self.width(), self.height())

        scale_loc = glGetUniformLocation(self.shader, "uScale")
        glUniform1f(scale_loc, self.current_scale)

        speed_loc = glGetUniformLocation(self.shader, "uSpeed")
        glUniform1f(speed_loc, self.current_speed)

        color_loc = glGetUniformLocation(self.shader, "uColorMix")
        glUniform1f(color_loc, self.current_color_mix)

        # 展开画布
        glBegin(GL_QUADS)
        glVertex2f(-1.0, -1.0)
        glVertex2f( 1.0, -1.0)
        glVertex2f( 1.0,  1.0)
        glVertex2f(-1.0,  1.0)
        glEnd()
        glUseProgram(0)


# [P0+19-final fix 5 / 2026-05-16] 全量跨模块类引用兜底（try/except 防循环依赖）
try:
    from jarvis_safety import *  # noqa: F401, F403
except Exception:
    pass
try:
    from jarvis_key_router import KeyRouter  # noqa: F401
except Exception:
    pass
try:
    from jarvis_llm_reflector import LlmReflector  # noqa: F401
except Exception:
    pass
try:
    from jarvis_env_probe import PhysicalEnvironmentProbe  # noqa: F401
except Exception:
    pass
try:
    from jarvis_sensors import (  # noqa: F401
        FunnelLogger, SensorFilter, HabitClock, CausalChain,
        ProjectTimeline, SubconsciousMailbox,
    )
except Exception:
    pass
try:
    from jarvis_routing import (  # noqa: F401
        SoulRouter, ContextRouter, ContentPreferenceTracker, ProfileCard,
        PromptCenter, GuardianCenter, CompanionCenter,
    )
except Exception:
    pass
try:
    from jarvis_memory_core import (  # noqa: F401
        PromptLayer, PromptCache, CorrectionEntry, CorrectionMemory,
        MemoryFragment, UnifiedMemoryGateway, FeedbackTracker,
        TaskWorkerPool, Anticipator, CorrectionLoop, SleepIntentDetector,
        HumorMemory,
    )
except Exception:
    pass
try:
    from jarvis_sentinels import (  # noqa: F401
        ChronosTick, ChronosSentinel, SystemSentinel, SoulArchivistSentinel,
        NudgeGate, UserStatusLedgerSentinel, ScreenshotSentinel,
        WellnessGuardian, ReflectionScheduler,
    )
except Exception:
    pass
try:
    from jarvis_conductor import Conductor  # noqa: F401
except Exception:
    pass
try:
    from jarvis_return_sentinel import ReturnSentinel  # noqa: F401
except Exception:
    pass
try:
    from jarvis_commitment_watcher import CommitmentWatcher  # noqa: F401
except Exception:
    pass
try:
    from jarvis_smart_nudge import SmartNudgeSentinel  # noqa: F401
except Exception:
    pass
try:
    from jarvis_chat_bypass import ChatBypass, _C3_ACTION_HAND_COMMANDS  # noqa: F401
except Exception:
    pass
try:
    from jarvis_blood import (  # noqa: F401
        JarvisBlood, ExecutionResult, FeedbackSignal, Action, PerceptionData, TaskSnapshot,
    )
except Exception:
    pass
try:
    from jarvis_hippocampus import Hippocampus  # noqa: F401
except Exception:
    pass
try:
    from jarvis_vocal_cord import VocalCord  # noqa: F401
except Exception:
    pass
try:
    from jarvis_enhanced import ProactiveShield, SkillTreeTracker, ProactiveCompanion  # noqa: F401
except Exception:
    pass
try:
    from jarvis_skill_registry import (  # noqa: F401
        SkillRegistry, SkillManifest, OfferGuard, PromiseExecutor, PromiseActivator,
        get_registry,
    )
except Exception:
    pass
try:
    from l1_right_brain import RightBrain  # noqa: F401
except Exception:
    pass
try:
    from l3_left_brain import LeftBrain  # noqa: F401
except Exception:
    pass
try:
    from l5_reflection_brain import ReflectionBrain  # noqa: F401
except Exception:
    pass
try:
    from jarvis_utils import (  # noqa: F401
        bg_log, set_conversation_active, is_conversation_active,
        register_jarvis_tts, is_recent_jarvis_echo, clear_jarvis_tts_ring,
        safe_gemini_call, safe_openrouter_call, create_genai_client,
        get_local_fallback, QuickClassifier, get_quick_classifier,
        ConversationEventBus, JarvisState, PlanLedger, WorkingMemoryFeed,
        SessionDigest, ToneSelector, AntiCommonPhraseTracker,
        VerbosityPreferenceTracker, ProjectContextProbe,
        ClipboardWatcher, PSHistoryWatcher, AttentionSlot,
        render_yesterday_block, render_open_threads_block,
        render_active_reminders_block, render_attention_block,
        render_silent_nudge_text, render_project_block,
        extract_open_threads, capture_attention_snapshot,
        resolve_nudge_channel, network_retry, get_rate_limiter,
        get_default_attention_slot, get_default_event_bus,
        get_default_phrase_tracker, get_default_plan_ledger,
        get_default_tone_selector, get_default_verbosity_tracker,
        get_default_working_feed,
    )
except Exception:
    pass

