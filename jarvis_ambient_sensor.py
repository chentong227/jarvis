# -*- coding: utf-8 -*-
"""Ambient audio sensor — 轻量被动听感, publish 到 SWM, 不调 ASR.

🩹 [β.5.40-A1 / 2026-05-20] Sir 方向 A.1 (~3h)

设计:
  - Hook AuditoryCortex 同一帧 PyAudio data (不抢麦克风, 不双开 stream)
  - 累积 ~500ms (8000 samples @ 16kHz) 跑一次 classifier
  - FFT + 简单 rule (frequency band energy + peak detect + temporal pattern)
  - 5 类: laughter / sigh / humming / video_playing / conversation
  - 隐私保护: 不存 audio raw, 只 publish signal (type + confidence + ts)
  - 限频: 同类 60s 不重复 publish
  - 精准: ≥ 3 个连续 sample 同意 + confidence ≥ 0.6 才 fire (Sir "算法要精准" 要求)
  - state gate: 仅 IDLE 时跑 (Sir 不说话 + Jarvis 不说话 + 不 mute)

接 SWM ConversationEventBus etype='ambient_state', salience=0.45.

主脑用法: 后续 directive 看 SWM ambient_state 自决场景:
  - conversation → SILENT (不打断 Sir 跟别人聊)
  - laughter → 主脑可能轻应 "听见您高兴"
  - sigh → 主脑关切 "Sir 累了吗"
  - humming → 主脑暖意"心情不错"
  - video_playing → 主脑知 Sir 在看视频不打扰

测试: tests/_test_p0_plus_20_beta540_ambient_sensor.py
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, List, Optional


# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------

# 16kHz @ 500ms = 8000 samples per analysis window
SAMPLE_RATE = 16000
ANALYSIS_WINDOW_SAMPLES = 8000

# 单次 publish 后, 同类 cooldown
PER_TYPE_COOLDOWN_S = 60.0

# Sir 精准要求: ≥ N 个连续 sample 同意才 fire
CONSECUTIVE_AGREE_THRESHOLD = 3

# 最低置信度
MIN_CONFIDENCE = 0.60

# Volume 阈值: 静音背景不分析 (节能 + 防误判)
MIN_VOLUME_FOR_ANALYSIS = 30  # int16 mean abs, 极静背景不算

# Volume 太大 (Sir 自己说话或 Jarvis TTS 余音) 不分析
MAX_VOLUME_FOR_ANALYSIS = 1500


# ----------------------------------------------------------------------------
# Result dataclass
# ----------------------------------------------------------------------------

@dataclass
class AmbientObservation:
    """单次 classifier 输出."""

    ambient_type: str = ''  # 'laughter' / 'sigh' / 'humming' / 'video_playing' / 'conversation' / ''
    confidence: float = 0.0
    timestamp: float = 0.0
    metadata: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------
# Classifier (FFT + rule based, all local, < 5ms per window)
# ----------------------------------------------------------------------------

def _classify_window(pcm_int16, sample_rate: int = SAMPLE_RATE) -> AmbientObservation:
    """分类 8000-sample PCM 窗口. 不抛异常.
    
    规则 (保守, 优先 sigh/humming/video, 含糊场景给低 confidence):
      - laughter: 800-3000 Hz 段能量峰 + 短促节奏 (envelope 跳跃)
      - sigh: < 500 Hz 长持续低频 + envelope 平稳衰减
      - humming: 80-400 Hz 持续 + harmonic structure
      - video_playing: 多频带稳定能量 + 长持续 (≥ window length)
      - conversation: 200-3000 Hz 多变 + 非 Sir 单声 (multi-formant pattern)
    """
    obs = AmbientObservation(timestamp=time.time())
    try:
        import numpy as np
    except ImportError:
        return obs

    if pcm_int16 is None or len(pcm_int16) < sample_rate // 4:
        return obs

    try:
        arr = np.asarray(pcm_int16, dtype=np.float32)
    except Exception:
        return obs

    # 归一化
    arr = arr / 32768.0

    # 时域特征: envelope (能量包络)
    abs_arr = np.abs(arr)
    if len(abs_arr) == 0:
        return obs
    mean_amp = float(np.mean(abs_arr))
    if mean_amp < (MIN_VOLUME_FOR_ANALYSIS / 32768.0):
        return obs  # 太静

    # envelope smoothing (~50ms window)
    smooth_win = max(1, sample_rate // 20)  # 50ms
    if len(abs_arr) < smooth_win * 2:
        return obs
    envelope = np.convolve(abs_arr, np.ones(smooth_win) / smooth_win, mode='valid')
    env_std = float(np.std(envelope))
    env_mean = float(np.mean(envelope))
    env_var_ratio = env_std / max(env_mean, 1e-6)  # 0=平稳, > 1=跳跃

    # 频域: FFT magnitude
    try:
        fft = np.fft.rfft(arr)
        mag = np.abs(fft)
        freqs = np.fft.rfftfreq(len(arr), 1.0 / sample_rate)
    except Exception:
        return obs

    if len(mag) < 10:
        return obs

    # band energies (Hz):
    band_subwoofer = (0, 80)
    band_low = (80, 400)
    band_mid_low = (400, 800)
    band_voice = (800, 3000)
    band_high = (3000, 8000)

    def _band_energy(low_hz, high_hz):
        idx = (freqs >= low_hz) & (freqs < high_hz)
        if not np.any(idx):
            return 0.0
        return float(np.sum(mag[idx]))

    e_sub = _band_energy(*band_subwoofer)
    e_low = _band_energy(*band_low)
    e_midlow = _band_energy(*band_mid_low)
    e_voice = _band_energy(*band_voice)
    e_high = _band_energy(*band_high)
    e_total = e_sub + e_low + e_midlow + e_voice + e_high + 1e-6

    r_voice = e_voice / e_total
    r_low = e_low / e_total
    r_high = e_high / e_total
    r_midlow = e_midlow / e_total

    # peak frequency in voice band
    voice_idx = (freqs >= band_voice[0]) & (freqs < band_voice[1])
    voice_mag = mag[voice_idx] if np.any(voice_idx) else np.array([0.0])
    voice_peak = float(np.max(voice_mag)) if len(voice_mag) > 0 else 0.0

    # harmonic-ness: count distinct peaks > 30% of max in low+mid band
    low_mid_idx = (freqs >= 80) & (freqs < 1500)
    lm_mag = mag[low_mid_idx] if np.any(low_mid_idx) else np.array([0.0])
    n_peaks = 0
    if len(lm_mag) > 5:
        max_lm = float(np.max(lm_mag))
        if max_lm > 0:
            # local maxima > 30% of max
            for i in range(1, len(lm_mag) - 1):
                if lm_mag[i] > lm_mag[i - 1] and lm_mag[i] > lm_mag[i + 1]:
                    if lm_mag[i] > 0.3 * max_lm:
                        n_peaks += 1

    # ---- Rule based classification (conservative) ----
    # Sir 精准要求: 多条件协同, 单一特征不 fire

    # Rule 1: laughter — voice band 强 (≥ 0.45) + envelope 跳跃 (env_var_ratio ≥ 0.4) + 高频也含
    if r_voice >= 0.45 and env_var_ratio >= 0.4 and r_high >= 0.10:
        confidence = min(1.0, 0.5 + 0.5 * (env_var_ratio - 0.4))
        if confidence >= MIN_CONFIDENCE:
            obs.ambient_type = 'laughter'
            obs.confidence = confidence
            obs.metadata = {
                'r_voice': round(r_voice, 3),
                'env_var': round(env_var_ratio, 3),
                'r_high': round(r_high, 3),
            }
            return obs

    # Rule 2: sigh — 低频集中 (r_low >= 0.45) + 长持续 (env_var_ratio < 0.3 平稳) + 中音弱 (r_midlow < 0.20)
    if r_low >= 0.45 and env_var_ratio < 0.30 and r_midlow < 0.20:
        confidence = min(1.0, 0.5 + 0.5 * (r_low - 0.45))
        if confidence >= MIN_CONFIDENCE:
            obs.ambient_type = 'sigh'
            obs.confidence = confidence
            obs.metadata = {
                'r_low': round(r_low, 3),
                'env_var': round(env_var_ratio, 3),
                'r_midlow': round(r_midlow, 3),
            }
            return obs

    # Rule 3: humming — 低频集中 (r_low >= 0.40) + harmonic (n_peaks ≥ 3) + env 较平稳 (< 0.5)
    if r_low >= 0.40 and n_peaks >= 3 and env_var_ratio < 0.50:
        confidence = min(1.0, 0.5 + 0.1 * n_peaks)
        if confidence >= MIN_CONFIDENCE:
            obs.ambient_type = 'humming'
            obs.confidence = confidence
            obs.metadata = {
                'r_low': round(r_low, 3),
                'n_peaks': n_peaks,
                'env_var': round(env_var_ratio, 3),
            }
            return obs

    # Rule 4: video_playing — 多频段平衡 (max band ratio < 0.55) + 长持续 (env_var < 0.5) + 高频含 (≥ 0.10)
    max_band_ratio = max(r_sub := e_sub / e_total, r_low, r_midlow, r_voice, r_high)
    if max_band_ratio < 0.55 and env_var_ratio < 0.50 and r_high >= 0.10 and mean_amp > 0.01:
        confidence = min(1.0, 0.5 + 0.5 * (1 - max_band_ratio))
        if confidence >= MIN_CONFIDENCE:
            obs.ambient_type = 'video_playing'
            obs.confidence = confidence
            obs.metadata = {
                'max_band_ratio': round(max_band_ratio, 3),
                'r_high': round(r_high, 3),
            }
            return obs

    # Rule 5: conversation — voice + midlow 强 + 跳跃中等 (multi-formant pattern, 多人话)
    if r_voice >= 0.30 and r_midlow >= 0.15 and 0.25 <= env_var_ratio <= 0.60 and n_peaks >= 4:
        confidence = min(1.0, 0.45 + 0.15 * (n_peaks - 4))
        if confidence >= MIN_CONFIDENCE:
            obs.ambient_type = 'conversation'
            obs.confidence = confidence
            obs.metadata = {
                'r_voice': round(r_voice, 3),
                'r_midlow': round(r_midlow, 3),
                'n_peaks': n_peaks,
            }
            return obs

    # 没匹配 — 留空 (Sir 要求保守, 含糊不 fire)
    return obs


# ----------------------------------------------------------------------------
# AmbientSensor (单例)
# ----------------------------------------------------------------------------

class AmbientSensor:
    """Hook 同一帧 PyAudio data, 累积满 window 分类, publish 到 SWM.
    
    用法 (在 AuditoryCortex 主循环每帧):
        sensor.feed_frame(data, is_jarvis_speaking, is_sir_speaking, sir_in_active)
    
    feed_frame 内部:
      1. state gate: Jarvis/Sir 说话期 reset accum 不分析
      2. 累积到 ANALYSIS_WINDOW_SAMPLES (8000 = 500ms)
      3. 调 _classify_window → AmbientObservation
      4. ≥ CONSECUTIVE_AGREE 同类 + confidence ≥ MIN_CONF → publish SWM
      5. 同类 PER_TYPE_COOLDOWN_S 内不重复
    """

    def __init__(self, event_bus: Any = None, enabled: bool = True):
        self._lock = threading.Lock()
        self._enabled = enabled
        self._event_bus = event_bus
        # 累积 buffer (int16 list)
        self._accum: List[int] = []
        # 最近 N 次 observation (用做 consecutive agree 检测)
        self._recent_obs: Deque[AmbientObservation] = deque(maxlen=CONSECUTIVE_AGREE_THRESHOLD)
        # 每类 last publish ts
        self._last_publish_at: dict = {}
        # 总统计
        self._n_windows_analyzed = 0
        self._n_signals_published = 0

    def is_enabled(self) -> bool:
        return self._enabled and self._event_bus is not None

    def attach_event_bus(self, bus: Any) -> None:
        with self._lock:
            self._event_bus = bus

    def feed_frame(
        self,
        pyaudio_buffer,
        is_jarvis_speaking: bool = False,
        is_sir_speaking: bool = False,
        sir_in_active: bool = False,
    ) -> Optional[AmbientObservation]:
        """喂一帧 PyAudio data. 满 window 触发分类.
        
        Args:
            pyaudio_buffer: bytes / np.ndarray int16
            is_jarvis_speaking: Jarvis TTS 期间 reset accum
            is_sir_speaking: Sir 正在说话 (volume > 180) 期间 reset accum
            sir_in_active: Sir 已唤醒在对话期 — ambient 不 fire (避免跟 ASR 抢主脑注意)
        
        Returns:
            AmbientObservation if window 满且 classify 有结果, 否则 None
        """
        if not self._enabled:
            return None

        # state gate: 任何 "非纯 ambient" 状态 → reset accum 不分析
        if is_jarvis_speaking or is_sir_speaking or sir_in_active:
            with self._lock:
                self._accum = []
                self._recent_obs.clear()
            return None

        try:
            import numpy as np
            if isinstance(pyaudio_buffer, bytes):
                arr = np.frombuffer(pyaudio_buffer, dtype=np.int16)
            elif isinstance(pyaudio_buffer, (list, tuple)):
                arr = np.array(pyaudio_buffer, dtype=np.int16)
            else:
                arr = (
                    pyaudio_buffer.astype(np.int16)
                    if hasattr(pyaudio_buffer, 'astype')
                    else np.asarray(pyaudio_buffer, dtype=np.int16)
                )
        except Exception:
            return None

        with self._lock:
            self._accum.extend(arr.tolist())
            if len(self._accum) < ANALYSIS_WINDOW_SAMPLES:
                return None
            # 取一个 window 出来
            window = self._accum[:ANALYSIS_WINDOW_SAMPLES]
            self._accum = self._accum[ANALYSIS_WINDOW_SAMPLES:]

        try:
            import numpy as np
            window_arr = np.array(window, dtype=np.int16)
        except Exception:
            return None

        # volume gate
        try:
            mean_abs = float(np.abs(window_arr).mean())
        except Exception:
            mean_abs = 0.0
        if mean_abs < MIN_VOLUME_FOR_ANALYSIS or mean_abs > MAX_VOLUME_FOR_ANALYSIS:
            return None

        # classify
        obs = _classify_window(window_arr)
        self._n_windows_analyzed += 1

        with self._lock:
            self._recent_obs.append(obs)
            # Check consecutive agree
            if obs.ambient_type and obs.confidence >= MIN_CONFIDENCE:
                same_type_obs = [
                    o for o in self._recent_obs
                    if o.ambient_type == obs.ambient_type and o.confidence >= MIN_CONFIDENCE
                ]
                if len(same_type_obs) >= CONSECUTIVE_AGREE_THRESHOLD:
                    # cooldown 检查
                    last_pub = self._last_publish_at.get(obs.ambient_type, 0.0)
                    if time.time() - last_pub >= PER_TYPE_COOLDOWN_S:
                        self._publish_to_swm(obs, same_type_obs)
                        self._last_publish_at[obs.ambient_type] = time.time()
                        self._n_signals_published += 1

        return obs

    def _publish_to_swm(self, obs: AmbientObservation, agree_obs: List[AmbientObservation]) -> None:
        """publish ambient_state signal."""
        if self._event_bus is None:
            return
        try:
            # 平均 confidence
            avg_conf = sum(o.confidence for o in agree_obs) / max(1, len(agree_obs))
            desc = f"Ambient: {obs.ambient_type} (conf={avg_conf:.2f}, n={len(agree_obs)})"
            self._event_bus.publish(
                etype='ambient_state',
                description=desc,
                source='ambient_sensor',
                metadata={
                    'ambient_type': obs.ambient_type,
                    'confidence': round(avg_conf, 3),
                    'n_consecutive': len(agree_obs),
                    'last_classifier_meta': obs.metadata,
                },
                salience=0.45,  # 背景信号默认偏低
                ttl=180.0,
            )
            try:
                from jarvis_utils import bg_log
                bg_log(
                    f"🎵 [AmbientSensor] {obs.ambient_type} "
                    f"conf={avg_conf:.2f} (n={len(agree_obs)} 连续同意)"
                )
            except Exception:
                pass
        except Exception as e:
            try:
                from jarvis_utils import bg_log
                bg_log(f"⚠️ [AmbientSensor] publish err: {e}")
            except Exception:
                pass

    def reset(self) -> None:
        with self._lock:
            self._accum = []
            self._recent_obs.clear()

    def get_stats(self) -> dict:
        with self._lock:
            return {
                'enabled_flag': self._enabled,
                'bus_attached': self._event_bus is not None,
                'effective_enabled': self._enabled and self._event_bus is not None,
                'n_windows': self._n_windows_analyzed,
                'n_published': self._n_signals_published,
                'last_publish_at': dict(self._last_publish_at),
                'accum_samples': len(self._accum),
            }


# Register etype + default salience to ConversationEventBus
def _register_etype_defaults():
    """注册 ambient_state 到 ConversationEventBus 默认 TTL + salience.
    
    幂等 — 多次调用安全.
    """
    try:
        from jarvis_utils import ConversationEventBus
        if 'ambient_state' not in ConversationEventBus.DEFAULT_TTL:
            ConversationEventBus.DEFAULT_TTL['ambient_state'] = 180
        if 'ambient_state' not in ConversationEventBus.DEFAULT_SALIENCE:
            ConversationEventBus.DEFAULT_SALIENCE['ambient_state'] = 0.45
    except Exception:
        pass


_register_etype_defaults()


# Singleton
_GLOBAL_SENSOR: Optional[AmbientSensor] = None
_SINGLETON_LOCK = threading.Lock()


def get_ambient_sensor(event_bus: Any = None) -> AmbientSensor:
    """获取全局 sensor 单例. 第一次调用决定是否 enabled (env var JARVIS_AMBIENT_DISABLE=1 强制 disable)."""
    global _GLOBAL_SENSOR
    with _SINGLETON_LOCK:
        if _GLOBAL_SENSOR is None:
            enabled = os.environ.get('JARVIS_AMBIENT_DISABLE', '0') != '1'
            _GLOBAL_SENSOR = AmbientSensor(event_bus=event_bus, enabled=enabled)
        elif event_bus is not None and _GLOBAL_SENSOR._event_bus is None:
            _GLOBAL_SENSOR.attach_event_bus(event_bus)
        return _GLOBAL_SENSOR
