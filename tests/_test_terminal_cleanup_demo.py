"""演示终端打印整顿后的视觉效果。
模拟 stream_chat 期间多个后台线程乱喷的场景，看新的 bg_log 是否能清出干净的对话框。"""
import sys
import os
import time
import threading
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from jarvis_utils import bg_log, set_conversation_active


def background_noise_burst():
    """模拟 4 个并发后台噪音源同时往 stdout/stderr 乱喷。"""
    def noise(name, delay, count):
        for i in range(count):
            time.sleep(delay)
            bg_log(f"[{name}] noisy event #{i+1}")
    threading.Thread(target=noise, args=("KeyRouter", 0.05, 3), daemon=True).start()
    threading.Thread(target=noise, args=("HabitClock", 0.07, 2), daemon=True).start()
    threading.Thread(target=noise, args=("Pipeline Timer", 0.04, 4), daemon=True).start()
    threading.Thread(target=noise, args=("Hippocampus", 0.06, 2), daemon=True).start()


def fake_stream_chat():
    """模拟 stream_chat 的对话框打印。"""
    set_conversation_active(True)
    try:
        print("╔" + "═" * 63)
        print("║ 🗣️  [Human] 帮我把音量调到 30%")
        print("╠" + "═" * 63)
        print(f"║ ⏰ [{time.strftime('%H:%M:%S')}] Jarvis 开始响应")
        print("║ 🤖  [Jarvis] ", end="", flush=True)

        # 启动背景噪音
        background_noise_burst()

        # 模拟流式输出
        for word in ["Done", ", ", "Sir", "."]:
            time.sleep(0.1)
            print(word, end="", flush=True)
        print()  # newline

        # 模拟工具结果
        print("\n╔" + "═" * 63)
        print("║ 🔧 [Tool Results]")
        print("╠" + "═" * 63)
        print("║ ✅ audio_hands.set_volume: 音量已设为约 30%")
        print("╚" + "═" * 63 + "\n")

        time.sleep(0.4)  # 让所有噪音线程跑完
    finally:
        set_conversation_active(False)


def main():
    print("=" * 65)
    print("DEMO: stream_chat 期间，对话框 vs 背景日志")
    print("=" * 65)
    print("（如果整顿成功：对话框内只剩 Jarvis 自己的话，背景日志在框外）\n")
    fake_stream_chat()
    print("\n=" * 65)
    print("End of demo. Background section should appear AFTER the box closed.")


if __name__ == "__main__":
    main()
