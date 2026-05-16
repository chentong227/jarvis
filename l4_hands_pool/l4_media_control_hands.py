import ctypes
import time
from jarvis_blood import Action, ExecutionResult

MANIFEST = {
    "name": "media_control_hands",
    "description": "媒体控制器。播放/暂停/上一首/下一首/停止/音量调节。通过模拟多媒体键实现，纯本地。",
}

user32 = ctypes.windll.user32

VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001


class Hands:
    def __init__(self):
        self.requires_memory_seal = False

    def get_instruction_dict(self) -> str:
        return """
        【媒体控制器 指令字典】：
        1. "play_pause": {} — 播放/暂停
        2. "next": {} — 下一首
        3. "prev": {} — 上一首
        4. "stop": {} — 停止
        5. "volume_up": {"steps": <整数, 默认 5>} — 音量+
        6. "volume_down": {"steps": <整数, 默认 5>} — 音量-
        7. "mute": {} — 静音切换
        8. "set_volume": {"level": <0-100 整数, 必填>}
           — 设置音量。level 必须显式来自用户原话（如 "30%" → 30）；不要使用任何默认值。
           — 别名亦可：volume_level / volume / vol / percent。
        """

    def _send_key(self, vk, up=False):
        flags = KEYEVENTF_EXTENDEDKEY
        if up:
            flags |= KEYEVENTF_KEYUP
        user32.keybd_event(vk, 0, flags, 0)

    def _press_key(self, vk):
        self._send_key(vk, up=False)
        time.sleep(0.02)
        self._send_key(vk, up=True)

    def execute(self, action: Action) -> ExecutionResult:
        cmd = action.command
        params = action.params
        try:
            if cmd == "play_pause":
                self._press_key(VK_MEDIA_PLAY_PAUSE)
                return ExecutionResult(success=True, msg="播放/暂停")

            elif cmd == "next":
                self._press_key(VK_MEDIA_NEXT_TRACK)
                return ExecutionResult(success=True, msg="下一首")

            elif cmd == "prev":
                self._press_key(VK_MEDIA_PREV_TRACK)
                return ExecutionResult(success=True, msg="上一首")

            elif cmd == "stop":
                self._press_key(VK_MEDIA_STOP)
                return ExecutionResult(success=True, msg="停止")

            elif cmd == "volume_up":
                steps = params.get("steps", 5)
                for _ in range(steps):
                    self._press_key(VK_VOLUME_UP)
                    time.sleep(0.03)
                return ExecutionResult(success=True, msg=f"音量 +{steps}")

            elif cmd == "volume_down":
                steps = params.get("steps", 5)
                for _ in range(steps):
                    self._press_key(VK_VOLUME_DOWN)
                    time.sleep(0.03)
                return ExecutionResult(success=True, msg=f"音量 -{steps}")

            elif cmd == "mute":
                self._press_key(VK_VOLUME_MUTE)
                return ExecutionResult(success=True, msg="静音切换")

            elif cmd == "set_volume":
                # 🛡️ 与 audio_hands.set_volume 一致：不允许静默默认 + 兼容大模型常见别名
                _level_aliases = ("level", "volume_level", "volume", "vol",
                                  "value", "percent", "percentage", "media_volume",
                                  "audio_level", "vol_level")
                raw_level = None
                used_alias = None
                for _k in _level_aliases:
                    if _k in params and params[_k] not in (None, ""):
                        raw_level = params[_k]
                        used_alias = _k
                        break
                if raw_level is None:
                    return ExecutionResult(
                        success=False,
                        msg="set_volume 需要明确传入 level 参数（0-100 的整数）。"
                            "也可使用别名 volume_level/volume/vol/percent。"
                            "请重新发起 FAST_CALL 并显式指定。",
                    )
                if isinstance(raw_level, str):
                    raw_level = raw_level.strip().rstrip("%").strip()
                try:
                    level = int(float(raw_level))
                except (TypeError, ValueError):
                    return ExecutionResult(
                        success=False,
                        msg=f"set_volume 收到非法 level={raw_level!r}（来自 '{used_alias}'），无法解析为整数。请用 0-100 的数字。",
                    )
                if not (0 <= level <= 100):
                    return ExecutionResult(
                        success=False,
                        msg=f"set_volume 的 level={level} 越界（必须在 0-100 之间）",
                    )
                for _ in range(50):
                    self._press_key(VK_VOLUME_DOWN)
                    time.sleep(0.01)
                for _ in range(level // 2):
                    self._press_key(VK_VOLUME_UP)
                    time.sleep(0.01)
                return ExecutionResult(success=True, msg=f"音量设为 {level}%")

            else:
                return ExecutionResult(success=False, msg=f"未知指令: {cmd}")

        except Exception as e:
            return ExecutionResult(success=False, msg=f"媒体控制异常: {str(e)}")