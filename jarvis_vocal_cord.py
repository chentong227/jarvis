
import os
import sys

# 🚀 1. 环境变量封杀进度条
os.environ["TQDM_DISABLE"] = "1"

# 🚀 2. 物理级劫持：把 tqdm 替换成“哑巴”
from functools import partialmethod
try:
    import tqdm
    tqdm.tqdm.__init__ = partialmethod(tqdm.tqdm.__init__, disable=True)
except Exception:
    pass

import torch
import numpy as np
import pyaudio
import re
import time
import torchaudio
import logging

# 👇 暴力接管 Python 原生日志系统，彻底静音所有 Warning！
logging.getLogger().setLevel(logging.ERROR)

# =========================================================================
# 🚨 修复 torchaudio 的加载 Bug (保留之前的环境补丁)
# =========================================================================
_original_load = torchaudio.load
def _safe_torchaudio_load(uri, *args, **kwargs):
    if isinstance(uri, torch.Tensor):
        audio_data = uri.clone()
        if audio_data.dim() == 1:
            audio_data = audio_data.unsqueeze(0)
        return audio_data, 16000
    return _original_load(uri, *args, **kwargs)

torchaudio.load = _safe_torchaudio_load

sys.path.append(os.path.join(os.path.dirname(__file__), 'CosyVoice'))

try:
    from cosyvoice.cli.cosyvoice import CosyVoice
except ImportError as e:
    print(f"❌[致命错误] 找不到 CosyVoice 模块: {e}")
    sys.exit(1)

# ----- 下面是你的 class VocalCord: -----

class VocalCord:
    def __init__(self):
        print("🗣️ [声带器官] 正在挂载纯血英文 ETE 引擎...")
        self.cosyvoice = CosyVoice('iic/CosyVoice-300M')
        
        prompt_path = os.path.join(os.path.dirname(__file__), 'jarvis_prompt.wav')
        query_audio, sr = _original_load(prompt_path)
        if sr != 16000:
            query_audio = torchaudio.transforms.Resample(sr, 16000)(query_audio)
        if query_audio.shape[0] > 1:
            query_audio = query_audio.mean(dim=0, keepdim=True)
        if query_audio.dim() == 1:
            query_audio = query_audio.unsqueeze(0)

        max_val = torch.abs(query_audio).max()
        if max_val > 0:
            query_audio = query_audio / max_val * 0.9 

        self.prompt_speech_16k = query_audio 
        
        # 🚨 终极密码：与你新剪辑的 5 秒音频台词一字不差，作为零样本对齐的锚点
        self.prompt_text = "I am JARVIS, a virtual artificial intelligence. And I'm here to assist you with a variety of tasks as best I can."
        
        self.p = pyaudio.PyAudio()
        
        # 👇 核心手术：声卡总闸常驻开启，消灭每次 0.5 秒的硬件唤醒延迟！
        self.stream = self.p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=22050,
            output=True
        )
        self._render_count = 0

        # 🩹 [P0+20-β.5.10 / 2026-05-19] BUG-3 真因修: prompt encoding cache
        # 根因 (benchmark 实证): frontend_zero_shot 每次 inference 都重算 5 秒 prompt_wav 的
        #   - _extract_speech_feat (mel spectrogram)
        #   - _extract_speech_token (speech tokenizer onnx)
        #   - _extract_spk_embedding (campplus onnx)
        # 这是 ~6s 固定开销, 跟字数无关 (9 chars 6.2s / 88 chars 8.5s, 增量极小).
        # CosyVoice 提供 add_zero_shot_spk(): 一次性 cache prompt encoding 到 spk2info dict,
        # 后续 inference 传 zero_shot_spk_id 直接复用 cached state, 跳过 prompt encoding.
        # 预期: 6.67s → ~1-2s (5x speedup).
        self._jarvis_spk_id = 'jarvis_default'
        print("⚡ [声带器官] cache prompt encoding (β.5.10)...")
        try:
            self.cosyvoice.add_zero_shot_spk(self.prompt_text, self.prompt_speech_16k, self._jarvis_spk_id)
            print(f"✅ [声带器官] prompt cached as spk_id='{self._jarvis_spk_id}'")
        except Exception as _cache_e:
            print(f"⚠️  [声带器官] add_zero_shot_spk 失败, fallback 每次重算: {_cache_e}")
            self._jarvis_spk_id = ''  # fallback 走 legacy 路径

        print("🔥 [声带器官] 正在给 GPU 注入高压点火预热，请稍候...")
        try:
            self.render_only("Systems fully operational.")
            print("✅ [声带器官] 显存预热完毕！")
        except Exception:
            pass

    # 👇 纯渲染函数 (只调动 4070 Ti SUPER 算数据，不说话)
    def _normalize_for_tts(self, text: str) -> str:
        text = text.strip()
        text = re.sub(r'\s+', ' ', text)
        text = text.replace('\n', '. ').replace('\r', ' ')
        text = re.sub(r'\.{2,}', '.', text)
        text = re.sub(r'!{2,}', '!', text)
        text = re.sub(r'\?{2,}', '?', text)
        text = re.sub(r'\b([a-z])\.([a-z])(?![a-z])', r'\1 dot \2', text)
        text = re.sub(r'\b(\d+)\.(\d+)\b', r'\1 point \2', text)
        text = re.sub(r'\b(\d{4})s\b', r'\1s', text)
        text = re.sub(r'\b(\d+)\s*(GB|MB|KB|TB)\b', r'\1 \2', text)
        text = re.sub(r'\b(\d+)\s*(am|pm)\b', r'\1 \2', text)
        text = re.sub(r'\b(\d+):(\d+)\b', r'\1 \2', text)
        text = re.sub(r'(\w)-(\w)', r'\1 \2', text)
        text = re.sub(r'[^\w\s.,?!\'，。？！；：、\-:()]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _split_long_sentence(self, text: str, max_len: int = 200) -> list:
        if len(text) <= max_len:
            return [text]
        parts = []
        remaining = text
        while len(remaining) > max_len:
            split_at = remaining.rfind('. ', 0, max_len)
            if split_at == -1:
                split_at = remaining.rfind(', ', 0, max_len)
            if split_at == -1:
                split_at = remaining.rfind(' ', 0, max_len)
            if split_at == -1 or split_at < 20:
                split_at = max_len
            parts.append(remaining[:split_at + 1].strip())
            remaining = remaining[split_at + 1:].strip()
            if not remaining:
                break
        if remaining:
            parts.append(remaining)
        return parts

    def render_only(self, text: str, retry: int = 2):
        if not text: return None
        safe_text = self._normalize_for_tts(text)
        if not safe_text:
            return None

        sentences = self._split_long_sentence(safe_text)

        all_audio = []
        for sentence in sentences:
            if not sentence.strip():
                continue
            for attempt in range(retry + 1):
                try:
                    # 🩹 [P0+20-β.5.10] zero_shot_spk_id 非空时跳过 prompt encoding (5x 加速)
                    output_generator = self.cosyvoice.inference_zero_shot(
                        sentence,
                        self.prompt_text,
                        self.prompt_speech_16k,
                        zero_shot_spk_id=self._jarvis_spk_id,
                        stream=False
                    )

                    audio_chunks = []
                    for output_dict in output_generator:
                        audio_chunks.append(output_dict['tts_speech'].numpy().flatten())

                    audio_data = np.concatenate(audio_chunks)
                    audio_data = audio_data * 1.3
                    audio_data = np.clip(audio_data, -1.0, 1.0)
                    all_audio.append(audio_data)
                    break
                except Exception as e:
                    try:
                        from jarvis_utils import bg_log as _bg
                        _bg(f"⚠️ [渲染失败] attempt {attempt+1}/{retry+1}: {e}")
                    except Exception:
                        pass
                    if attempt < retry:
                        import gc
                        gc.collect()
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                        time.sleep(0.3)
                    else:
                        try:
                            from jarvis_utils import bg_log as _bg
                            _bg(f"❌ [渲染彻底失败] 已重试{retry}次，放弃: {sentence[:80]}")
                        except Exception:
                            pass
            self._render_count += 1
            # 🆕 [P5-fix62 / 2026-05-23 16:25] Sir 16:23 真测痛点: TTS 卡顿渐重
            # (turn 1 OK / turn 2 渐卡 / turn 3 full 16.4s 严重). 根因: 老阈值 10
            # 才清 GPU, CosyVoice-300M GPU 内存碎片累积 → 后续 render 卡.
            # Sir 听感真痛点, BUG-A.
            #
            # 修法: 阈值 10 → 3 (更频繁清). 不动 stream=False (避免 cascading 改动).
            # 每次 render 后轻 empty_cache (无 gc.collect 重负担).
            if torch.cuda.is_available():
                torch.cuda.empty_cache()  # 轻 cache 清理 (无 gc.collect 重负担)
            if self._render_count >= 3:
                self._render_count = 0
                import gc
                gc.collect()  # 重 GC 每 3 次 (vs 老 10 次)
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

        if not all_audio:
            return None

        audio_data = np.concatenate(all_audio)
        audio_data_int16 = (audio_data * 32767).astype(np.int16)

        # [v3 fix] 前后都加静音 padding：
        # - 前 0.15s：保留原有的"起音保护"（避免 stream 第一帧丢失开头辅音）
        # - 后 0.25s：解决"Done, Sir." / "Yes, Sir." 等短句末尾 's' / 'r' 被截的问题
        #   根因：pyaudio.stream.write 是异步缓冲，短音频写完立刻返回，但驱动还没真正放完，
        #   下游一旦切到 IDLE/状态机变化就把缓冲冲掉了。追加 0.25s 静音让最后真实音节有时间播完。
        leading_silence_samples = int(0.15 * 22050)
        trailing_silence_samples = int(0.25 * 22050)
        leading_silence = np.zeros(leading_silence_samples, dtype=np.int16)
        trailing_silence = np.zeros(trailing_silence_samples, dtype=np.int16)
        final_audio_int16 = np.concatenate((leading_silence, audio_data_int16, trailing_silence))

        return final_audio_int16.tobytes()

    def play_only(self, audio_bytes: bytes):
        if not audio_bytes: return
        try:
            self.stream.write(audio_bytes)
        except Exception as e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"⚠️ [播放失败] 声卡流异常: {e}")
            except Exception:
                pass
            self._recover_stream()
            if self.stream:
                try:
                    self.stream.write(audio_bytes)
                    print("✅ [声卡恢复] 音频流已重新建立，重播成功")
                except Exception as e2:
                    try:
                        from jarvis_utils import bg_log as _bg
                        _bg(f"❌ [声卡恢复] 重播仍然失败: {e2}")
                    except Exception:
                        pass

    def _recover_stream(self):
        try:
            self.stream.stop_stream()
            self.stream.close()
        except:
            pass
        try:
            self.stream = self.p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=22050,
                output=True
            )
        except Exception as e:
            try:
                from jarvis_utils import bg_log as _bg
                _bg(f"❌ [声卡重建失败]: {e}")
            except Exception:
                pass
            self.stream = None

    # 为了兼容你其他旧代码的调用逻辑，保留 say 函数
    def say(self, text: str):
        # [轴 1.3 / 2026-05-15] 单点回声防御：所有 vocal.say(text) 的调用方
        # （ReturnSentinel AFK 问候 / Mailbox 通知 / 反射回应 / dynamic_wake / interrupt_all 的 _speak_exit /
        #  ChronosTick 邮箱播报 等）一律在播放前把 text 注册进回声指纹环，
        # 防 ASR 把 Jarvis 自己说的话拾回触发自循环。
        # _render_worker 主对话路径已在 jarvis_nerve.py 6170 主动 register，
        # 这里覆盖所有"短路绕开主路径"的 say 调用 —— 一处修，全局兜底。
        # [P0+18-a.14 / 2026-05-15] 修 BUG #9: 第一句对话念中文 — 兜底守门：
        # 任何含中文的 text 在 render 前 strip 中文。Jarvis 是英文 zero-shot TTS，不应念中文。
        if text:
            try:
                if re.search(r'[\u4e00-\u9fa5]', text):
                    _orig = text
                    if '---ZH---' in text:
                        text = text.split('---ZH---')[0].strip()
                    else:
                        text = re.sub(r'[\u4e00-\u9fa5，。！？；：、""''（）【】《》]+', ' ', text)
                        text = re.sub(r'\s+', ' ', text).strip()
                    try:
                        from jarvis_utils import bg_log
                        bg_log(f"⚠️ [VocalSay Guard] 拦截含中文输入: '{_orig[:60]}' → '{text[:60]}'")
                    except Exception:
                        pass
            except Exception:
                pass
        if not text:
            return
        try:
            from jarvis_utils import register_jarvis_tts
            register_jarvis_tts(text)
        except Exception:
            pass
        audio = self.render_only(text)
        self.play_only(audio)

    def __del__(self):
        if hasattr(self, 'stream'):
            self.stream.stop_stream()
            self.stream.close()
        if hasattr(self, 'p'):
            self.p.terminate()
