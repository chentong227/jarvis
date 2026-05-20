# JARVIS Gap 3 — Vision LLM 集成: raw screenshot → 看懂屏幕

> **状态**: 设计构思, 未排 sprint 编号. 时间可变.
> **关联**: `docs/JARVIS_AGENTS_GAP_ANALYSIS_2026_05_20.md` §3 Gap 3, `docs/JARVIS_FUTURE_VISION_DESKTOP_COPILOT.md` 模块 A (本 Gap 是它的子集 — 仅 vision 集成, 不含 GUI 元素定位 + workflow)
> **依赖**: 已有 `l4_hands_pool/l4_screenshot_hands.py` (raw screenshot 全屏/窗口/region/clipboard/base64), KeyRouter (google key 配额足), ConversationEventBus (SWM)
> **新模块**: `jarvis_screen_vision.py` + 改 `_assemble_prompt` 注 `[WHAT SIR IS LOOKING AT]` block

---

## 0. TL;DR — 一句话

> **Jarvis 已经能拿截图, 但截图没塞进主脑 prompt. 加 vision LLM (Gemini 2.5 Pro Vision) 描述屏幕 + 注 prompt 作 [WHAT SIR IS LOOKING AT] block — 主脑终于"能看 Sir 在做什么", Sir-aware AGI 立刻多一个 perception 维度.**

---

## 1. 起源 / 痛点

### 1.1 Sir 真实场景

Sir 在 Cursor 写 code, Jarvis 知道**进程 / window title** ("Cursor — jarvis_directives.py"), 但**不知道**:
- 哪个 file 哪一行
- 屏幕上有什么 error / warning
- Sir cursor 停在第几行 (心智停留点)
- Build output panel 显示什么
- Sir 是不是在看 stack trace

Sir 跟 Jarvis 对话需要**口述上下文**: "我在 jarvis_directives.py 1547 行看 past_action_honesty, 你看一下...". 累.

### 1.2 现状

| 已有 | 状态 |
|---|---|
| `l4_screenshot_hands` 截图 | ✅ 全屏/窗口/region/base64 |
| `PhysicalEnvironmentProbe` 拿 active window title | ✅ |
| Vision LLM 后端 | ❌ |
| 注入主脑 prompt | ❌ |
| 截图周期采样 | ❌ |
| GUI 元素坐标定位 | ❌ (留 `JARVIS_FUTURE_VISION_DESKTOP_COPILOT.md` 后续) |

**本 Gap 只做 vision 集成 (前 2 项)**, 不含 GUI 元素定位 (那是桌面 copilot 框架的事).

### 1.3 为什么这是"Sir-aware AGI"的真大跃迁

人类老友看你写 code 跟你聊天 — 你说"这里我卡住", 老友扫一眼屏幕就懂. Jarvis 没 vision → 你必须口述. 加 vision → Jarvis **真正能"在场"**.

也是 Gap 1 ToM 的**最强 grounding** — 没 vision, ToM hypothesis 全靠语音 + 键盘节奏猜. 有 vision, hypothesis 立刻 grounded.

---

## 2. 设计 — 采样 + 描述 + 注入

### 2.1 三阶段 pipeline

```
Stage 1 — 采样 (sampling)
   ↓
   节能策略:
   - Sir wake + 主对话开始 → 触发 1 次 (即时)
   - 主对话进行中 → 不再采 (旧帧足够, 防 token 烧)
   - 长 idle (> 5min) → 每 5min 1 帧 backfill
   - Sir 明确说 "看一下我屏幕" → 立即采
   ↓
Stage 2 — 描述 (vision LLM)
   ↓
   Gemini 2.5 Pro Vision (Sir google key 配额足):
   - 输入: 截图 base64 + 简短 prompt
   - 输出: JSON 结构化描述 (见 §2.3)
   ↓
   写 memory_pool/screen_snapshot.json (atomic, 全量覆盖)
   ↓
   publish SWM 'screen_described'
   ↓
Stage 3 — 注入主脑 prompt
   ↓
   [NEW] _assemble_prompt 加 [WHAT SIR IS LOOKING AT] block:
     - active_app + file + cursor_line_approx
     - screen_summary (1-2 句 LLM 描述)
     - recent_visible_keywords
     - errors_visible / build_output_status
   ↓
   主脑自然用 — reply 含"我看到你在 X" 类话, 不再瞎猜
```

### 2.2 节能策略 (核心)

Vision LLM 每次调用 ~$0.001 + 1-2s 延迟. 不能每秒采.

```python
SAMPLING_TRIGGERS = {
    'wake_word_detected': True,         # Sir 唤醒 → 即采 (最重要)
    'sir_explicit_screen_ref': True,    # "看一下我屏幕" → 即采
    'long_idle_backfill': 300.0,        # 5min idle → 采 1 次
    'after_active_app_switch': True,    # active window 切换 → 采 (用 PhysicalEnvProbe)
    'during_active_conversation': False, # 对话进行中 NOT 重采
}

CACHE_TTL_S = 60.0  # 屏幕快照 1min cache, 同 turn 复用
```

预期: 平均 1-2 调/min, 月成本 < $5 (Sir 跟 Jarvis 主对话频率).

### 2.3 Vision LLM prompt + 输出 schema

**Vision prompt (极简, 让 LLM 自由发挥)**:
```
Describe what's on this screen for Jarvis (Sir's AI butler). 
Focus on what Sir is likely working on or paying attention to. 
Be concise. Output JSON only:

{
  "active_app": "Cursor / VS Code / Chrome / ...",
  "file_or_url_visible": "jarvis_directives.py / https://...",
  "cursor_line_approx": <int or null>,
  "screen_summary": "Sir is reading code about past action honesty directive, 
                     specifically the unsolicited callback ban clause...",
  "recent_visible_keywords": ["past_action", "apology", "directive"],
  "errors_visible": [],
  "build_output_status": "idle / running / failed / passed / null",
  "notable_elements": ["red squiggly on line 1547", "PR review panel open"],
  "confidence": 0.0-1.0
}
```

**输出 schema** (持久化到 `screen_snapshot.json`):
```python
@dataclass
class ScreenSnapshot:
    captured_at: float
    captured_iso: str
    active_app: str
    file_or_url_visible: str
    cursor_line_approx: int | None
    screen_summary: str           # 1-2 句 LLM 描述
    recent_visible_keywords: list[str]
    errors_visible: list[str]
    build_output_status: str       # idle/running/failed/passed
    notable_elements: list[str]
    confidence: float
    vision_model_used: str         # 'gemini-2.5-pro-vision' / 'gpt-4o-vision'
    sampling_trigger: str          # 'wake' / 'backfill' / 'sir_ref' / 'app_switch'
```

### 2.4 主脑 prompt 注入示例

```
=== WHAT SIR IS LOOKING AT (15s ago, vision LLM hypothesis) ===
[ACTIVE] Cursor — jarvis_directives.py @ line ~1547
[SUMMARY] Sir is reading the past_action_honesty directive code, specifically 
the new UNSOLICITED callback ban clause added today (beta.5.43-fix-revise3).
[KEYWORDS] past_action, apology, hydration, fix-revise3
[ERRORS] none visible
[BUILD] idle
[NOTABLE] terminal panel shows last commit hash ac53148

[HOW TO USE THIS]
- 我可以 reference Sir 在看的具体 code 段 ("看 1547 行你刚加的 ban clause 吗?")
- 不重复 Sir 已经看到的信息
- 如果 Sir 问含糊的"这个", 多半指屏幕上的东西
```

---

## 3. 实施层级

### Layer A — Vision 后端
- 新文件: `jarvis_screen_vision.py` (~500 行)
  - `ScreenVisionEngine` class
  - `_call_gemini_vision(b64) -> dict`
  - `_call_gpt4o_vision_fallback(b64) -> dict` (备份)
  - cache LRU (60s TTL, 防同帧重调)
  - 失败 fallback: 只返 `{active_app, file_or_url_visible}` (来自 PhysicalEnvProbe)
- 测试: ~10 testcase (mock LLM response)

### Layer B — 采样调度
- 加 SWM listener 监 `wake_word_detected` / `active_app_changed`
- 加 backfill daemon (5min tick)
- 加 sir_explicit_screen_ref detect (LLM judge "Sir 是否 reference 屏幕")
- 全异步, 不阻塞主对话

### Layer C — 持久化 + CLI
- `memory_pool/screen_snapshot.json` (latest 1 帧, atomic 覆盖)
- `memory_pool/screen_history.jsonl` (rolling 100 帧, 用于演化分析)
- 新文件: `scripts/screen_vision_dump.py`
  - `--latest` 看最新 snapshot
  - `--history 10` 看最近 10 帧
  - `--snap-now` 立即触发一次采样 + describe (调试用)

### Layer D — 主脑 prompt 注入
- 改 `jarvis_central_nerve._assemble_prompt`
- 加 `[WHAT SIR IS LOOKING AT]` block
- 加 `[HOW TO USE THIS]` 子段教主脑用法
- block 大小控制 < 800 chars

### Layer E — Privacy / 安全
- env flag `JARVIS_SCREEN_VISION=1` 才启用 (默认关, Sir gradual opt-in)
- 截图永不发**完整 base64** 进 STM (只描述结果)
- 截图 base64 临时 disk → vision LLM 调用后立即 delete
- Sir CLI `--privacy-mode` 启用时只描述 active_app, 不描述具体内容
- 敏感场景检测 (密码框 / 银行 / 私聊) → vision LLM 自己识别 → 返回 `confidence=0` + `summary="privacy-sensitive content, not described"`

---

## 4. 准则 6 4 问 binding

| # | 问 | 本设计答 |
|---|---|---|
| 1 | 数据 publish 进 SWM? | ✅ publish 'screen_described' + ScreenSnapshot 持久化 |
| 2 | 决策让 LLM 做? | ✅ Vision LLM describe, 不用 OCR + 硬编码 keyword. 主脑用 description 时也是 LLM 自由发挥 |
| 3 | 配置持久化 + CLI 可改? | ✅ memory_pool/screen_snapshot.json + scripts/screen_vision_dump.py + env flag |
| 4 | 和已有 module 正交? | ✅ 跟 PhysicalEnvProbe (active window title) / WorkingMemoryFeed / Skill Registry (l4 hands) 全正交. 是新 perception 维度 |

---

## 5. 风险 & 缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| **Vision LLM 调用烧 token** | 高 | 中 | 节能采样 (1-2 调/min), 60s cache, env flag 让 Sir gradual rollout |
| **Vision 描述不准 / hallucinate** | 中 | 中 | confidence 字段, 主脑教 "confidence < 0.5 不用". Sir 可 CLI `--snap-now` debug |
| **Privacy** (密码 / 隐私内容上传) | 中 | **致命** | 1) env flag opt-in 2) sensitive 场景 LLM 自己识别拒描述 3) base64 不进 STM 4) 临时 disk → delete |
| **截图延迟 > 1s** 阻塞主对话 | 低 | 中 | 全异步 fire-and-forget. 主对话不等. 旧帧 (60s 内) 立刻可用 |
| **Vision LLM API 超时** | 中 | 低 | timeout 3s, fallback 只返 active_app. 主脑容忍空 screen block |
| **Sir 觉得"被监视"不适** | 中 | **致命** | env flag default off. Privacy mode. CLI 可随时关. UI 加红点显"截屏中" |

---

## 6. 完成验收 (Sir 真机判定)

- [ ] Sir 说"看一下我屏幕" → Jarvis < 2s 内描述 active file + cursor 大概位置
- [ ] Sir 用代词"这个" / "那段" → Jarvis 多数情况能正确 referent 到屏幕内容
- [ ] Sir build 失败 → Jarvis 主动 surface ("我看你 build 红了, 要看 error 吗?") 而不是等 Sir 说
- [ ] Sir privacy 敏感内容 (密码 / 私聊) → Jarvis 描述时自动 redact
- [ ] 月 vision token 成本 < $10 (Sir 接受度)
- [ ] TTFT 不退步 (vision 是异步, 不阻塞)

---

## 7. 与现有架构的关系

```
PhysicalEnvironmentProbe (active window title — Win32 API, < 10ms)
   ↓ 给 Vision Engine 提供 trigger 信号 (app 切换 → 重采)
   
l4_screenshot_hands (raw png 截图 — PIL ImageGrab, < 100ms)
   ↓ 给 Vision Engine 提供 raw frames
   
[NEW] jarvis_screen_vision.py
   - 节能采样调度
   - Vision LLM call (Gemini Vision)
   - 描述 → JSON → 持久化 + publish SWM
   ↓
   
_assemble_prompt → [WHAT SIR IS LOOKING AT] block
   ↓
主脑用 description 做 ground-aware reply
   ↓ 也喂 Gap 1 SirMentalState (ToMReflector 用 screen evidence 升级 task_hypothesis)
```

Vision Engine 是**桥**: PhysicalEnvProbe + raw screenshot → 主脑 + ToM.

---

## 8. 跟 JARVIS_FUTURE_VISION_DESKTOP_COPILOT.md 的关系

桌面 Copilot 框架的**模块 A** 含 3 层:
1. **Vision 描述** (看懂屏幕) ← **本 Gap**
2. **GUI 元素定位** (找按钮坐标)
3. **Action 触发** (点 / 拖 / 输入)

本 Gap 只做第 1 层. 第 2-3 层是**桌面 copilot** 工程, 不属于"懂我 + 像真人" 主线 — 留给 `JARVIS_FUTURE_VISION_DESKTOP_COPILOT.md` 后续 sprint.

理由: Sir 22:47 真理 — "懂我为主, 工具有现成的". GUI 元素定位 + Action 是工具方向 (现成 Anthropic computer use API 可参考), 不是 "懂我" 方向. Vision 描述是 "懂我" 必需.

---

## 9. 关键参考

- `@d:\Jarvis\l4_hands_pool\l4_screenshot_hands.py:1-168` raw 截图 (本 Gap 复用)
- `@d:\Jarvis\jarvis_env_probe.py` PhysicalEnvironmentProbe (active window title)
- `@d:\Jarvis\jarvis_hippocampus.py:1-200` Gemini API 调用 pattern (复用)
- `@d:\Jarvis\jarvis_key_router.py` Key 切换 (google key 多 key 切)
- `@d:\Jarvis\docs\JARVIS_FUTURE_VISION_DESKTOP_COPILOT.md` 模块 A (本 Gap 是它的第 1 层)
- `@d:\Jarvis\docs\JARVIS_TOM_SIR_MENTAL_MODEL.md` (Gap 1, 本 Vision 是它的 evidence source)

---

## 10. 落地后涌现的可能 Gap (Gap 7+)

- **多屏支持** (Sir 双屏 / 三屏): 现在 ImageGrab.grab() 默认主屏. 加 multi-monitor enumeration
- **视频流截屏** (代替单帧): Sir 玩游戏 / 看视频时 LLM 看动态画面
- **OCR 强化**: vision LLM 描述偶尔漏小字, 加专门 OCR pass (Tesseract / EasyOCR) 兜底
- **跨 vision 模型 ensemble**: Gemini + GPT-4o 同时调, 投票 / 互校
- **GUI 元素坐标定位** (Anthropic computer use pattern): 推 `JARVIS_FUTURE_VISION_DESKTOP_COPILOT.md` 模块 A 第 2 层

---

*文档作者: Sir 22:47 真授权 + Cascade 23:02 沉淀 / 2026-05-20*
*这是 Sir-aware AGI 的 perception 新维度, 跟 Gap 1 ToM 互为基础.*
