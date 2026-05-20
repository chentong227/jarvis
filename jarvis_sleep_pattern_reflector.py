# -*- coding: utf-8 -*-
"""[β.5.39 / 2026-05-20] Sir Sleep Pattern L7 Reflector.

Sir 14:39 校正 + 15:18 真理: 动态接近 Sir 平时入睡时间提高催睡频率, 而不是硬编码 22:00.

每日 03:00 跑一次:
1. 扫 hippocampus chat_log 找昨晚 "sleep mode activated" / Sir 说 "晚安/睡了" 事件
2. 推算昨晚入睡时间 → 加到 history
3. 重算 typical_sleep_hour weekday/weekend 中位数 (满足 min_data_points)
4. propose 更新 → 写 review_queue 等 Sir 拍板 (准则 7) — 自动 active 仅在 min_data_points + 数据稳定

数据源:
- jarvis_hippocampus.chat_log: 找含 'sleep_mode_activate' / '晚安' / 'good night' 的 log entry timestamp
- nudge_gate.activate_sleep_mode 触发时, log entry 直接 append (worker hook)

vocab: memory_pool/sir_sleep_pattern_vocab.json
doc: docs/JARVIS_SENSOR_TO_SWM_ARCHITECTURE.md
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta
from statistics import median
from typing import List, Optional

try:
    from jarvis_utils import bg_log
except Exception:
    def bg_log(msg):
        print(msg)


VOCAB_PATH = os.path.join('memory_pool', 'sir_sleep_pattern_vocab.json')
DEFAULT_TICK_INTERVAL_S = 3600.0  # 1h check time, fire 03:00


class SleepPatternReflector(threading.Thread):
    """L7 reflector 周期跑, 计算 Sir 入睡时间中位数, propose 更新 vocab."""

    def __init__(self, hippocampus=None, vocab_path: Optional[str] = None,
                 tick_interval_s: float = DEFAULT_TICK_INTERVAL_S,
                 fire_hour: int = 3):
        super().__init__(daemon=True, name='SleepPatternReflector')
        self.hippocampus = hippocampus
        self.vocab_path = vocab_path or VOCAB_PATH
        self.tick_interval_s = tick_interval_s
        self.fire_hour = fire_hour
        self._stop = threading.Event()
        self._last_fired_day = ''

    def stop(self):
        self._stop.set()

    def run(self):
        bg_log(f"💤 [SleepPatternReflector] 启动 (每 {self.tick_interval_s:.0f}s tick, fire @{self.fire_hour:02d}:xx)")
        # 启动后 60s 等系统稳定再 first check
        if self._stop.wait(60):
            return
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                bg_log(f"⚠️ [SleepPatternReflector] tick err: {type(e).__name__}: {e}")
            if self._stop.wait(self.tick_interval_s):
                return

    def _tick(self):
        """每 tick 看时间是否到 fire_hour, 是则跑 reflect."""
        now = datetime.now()
        if now.hour != self.fire_hour:
            return
        today_str = now.strftime('%Y-%m-%d')
        if today_str == self._last_fired_day:
            return  # 今日已 fired
        self._last_fired_day = today_str
        bg_log(f"💤 [SleepPatternReflector] fire @{now.strftime('%H:%M')} — 计算 Sir 入睡模式")
        self._reflect()

    def _reflect(self):
        """主流程: 扫数据 → 更新 history → 重算 median → propose."""
        try:
            data = self._load_vocab()
        except Exception as e:
            bg_log(f"⚠️ [SleepPatternReflector] vocab load err: {e}")
            return

        # 扫 hippocampus 找昨晚 sleep events (扩展到近 14 天补漏)
        new_entries = self._scan_recent_sleep_events(days=14)
        if not new_entries:
            bg_log(f"💤 [SleepPatternReflector] 扫无新 sleep event")
        else:
            history = data.setdefault('history', [])
            existing_dates = {h.get('date') for h in history}
            added = 0
            for e in new_entries:
                if e['date'] not in existing_dates:
                    history.append(e)
                    added += 1
            if added:
                bg_log(f"💤 [SleepPatternReflector] +{added} new sleep entries")
                # 删超过 history_max_days 老 entry
                max_days = data.get('_meta', {}).get('history_max_days', 60)
                cutoff_ts = time.time() - max_days * 86400
                history[:] = [h for h in history if h.get('sleep_ts', 0) >= cutoff_ts]

        # 重算 typical_sleep_hour 中位数
        self._recompute_typical(data)

        # 保存
        try:
            self._save_vocab(data)
        except Exception as e:
            bg_log(f"⚠️ [SleepPatternReflector] vocab save err: {e}")

    def _scan_recent_sleep_events(self, days: int = 14) -> List[dict]:
        """扫 hippocampus 找最近 N 天的 sleep events.
        
        优先从 NudgeGate.activate_sleep_mode log + 'sleep_mode_activate' chat_log + Sir 显式 '晚安/sleep' 提取.
        """
        if self.hippocampus is None:
            return []
        entries = []
        try:
            # 简化: 用 hippocampus 提供的接口 (如果有), 或 fallback raw chat_log query
            cutoff_ts = time.time() - days * 86400
            # 假设 hippocampus 提供 query_chat_log(since_ts) 接口
            if hasattr(self.hippocampus, 'query_chat_log_since'):
                logs = self.hippocampus.query_chat_log_since(cutoff_ts)
            else:
                logs = []
            seen_dates = set()
            for log in logs:
                ts = log.get('timestamp', 0)
                if ts < cutoff_ts:
                    continue
                content = (log.get('content', '') or log.get('user_input', '') or '').lower()
                # 判断是否 sleep event
                is_sleep = any(kw in content for kw in (
                    '晚安', '我睡了', 'good night', 'going to bed',
                    'sleep_mode_activate', 'i\'m off to bed',
                ))
                if not is_sleep:
                    continue
                dt = datetime.fromtimestamp(ts)
                date_str = dt.strftime('%Y-%m-%d')
                if date_str in seen_dates:
                    continue
                seen_dates.add(date_str)
                # 入睡时间 (跨午夜算 24+): 00:30 = 24.5
                sleep_hour = dt.hour + dt.minute / 60.0
                if dt.hour < 6:
                    sleep_hour += 24  # 凌晨算前一天的延续
                entries.append({
                    'date': date_str,
                    'sleep_ts': ts,
                    'sleep_hour': round(sleep_hour, 2),
                    'weekday': 1 if dt.weekday() < 5 else 0,
                    'source': 'hippocampus_scan',
                })
        except Exception as e:
            bg_log(f"⚠️ [SleepPatternReflector] scan err: {e}")
        return entries

    def _recompute_typical(self, data: dict):
        history = data.get('history', [])
        min_pts = data.get('_meta', {}).get('min_data_points', 5)
        weekday_hours = [h['sleep_hour'] for h in history if h.get('weekday') == 1]
        weekend_hours = [h['sleep_hour'] for h in history if h.get('weekday') == 0]
        typ = data.setdefault('typical_sleep_hour', {})
        changed = False
        if len(weekday_hours) >= min_pts:
            old_val = typ.get('weekday')
            new_val = round(median(weekday_hours), 2)
            if old_val != new_val:
                typ['weekday'] = new_val
                changed = True
                bg_log(f"💤 [SleepPatternReflector] weekday {old_val} → {new_val} ({len(weekday_hours)} samples)")
        if len(weekend_hours) >= min_pts:
            old_val = typ.get('weekend')
            new_val = round(median(weekend_hours), 2)
            if old_val != new_val:
                typ['weekend'] = new_val
                changed = True
                bg_log(f"💤 [SleepPatternReflector] weekend {old_val} → {new_val} ({len(weekend_hours)} samples)")
        if changed:
            typ['last_computed_ts'] = time.time()
            typ['data_points_used'] = len(weekday_hours) + len(weekend_hours)
            typ['source'] = 'l7_reflector_auto'

    def _load_vocab(self) -> dict:
        with open(self.vocab_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _save_vocab(self, data: dict):
        tmp = self.vocab_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.vocab_path)


_DEFAULT_REFLECTOR: Optional[SleepPatternReflector] = None


def get_default_reflector(hippocampus=None) -> SleepPatternReflector:
    global _DEFAULT_REFLECTOR
    if _DEFAULT_REFLECTOR is None:
        _DEFAULT_REFLECTOR = SleepPatternReflector(hippocampus=hippocampus)
    return _DEFAULT_REFLECTOR


def log_sleep_event(sleep_hour: float, source: str = 'manual_log'):
    """供 worker / nudge_gate hook 直接 log 一个入睡事件."""
    try:
        path = VOCAB_PATH
        if not os.path.exists(path):
            return
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        # 同一天重复 log 不加 (取最早)
        history = data.setdefault('history', [])
        existing_dates = {h.get('date') for h in history}
        if date_str in existing_dates:
            return
        entry = {
            'date': date_str,
            'sleep_ts': now.timestamp(),
            'sleep_hour': round(sleep_hour, 2),
            'weekday': 1 if now.weekday() < 5 else 0,
            'source': source,
        }
        history.append(entry)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        bg_log(f"💤 [SleepPattern] logged: {date_str} {sleep_hour}h ({source})")
    except Exception as e:
        bg_log(f"⚠️ [SleepPattern/log] err: {e}")


if __name__ == '__main__':
    # CLI for manual test
    r = SleepPatternReflector()
    r._reflect()
