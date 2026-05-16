"""
P0+18-a.0 一次性数据修复脚本：
  Sir 13:03:37 实测 "帮我把 D:\\Jarvis\\test_dummy.txt 文件删了"
  → Gatekeeper LLM 误把它解读成"删 STM 关于这个文件的记忆条目" → 触发 delete_memory_hint='D盘 test.txt 文件'
  → search_memory 找到 5 条 0.68-0.72 相似度的无辜记忆 → 全删（ID=110/9/5/194/198 P0+16 复发）

本脚本：调 hippocampus.restore_memory(id) × 5 把这 5 条无辜记忆从软删恢复 LIVE。
跑一次后 Sir 可以删本脚本（或保留作回溯样板）。

用法（在工程根目录）：
    python tools/restore_p0_plus_18.py
"""
import os
import sys

# 让脚本能从工程根目录跑
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from jarvis_hippocampus import Hippocampus

# P0+18-a.0：13:03:37 误删的 5 条 ID（来自 P0+18 调查阶段日志）
TARGET_IDS = [110, 9, 5, 194, 198]


def main():
    print("=" * 64)
    print("🛟 [P0+18-a.0] Memory Restore 脚本启动")
    print(f"   目标 ID: {TARGET_IDS}")
    print(f"   操作：UPDATE TaskMemories SET is_deleted=0 WHERE id IN (...)")
    print("=" * 64)

    hippo = Hippocampus()
    restored = []
    skipped = []
    for mid in TARGET_IDS:
        try:
            hippo.restore_memory(mid)
            restored.append(mid)
        except Exception as e:
            print(f"   ⚠️ ID={mid} 恢复失败: {e}")
            skipped.append((mid, str(e)))

    print("=" * 64)
    print(f"✅ 恢复成功: {len(restored)} 条 → {restored}")
    if skipped:
        print(f"⚠️ 跳过: {len(skipped)} 条 → {skipped}")
    print("=" * 64)
    print("   提示：Sir 重启 Jarvis 后可以用 search_memory 验证这 5 条已 LIVE。")
    print("   本脚本是一次性的，跑完就可以删。")


if __name__ == '__main__':
    main()
