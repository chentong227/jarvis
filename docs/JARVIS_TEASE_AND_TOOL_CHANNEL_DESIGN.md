# JARVIS_TEASE_AND_TOOL_CHANNEL_DESIGN

> **Sir 2026-05-20 10:46 实测两条相关痛点的大修方案**
>
> Sir 拍板: **BUG 1+4 现在小修 ✓** (β.5.34 commit `8c633a4`); **BUG 2+3 大修, 写 design doc 拍板**.
>
> 本 doc 涵盖:
> - **BUG 2**: `screen_tease` 一周静音 + `offer_help` 触发位置不对 (现在像 screen_tease)
> - **BUG 3**: 工具名泄漏 (`process_hands.get_top_cpu` 直接被 LLM 说出)
>
> 准则 6 工程方法论: **持久化 + CLI 可改 + L7 Reflector LLM-propose**

---

## 一. 现状 audit

### BUG 2 — 触发链 audit

`@/Jarvis/jarvis_smart_nudge.py:361-372` (β.4.X 写死的 keyword tuple):

```python
error_kw = ["error", "exception", "failed", "traceback", "崩溃", "报错", "404", "500",
            "stack trace", "undefined", "null pointer"]
fun_kw = ["bilibili", "youtube", "直播", "游戏", "steam", "netflix", "视频", "番剧", "twitch"]
slack_kw = ["reddit", "twitter", "微博", "知乎", "douyin", "抖音", "xiaohongshu", "小红书"]

if any(kw in lower_title for kw in error_kw):
    candidates.append(("screen_tease", {"window_title": ..., "category": "error"}))
elif any(kw in lower_title for kw in fun_kw):
    candidates.append(("screen_tease", {"window_title": ..., "category": "entertainment"}))
elif any(kw in lower_title for kw in slack_kw):
    candidates.append(("screen_tease", {"window_title": ..., "category": "slacking"}))
```

**违反准则 6**:
- ✗ vocab 硬编码在 `.py` 源文件 (非 `memory_pool/*.json`)
- ✗ 无 CLI 可改 (改个 keyword 要 git commit + restart)
- ✗ 无 L7 Reflector — Sir 一周屏幕上 `Cascade` / `Cursor` / `Windsurf` / `IDE 项目名` 都不在 fun/slack/error → **永远 0 命中**
- ✗ category 三档写死 `error / entertainment / slacking` → 实际 Sir 屏幕场景远超这 3 档 (debugging / reading docs / 思考停顿 / 写邮件 / 看教程)

**一周静音根因**: keyword tuple 跟不上 Sir 真实使用场景, 0 命中.

### BUG 2 — `offer_help` 当前形态

`@/Jarvis/jarvis_chat_bypass.py:3784-3789` directive:

```python
"offer_help": (
    f"Sir seems to be stuck on an error or debugging issue. "
    f"You can offer help if you have a real way to help.\n\n"
    f"[INTEGRITY — Sir 准则 5]: NEVER mention internal tool names ..."
)
```

触发位置 (`@/Jarvis/jarvis_conductor.py` / `@/Jarvis/jarvis_smart_nudge.py`): Conductor 看 API rate limit 报错 / SmartNudge 看 error keyword → 触发 offer_help.

**Sir 语义**:
- ✗ 现在的 `offer_help` 像调皮观察 ("Sir 你卡住了"), 跟 `screen_tease` 重叠
- ✓ Sir 期望: **"Sir 明确表达困难时 → 主动援助"** — 触发 signal 是 Sir 的语言/情绪/抱怨, 不是屏幕看到的报错
- ✓ `screen_tease` 应该是: **"Jarvis 观察到屏幕动作模式 → 调皮关心"** (远场观察, 不主动给方案)

两者语义错位.

### BUG 3 — 工具名泄漏链 audit

Log line 1234 (`@/Jarvis/docs/runtime_logs/jarvis_20260520_034755.log`):

```
I can run process_hands.get_top_cpu to ensure no background tasks are further hindering your progress.
```

**触发链**:

1. `@/Jarvis/jarvis_chat_bypass.py:3910-3917` — 在 `offer_help` / `commitment_check` / `context_switch_alert` 时:
   ```python
   nudge_skills_block = get_registry().to_prompt_block(
       only_healthy=True, filter_safe_only=True
   )
   ```
2. `@/Jarvis/jarvis_skill_registry.py:423-426` — `to_prompt_block()` 注入 instruction:
   ```
   "These are the ONLY actions you can truly perform right now.
    When offering to help Sir, you MUST reference one of these by name.
    Generic offers like 'can I help' or 'shall I take a look' are FORBIDDEN."
   ```
3. LLM 看到 skill list + "MUST reference one of these by name" → 自然引用 `process_hands.get_top_cpu`
4. `@/Jarvis/jarvis_chat_bypass.py:601-605` Audio Guard 拦 TTS 替换成 "a quick check" — **但 subtitle 用 ZH path 漏过去了**, 且 LLM 一开始就不该说

**根因**: skill registry 当前是 **"暴露 + INTEGRITY 警告"** 模式 — 既要 LLM 引用真实能力 (β.4.X 修 "Jarvis 吹牛能做但做不到" 时的设计), 又要它不说工具名. 两个 directive 矛盾, LLM 选 "MUST reference" (前 INTEGRITY 弱).

---

## 二. 大修方案

### 方案 A — `screen_tease` vocab 持久化 + L7 reflector

**遵循准则 6 工程方法论** (持久化 + CLI + L7).

#### A.1 vocab 持久化

新建 `memory_pool/screen_tease_vocab.json` schema:

```json
{
  "version": 1,
  "categories": {
    "error_debugging": {
      "keywords": ["error", "exception", "failed", "traceback",
                   "崩溃", "报错", "404", "500", "stack trace",
                   "undefined", "null pointer"],
      "directive_hint": "Sir 屏幕在 debug 报错",
      "ttl_seconds": null,
      "active": true,
      "created_at": "2026-05-20T11:00:00",
      "source": "β.4.X manual / β.5.34 seed"
    },
    "entertainment": {
      "keywords": ["bilibili", "youtube", "直播", "游戏", "steam", "netflix", "视频", "番剧", "twitch"],
      "directive_hint": "Sir 屏幕在看娱乐内容",
      "ttl_seconds": null,
      "active": true,
      "created_at": "2026-05-20T11:00:00",
      "source": "β.4.X manual / β.5.34 seed"
    },
    "slacking": {
      "keywords": ["reddit", "twitter", "微博", "知乎", "douyin", "抖音", "xiaohongshu", "小红书"],
      "directive_hint": "Sir 屏幕在社交媒体摸鱼",
      "ttl_seconds": null,
      "active": true,
      "created_at": "2026-05-20T11:00:00",
      "source": "β.4.X manual / β.5.34 seed"
    },
    "reading_docs": {
      "keywords": ["readthedocs", "docs", "documentation", "mdn", "stackoverflow"],
      "directive_hint": "Sir 在读文档/查 SO",
      "ttl_seconds": null,
      "active": true,
      "created_at": "2026-05-20T11:00:00",
      "source": "β.5.34 seed (extends Sir 实际使用)"
    },
    "ide_focus": {
      "keywords": ["Cascade", "Cursor", "Windsurf", "VSCode", "PyCharm", "Jarvis"],
      "directive_hint": "Sir 在 IDE 写代码 (核心工作)",
      "ttl_seconds": null,
      "active": true,
      "created_at": "2026-05-20T11:00:00",
      "source": "β.5.34 seed (Sir 一周高频)"
    }
  }
}
```

`memory_pool/screen_tease_review.json` (L7 propose queue):

```json
{
  "version": 1,
  "pending": [
    {
      "category": "writing_email",
      "keywords": ["Outlook", "Gmail", "邮件"],
      "directive_hint": "Sir 在写邮件",
      "source": "L7 reflector / observed 2026-05-19 14:32",
      "proposed_at": "..."
    }
  ],
  "accepted_history": [...],
  "rejected_history": [...]
}
```

#### A.2 CLI 工具

新建 `scripts/screen_tease_vocab_dump.py` (类 `scripts/concerns_dump.py` 风格):

```
python scripts/screen_tease_vocab_dump.py list
python scripts/screen_tease_vocab_dump.py add <category> <keyword>
python scripts/screen_tease_vocab_dump.py review-accept <category_name>
python scripts/screen_tease_vocab_dump.py review-reject <category_name>
python scripts/screen_tease_vocab_dump.py deactivate <category>
```

#### A.3 SmartNudge 改读 vocab

`@/Jarvis/jarvis_smart_nudge.py:361-372` 改成读 `memory_pool/screen_tease_vocab.json`. 加 cache + mtime watch (vocab 改后秒级生效, 不需重启).

#### A.4 L7 Reflector (新)

`@/Jarvis/jarvis_screen_tease_reflector.py` (新 daemon, ~150 行):

- 看 `window_title_log` (来自 PhysicalEnvironmentProbe snapshots) + Sir 当时 SOUL state
- LLM (OpenRouter cheap model, ~30 day 1 跑) 提取**没命中现有 vocab 但出现 ≥ 3 次**的 window title pattern
- 写 `screen_tease_review.json` `pending` 队列, Sir 用 CLI 拍板.

### 方案 B — `offer_help` 触发语义重新设计

#### B.1 触发 signal 改源

| 旧 (BUG 2) | 新 (β.5.34) |
|---|---|
| Conductor 看 API rate limit → offer_help | 移到 `screen_tease` (这是观察, 不是援助) |
| SmartNudge 看 error keyword → offer_help | 同上 |
| (无) | **Sir 语音明确抱怨** (新源) — 抱怨 vocab 持久化 |
| (无) | **Sir 在某窗口 stuck > N min** (新源, 来自 attention slot) |

#### B.2 新建 `memory_pool/sir_struggle_vocab.json`

抱怨语 / 困难表达 vocab, 持久化:

```json
{
  "version": 1,
  "phrases": [
    {"phrase": "卡住", "severity": "high", "active": true},
    {"phrase": "搞不定", "severity": "high", "active": true},
    {"phrase": "怎么办", "severity": "medium", "active": true},
    {"phrase": "啊", "severity": "low", "active": true},
    {"phrase": "fuck", "severity": "high", "active": true},
    {"phrase": "shit", "severity": "high", "active": true}
  ]
}
```

CLI: `scripts/struggle_vocab_dump.py` (类 concerns_dump).
L7 reflector: 类 A.4.

#### B.3 directive 改成 evidence-driven

`@/Jarvis/jarvis_chat_bypass.py:3784-3789` 改:

```python
"offer_help": (
    f"Sir 显式表达困难 (struggle vocab 命中 / stuck > {stuck_min}min on '{window_title}').\n"
    f"主脑可参考 SOUL inject 已注入的能力 evidence — 但**不要说工具名** (见 [TOOL NAME RULE] 下)."
)
```

### 方案 C — 工具 channel 重构 (BUG 3 大修)

**核心: skill registry 从 "directly expose to LLM" 改成 "tool_call channel"**.

#### C.1 双轨设计

```
+-------------------------------------------------------------+
|   nudge prompt (LLM 看)                                      |
|   --------------------------------------------------------   |
|   [CAPABILITIES — semantic only, NO tool names]:             |
|     - 可以查后台 CPU/内存使用 (system inspection)             |
|     - 可以静音/调音量 (audio control)                          |
|     - 可以发送桌面通知 (notification)                          |
|     - ...                                                    |
|                                                              |
|   [TOOL CALL CHANNEL]:                                       |
|   若决定执行能力, 输出 JSON tag:                                |
|     <TOOL_CALL>{"intent": "check_top_cpu"}</TOOL_CALL>       |
|   后端 intent → 工具名映射. LLM 不直接说工具名.                  |
+-------------------------------------------------------------+
                          ↓
+-------------------------------------------------------------+
|   后端 intent_router.py (新):                                |
|     {"check_top_cpu"} → process_hands.get_top_cpu()         |
|     {"mute_audio"} → audio_hands.mute()                     |
|     ...                                                     |
|   命中工具 → 执行 → 结果灌回主脑 next turn 作 SWM evidence       |
+-------------------------------------------------------------+
```

#### C.2 `skill_registry.to_prompt_block` 改

旧 (line 423-426):
```
"When offering to help Sir, you MUST reference one of these by name."
```

新:
```
"=== SEMANTIC CAPABILITIES ===\n"
"Below are intents you can declare via <TOOL_CALL> tag.\n"
"NEVER speak tool names (e.g. 'process_hands.get_top_cpu' is FORBIDDEN).\n"
"Speak in human terms ('let me check CPU usage') and emit <TOOL_CALL>{intent}.\n"
"  - intent='check_top_cpu' → 查看 top CPU process\n"
"  - intent='mute_audio' → 静音\n"
"  - ...\n"
"=== END ==="
```

#### C.3 持久化

`memory_pool/intent_to_tool_map.json` (新):

```json
{
  "version": 1,
  "intents": {
    "check_top_cpu": {
      "tool": "process_hands.get_top_cpu",
      "semantic_hint": "查看后台 CPU 占用最高的进程",
      "human_phrases_en": ["let me check CPU", "look at running processes"],
      "human_phrases_zh": ["查一下 CPU", "看看后台进程"],
      "dangerous_flag": "safe",
      "ttl_seconds": null,
      "active": true
    },
    "mute_audio": {
      "tool": "audio_hands.mute",
      "semantic_hint": "全局静音",
      "human_phrases_en": ["mute audio", "silence the system"],
      "human_phrases_zh": ["静音", "把声音关了"],
      "dangerous_flag": "safe",
      "ttl_seconds": null,
      "active": true
    }
  }
}
```

CLI: `scripts/intent_map_dump.py` (类 concerns_dump).
L7 reflector: 看 LLM 历史输出 + 工具实际执行历史, propose 新 intent.

#### C.4 后端 intent router

新文件 `@/Jarvis/jarvis_intent_router.py` (~200 行):

- 输入: LLM stream 输出
- 解析 `<TOOL_CALL>{...}</TOOL_CALL>` tag
- 查 `intent_to_tool_map.json` 把 intent → tool name
- 调 `skill_registry.invoke(tool_name, ...)` 执行
- 结果灌回下轮主脑 SWM evidence

#### C.5 STM / subtitle 漏出防御

`@/Jarvis/jarvis_chat_bypass.py:601-605` (Audio Guard 已有) — **扩到 subtitle path 也过 audio guard 替换**:

- 替换 `_TOOL_NAME_RE` 命中 → "(internal tool)" / "(a quick check)" 之类
- LLM 即使违规说了, subtitle/STM 也不会泄漏

---

## 三. Sir 拍板项

### 拍板项 1: 范围 / 阶段

| 阶段 | 内容 | 工期估 |
|---|---|---|
| **β.5.35-A** | screen_tease vocab 持久化 + CLI + 5 个 seed category | 1.5h |
| **β.5.35-B** | screen_tease L7 reflector (cheap LLM, 30day 1 跑) | 1h |
| **β.5.35-C** | offer_help 触发源改 (struggle vocab / stuck timer) + directive 改 | 2h |
| **β.5.35-D** | struggle vocab 持久化 + CLI + L7 reflector | 1.5h |
| **β.5.35-E** | intent_to_tool_map 持久化 + CLI | 1.5h |
| **β.5.35-F** | skill_registry.to_prompt_block 改双轨 (intent + 禁工具名) | 1h |
| **β.5.35-G** | jarvis_intent_router 后端解析 + 调用 + SWM evidence 回流 | 3h |
| **β.5.35-H** | Audio Guard 扩到 subtitle/STM path | 0.5h |
| **β.5.35-I** | regression test (~20 testcase) | 2h |
| **合计** | | **~14h** |

### 拍板项 2: 是否拆 2 commit 还是 1 commit

- A + B = BUG 2 small piece (~2.5h, 单 commit)
- C + D = BUG 2 medium piece (struggle 重新设计, ~3.5h)
- E + F + G + H = BUG 3 大修 (~6h)
- I = test 单 commit

**推荐 4 commits** (β.5.35-A/B, C/D, E-H, I).

### 拍板项 3: intent 命名 schema

3 选项, Sir 拍板:

- **3a 通用名词**: `check_top_cpu`, `mute_audio`, `kill_process` (动词_名词, 通用)
- **3b 自然语**: `look_at_running_processes`, `silence_system` (像人话, 易理解但长)
- **3c 域名_动作**: `system.cpu_top`, `audio.mute` (近似 tool 名但语义化)

### 拍板项 4: L7 Reflector LLM 选型

- **4a 复用 OpenRouter cheap (e.g. `qwen-2.5-7b`)** — Sir 已有 key, 加 daemon 24h 1 跑
- **4b 用 Gemini 2.5 Flash** — Sir 已有 key, 速度快
- **4c 跳过 L7, 纯 Sir 手动加 vocab** — 最低工作量

### 拍板项 5: BUG 2 + BUG 3 是否合并执行

- **5a 合并**: 一次 ~14h 一气呵成, 立 β.5.35 大版本
- **5b 拆开**: 先 BUG 2 (β.5.35), 真机实测稳了再 BUG 3 (β.5.36)

---

## 四. 配合的 testcase

### TestScreenTeaseVocabPersistence (β.5.35-A/B)
- 文件存在
- CLI 增删查改
- SmartNudge 读 vocab 命中场景
- mtime cache invalidation
- 默认 5 category seed 存在

### TestOfferHelpSignalSource (β.5.35-C/D)
- offer_help 不再从 error_keyword 触发
- struggle vocab 命中触发 offer_help
- stuck timer >= threshold 触发

### TestIntentRouter (β.5.35-E/F/G)
- intent_to_tool_map 持久化 schema
- LLM `<TOOL_CALL>{intent}` 解析正确
- intent → tool_name 映射执行
- 工具结果回流 SWM
- LLM 直接说工具名 → Audio Guard 替换 (regression)

### TestToolNameNoLeak (β.5.35-H)
- subtitle / STM 都过 Audio Guard
- 即便 LLM 违规说了 process_hands.X, 字幕 / STM 不出现

---

## 五. 风险 / 反例

| 风险 | 缓解 |
|---|---|
| LLM 不学 intent schema, 还说工具名 | C.5 Audio Guard 兜底; 多次违规 → L7 reflector 提示加强 directive |
| L7 cheap model 误 propose 垃圾 vocab | review_queue + Sir CLI 拍板; rejected 写黑名单防回流 |
| screen_tease vocab 误命中 (例 `Cursor` keyword 跟 `Cursor IDE`) | category 加正/反 pattern; L7 reflector 自动检测误命中 |
| intent_map 漏 intent → LLM 说 "I can't" | 加 `fallback_intent` "I don't have that capability yet"; L7 提议新 intent |
| 大修引入 regression | 4 commit 分批, 每个独立可 revert; testcase 覆盖 |

---

## 六. 配合 docs 更新

落地时同步:
- `TODO.md`: β.5.35-A 到 -I 板块加入
- `docs/JARVIS_PROACTIVITY_NEXT.md`: 加 §F screen_tease + offer_help + intent channel
- `docs/JARVIS_WORKFLOW_PROTOCOL.md`: 加准则 6 vocab 范式新示例 (intent_map)
- `AGENTS.md`: 加 intent_to_tool_map / screen_tease_vocab / struggle_vocab 到三维耦合工程落地示例

---

**Sir 拍板, 我立刻开干.**
