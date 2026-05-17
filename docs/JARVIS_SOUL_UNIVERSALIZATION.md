# Jarvis Soul Universalization — 灵魂通用化重构方案

**版本**：v1.1 / 2026-05-17（subagent 全景调研后修订）
**作者**：Sir + Claude（Cursor agent / β.2.7 设计会话）
**前置**：`docs/JARVIS_SOUL_DRIVE.md`（5 层灵魂工程已完工 / `v0.25.0-soul-evolving`）

> "把贾维斯其他发声的部分重构到主脑上（经过 layer0~5 层）比如 SmartNudge 等等，
> 规划整个架构接入主脑，这样贾维斯就能完成完整的灵魂通用，对吧？"
> —— Sir 2026-05-17 01:16

**v1.1 主要修订**：

1. **发现已存在的正确范本**：`ChronosTick._speak_mail` → `_assemble_prompt(mode="mail")` → `stream_chat` —— Chronos 信箱播报**已经**走 Layer 0-3 注入路径。CentralNerve 致命异常恢复 `_assemble_prompt(mode="light")` 同款。统一方案应该向它对齐。
2. **Phase 1 方案调整**：从"抽 helper 给 `_build_public_layers` 复用"改为"`stream_nudge` **直接用** `_assemble_prompt(mode='nudge')`"——更彻底，整段 `_build_public_layers` 可考虑废弃。
3. **ReturnSentinel `_speak_and_soft_focus` 实际是死代码**（`_on_return` 在 `use_llm` 分支已 return）。Phase 2 可大幅简化或合并入 Phase 1。
4. **新增次要路径盘点**：SleepIntentDetector / `_check_short_sleep` / Spinal reflex (`reflex_dict`) / Blood ask_user / backchannel PCM 池 / `SILENT_NUDGE_TEMPLATES` / `_speak_exit` standby。共 5+ 条纯模板路径。
5. **修正认知错误**：SmartNudge / Conductor / CommitmentWatcher 当前**就是走 LLM**（`stream_nudge`），不是"纯模板"。问题只在 prompt 不含 Layer 0-3 注入。

---

## 0. TL;DR

灵魂工程 5 层 (`v0.25.0-soul-evolving`) **只接到了主对话路径**。所有 nudge / sentinel /
归来感知 / 退场语 等"主动发声"路径要么**走主脑但 prompt 缺 Layer 0-5 注入**，要么
**纯模板硬出**。本文规划"灵魂通用化"重构 —— 让 **Jarvis 所有发声都流过 Layer 0-5**。

3 阶段实施：
- **Phase 1 (必做, ~1h)**：抽出 `build_soul_prompt_extension()` helper，注入
  `_build_public_layers` → SmartNudge / Conductor / CommitmentWatcher / translate_worker
  全部立即受益。最大快速胜利。
- **Phase 2 (~2h)**：ReturnSentinel `get_dynamic_greeting` 改 push `__NUDGE__:return_greeting`
  走主脑（return_greeting directive 已存在）。
- **Phase 3 (~1.5h)**：standby 退场 `_speak_exit` 改"模板即播 + 主脑后台生成进 STM"
  双轨（延迟不允许等主脑）。其他纯模板路径同款处理。

总工时 ~5h，分 4 个独立 commit + tag `v0.26.0-soul-universal`。

---

## 1. 现状盘点

### 1.1 发声路径全景

| # | 路径 | 入口 | 内容生成 | 当前是否含 Layer 0-5 |
|---|---|---|---|---|
| 1 | 主对话 | `stream_chat` / `_assemble_prompt` | 主脑 LLM (full prompt) | ✅ 完整 |
| 2 | SmartNudge | `push_command("__NUDGE__:...")` → `stream_nudge` → `_build_public_layers` | 主脑 LLM (nudge_directive) | ❌ **只有 JARVIS_CORE_PERSONA 静态常量** |
| 3 | Conductor | 路由后同 #2 路径 | 同上 | ❌ 同上 |
| 4 | CommitmentWatcher | 同 #2 push __NUDGE__:commitment_check | 同上 | ❌ 同上 |
| 5 | stream_chat_local | local 降级路径 | 同上 _build_public_layers | ❌ 同上 |
| 6 | translate_worker | 翻译路径 | 同上 (line 753 引 JCP) | ❌ 同上 |
| 7 | **ReturnSentinel.get_dynamic_greeting** | 无 LLM | `random.choice(greetings_list)` | ❌ **纯模板** |
| 8 | **ReturnSentinel.get_dynamic_wake_response** | 无 LLM | `random.choice` | ❌ 纯模板 |
| 9 | **_speak_exit (standby 退场)** | 无 LLM, jarvis_worker.py:1477 | `random.choice(stand_down_phrases)` (5 句) | ❌ 纯模板 |
| 10 | SoulArchivistSentinel 自身 say | 无（只更新 sir_profile） | — | — |
| 11 | SystemSentinel / ChronosSentinel | 待 subagent 详查 | — | 待查 |

### 1.2 两类泄漏

| 泄漏类型 | callsite 数 | 严重程度 | 修复难度 |
|---|---|---|---|
| **A. 走主脑但 prompt 缺注入** (#2-6) | 5 | 🔴 高 — 已经在调主脑，但灵魂没传过去 | 🟢 低（改一处 helper 即所有受益）|
| **B. 完全不走主脑** (#7-9 + 可能其他) | 3+ | 🟡 中 — 模板有"工程懒惰"风险，但低延迟场景模板有合理性 | 🟡 中（每个 callsite 独立改造）|

### 1.3 关键证据

主对话拼接（line 826-871，β.2.0+1+2+3 注入）：
```883:898:jarvis_central_nerve.py
        _parts = [_base_persona]
        if self_anchor_block:
            _parts.append(self_anchor_block)
        if soul_block:
            _parts.append(soul_block)
        if relational_block:
            _parts.append(relational_block)
        if attention_block:
            _parts.append(attention_block)
        core_persona = '\n\n'.join(_parts)
```

Nudge 路径拼接（line 3029，**只有静态 PERSONA**）：
```3025:3030:jarvis_chat_bypass.py
        try:
            from jarvis_central_nerve import JARVIS_CORE_PERSONA as _JCP
        except Exception:
            _JCP = ""

        public_layers = f"""{_JCP}
```

---

## 2. 重构方案（v1.1 修订）

### 总策略

向 `ChronosTick._speak_mail` 的范本对齐：**所有主动发声都走 `_assemble_prompt(mode=<X>)` + `stream_chat`**，不再用并行的 `_build_public_layers` 拼装路径。`_assemble_prompt` 扩展 `mode` 参数（已有 `full` / `mail` / `light`），新增 `nudge`（瘦身版用于 SmartNudge 类短促主动发声）。

### Phase 1：`_assemble_prompt(mode='nudge')` + stream_nudge 切换主装配（核心，~2h）

**问题**：`_build_public_layers` (chat_bypass.py:3029) 用 `JARVIS_CORE_PERSONA` 静态常量，**完全绕过 `_assemble_prompt`** 的 Layer 0-3 注入。`stream_nudge` 这条路其实已经走 LLM 了，只是装配错了。

**方案**：让 `_assemble_prompt` 接受 `mode='nudge'` 走轻量分支（裁掉重型 section 如 LTM / anticipator / skill_tree，保留 Layer 0-3 + persona + profile_block + 关键 context），`stream_nudge` 调用 `_assemble_prompt(mode='nudge', user_input=<derived>)` 替换 `_build_public_layers`。

**主改动**：

1. `jarvis_central_nerve.py:_assemble_prompt` 加 `mode='nudge'` 分支：
   - 保留 Layer 0-3 注入（最大价值）
   - 跳过 LTM 检索 / anticipator / skill_tree / memory_gateway（这些重 section 在 nudge 短发声场景没必要，等同 `SHORT_CHAT` tier）
   - `user_input` 由 `nudge_context.get('nudge_directive', '')` 衍生（用 directive 摘要替代真实用户输入）
   - 输出 prompt 字符串体积 ~5-7K（vs 主对话 ~22K）

2. `jarvis_chat_bypass.py:stream_nudge`：
   - 删 `_build_public_layers` 调用
   - 改 `prompt = self.jarvis._assemble_prompt(user_input=nudge_directive, mode='nudge', soul_tags=...)`
   - 保留 `nudge_directive` 作为**尾随 task instruction**（在 prompt 末尾追加 `=== THIS TURN'S TASK ===\n{nudge_directive}`）
   - `_create_stream` 不变

3. **保险措施**：保留 `_build_public_layers` 不删（注释 deprecated）；如发现 nudge 体感退步可一键 revert 单 commit。

**效果**：SmartNudge / Conductor / CommitmentWatcher / ReturnSentinel `__NUDGE__:return_greeting`（实际也是走 stream_nudge）**全部立即接通 Layer 0-3**，发声 prompt 含 `🪞 [SOUL inject]` 诊断 log。

**测试**：
- 单测：mock 一个 nerve fixture 调 `_assemble_prompt(mode='nudge')`，断言输出含 SelfAnchor/Concerns/Relational 子串
- 静态扫：`stream_nudge` 不再含 `_build_public_layers` / `JARVIS_CORE_PERSONA` 直接引用
- 回归：现有 206/206 testcase 全绿（特别是 `_test_r7_alpha_nudge_channel`、`_test_p0_plus_18_c2_reminder_firing`）
- 真机：SmartNudge offer_help 时 log 应出 `[SOUL inject]` 且 prompt size 在 ~5-7K

**commit**：`feat(P0+20-β.2.7.1): _assemble_prompt(mode='nudge') + stream_nudge 切换主装配`

### Phase 2：ReturnSentinel 死代码清理 + Silent Nudge 接入（~1h）

**v1.1 修订**：原 Phase 2 假设 ReturnSentinel 全模板。subagent 调研显示 `_speak_and_soft_focus`（模板路径）**实际是死代码** —— `_on_return` 在 `use_llm` 分支已 return，模板+glow 路径不可达。归来感知**实际已经走 `__NUDGE__:return_greeting` → stream_nudge** 路径，Phase 1 完成后**自动接通 Layer 0-3**。

**Phase 2 改做**：
1. 死代码清理：删 `jarvis_return_sentinel.py` 的 `_speak_and_soft_focus` + 模板 greetings 列表（保留 fallback 路径）
2. Silent Nudge 文案接入：`render_silent_nudge_text` 当前用 `SILENT_NUDGE_TEMPLATES`（10+ 模板）。考虑接入 `_assemble_prompt(mode='silent_nudge')` 短促瘦身版（不出声只字幕 → prompt 可以更小 ~3K）

**测试**：现有 silent_nudge testcase 全绿；新增 1 个 `_assemble_prompt(mode='silent_nudge')` 单测。

**commit**：`refactor(P0+20-β.2.7.2): ReturnSentinel 死代码清理 + silent_nudge 走 mode='silent_nudge'`

### Phase 3：延迟敏感模板路径双轨化（~1.5h）

**问题**：以下路径**应该保留低延迟模板**（< 100ms 必须出声），但同时让主脑后台"消化"该事件 → 写关系状态：
- `_speak_exit` (worker.py:1477)：standby 退场 5 句模板
- Spinal reflex（reflex_dict 词典命中）：唤醒词应答
- SleepIntentDetector.request_confirmation：睡前确认
- `_check_short_sleep`：短睡眠唤醒追问
- 本地 backchannel PCM 池：TTFT 等待时插话

**双轨方案**：
- **前台即播**：保留 random.choice / 模板 f-string，` < 50ms 内出声（用户体验不退步）
- **后台 capture**：fire-and-forget thread 调 `nerve.async_soul_capture(event_type, context)`：
  - 生成一个简短的"事件 → 主脑总结"，调 `_assemble_prompt(mode='reflection')` 走 LLM
  - 解析输出 → 写 `relational_state.shared_history_threads` highlights 或 `concerns_ledger.record_signal`
  - **不发声**，只是让灵魂"知道刚才发生了什么"

```python
# jarvis_worker.py _speak_exit 末尾
threading.Thread(
    target=lambda: self.jarvis.async_soul_capture(
        event_type='standby_exit',
        context={'spoken': en_phrase, 'reason': 'sir said stand down'},
    ),
    daemon=True, name='SoulCapture/StandbyExit'
).start()
```

**测试**：standby 后 5-10s 内 `memory_pool/relational_state.json` 多一条 highlight。

**commit**：`feat(P0+20-β.2.7.3): 低延迟模板路径双轨化 - 即播 + 后台 async_soul_capture`

### Phase 4：全测 + tag（~30 min）

- `tests/_runall.ps1` 全绿
- 新增 testcase：~12 个（Phase 1: 6, Phase 2: 4, Phase 3: 2）
- 真机 Sir 实测 5 条场景
- tag `v0.26.0-soul-universal`

---

## 3. 工程总量（v1.1 修订）

| Phase | 内容 | 估时 | 累计 |
|---|---|---|---|
| 1 | `_assemble_prompt(mode='nudge')` + stream_nudge 切换主装配 | 2.0h | 2.0h |
| 2 | ReturnSentinel 死代码清理 + silent_nudge mode | 1.0h | 3.0h |
| 3 | 延迟敏感模板路径双轨化（_speak_exit / reflex / sleep_detector）+ `async_soul_capture` API | 1.5h | 4.5h |
| 4 | 全测 + tag `v0.26.0-soul-universal` | 0.5h | 5.0h |

总 ~5h。分 4 commit + 1 tag。**Phase 1 ROI 最高**——一改 stream_nudge 装配函数，5 条主动发声路径（SmartNudge / Conductor / Commitment / ReturnSentinel / 部分 sentinels）**同时受益**。

---

## 4. 风险 & 回滚

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Phase 1 改 helper 破坏 _assemble_prompt 现有行为 | 低 | 高 | 完整 206/206 testcase 回归 |
| Phase 2 主脑生成失败时 Jarvis 完全没问候 | 中 | 中 | 双轨 fallback（解决方案 A）|
| nudge 路径接入 Layer 0-5 后 prompt 体积从 ~5K 涨到 ~7K | 高 | 低 | nudge prompt 仍 < 主对话的 22K，可接受 |
| OpenRouter 评分 quota 因 SoulEvaluator 每条 nudge 都评分而暴涨 | 低 | 中 | rate limit 30/min 已设；nudge 频率 ~1/h |

每个 Phase 独立 commit，失败可单独 revert。

---

## 5. 完成验收

**核心判定**（Sir 实测）：
- [ ] SmartNudge 发 offer_help 时引用 [LONG-TERM WATCH] 里的具体 concern
- [ ] Conductor 路由后的问候带 inside_joke 或 unfinished_business 元素
- [ ] ReturnSentinel 归来问候不再是"Welcome back, Sir~"模板，而是引用 STM 具体话题
- [ ] standby 后 10s 内 `relational_state.json` 多一条 thread highlight
- [ ] `concerns_dump` 显示 nudge 路径触发的 alignment 累计

**辅助指标**：
- nudge 路径 prompt 体积 ~5K → ~7K（含 Layer 0-5）
- nudge 路径 TTFT 不退步 (~3s 量级)
- β.2 全套 206 → 218+ testcase 全绿

---

## 6. 与现有原则一致性

`docs/JARVIS_SOUL_DRIVE.md §10` 已明确两条基本原则：
1. **INTEGRITY ABSOLUTE**（言出必行）
2. **SOUL & DRIVE**（灵魂与驱动力）

本文不增新原则，只是把 #2 从"主对话路径"扩展到"所有 Jarvis 发声路径"。

---

## 7. 归档协议

完工时：
1. 本 design doc **不动**（历史参考）
2. `TODO.md` 加"P0+20-β.2.7 完工速览"
3. `docs/TODO_ARCHIVE.md` 沉档（β.2.0-2.7 整轮）
4. tag `v0.26.0-soul-universal`

---

*文档作者：Sir 提出需求 + Claude 综合设计 / 2026-05-17 01:16-01:25*
*与 `JARVIS_SOUL_DRIVE.md` 同等地位 — 完成"灵魂通用化"后才算真正落地第二基本原则。*
