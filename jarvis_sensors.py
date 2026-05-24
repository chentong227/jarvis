# -*- coding: utf-8 -*-
"""[P0+19-3 / 2026-05-16] Jarvis Sensors — 传感/感知/工具类（无 Thread 子类）

从 jarvis_nerve.py 拆出 6 个类（不含 threading.Thread 子类）：

| Class               | 用途                                                  |
|---------------------|-------------------------------------------------------|
| FunnelLogger        | 智能轻推漏斗判定 logger（命中/拒绝/原因）              |
| SensorFilter        | 28 维传感器矩阵 + LLM 分类兜底的"打扰阻力值"滤波器     |
| HabitClock          | 习惯时钟 — 时段语义 / 凌晨上下文 / 睡眠倾向            |
| CausalChain         | 因果链记忆 — 用户行为 → 系统反应 → 用户反馈           |
| ProjectTimeline     | 项目时间线 — 长跨度任务的"上次干到哪了"反查           |
| SubconsciousMailbox | 潜意识收件箱 — 三级递进提醒 + 心脏起搏器仲裁源        |

依赖：
- 标准库：time / threading / collections / queue / random / re / json
- jarvis_env_probe.PhysicalEnvironmentProbe (SensorFilter 内部用)
- jarvis_utils.bg_log (延迟 import)
- jarvis_llm_reflector.LlmReflector (延迟 import, 用 reflect 接口)

向后兼容：jarvis_nerve.py 用 `from jarvis_sensors import *` 转发，
旧 `from jarvis_nerve import FunnelLogger / SensorFilter / HabitClock /
CausalChain / ProjectTimeline / SubconsciousMailbox` 0 改动。
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


import time
import threading
import collections
import queue  # noqa: F401 — SubconsciousMailbox 可能用
import random  # noqa: F401
import re
import json

from jarvis_env_probe import PhysicalEnvironmentProbe  # SensorFilter / HabitClock 内部用

__all__ = [
    'FunnelLogger',
    'SensorFilter',
    'HabitClock',
    'CausalChain',
    'ProjectTimeline',
    'SubconsciousMailbox',
]


class FunnelLogger:
    _instance = None
    _lock = threading.Lock()

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
        self._log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs', 'funnel_logs')
        os.makedirs(self._log_dir, exist_ok=True)
        self._session_id = time.strftime('%Y%m%d_%H%M%S')
        self._log_path = os.path.join(self._log_dir, f'funnel_{self._session_id}.log')
        self._lock = threading.Lock()
        print(f"[FunnelLogger] 漏斗日志: {self._log_path}")

    def _write(self, text: str):
        with self._lock:
            try:
                with open(self._log_path, 'a', encoding='utf-8') as f:
                    f.write(text + '\n')
            except Exception:
                pass

    def log_layer1_stat(self, deviation_report: dict, snapshot: dict):
        ts = time.strftime('%H:%M:%S')
        lines = [f"\n{'='*60}",
                 f"⏰ {ts} | 漏斗第一层：统计门 (z-score)",
                 f"{'='*60}"]
        lines.append(f"融合分: {PhysicalEnvironmentProbe.compute_fusion_score()}")
        lines.append(f"偏离参数数: {deviation_report.get('deviated_count', 0)}/{deviation_report.get('total_params', 0)}")
        for d in deviation_report.get('deviations', []):
            if d.get('direction') == '状态翻转':
                lines.append(f"  [{d['label']}] z={d['z_score']} | {d['baseline_state']} → {d['current']}")
            else:
                lines.append(f"  [{d['label']}] z={d['z_score']} | {d['baseline_mean']} → {d['current']} ({d['direction']})")
        has_extreme = any(d['z_score'] >= SensorFilter.EXTREME_Z_THRESHOLD for d in deviation_report.get('deviations', []))
        lines.append(f"判定: {'极端偏离→直通第三层' if has_extreme else '进入第二层语义门'}")
        self._write('\n'.join(lines))

    def log_layer2_semantic(self, deviation_report: dict, semantic_result: dict, model: str = "qwen2.5:0.5b"):
        ts = time.strftime('%H:%M:%S')
        lines = [f"\n{'='*60}",
                 f"⏰ {ts} | 漏斗第二层：语义门 ({model})",
                 f"{'='*60}"]
        lines.append(f"输入偏离项数: {len(deviation_report.get('deviations', []))}")
        lines.append(f"语义判断: {semantic_result.get('should_alert', False)}")
        lines.append(f"语义原因: {semantic_result.get('reason', '')}")
        self._write('\n'.join(lines))

    def log_layer3_decision(self, filter_result: dict, decision: dict, prompt: str):
        ts = time.strftime('%H:%M:%S')
        lines = [f"\n{'='*60}",
                 f"⏰ {ts} | 漏斗第三层：决策LLM (gemini-3.1-flash-lite)",
                 f"{'='*60}"]
        lines.append(f"触发原因: {filter_result.get('reason', '')}")
        lines.append(f"融合分趋势: {filter_result.get('fusion_trend', '')}")
        lines.append(f"是否跳过语义门: {filter_result.get('bypass_semantic', False)}")
        lines.append(f"--- 决策LLM输出 ---")
        lines.append(f"should_speak: {decision.get('should_speak', False)}")
        lines.append(f"action: {decision.get('action', '')}")
        lines.append(f"confidence: {decision.get('confidence', 0)}")
        lines.append(f"tone: {decision.get('tone', '')}")
        lines.append(f"nudge_type: {decision.get('nudge_type', '')}")
        lines.append(f"decision_reason: {decision.get('decision_reason', '')}")
        lines.append(f"--- 决策LLM输入(prompt) ---")
        lines.append(prompt[:2000])
        self._write('\n'.join(lines))


class SensorFilter:
    """传感器漏斗：统计门(z-score) + 语义门，替代融合分作为异常触发引擎
    
    三层漏斗：
    第一层(统计门)：滚动基线 z-score，任意参数 z>3.0 直通第三层，偏离数≥1 进入第二层
    第二层(语义门)：小模型批量判断"是否值得关注"，NO→跳过，YES→进入第三层
    """
    BASELINE_SIZE = 10
    EXTREME_Z_THRESHOLD = 3.0

    def __init__(self):
        self._baseline = collections.deque(maxlen=self.BASELINE_SIZE)
        self._fusion_score_history = collections.deque(maxlen=20)
        self._last_filter_time = 0
        self._filter_interval = 30

    def should_trigger(self) -> dict:
        now = time.time()
        if now - self._last_filter_time < self._filter_interval:
            return {"triggered": False, "reason": "冷却中"}
        self._last_filter_time = now

        snapshot = PhysicalEnvironmentProbe.get_sensor_snapshot()
        if not snapshot:
            return {"triggered": False, "reason": "无传感器数据"}

        fusion_score = PhysicalEnvironmentProbe.compute_fusion_score()
        self._fusion_score_history.append({"time": now, "score": fusion_score})

        self._baseline.append(snapshot)
        if len(self._baseline) < 3:
            return {"triggered": False, "reason": "基线数据不足"}

        deviation_report = self._compute_deviations(snapshot)
        if not deviation_report["deviations"]:
            return {"triggered": False, "reason": "无参数偏离"}

        FunnelLogger().log_layer1_stat(deviation_report, snapshot)

        has_extreme = any(d["z_score"] >= self.EXTREME_Z_THRESHOLD for d in deviation_report["deviations"])
        if has_extreme:
            return {
                "triggered": True,
                "bypass_semantic": True,
                "reason": f"极端偏离(z>{self.EXTREME_Z_THRESHOLD})，直通决策层",
                "deviation_report": deviation_report,
                "fusion_score": fusion_score,
                "fusion_trend": self._get_fusion_trend(),
                "snapshot": snapshot,
            }

        semantic_result = self._semantic_gate(deviation_report)
        _model = getattr(self, '_cached_semantic_model', 'qwen2.5:0.5b')
        FunnelLogger().log_layer2_semantic(deviation_report, semantic_result, _model)
        if semantic_result.get("should_alert"):
            return {
                "triggered": True,
                "bypass_semantic": False,
                "reason": f"语义门判断: {semantic_result.get('reason', '')}",
                "deviation_report": deviation_report,
                "semantic_judgment": semantic_result,
                "fusion_score": fusion_score,
                "fusion_trend": self._get_fusion_trend(),
                "snapshot": snapshot,
            }

        return {"triggered": False, "reason": "语义门判断无需关注"}

    def _compute_deviations(self, current: dict) -> dict:
        numeric_sensors = [
            'switch_frequency_5min', 'window_stay_seconds', 'category_entropy',
            'key_press_count_5min', 'backspace_ratio', 'burst_pause_ratio',
            'shortcut_save_5min', 'shortcut_undo_5min',
            'mouse_distance_5min', 'click_count_5min', 'scroll_amount_5min',
            'idle_seconds', 'session_duration_minutes', 'background_distraction_count',
        ]
        binary_sensors = [
            'is_night_time', 'is_first_active_today', 'wechat_has_unread',
            'audio_playing', 'video_editor_open', 'error_visible',
        ]
        sensor_labels = {
            'switch_frequency_5min': '窗口切换频率',
            'window_stay_seconds': '窗口停留时间',
            'category_entropy': '类别熵',
            'key_press_count_5min': '按键数',
            'backspace_ratio': '退格率',
            'burst_pause_ratio': '爆发/暂停比',
            'shortcut_save_5min': 'Ctrl+S次数',
            'shortcut_undo_5min': 'Ctrl+Z次数',
            'mouse_distance_5min': '鼠标移动距离',
            'click_count_5min': '点击次数',
            'scroll_amount_5min': '滚动量',
            'idle_seconds': '空闲时间',
            'session_duration_minutes': '会话时长',
            'background_distraction_count': '后台干扰数',
            'is_night_time': '深夜模式',
            'is_first_active_today': '今日首次活跃',
            'wechat_has_unread': '微信未读',
            'audio_playing': '音频播放',
            'video_editor_open': '视频编辑器',
            'error_visible': '屏幕报错',
        }

        deviations = []
        for sensor in numeric_sensors:
            values = [s.get(sensor, 0) for s in self._baseline if s]
            if len(values) < 3:
                continue
            mean_val = sum(values) / len(values)
            variance = sum((v - mean_val) ** 2 for v in values) / len(values)
            std_val = math.sqrt(variance) if variance > 0 else 0.001
            current_val = current.get(sensor, 0)
            z = abs(current_val - mean_val) / std_val
            if z >= 1.5:
                deviations.append({
                    "sensor": sensor,
                    "label": sensor_labels.get(sensor, sensor),
                    "current": round(current_val, 2),
                    "baseline_mean": round(mean_val, 2),
                    "z_score": round(z, 2),
                    "direction": "上升" if current_val > mean_val else "下降",
                })

        for sensor in binary_sensors:
            current_val = current.get(sensor, False)
            past_vals = [s.get(sensor, False) for s in self._baseline if s]
            if len(past_vals) < 3:
                continue
            past_ratio = sum(1 for v in past_vals if v) / len(past_vals)
            if bool(current_val) != (past_ratio > 0.5):
                deviations.append({
                    "sensor": sensor,
                    "label": sensor_labels.get(sensor, sensor),
                    "current": current_val,
                    "baseline_state": "通常为True" if past_ratio > 0.5 else "通常为False",
                    "z_score": 2.0,
                    "direction": "状态翻转",
                })

        return {
            "deviations": deviations,
            "total_params": len(numeric_sensors) + len(binary_sensors),
            "deviated_count": len(deviations),
        }

    def _resolve_semantic_model(self) -> str:
        if hasattr(self, '_cached_semantic_model'):
            return self._cached_semantic_model
        try:
            import urllib.request, json as _json
            req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = _json.loads(resp.read().decode())
                models = {m["name"] for m in data.get("models", [])}
                for candidate in ["qwen2.5:1.5b", "qwen2.5:0.5b"]:
                    if candidate in models:
                        self._cached_semantic_model = candidate
                        return candidate
        except Exception:
            pass
        self._cached_semantic_model = "qwen2.5:0.5b"
        return "qwen2.5:0.5b"

    def _semantic_gate(self, deviation_report: dict) -> dict:
        deviations = deviation_report.get("deviations", [])
        if not deviations:
            return {"should_alert": False, "reason": "无偏离"}

        change_lines = []
        for d in deviations:
            if d.get("direction") == "状态翻转":
                change_lines.append(f"· {d['label']}: {d['baseline_state']} → 当前为{d['current']}")
            else:
                change_lines.append(
                    f"· {d['label']}: {d['baseline_mean']} → {d['current']} "
                    f"(z={d['z_score']}, {d['direction']})"
                )
        change_text = "\n".join(change_lines)

        prompt = f"""判断以下传感器参数变化是否值得关注。

{change_text}

如果变化暗示用户遇到问题（卡住、报错、反复修改、注意力崩溃），回答 YES
如果只是正常波动（打字速度变化、任务切换），回答 NO

关键信号：
- 退格率上升+会话时长延长 = 卡住了
- 爆发/暂停比下降 = 犹豫/分心
- 多个参数同时同向偏离 = 系统性异常

输出格式（必须严格遵守）：
YES
原因一句话

或者：
NO
原因一句话"""

        try:
            import urllib.request
            import json as _json

            _semantic_model = self._resolve_semantic_model()

            payload = _json.dumps({
                "model": _semantic_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 80},
            }).encode("utf-8")
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = _json.loads(resp.read().decode())
                raw = result.get("response", "").strip()
                response_text = raw.upper()

                if "\n" in raw:
                    _lines = raw.split("\n", 1)
                    _first_line = _lines[0].strip().upper()
                    _reason_text = _lines[1].strip() if len(_lines) > 1 else ""
                    should_alert = _first_line.startswith("YES")
                    reason = _reason_text if _reason_text else raw
                elif "|" in raw:
                    should_alert = response_text.startswith("YES")
                    reason = raw.split("|", 1)[-1].strip()
                else:
                    should_alert = response_text.startswith("YES")
                    if should_alert:
                        reason = f"模型未提供原因，偏离项数={len(deviations)}"
                    else:
                        reason = f"模型未提供原因，偏离项数={len(deviations)}，判定为正常波动"

                if not should_alert and reason:
                    _contradiction_keywords = ['问题', '异常', '卡住', '报错', '困难', '受阻', '出错', '失败', '需要关注', '值得关注']
                    _reason_lower = reason.lower()
                    # [Funnel/FP-fix] 矛盾修正太激进的副作用：LLM 说"没有显示出系统性异常或用户遇到问题的迹象"
                    # 也被反转成 YES。先检查 reason 里是否带"否定/正常"语境，是的话不再强行翻转。
                    _dismissive_markers = [
                        '正常', '可能是正常', '是正常', '属于正常', '正常波动', '正常的',
                        '没有问题', '不是问题', '没有显示出', '没有出现', '没有遇到', '没有任何',
                        '没有明显的', '没有迹象', '不存在', '无异常', '无明显', '无需', '不需要',
                        '没有受阻', '没有困难', '没有报错', '没有失败', '没有卡住',
                        'no issue', 'no problem', 'no anomaly', 'not a problem',
                        'no sign of', 'no evidence of', 'normal', 'as expected', 'expected',
                    ]
                    _has_dismissive = any(m in _reason_lower for m in _dismissive_markers)
                    if (not _has_dismissive) and any(kw in _reason_lower for kw in _contradiction_keywords):
                        should_alert = True
                        reason = f"[矛盾修正] 原因暗示有问题但模型判NO，自动修正为YES | {reason}"

                return {"should_alert": should_alert, "reason": reason}
        except Exception as e:
            return {"should_alert": len(deviations) >= 3, "reason": f"语义模型不可用，偏离数≥3自动触发 ({len(deviations)}项偏离)"}

    def _get_fusion_trend(self) -> str:
        if len(self._fusion_score_history) < 2:
            return "趋势数据不足"
        scores = [h["score"] for h in self._fusion_score_history]
        trend = "上升" if scores[-1] > scores[0] else "下降" if scores[-1] < scores[0] else "平稳"
        return f"{scores[0]:.3f} → {scores[-1]:.3f} ({trend})"

class HabitClock:
    """习惯时钟：纯本地规则引擎，从窗口历史中提取结构化行为模式，不消耗 LLM token"""
    
    def __init__(self):
        self.daily_start_times = []
        self.break_patterns = []
        self.work_category_heatmap = {}
        self.peak_focus_windows = []
        self.distraction_windows = []
        self.last_update_time = 0
        self._update_interval = 3600
    
    def update_from_probe(self):
        """从 PhysicalEnvironmentProbe 的窗口历史中增量更新模式"""
        now = time.time()
        if now - self.last_update_time < self._update_interval:
            return
        self.last_update_time = now
        
        try:
            history = list(PhysicalEnvironmentProbe.window_history)
            if len(history) < 60:
                return
            
            weekday = time.strftime('%A')
            current_hour = int(time.strftime('%H'))
            
            if weekday not in self.work_category_heatmap:
                self.work_category_heatmap[weekday] = {}
            
            category = PhysicalEnvironmentProbe.current_work_category
            if current_hour not in self.work_category_heatmap[weekday]:
                self.work_category_heatmap[weekday][current_hour] = {}
            
            self.work_category_heatmap[weekday][current_hour][category] = \
                self.work_category_heatmap[weekday][current_hour].get(category, 0) + 1
            
            recent = [e for e in history if now - e['time'] < 3600]
            if len(recent) >= 10:
                switches = 0
                last_title = None
                for e in sorted(recent, key=lambda x: x['time']):
                    if last_title is not None and e['title'] != last_title and e['title'] != '':
                        switches += 1
                    last_title = e['title']
                
                switch_rate = switches / max(len(recent) / 60, 1)
                
                if switch_rate < 2:
                    if not any(w[0] == current_hour for w in self.peak_focus_windows):
                        self.peak_focus_windows.append((current_hour, weekday, switch_rate))
                        self.peak_focus_windows = self.peak_focus_windows[-20:]
                elif switch_rate > 8:
                    if not any(w[0] == current_hour for w in self.distraction_windows):
                        self.distraction_windows.append((current_hour, weekday, switch_rate))
                        self.distraction_windows = self.distraction_windows[-20:]
        except Exception:
            pass
    
    def predict_current_state(self) -> dict:
        """返回当前时段的预测状态"""
        weekday = time.strftime('%A')
        current_hour = int(time.strftime('%H'))
        
        result = {
            'expected_category': 'Unknown',
            'is_break_time': False,
            'focus_prediction': 'normal',
            'anomaly_detected': False,
            'anomaly_detail': ''
        }
        
        if weekday in self.work_category_heatmap and current_hour in self.work_category_heatmap[weekday]:
            hour_data = self.work_category_heatmap[weekday][current_hour]
            if hour_data:
                result['expected_category'] = max(hour_data, key=hour_data.get)
        
        for h, w, rate in self.peak_focus_windows:
            if h == current_hour and w == weekday:
                result['focus_prediction'] = 'high'
                break
        
        for h, w, rate in self.distraction_windows:
            if h == current_hour and w == weekday:
                result['focus_prediction'] = 'low'
                break
        
        actual_category = PhysicalEnvironmentProbe.current_work_category
        if result['expected_category'] != 'Unknown' and actual_category not in ('AFK', 'Idle'):
            if actual_category != result['expected_category']:
                result['anomaly_detected'] = True
                result['anomaly_detail'] = f"Expected {result['expected_category']} but seeing {actual_category}"
        
        return result
    
    def get_habit_summary(self) -> str:
        """生成可注入 Prompt 的习惯摘要"""
        prediction = self.predict_current_state()
        parts = []
        
        if prediction['expected_category'] != 'Unknown':
            parts.append(f"Historically, Sir is usually '{prediction['expected_category']}' at this hour on {time.strftime('%A')}.")
        
        if prediction['focus_prediction'] == 'high':
            parts.append("This is typically a HIGH FOCUS window for Sir. Keep interactions minimal.")
        elif prediction['focus_prediction'] == 'low':
            parts.append("This is typically a LOW FOCUS window. Sir may be open to conversation.")
        
        if prediction['anomaly_detected']:
            parts.append(f"ANOMALY: {prediction['anomaly_detail']}. Sir may be off his usual routine.")
        
        return ' '.join(parts) if parts else ''
    
    def _llm_reflect(self, reflector: 'LlmReflector' = None) -> dict:
        """LLM 增强反思：窗口标题 → 精确工作类别 + 项目名 + 自然语言洞察
        
        规则引擎只能根据进程名分类（Code.exe → Coding），
        LLM 能通过窗口标题判断：是在写 Jarvis 代码还是在写个人项目。
        
        频率：每 30min 一次，由 ReflectionScheduler 调度
        模型：flash_lite（极低成本）
        """
        if reflector is None:
            reflector = LlmReflector()
        
        try:
            history = list(PhysicalEnvironmentProbe.window_history)
            if len(history) < 10:
                return {'success': False, 'reason': 'insufficient_data'}
            
            now = time.time()
            recent_titles = []
            seen = set()
            for entry in reversed(history):
                title = entry.get('title', '').strip()
                if title and title not in seen and now - entry['time'] < 1800:
                    recent_titles.append({
                        'title': title[:120],
                        'minutes_ago': round((now - entry['time']) / 60, 1)
                    })
                    seen.add(title)
                if len(recent_titles) >= 15:
                    break
            
            if not recent_titles:
                return {'success': False, 'reason': 'no_titles'}
            
            rule_category = PhysicalEnvironmentProbe.current_work_category
            rule_process = PhysicalEnvironmentProbe.current_process_name
            work_duration = PhysicalEnvironmentProbe.work_duration_minutes
            
            weekday = time.strftime('%A')
            current_hour = int(time.strftime('%H'))
            heatmap_snapshot = {}
            if weekday in self.work_category_heatmap:
                heatmap_snapshot = {
                    str(h): self.work_category_heatmap[weekday].get(h, {})
                    for h in range(max(0, current_hour - 3), min(24, current_hour + 1))
                }
            
            system_prompt = """You are a precise work activity classifier. Your job is to look at window titles and determine EXACTLY what Sir is working on.

RULES:
1. Output ONLY valid JSON. No markdown, no explanation.
2. Be specific: "Writing Jarvis nerve system Python code in VS Code" is better than "Coding".
3. If you see project names in window titles, extract them.
4. Confidence must be 0.0-1.0 based on how clear the evidence is.
5. If the window titles are ambiguous, set confidence lower and explain why."""

            user_prompt = f"""Analyze these recent window titles from Sir's desktop:

Current Rule Engine Classification: {rule_category}
Active Process: {rule_process}
Session Duration: {work_duration} minutes
Current Time: {current_hour}:00 on {weekday}
Historical Pattern: {json.dumps(heatmap_snapshot, ensure_ascii=False)}

Recent Window Titles (most recent first):
{json.dumps(recent_titles, ensure_ascii=False, indent=2)}

Output this JSON:
{{
    "precise_activity": "Specific description of what Sir is actually doing",
    "project_name": "Detected project name or 'unknown'",
    "work_subcategory": "One of: work-coding, personal-coding, work-research, personal-research, entertainment, learning, communication, system-admin, idle",
    "confidence": 0.0-1.0,
    "evidence": "Which window titles led to this conclusion",
    "is_focused": true/false,
    "natural_language_insight": "One sentence in English describing Sir's current activity pattern"
}}"""

            result = reflector.reflect('flash_lite', system_prompt, user_prompt, cache_ttl=900)
            
            if result['success'] and result['result']:
                reflector.store_reflection('habit_clock', 'latest', result['result'])
            
            return result
            
        except Exception as e:
            print(f"[HabitClock._llm_reflect] 异常: {e}")
            return {'success': False, 'reason': str(e)}
    
    def get_llm_enhanced_summary(self) -> str:
        """获取 LLM 增强后的习惯摘要（规则引擎 + LLM 反思融合）"""
        base = self.get_habit_summary()
        
        reflector = LlmReflector()
        reflection = reflector.get_reflection('habit_clock', 'latest')
        
        if not reflection:
            return base
        
        parts = [base] if base else []
        
        activity = reflection.get('precise_activity', '')
        if activity:
            parts.append(f"[LLM INSIGHT] Sir appears to be: {activity}.")
        
        project = reflection.get('project_name', '')
        if project and project != 'unknown':
            parts.append(f"Current project context: {project}.")
        
        insight = reflection.get('natural_language_insight', '')
        if insight:
            parts.append(f"Pattern: {insight}")
        
        return ' '.join(parts) if parts else ''

class CausalChain:
    """因果链引擎：纯规则引擎，维护最近 7 天关键事件时间线，检测跨事件因果模式"""
    
    def __init__(self):
        self.events = []
        self.max_age_days = 7
    
    def record(self, event_type: str, detail: str = ""):
        """记录关键事件"""
        now = time.time()
        self.events.append({
            'timestamp': now,
            'type': event_type,
            'detail': detail
        })
        self._prune()
    
    def _prune(self):
        """清理超过 7 天的事件"""
        cutoff = time.time() - (self.max_age_days * 86400)
        self.events = [e for e in self.events if e['timestamp'] >= cutoff]
    
    def detect_patterns(self) -> list:
        """检测因果模式，返回可注入 Prompt 的描述列表"""
        self._prune()
        patterns = []
        now = time.time()
        
        late_nights = [e for e in self.events if e['type'] == 'late_night']
        commitment_breaches = [e for e in self.events if e['type'] == 'commitment_breach']
        long_sessions = [e for e in self.events if e['type'] == 'long_coding_session']
        media_binges = [e for e in self.events if e['type'] == 'media_binge']
        
        recent_late = [e for e in late_nights if now - e['timestamp'] < 86400]
        recent_breaches = [e for e in commitment_breaches if now - e['timestamp'] < 86400]
        
        if len(late_nights) >= 3:
            last_3 = sorted(late_nights, key=lambda x: x['timestamp'])[-3:]
            if len(last_3) >= 3:
                span_days = (last_3[-1]['timestamp'] - last_3[0]['timestamp']) / 86400
                if span_days <= 7:
                    patterns.append(f"Sir has been staying up late {len(late_nights)} times in the past week. This is a recurring pattern — not an isolated incident.")
        
        if len(commitment_breaches) >= 2:
            last_2 = sorted(commitment_breaches, key=lambda x: x['timestamp'])[-2:]
            if len(last_2) >= 2:
                span_days = (last_2[-1]['timestamp'] - last_2[0]['timestamp']) / 86400
                if span_days <= 7:
                    patterns.append(f"Sir has broken {len(commitment_breaches)} self-imposed commitments this week. He may be overworking or avoiding rest deliberately.")
        
        if recent_late and recent_breaches:
            patterns.append("CAUSAL LINK: Sir stayed up late AND broke a commitment within the same 24h window. He may be in a high-pressure cycle.")
        
        if len(long_sessions) >= 5:
            patterns.append(f"Sir has had {len(long_sessions)} extended coding sessions this week. High intensity period detected.")
        
        if len(media_binges) >= 3:
            patterns.append(f"Sir has had {len(media_binges)} extended media/entertainment sessions this week. Possible procrastination or decompression pattern.")
        
        return patterns
    
    def get_causal_summary(self) -> str:
        """生成可注入 Prompt 的因果链摘要"""
        patterns = self.detect_patterns()
        if not patterns:
            return ""
        
        parts = ["[CAUSAL CHAIN - Cross-event patterns detected by Jarvis]:"]
        for p in patterns:
            parts.append(f"  - {p}")
        parts.append("[DIRECTIVE]: If Sir's current situation relates to any pattern above, you may reference it naturally. Be subtle — like a friend who noticed, not a therapist.")
        
        return '\n'.join(parts)
    
    def _llm_reflect(self, reflector: 'LlmReflector' = None) -> dict:
        """LLM 增强因果推理：事件序列 → 叙事因果链 + 置信度 + 可操作建议
        
        这是整个混合架构的核心。规则引擎只能检测共现（"熬夜+违约同时发生"），
        LLM 能构建叙事因果链（"项目A的bug→熬夜→效率低→项目B延期"）。
        
        频率：检测到新模式时触发，由 ReflectionScheduler 调度
        模型：flash（更高质量推理）
        """
        if reflector is None:
            reflector = LlmReflector()
        
        try:
            self._prune()
            if len(self.events) < 3:
                return {'success': False, 'reason': 'insufficient_events'}
            
            rule_patterns = self.detect_patterns()
            
            events_summary = []
            for e in sorted(self.events, key=lambda x: x['timestamp']):
                events_summary.append({
                    'time': time.strftime('%m/%d %H:%M', time.localtime(e['timestamp'])),
                    'type': e['type'],
                    'detail': e['detail']
                })
            
            now = time.time()
            time_range_days = round((now - self.events[0]['timestamp']) / 86400, 1) if self.events else 0
            
            system_prompt = """You are a causal reasoning engine for J.A.R.V.I.S. Your job is to analyze event sequences and construct narrative causal chains.

CRITICAL RULES:
1. Output ONLY valid JSON. No markdown, no explanation outside JSON.
2. Be honest about uncertainty. If the causal link is weak, say so.
3. Distinguish correlation from causation. Just because two events happened near each other doesn't mean one caused the other.
4. Consider alternative explanations.
5. Confidence scores must reflect genuine certainty, not optimism.
6. Focus on ACTIONABLE insights — what can Sir actually do differently?"""

            user_prompt = f"""Analyze this event timeline from Sir's past {time_range_days} days:

Rule Engine Detected Patterns:
{json.dumps(rule_patterns, ensure_ascii=False, indent=2)}

Complete Event Timeline:
{json.dumps(events_summary, ensure_ascii=False, indent=2)}

Output this JSON:
{{
    "causal_chains": [
        {{
            "narrative": "A clear, concise causal story connecting 2+ events (e.g., 'Late night coding on Project X led to missed morning commitment Y')",
            "events_involved": ["event_type_1", "event_type_2"],
            "causal_direction": "A_causes_B | bidirectional | correlated_only",
            "confidence": 0.0-1.0,
            "alternative_explanation": "What else could explain this pattern?",
            "actionable_insight": "What Sir could do to break this cycle"
        }}
    ],
    "dominant_pattern": "The single most important pattern in this timeline",
    "risk_assessment": {{
        "burnout_risk": "low|moderate|high|critical",
        "productivity_trend": "improving|stable|declining|volatile",
        "key_risk_factor": "The biggest risk factor identified"
    }},
    "summary_for_jarvis": "A 2-3 sentence summary Jarvis can use to understand Sir's current situation. Written as if Jarvis is speaking to himself about Sir. Be insightful but not judgmental.",
    "overall_confidence": 0.0-1.0
}}"""

            result = reflector.reflect('flash', system_prompt, user_prompt, cache_ttl=3600)
            
            if result['success'] and result['result']:
                result['result']['_rule_patterns'] = rule_patterns
                result['result']['_events_count'] = len(self.events)
                result['result']['_timestamp'] = time.time()
                reflector.store_reflection('causal_chain', 'latest', result['result'])
                
                if result['result'].get('overall_confidence', 0) >= 0.7:
                    # 🆕 [Sir 2026-05-24 23:29 真测 BUG-B 治本] 改 bg_log 防混进 reply stdout.
                    # 老 print 在 reply stream 时插队, 字幕显示 'It appears...[CausalChain LLM]...'
                    try:
                        from jarvis_utils import bg_log as _cc_bg
                        _cc_bg(f"[CausalChain LLM] 高置信度因果链: {result['result'].get('dominant_pattern', 'N/A')}")
                    except Exception:
                        pass

            return result

        except Exception as e:
            try:
                from jarvis_utils import bg_log as _cc_err_bg
                _cc_err_bg(f"[CausalChain._llm_reflect] 异常: {e}")
            except Exception:
                pass
            return {'success': False, 'reason': str(e)}
    
    def get_llm_enhanced_summary(self) -> str:
        """获取 LLM 增强后的因果链摘要（规则引擎 + LLM 叙事融合）"""
        base = self.get_causal_summary()
        
        reflector = LlmReflector()
        reflection = reflector.get_reflection('causal_chain', 'latest')
        
        if not reflection:
            return base
        
        parts = [base] if base else []
        
        summary = reflection.get('summary_for_jarvis', '')
        if summary:
            parts.append(f"\n[LLM NARRATIVE ANALYSIS]: {summary}")
        
        risk = reflection.get('risk_assessment', {})
        if risk:
            burnout = risk.get('burnout_risk', '')
            if burnout and burnout in ('high', 'critical'):
                parts.append(f"⚠️ Burnout risk: {burnout.upper()}. {risk.get('key_risk_factor', '')}")
        
        chains = reflection.get('causal_chains', [])
        high_conf_chains = [c for c in chains if c.get('confidence', 0) >= 0.7]
        for c in high_conf_chains[:2]:
            insight = c.get('actionable_insight', '')
            if insight:
                parts.append(f"Suggestion: {insight}")
        
        return '\n'.join(parts) if parts else ''

class ProjectTimeline:
    """项目时间线：进程会话追踪 + LLM 项目识别
    
    规则引擎只能记录进程名（python.exe、chrome.exe），
    LLM 通过窗口标题识别真实项目名。
    """
    
    def __init__(self):
        self.sessions = []
        self.current_session = None
        self.projects = {}
        self._last_llm_check = 0
        self._llm_check_interval = 1800
    
    def start_session(self, process_name: str, window_title: str = ""):
        now = time.time()
        if self.current_session:
            self.end_session()
        
        self.current_session = {
            'process': process_name,
            'start_time': now,
            'window_titles': [window_title] if window_title else [],
            'project_name': 'unknown',
            'project_confidence': 0.0
        }
    
    def update_title(self, window_title: str):
        if self.current_session and window_title:
            titles = self.current_session['window_titles']
            if not titles or titles[-1] != window_title:
                titles.append(window_title)
                if len(titles) > 30:
                    titles.pop(0)
    
    def end_session(self):
        if not self.current_session:
            return
        now = time.time()
        self.current_session['end_time'] = now
        self.current_session['duration_minutes'] = round(
            (now - self.current_session['start_time']) / 60, 1
        )
        
        if self.current_session['duration_minutes'] >= 1:
            self.sessions.append(self.current_session)
            if len(self.sessions) > 200:
                self.sessions = self.sessions[-200:]
        
        self.current_session = None
    
    def get_active_projects(self, min_duration: float = 10) -> list:
        now = time.time()
        recent = [s for s in self.sessions if now - s.get('end_time', now) < 86400 * 3]
        
        project_times = {}
        for s in recent:
            name = s.get('project_name', 'unknown')
            if name == 'unknown':
                name = s.get('process', 'unknown')
            duration = s.get('duration_minutes', 0)
            project_times[name] = project_times.get(name, 0) + duration
        
        return sorted(
            [{'name': k, 'total_minutes': round(v, 1)} for k, v in project_times.items() if v >= min_duration],
            key=lambda x: x['total_minutes'], reverse=True
        )[:10]
    
    def _llm_reflect(self, reflector: 'LlmReflector' = None) -> dict:
        """LLM 项目识别：窗口标题 + 进程名 → 真实项目名
        
        频率：检测到新进程时触发
        模型：flash_lite
        """
        if reflector is None:
            reflector = LlmReflector()
        
        try:
            if not self.current_session:
                return {'success': False, 'reason': 'no_active_session'}
            
            titles = self.current_session.get('window_titles', [])
            if len(titles) < 2:
                return {'success': False, 'reason': 'insufficient_titles'}
            
            process = self.current_session.get('process', 'unknown')
            unique_titles = list(dict.fromkeys(titles[-10:]))
            
            system_prompt = """You are a project identifier. Based on window titles and process names, identify what project Sir is working on.

RULES:
1. Output ONLY valid JSON.
2. Project name should be concise (2-5 words max).
3. If you can't determine the project, set confidence to 0 and project_name to "unknown".
4. Look for project names, repository names, or distinctive keywords in window titles."""

            user_prompt = f"""Identify the project from these window titles:

Process: {process}
Recent Window Titles:
{json.dumps(unique_titles, ensure_ascii=False, indent=2)}

Output this JSON:
{{
    "project_name": "Identified project name or 'unknown'",
    "project_type": "coding|research|media|communication|system|other",
    "confidence": 0.0-1.0,
    "keywords_matched": ["keyword1", "keyword2"],
    "is_same_as_previous": true/false
}}"""

            result = reflector.reflect('flash_lite', system_prompt, user_prompt, cache_ttl=600)
            
            if result['success'] and result['result']:
                proj_name = result['result'].get('project_name', 'unknown')
                confidence = result['result'].get('confidence', 0)
                
                if self.current_session:
                    self.current_session['project_name'] = proj_name
                    self.current_session['project_confidence'] = confidence
                
                if proj_name != 'unknown' and confidence >= 0.5:
                    if proj_name not in self.projects:
                        self.projects[proj_name] = {
                            'first_seen': time.time(),
                            'total_sessions': 0,
                            'total_minutes': 0
                        }
                    self.projects[proj_name]['total_sessions'] += 1
            
            return result
            
        except Exception as e:
            print(f"[ProjectTimeline._llm_reflect] 异常: {e}")
            return {'success': False, 'reason': str(e)}
    
    def get_summary(self) -> str:
        projects = self.get_active_projects()
        if not projects:
            return ""
        parts = ["[ACTIVE PROJECTS - Last 3 days]:"]
        for p in projects[:5]:
            parts.append(f"  - {p['name']}: {p['total_minutes']}min")
        return '\n'.join(parts)

class SubconsciousMailbox:
    """潜意识信箱：异步解耦业务与发声"""
    def __init__(self):
        self.mails = []
        self.lock = threading.Lock()

    def deliver(self, priority: str, content: str, **kwargs):
        """priority: 'URGENT' | 'NORMAL' | 'TRIVIA'. kwargs: tone_override, reminder_id, etc."""
        with self.lock:
            mail = {"priority": priority, "content": content, "timestamp": time.time()}
            mail.update(kwargs)
            self.mails.append(mail)
            priority_map = {"URGENT": 0, "NORMAL": 1, "TRIVIA": 2}
            self.mails.sort(key=lambda x: priority_map.get(x["priority"], 1))

    def has_mail(self):
        return len(self.mails) > 0
        
    def peek_highest_priority(self):
        with self.lock:
            return self.mails[0]["priority"] if self.mails else None

    def pop_mail(self):
        with self.lock:
            return self.mails.pop(0) if self.mails else None
    
    def cancel_by_reminder_id(self, reminder_id: int):
        with self.lock:
            before = len(self.mails)
            self.mails = [m for m in self.mails if m.get('reminder_id') != reminder_id]
            after = len(self.mails)
            if before != after:
                print(f" └─ [Mailbox] Removed {before - after} related items from pending queue (ID:{reminder_id})")

# ==========================================


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

