# JARVIS Desktop Copilot — Sir 新定位大方向设计 (β.5.42+)

> Sir 2026-05-20 16:30 真理: "**让 Jarvis 脱离繁重数据工作流, 给予他 (1) 稳固的交互地基 (2) 真正用鼠标键盘操作我电脑的复杂操作流程**".
>
> 不再扩 LLM 重模块. 聚焦"**没对外 API 但 Sir 常用的桌面软件**" — Sir 不在家时 Jarvis 代劳.
>
> 本文档是大方向设计, 不是详细 spec. 后续以现讨论想法逐步完善后再 sprint 实施.

---

## 1. Sir 原话 + 核心理念

> "我只是说，不要让贾维斯去做复杂的数据处理或者繁重的数据任务，而是聚焦在如何用鼠标键盘操控一些没有对外数据接口但是我又很常用的软件上，如，PR的快速剪辑？封面的快速制作？等等，这很关键，也是真能生产力工具（我不在家也可以让jarvis代劳）"

### 关键词解析

| 关键词 | 含义 |
|---|---|
| **"没对外数据接口"** | 不是 OpenAI API / GitHub API / Zapier 这种可调 API. 是必须**真手点鼠标**才能驱动的桌面软件 |
| **"我又很常用"** | Sir 的真实工作流, 非通用 — 个性化定制 |
| **"PR 快速剪辑 / 封面快速制作"** | 高价值具体用例: Adobe Premiere Pro / Photoshop / Figma / DaVinci... |
| **"不在家也可以让 Jarvis 代劳"** | Sir 远程语音 → Jarvis 在本机执行 (Sir 已在 β.4.X 做过远程控制相关) |
| **"真生产力工具"** | 区别于"陪伴聊天" — 能省 Sir 真实时间 |

### 对比 Cascade / Codex / 其他 Agent

| 维度 | Cascade / Codex (现有 agent) | Jarvis Desktop Copilot |
|---|---|---|
| **API 操作** | 强 (调 GitHub / OpenAI / etc) | 弱 (不擅长) |
| **数据 ETL** | 强 (parse / transform / aggregate) | **故意不做** |
| **代码生成** | 强 (LLM heavy) | 不做 (Sir 让 Cascade 做) |
| **桌面软件点击** | 弱 (没接口) | **强** — 用 `input_hands` + `window_hands` + vision |
| **语音交互** | 弱 (大部分是 chat UI) | **强** — wake word + ASR + TTS 完整 |
| **长期记忆 Sir** | 弱 (每次新 session) | 强 (hippocampus + relational + concerns) |

**结论**: Jarvis = **桌面操作 + 语音交互 + 长期陪伴**, Cascade/Codex = **API + 代码 + 数据**. 互补不重叠.

---

## 2. 现状 — Jarvis 已有的能力

### 2.1 输入控制 (`@d:\Jarvis\l4_hands_pool\l4_input_hands.py`, 19+ 命令)

| 命令 | 能干啥 |
|---|---|
| `click` / `double_click` / `right_click` / `middle_click` | 鼠标点击 |
| `drag` | 拖拽 |
| `scroll` / `scroll_up` / `scroll_down` | 滚轮 |
| `move_to` / `move_relative` / `get_pos` | 鼠标移动 |
| `type_text` / `paste_text` / `type_line` | 键盘输入 |
| `key_press` / `key_down` / `key_up` / `hotkey` | 按键 / 组合键 |

### 2.2 窗口管理 (`@d:\Jarvis\l4_hands_pool\l4_window_hands.py`)

minimize / maximize / close / pin / focus / arrange / split / hide / list_windows

### 2.3 屏幕感知 (`watcher_hands.screenshot` 等)

可截图. **但没**: OCR / 图像识别 / GUI 元素定位.

### 2.4 已有 intent_map (`@d:\Jarvis\memory_pool\intent_to_tool_map.json`)

15+ semantic intents 主要做 system 控制 (`check_top_cpu` / `mute_audio` / `dashboard_open`). **没有桌面软件操作 intent**.

---

## 3. 缺口分析

| 缺口 | 严重度 | 影响 |
|---|---|---|
| **没 screen vision** — Jarvis 截图后看不懂屏幕上有什么 | 🔴 致命 | 没法精准点 "保存按钮" 因为不知按钮在哪 |
| **intent_map 没桌面软件 intent** | 🟠 严重 | Sir 说"剪个视频" 主脑不知 emit 什么 tool call |
| **没 software-specific workflow library** | 🟠 严重 | "PR 剪辑" 需要 N 步操作, 没预定义脚本 |
| **没 trust/safety gate** | 🟡 中 | Jarvis 误点 "删除" 怎办? 需 Sir 二次确认机制 |
| **没远程触发** | 🟡 中 | Sir 不在家时怎么发指令? 微信/Telegram bot? (已有 β.4.X 思路) |
| **没 dry-run / preview** | 🟡 中 | Sir 不在场, Jarvis 操作前应"我要这样这样, 5s 内说停" |

---

## 4. β.5.42 路线图 (4 大模块, ~20-30h 总)

### 模块 A: Screen Vision 集成 (~6-10h, 最关键)

**目标**: Jarvis 截图后用 vision LLM 看懂屏幕, 找到 "保存按钮 / 剪辑 timeline 起点 / 红色字体" 的精准坐标.

**技术选型**:
| 方案 | 优点 | 缺点 |
|---|---|---|
| **Gemini 2.5 Pro Vision** | Sir 已用 google key, 便宜 | 不擅长 GUI 元素定位 |
| **Claude 3.5 Sonnet (computer use API)** | Anthropic 专门做了 computer use, 强 | 贵, Sir key 可能没买 |
| **GPT-4o Vision** | 强 GUI 理解 | OpenAI key 配额 |
| **本地 vision (CogVLM / LLaVA)** | 私有 + 免费 | GPU 慢, 安装麻烦 |

**推荐**: Gemini 2.5 Pro 优先 (Sir 配额最足), Claude 3.5 fallback (computer use 模式).

**新模块**: `jarvis_screen_vision.py`
```python
def find_element(screenshot_path, target_desc: str) -> dict | None:
    """Vision LLM 看截图找 target_desc 的元素.
    
    Returns:
        {'x': int, 'y': int, 'confidence': float, 'description': str}
        or None if not found.
    """
```

### 模块 B: 桌面软件 Workflow Vocab (~5-8h)

**目标**: 把 Sir 常用的桌面软件操作 codify 成 vocab, 主脑可调.

**新文件**: `memory_pool/desktop_workflow_vocab.json`
```json
{
  "workflows": {
    "premiere_cut_clip": {
      "id": "premiere_cut_clip",
      "description": "PR 剪辑: 选中片段, 在指定时间点切割",
      "software": "Adobe Premiere Pro",
      "steps": [
        {"action": "focus_window", "params": {"title_contains": "Premiere"}},
        {"action": "vision_find", "params": {"target": "razor tool (剃刀工具)"}},
        {"action": "click", "params": {"x": "@vision.x", "y": "@vision.y"}},
        {"action": "vision_find", "params": {"target": "timeline 上 ${time_point} 位置"}},
        {"action": "click", "params": {"x": "@vision.x", "y": "@vision.y"}}
      ],
      "preview_msg": "我会用剃刀工具在 ${time_point} 切一刀, 5 秒内说停可取消",
      "dangerous_level": "risky"
    },
    "photoshop_export_jpg": { ... },
    "figma_export_png": { ... },
    "obs_start_recording": { ... }
  }
}
```

**CLI**: `scripts/desktop_workflow_dump.py` — Sir add/show/remove workflow

**主脑 prompt**: 加 `[DESKTOP WORKFLOWS]` block 列 active workflows 名 + description.

### 模块 C: Intent Router 扩 + Safety Gate (~3-5h)

**目标**: 主脑 emit `<TOOL_CALL>{intent="premiere_cut_clip", time_point="00:01:23"}` → router 找 workflow → preview → execute.

**改 `@d:\Jarvis\jarvis_intent_router.py`**:
- 加 desktop_workflow 类 intent (区别于现有 hands intent)
- Sir-not-present 模式 (远程触发): 5s preview 后默认执行
- Sir-present 模式 (语音触发): 立即 preview, Sir 说停就取消

**新 directive `desktop_workflow_judge`**:
```
[DESKTOP WORKFLOW JUDGE - β.5.42-C]:
当 Sir 说 "帮我 X" 且 X 命中 desktop_workflow_vocab → emit <TOOL_CALL>.
重要: preview 5s 是机会窗口, 不是 fait accompli — Sir 可中止.
危险操作 (delete/overwrite/publish) → 必须等 Sir 显式确认.
```

### 模块 D: 远程触发 (~6-8h, 可选)

**目标**: Sir 出门时手机微信 / Telegram bot 发指令 → 家里 Jarvis 收 → 执行.

**架构**:
- 新模块 `jarvis_remote_bridge.py` (telegram-bot / wechat-mp / Pushover webhook)
- 收到 message → 走 stream_chat 同款 pipeline → 主脑判 → workflow execute
- 结果回流 Sir 手机 (text + screenshot)

**安全**: Sir-only auth (Telegram chat_id whitelist).

---

## 5. 实施优先级 (Sir 拍板)

| 阶段 | 内容 | 时长 | Sir 体感 |
|---|---|---|---|
| **P0** | 模块 B (workflow vocab + CLI) — 第 1 个 workflow 例 `premiere_cut_clip` 落地 | 2-3h | 内部基础, Sir 暂看不到 |
| **P1** | 模块 A (vision integration) — Sir 第一次说 "帮我点保存" 真触发 | 6-10h | 🌟 Sir 真体感 "Jarvis 能操作软件" |
| **P2** | 模块 C (intent router + safety gate) — 5 个常用 workflow 落地 | 3-5h | Sir 工作流真生产力 |
| **P3** | 模块 D (远程触发) — Sir 出门也能用 | 6-8h | "Jarvis 代劳" 完整体验 |

---

## 6. 关键约束 (Sir 真理)

1. **不动 LLM 重模块的交互地基** (Sir 16:30 澄清: 那些是地基, 不是繁重工作流)
2. **不让 Jarvis 做 ETL / 数据流** — 那些让 Cascade 做
3. **算法精准** (Sir 一贯要求): vision 找元素 ≥ 0.85 confidence 才点
4. **Sir-可中止**: preview 5s 是黄金窗口, 不许"已经做了"
5. **危险操作 Sir 二次确认**: delete / publish / format / shutdown 不能 silent execute
6. **准则 6 evidence-driven**: workflow 选什么 vision 找什么, 全过主脑判, 不硬编码

---

## 7. 失败模式 + 缓解

| 失败 | 缓解 |
|---|---|
| Vision 找错按钮 → 点偏 | confidence ≥ 0.85 才点, < 0.85 → "我看不太清屏幕, Sir 能不能告诉我按钮在哪?" |
| Vision LLM API 超时 | 老 hands manual 路径 fallback (Sir 自己说坐标) |
| Workflow 步骤被中途中断 | 状态机记 current_step, Sir 说 "继续" 接力 |
| Sir 远程发指令但家里电脑锁屏 | Pushover/Telegram 回 "电脑锁屏了, 您要我先 ulock 吗?" |
| 误点危险按钮 | 加 software-specific danger list (PR 的"删除/保存关闭"等) |

---

## 8. 长期愿景 (1-2 年)

- **个性化 workflow 自学**: Jarvis 看 Sir 一周 PR 操作, L7 reflector propose "您经常这 3 步, 要不要打包成 workflow?"
- **多模态 perception**: 屏幕 vision + 麦克风 ambient + 键鼠节奏 → Jarvis "知道你现在在干什么"
- **协议化跨软件**: workflow 跨 PR + Figma + 微信 (剪个视频 → 导出 → 发朋友圈)
- **群机协同**: Sir 多台电脑, Jarvis 通过 Telegram bridge 跨机协作

---

## 9. 等 Sir 拍板的关键问题

1. **优先级**: P0-P3 哪个先 sprint? (推荐 P0 + P1, 6-13h MVP)
2. **Vision LLM 选型**: Gemini 2.5 Pro / Claude 3.5 / GPT-4o / 本地? (推荐 Gemini)
3. **第一个 workflow**: PR 剪辑? Photoshop 导出? Figma? (Sir 决定最常用)
4. **远程触发渠道**: Telegram bot? 微信公众号? Pushover? (Sir 已有偏好?)
5. **dry-run preview 时长**: 5s? 10s? (Sir 调)
6. **危险操作清单**: delete / overwrite / publish 默认全 require 确认, Sir 是否要 customize?

---

**状态**: 大方向 design 完, 等 Sir 拍板 sprint 时机.
**实现总时长**: P0+P1 (MVP) = 8-13h, 全部 P0-P3 = 20-30h.
