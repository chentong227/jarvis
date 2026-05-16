"""所有"简单设备控制"hands 的离线 smoke test。
专注于**参数校验**这一层 —— 用模拟方法把硬件触发的部分屏蔽掉，避免误触系统键导致 access violation。

正向用例只对那些不涉及硬件的指令（list/get/未知指令）做真实调用；
对涉及硬件的（set_volume / volume_up）只通过 patch 验证参数路径。"""
import sys
import os
import unittest.mock as mock
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def expect_ok(label, result):
    ok = result.success
    print(f"  {'OK ' if ok else 'FAIL'} {label:38s} success={ok} msg={result.msg[:60]!r}")
    return ok


def expect_fail(label, result, must_contain=None):
    ok = (not result.success)
    if must_contain:
        ok = ok and (must_contain in result.msg)
    print(f"  {'OK ' if ok else 'FAIL'} {label:38s} success={result.success} msg={result.msg[:80]!r}")
    return ok


def main():
    from jarvis_blood import Action
    fails = 0

    # ===== audio_hands set_volume 参数路径 =====
    print("\n--- audio_hands.set_volume parameter path ---")
    from l4_hands_pool import l4_audio_hands
    AH = l4_audio_hands.Hands
    a = AH()

    # 屏蔽真实 keybd_event 以免连续触发系统音量键
    with mock.patch.object(l4_audio_hands, 'user32', new=mock.MagicMock()):
        with mock.patch('time.sleep'):
            for alias in ("level", "volume_level", "volume", "vol", "percent", "percentage"):
                r = a.execute(Action(command="set_volume", params={alias: 50}))
                if not expect_ok(f"set_volume({alias}=50)", r):
                    fails += 1
            r = a.execute(Action(command="set_volume", params={"level": "30%"}))
            if not expect_ok("set_volume(str '30%')", r):
                fails += 1

    r = a.execute(Action(command="set_volume", params={}))
    if not expect_fail("set_volume missing", r, "明确传入 level"):
        fails += 1
    r = a.execute(Action(command="set_volume", params={"level": "abc"}))
    if not expect_fail("set_volume invalid str", r, "无法解析"):
        fails += 1
    r = a.execute(Action(command="set_volume", params={"level": 200}))
    if not expect_fail("set_volume out-of-range", r, "越界"):
        fails += 1
    r = a.execute(Action(command="bogus_cmd", params={}))
    if not expect_fail("bogus_cmd", r, "未知指令"):
        fails += 1

    # ===== media_control_hands set_volume 参数路径 =====
    print("\n--- media_control_hands.set_volume parameter path ---")
    from l4_hands_pool import l4_media_control_hands
    MH = l4_media_control_hands.Hands
    m = MH()
    with mock.patch.object(l4_media_control_hands, 'user32', new=mock.MagicMock()):
        with mock.patch('time.sleep'):
            for alias in ("level", "volume_level", "volume", "vol", "percent"):
                r = m.execute(Action(command="set_volume", params={alias: 40}))
                if not expect_ok(f"media.set_volume({alias}=40)", r):
                    fails += 1
            r = m.execute(Action(command="set_volume", params={"level": "60%"}))
            if not expect_ok("media.set_volume('60%')", r):
                fails += 1

    r = m.execute(Action(command="set_volume", params={}))
    if not expect_fail("media.set_volume missing", r, "明确传入 level"):
        fails += 1
    r = m.execute(Action(command="set_volume", params={"level": -1}))
    if not expect_fail("media.set_volume oor neg", r, "越界"):
        fails += 1

    # ===== clipboard_hands （真实 OS 调用，但安全） =====
    print("\n--- clipboard_hands (real OS API, but safe) ---")
    from l4_hands_pool.l4_clipboard_hands import Hands as CH
    cp = CH()
    test_payload = "jarvis-smoke-clipboard-12345"
    r = cp.execute(Action(command="set", params={"text": test_payload}))
    if not expect_ok("clipboard.set", r):
        fails += 1
    r = cp.execute(Action(command="get", params={}))
    if not expect_ok("clipboard.get", r):
        fails += 1
    if r.data and r.data.get("text") != test_payload:
        print(f"  FAIL clipboard.get returned wrong text! data={r.data!r}")
        fails += 1
    else:
        print(f"  OK   clipboard.get returned the exact text we set")
    r = cp.execute(Action(command="clear", params={}))
    if not expect_ok("clipboard.clear", r):
        fails += 1
    r = cp.execute(Action(command="bogus_cp", params={}))
    if not expect_fail("clipboard.bogus", r, "未知指令"):
        fails += 1

    # ===== notification_hands （只走未知指令路径 + 模拟 beep 调用） =====
    print("\n--- notification_hands ---")
    from l4_hands_pool import l4_notification_hands
    NH = l4_notification_hands.Hands
    n = NH()
    # 真实 beep 会发声；用 mock 避开
    with mock.patch.object(l4_notification_hands, 'ctypes', new=mock.MagicMock()) as ctypes_mock:
        ctypes_mock.windll.kernel32.Beep.return_value = 1
        r = n.execute(Action(command="beep", params={"freq": 500, "duration": 50}))
        if not expect_ok("notify.beep(mocked)", r):
            fails += 1
    r = n.execute(Action(command="bogus_notify", params={}))
    if not expect_fail("notify.bogus", r, "未知指令"):
        fails += 1

    # ===== window_hands 未知指令 =====
    print("\n--- window_hands ---")
    from l4_hands_pool.l4_window_hands import Hands as WH
    w = WH()
    r = w.execute(Action(command="bogus_win", params={}))
    if not expect_fail("window.bogus", r, "未知"):
        fails += 1

    print(f"\n{'='*60}\nTotal failures: {fails}\n{'='*60}")
    if fails:
        sys.exit(1)
    print("All hands smoke tests passed.")


if __name__ == "__main__":
    main()
