# -*- coding: utf-8 -*-
"""[Reshape M3.E / 2026-05-24] ProactiveShield 主动守护盾 — 拆自 jarvis_enhanced.py.

🩹 [P0+20-β.2.7.3 / 2026-05-17] 多信号加权评分 + L0-L5 修正
治 Sir 13:09 实测反馈: "切窗口频繁不等于困难".
原 thresholds 保留作 "信号触发起点", 但只有综合 score >= TRIGGER_SCORE 才真触发 nudge.

🆕 [Reshape M3.E] 单 class 独立 file. jarvis_enhanced.py re-export 兼容老 caller.
M6.4 真 class split 时此 file 会被 PromptAssembler / sentinel 群整理一起 design.
"""
import time
import threading
from collections import deque

from jarvis_env_probe import PhysicalEnvironmentProbe


class ProactiveShield(threading.Thread):
    # 🩹 [P0+20-β.2.7.3 / 2026-05-17] 从硬阈值 → 多信号加权评分 + L0-L5 修正
    # 治 Sir 13:09 实测反馈："切窗口频繁不等于困难"。
    # 原 thresholds 保留作"信号触发起点"，但只有综合 score >= TRIGGER_SCORE 才真触发 nudge。
    FRUSTRATION_SIGNALS = {
        'rapid_alt_tab': {'window_switches': 12, 'time_window': 300},
        'error_loop': {'same_page_minutes': 5},
        'repeated_edits': {'edit_count': 10, 'time_window': 600},
        'search_spiral': {'similar_searches': 4, 'time_window': 600},
    }
    TRIGGER_SCORE = 0.65  # 综合分阈值

    def __init__(self, central_nerve):
        super().__init__(daemon=True)
        self.jarvis = central_nerve
        self._window_switch_times = deque(maxlen=100)
        self._error_page_times = {}
        self._search_history = deque(maxlen=50)
        self._last_nudge_time = 0
        self._nudge_cooldown = 900
        self._daily_nudge_count = 0
        self._last_reset_day = ""
        self._last_diag_print_time = 0
        self._diag_print_interval = 30

    def run(self):
        time.sleep(15)
        print("🛡️ [ProactiveShield] Shield ready (多信号加权评分 trigger≥0.65, cooldown=15min, max 4/day)")
        while True:
            try:
                self._scan()
            except Exception as e:
                try:
                    from jarvis_utils import bg_log as _bg
                    _bg(f"[ProactiveShield] scan error: {e}")
                except Exception:
                    pass
            time.sleep(10)

    # 🩹 [P0+20-β.2.7.3 / 2026-05-17] 多信号加权
    def _compute_frustration_score(self, switches: int,
                                     error_duration_min: float,
                                     snapshot: dict) -> tuple:
        """返回 (score 0-1, breakdown dict)。

        权重设计：
        - 主信号：alt-tab / error_loop 各 0.45 max
        - 副信号：backspace_ratio / undo / burst_pause 各 0.10-0.15 max
        - 多信号叠加才能逼近 1.0 (单 alt-tab 12 不超过 0.4 → 单 signal 不触发)
        - 单 signal 极端（如 alt-tab 30 / error 15min）才单独可达 0.45+
        """
        breakdown = {}
        score = 0.0
        if switches >= 12:
            v = min(0.45, 0.18 + 0.27 * min(1.0, (switches - 12) / 18.0))
            score += v
            breakdown['alt_tab'] = round(v, 2)
        if error_duration_min >= 5:
            v = min(0.45, 0.18 + 0.27 * min(1.0, (error_duration_min - 5) / 10.0))
            score += v
            breakdown['error_loop'] = round(v, 2)
        if snapshot:
            bs_ratio = float(snapshot.get('backspace_ratio', 0) or 0)
            if bs_ratio >= 0.10:
                v = min(0.15, (bs_ratio - 0.05) * 1.0)
                score += v
                breakdown['backspace'] = round(v, 2)
            undo = int(snapshot.get('shortcut_undo_5min', 0) or 0)
            if undo >= 3:
                v = min(0.10, 0.04 + (undo - 3) * 0.015)
                score += v
                breakdown['undo'] = round(v, 2)
            burst = float(snapshot.get('burst_pause_ratio', 0) or 0)
            if burst >= 3.0:
                v = min(0.10, 0.04 + (burst - 3) * 0.015)
                score += v
                breakdown['burst_pause'] = round(v, 2)
            if snapshot.get('error_visible'):
                score += 0.10
                breakdown['error_visible'] = 0.10
            # 🩹 [β.5.37-C / 2026-05-20] Ghost activity dampen (Sir 14:39 准则 6)
            # Sensor evidence (β.5.37-A): idle_seconds_real + cascade_active
            # Sir 真离场 (真物理 idle > 30s) + IDE/Cascade 在 fg → 屏幕切换非 Sir 操作.
            # 不再 sentinel hard skip (fix3 revert), 改 sensor evidence 直接进评分:
            # score *= 0.1 大幅衰减, 让评分自然不达 TRIGGER_SCORE.
            try:
                idle_real = float(snapshot.get('idle_seconds_real', 0) or 0)
                cascade_active = bool(snapshot.get('cascade_active', False))
                if idle_real > 30 and cascade_active:
                    dampen_factor = 0.10
                    score *= dampen_factor
                    breakdown['ghost_activity_dampen'] = dampen_factor
                    breakdown['_ghost_evidence'] = {
                        'idle_seconds_real': round(idle_real, 1),
                        'cascade_process': snapshot.get('cascade_process_name', ''),
                    }
            except Exception:
                pass
        return min(1.0, score), breakdown

    def _apply_soul_modifiers(self, score: float) -> tuple:
        """L0-L5 修正乘子。返回 (修正后 score, modifier_breakdown)。"""
        modifiers = {}
        try:
            nerve = self.jarvis
            # L0: turn_count 多 (Sir 主动对话 ≥ 10) → 不像被动困难 → 衰减
            try:
                sa = getattr(nerve, 'self_anchor', None)
                if sa is not None:
                    tc = sa.get_turn_count() if hasattr(sa, 'get_turn_count') else 0
                    if tc >= 10:
                        score *= 0.85
                        modifiers['L0_active_dialog'] = 0.85
            except Exception:
                pass
            # L1: jarvis_keyrouter_health.severity 高 → Jarvis 自身不稳，offer 可能不准
            try:
                cl = getattr(nerve, 'concerns_ledger', None)
                if cl is not None:
                    kr_c = cl.get('jarvis_keyrouter_health')
                    if kr_c is not None and getattr(kr_c, 'severity', 0) > 0.5:
                        score *= 0.75
                        modifiers['L1_keyrouter_unhealthy'] = 0.75
                    # L1: sir_pomodoro_compliance 高 (Sir 工作深度集中)
                    # 此时多 frustration 信号 → 更可能是真困难 → 放大
                    pc = cl.get('sir_pomodoro_compliance')
                    if pc is not None and getattr(pc, 'severity', 0) > 0.6:
                        score *= 1.10
                        modifiers['L1_deep_work'] = 1.10
            except Exception:
                pass
            # L2: deep_work_silence 协议被 Sir 设了 → 静默期不打扰
            try:
                rs = getattr(nerve, 'relational_state', None)
                if rs is not None and hasattr(rs, 'list_protocols'):
                    for p in rs.list_protocols()[:5]:
                        rule = (getattr(p, 'rule', '') or '').lower()
                        if 'deep work' in rule or '勿扰' in rule or 'do not disturb' in rule:
                            # 看 last_referenced 是否近期（30min 内 Sir 提过）
                            last_ref = getattr(p, 'last_referenced', 0)
                            if last_ref > 0 and (time.time() - last_ref) < 1800:
                                score *= 0.50
                                modifiers['L2_deep_work_protocol'] = 0.50
                            break
            except Exception:
                pass
        except Exception:
            pass
        return min(1.0, score), modifiers

    def _scan(self):
        current_day = time.strftime('%Y-%m-%d')
        if current_day != self._last_reset_day:
            self._daily_nudge_count = 0
            self._last_reset_day = current_day

        now = time.time()
        if now - self._last_nudge_time < self._nudge_cooldown:
            return
        if self._daily_nudge_count >= 4:
            return

        try:
            # 🩹 [β.5.36-fix3 / 2026-05-20] Sir 13:05 实测真理:
            # "屏幕动的是 Cursor 自动编程的, 不是我".
            # 🔄 [β.5.37 / 2026-05-20 14:43] Sir 14:39 校正: fix3 硬编码 idle 60s 阈值 +
            # 架构方向错 — 不该 sentinel 自己 guard, 应该 sensor 区分真 input vs ghost activity
            # 并 publish 信号让主脑看. 已 revert. 详 docs/JARVIS_SENSOR_TO_SWM_ARCHITECTURE.md.
            # 架构改造后, PhysicalEnvironmentProbe.cascade_active_pid + idle_seconds_real 直接
            # 进 frustration_score breakdown, 让评分自然 0 化, 不再 sentinel hard skip.

            history = list(PhysicalEnvironmentProbe.window_history)
            if len(history) < 10:
                return

            recent = [e for e in history if now - e['time'] < 300]
            switches = 0
            last_title = None
            for e in sorted(recent, key=lambda x: x['time']):
                if last_title is not None and e.get('title', '') != last_title and e.get('title', ''):
                    switches += 1
                last_title = e.get('title', '')

            error_keywords = ['error', 'exception', 'traceback', 'stack trace', '报错', '错误',
                            'stackoverflow', 'stack overflow', 'stack_over', 'failed', 'failure']
            error_titles = []
            for e in recent:
                title = (e.get('title', '') or '').lower()
                if any(kw in title for kw in error_keywords):
                    error_titles.append(e)

            error_duration_min = 0.0
            if error_titles:
                earliest_error = min(error_titles, key=lambda x: x['time'])
                error_duration_min = (now - earliest_error['time']) / 60

            # 🩹 [P0+20-β.2.7.3 / 2026-05-17] 多信号加权评分代替硬阈值
            # 之前 "alt-tab >= 12" 就触发 → Sir 反馈 "切窗口频繁不等于困难"
            # 现在多信号 + L0-L5 修正后 score >= TRIGGER_SCORE 才触发
            snapshot = {}
            try:
                from jarvis_env_probe import PhysicalEnvironmentProbe as _PEP_score
                if hasattr(_PEP_score, 'get_sensor_snapshot'):
                    snapshot = _PEP_score.get_sensor_snapshot() or {}
            except Exception:
                snapshot = {}

            raw_score, breakdown = self._compute_frustration_score(
                switches, error_duration_min, snapshot
            )
            final_score, modifiers = self._apply_soul_modifiers(raw_score)

            switch_threshold = self.FRUSTRATION_SIGNALS['rapid_alt_tab']['window_switches']
            frustration_detected = (final_score >= self.TRIGGER_SCORE)
            frustration_type = ""
            if frustration_detected:
                if 'alt_tab' in breakdown and breakdown.get('alt_tab', 0) >= 0.30:
                    frustration_type = "rapid_context_switching"
                elif 'error_loop' in breakdown:
                    frustration_type = "extended_error_loop"
                else:
                    frustration_type = "multi_signal_confusion"

            # 接近阈值时打印诊断（限频 30s，避免刷屏）
            is_near = (final_score >= 0.40) and not frustration_detected
            if is_near:
                if now - self._last_diag_print_time > self._diag_print_interval:
                    self._last_diag_print_time = now
                    try:
                        from jarvis_utils import bg_log as _bg
                        _bg(
                            f"🛡️ [Shield watching] score={final_score:.2f} (raw={raw_score:.2f}) "
                            f"breakdown={breakdown} modifiers={modifiers} "
                            f"switches={switches} err_min={error_duration_min:.1f}"
                        )
                    except Exception:
                        pass

            if frustration_detected:
                try:
                    from jarvis_utils import bg_log as _bg_trig
                    _bg_trig(
                        f"🛡️ [Shield TRIGGER] type={frustration_type} score={final_score:.2f} "
                        f"(raw={raw_score:.2f}) breakdown={breakdown} modifiers={modifiers}"
                    )
                except Exception:
                    pass
                # 🩹 [β.5.37-C / 2026-05-20] SWM publish 'shield_observation' 让主脑看 evidence
                try:
                    from jarvis_utils import get_event_bus as _geb
                    _bus = _geb()
                    if _bus is not None:
                        _bus.publish(
                            etype='shield_observation',
                            description=(
                                f"frustration_type={frustration_type} score={final_score:.2f} "
                                f"switches={switches} err_min={error_duration_min:.1f}"
                            ),
                            source='ProactiveShield',
                            salience=min(0.4 + final_score * 0.5, 0.95),
                            metadata={
                                'kind': 'frustration_alert',
                                'frustration_type': frustration_type,
                                'score': round(final_score, 2),
                                'raw_score': round(raw_score, 2),
                                'breakdown': breakdown,
                                'modifiers': modifiers,
                                'switches': switches,
                                'error_duration_min': round(error_duration_min, 1),
                            },
                        )
                except Exception:
                    pass
                self._send_shield_nudge(frustration_type, switches, error_titles)
                self._last_nudge_time = now
                self._daily_nudge_count += 1

        except Exception as e:
            if 'PhysicalEnvironmentProbe' not in str(e):
                print(f"[ProactiveShield] _scan exception: {e}")

    def _send_shield_nudge(self, frustration_type: str, switch_count: int, error_titles: list):
        try:
            PhysicalEnvironmentProbe._shield_alert = {
                'active': True,
                'type': frustration_type,
                'switch_count': switch_count,
                'error_titles': [e.get('title', '')[:80] for e in (error_titles or [])],
                'timestamp': time.time(),
            }
            print(f"\n🛡️ [ProactiveShield] Productivity cliff detected ({frustration_type}), reported to Conductor")
        except Exception:
            pass
