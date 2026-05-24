# -*- coding: utf-8 -*-
"""[Archive / Reshape M6.5.3 / 2026-05-24] CentralNerve.run() v1 — 3-brain task flow.

🆕 此 file 是 3-brain (RightBrain/LeftBrain/L5Brain) task flow 的 historic archive.
Sir Q2 决议: 3-brain 彻底放弃, 主对话 100% 走 jarvis_chat_bypass.stream_chat
单脑路径 (Soul + Memory + Tool fast_call 直接).

老 `CentralNerve.run()` 364 行实现 archived 这里, 以备:
- M6.5.3 后审计回看 — 看老 task flow design intent
- 万一未来需要恢复 3-brain (极小概率 — Sir 已经验证单脑足够)

**当前不再 import / 不再调用**. 仅文件存档.

老调用路径: worker.py:5083 self.jarvis.run() ← worker.trigger_routing()
                                              ← chat_bypass.stream_chat 收 <ENGAGE_PHYSICAL_BODY> 标记 → callback

新行为: CentralNerve.run() (in jarvis_central_nerve.py) 改成 stub:
    1. publish SWM event `deprecated_3_brain_invoked`
    2. raise RuntimeError("3-brain deprecated")
    3. existing except block 接管 → chat_bypass.stream_chat 主脑 fallback 道歉 + 安抚 Sir

依赖 (老 task flow 需要):
    - self.right_brain.set_strategic_plan(voice_input, stm_text, organ_whitepaper) → tasks
    - self.left_brain.clear_working_memory()
    - self.left_brain.inject_capabilities(self.hands.get_instruction_dict())
    - self.left_brain.generate_actions(self.blood, current_tick_model) → (actions, thought)
    - self.l5_brain.analyze_deadlock(self.blood, available_tools) → advice
    - self.l5_brain.audit_high_risk_action(self.blood, action) → audit_result
    - self.eyes.scan(self.hands) → perception
    - self.hands.execute(action) → ExecutionResult
    - self.hippocampus.seal_memory(...)

老 file 备份: _legacy/3_brain_attempt/{l1_right_brain,l3_left_brain,l5_reflection_brain}.py

Cleanup trigger (M7+): Sir 真用 1 周 + SWM `deprecated_3_brain_invoked` event = 0
                        → 此 file 可 git rm 完全删除.
"""

# 老 method body (364 行) 完整 archive — 见 git history:
# git show <commit_before_M6.5.3>:jarvis_central_nerve.py
# 或: git log --all -p -- jarvis_central_nerve.py | grep -A 364 "def run(self, voice_input"
#
# 不在此 inline duplicate, 减少 archive file 大小. git history 永远可恢复.
