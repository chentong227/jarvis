# JARVIS Agent Mirror Testing

> **目的**: 给 Cascade/agent 一个 **复刻 d:/Jarvis 目录的隔离 sandbox**, 用 文本注入 模拟 Sir
> 说话, 真跑全套主脑/思考脑/sentinel/hub, 写一切输出 (chat reply / TTS / 字幕 / FAST_CALL) 进
> JSONL 给 agent audit, 0 影响主 Jarvis 实例.
>
> **Sir 原话 (2026-05-28 22:00 fix49)**:
> > "甚至可以理解成把贾维斯目录复制一份那种, 只是不需要测我说话, 转录这些, 相当于你直接输入
> > 文字等同于我说话就可以了, 其他完全一致, 主要用于测试贾维斯的能力是否能实现, 有没有实际
> > 使用的 BUG"

---

## 1. 总览

```
┌────────────────────────────────────────────────────────────────────┐
│ d:/Jarvis (主 Sir 真用)                                            │
│                                                                    │
│  jarvis_nerve.py — 主进程, 真麦克风, 真 TTS, 真 UI, 真 sqlite      │
│  memory_pool/*.json                                                │
│  jarvis.db                                                         │
└────────────────────────────────────────────────────────────────────┘
                          ▲ 0 共享 (cwd 隔离 + JARVIS_MIRROR=1 env gate)
                          │
┌────────────────────────────────────────────────────────────────────┐
│ D:/jarvis_mirror_<ts>/ (Cascade 测试 sandbox, 镜像 subprocess)     │
│                                                                    │
│  jarvis_nerve.py — JARVIS_MIRROR=1 → MockVocalCord / MirrorVoice  │
│                     Worker / MirrorBreathingLightUI 全启用         │
│  memory_pool/*.json (复制, mirror 写不影响主)                      │
│  jarvis.db (复制, mirror 写不影响主)                               │
│                                                                    │
│  _mirror_input.jsonl  ← Cascade append (Sir 说什么)                │
│  _mirror_output.jsonl → Cascade tail (chat / TTS / 字幕 / 工具)    │
│  _mirror_meta.json    (task / pid / cwd / ts)                      │
└────────────────────────────────────────────────────────────────────┘
```

设计准则: **准则 6 数据强耦合** (publish JSONL) + **准则 8 优雅** (4 hook 点 + cwd 隔离 + 0 下游改动)

---

## 2. 4 个 hook 点 (主进程 0 影响, env JARVIS_MIRROR=1 时才生效)

| # | 文件 | 位置 | 替代物 |
|---|---|---|---|
| **1** | `jarvis_central_nerve.py:215-217` | `CentralNerve.__init__` 创 vocal | `MockVocalCord` (跳 CosyVoice GPU + audio device) |
| **2** | `jarvis_nerve.py:325-330` | `__main__` 创 voice_worker | `MirrorVoiceWorker` (1s poll `_mirror_input.jsonl`) |
| **2b** | `jarvis_nerve.py:280-302` | `__main__` 创 UI + subtitle_overlay | `MirrorBreathingLightUI` + `MirrorSubtitleOverlay` (no-op + 写 JSONL) |
| **3** | `jarvis_chat_bypass.py:6132-6161` | `stream_chat_local` 末尾 | `append_mirror_output(event='turn_complete', ...)` |
| **4** | `jarvis_chat_bypass.py:1595-1609` | `_handle_fast_call_immediate` 顶 | `append_mirror_output(event='fast_call_attempt', ...)` |
| **4b** | `jarvis_chat_bypass.py:1641-1651` | ui_control.dashboard_* | mirror 短路返 mock success (防 8765 撞主进程) |

Hook 全部 wrap `try/except + is_mirror_mode()` gate, 非 mirror 路径 0 IO / 0 影响.

---

## 3. 启动一次镜像测试 (Cascade 标准流程)

```powershell
# Step 1. 启镜像 (复制 d:/Jarvis → D:/jarvis_mirror_<ts>/ + 起 subprocess)
python scripts/jarvis_mirror.py --task "测 Sir 说 'remind me in 2 hours 吃药' 后 reminder 链是否触发"

# 输出会有:
#   📁 [mirror] copying d:/Jarvis → D:/jarvis_mirror_20260528_223045 ...
#   📁 [mirror] copied: ~2500 files / ~180 MB / ~15s
#   🚀 [mirror] subprocess started, pid=12345
#   ⏬ 启动 cheat sheet (注入 / tail / 停)

# Step 2. 等 ~5s 让镜像 nerve 完成 init (看 _mirror_output.jsonl 是否有 mirror_voice_worker_started)
python scripts/jarvis_mirror_tail.py --event mirror_voice_worker_started --limit 1

# Step 3. 注入 Sir 模拟话
python scripts/jarvis_mirror_say.py "Hey Jarvis remind me in 2 hours to take medicine" --note "fix49 真测 reminder"

# Step 4. 等主脑出 reply (一般 5-10s), tail 看
python scripts/jarvis_mirror_tail.py --event turn_complete --limit 1

# 看到的格式:
#   [2026-05-28T22:31:05] 🧠 turn_complete dur=7.4s (tools=1)
#      ↳ Sir : 'Hey Jarvis remind me in 2 hours to take medicine'
#      ↳ Jrvs: 'Noted, Sir. Reminder set for 2 hours from now to take medicine.'

# Step 5. 继续聊 / 测下一句
python scripts/jarvis_mirror_say.py "actually make it 30 minutes instead"

# Step 6. 看主脑真发了什么 FAST_CALL
python scripts/jarvis_mirror_tail.py --event fast_call_attempt --limit 10

# Step 7. (可选) 持续 follow 模式
python scripts/jarvis_mirror_tail.py --follow

# Step N. 完毕, 杀镜像 + 清目录
taskkill /F /PID 12345
rmdir /S /Q "D:/jarvis_mirror_20260528_223045"
```

---

## 4. 输出事件类型 (`_mirror_output.jsonl`, 每行一 JSON)

### 4.1 Sir 输入 / 主脑 turn

| event | 写者 | payload key |
|---|---|---|
| `sir_input_received` | `MirrorVoiceWorker.run` | `text` / `input_entry` |
| `turn_complete` | `chat_bypass.stream_chat_local` 末尾 | `channel='main_chat'` / `turn_id` / `sir_utterance` / `final_reply` / `reply_len_chars` / `duration_sec` / `tool_results[]` / `circuit_broken_reason` |

### 4.2 TTS (MockVocalCord 不真出声)

| event | 写者 | payload key |
|---|---|---|
| `mock_tts` | `MockVocalCord.speak` | `text` / `len_chars` / `render_count` |
| `mock_tts_render` | `MockVocalCord.render_only` | `text` / `len_chars` / `retry` |
| `mock_audio_play` | `MockVocalCord.play_only` | `byte_len` / `text` |
| `mock_tts_stop` | `MockVocalCord.stop_immediately` | (空) |

### 4.3 工具调

| event | 写者 | payload key |
|---|---|---|
| `fast_call_attempt` | `chat_bypass._handle_fast_call_immediate` 顶 | `organ` / `command` / `params_excerpt` |
| `mirror_fast_call_skipped` | `chat_bypass` ui_control.dashboard_* | `organ` / `command` / `reason` |

### 4.4 UI / 字幕

| event | 写者 | payload key |
|---|---|---|
| `mirror_subtitle` | `MirrorSubtitleQueue.put` | `channel` (en/zh/control/etc) / `text` |
| `mirror_subtitle_overlay_started` | `MirrorSubtitleOverlay.__init__` | (空) |
| `mirror_ui_started` | `MirrorBreathingLightUI.__init__` | (空) |
| `mirror_ui_show_noop` | `MirrorBreathingLightUI.show` | (空) |
| `mirror_ui_state` | `MirrorBreathingLightUI.change_state` | `state` |
| `mirror_ui_awake` | `MirrorBreathingLightUI.set_awake_status` | `awake` |
| `mirror_ui_visual_pulse` | `MirrorBreathingLightUI.flash_pulse` | `kind` |

### 4.5 镜像基础设施

| event | 写者 | payload key |
|---|---|---|
| `mirror_voice_worker_started` | `MirrorVoiceWorker.run` 第一帧 | `input_path` / `poll_interval_s` |

---

## 5. 文件清单 (本次新加 / 修改)

### 5.1 新加

| 路径 | 用途 |
|---|---|
| `jarvis_mirror_mode.py` | mirror mode 核心 (env gate / path helper / `append_mirror_output` / `MockVocalCord` / `MirrorVoiceWorker` / `MirrorBreathingLightUI` / `MirrorSubtitleOverlay` / `write_mirror_meta`) |
| `scripts/jarvis_mirror.py` | launcher: 复制目录 + 启 subprocess (`--task` / `--root` / `--dry-run` / `--keep-runtime-logs` / `--include-models` / `--no-detach`) |
| `scripts/jarvis_mirror_say.py` | Cascade 注入 Sir 模拟话 → `_mirror_input.jsonl` |
| `scripts/jarvis_mirror_tail.py` | Cascade tail `_mirror_output.jsonl` (`--event` filter / `--follow` / `--raw` / `--limit`) |
| `docs/JARVIS_AGENT_MIRROR_TESTING.md` | 本文档 |
| `tests/_test_fix49_sir_20260528_mirror_mode.py` | mirror 单元测试 (无需启 subprocess) |

### 5.2 改动 (hook 注入)

| 路径 | 位置 | 改动 |
|---|---|---|
| `jarvis_central_nerve.py` | 95-99 / 215-217 / 5483-5488 | mirror gate `VocalCord` import + 用 `MockVocalCord` |
| `jarvis_nerve.py` | 244-250 / 280-302 / 325-330 | mirror import + UI/voice_worker 全切 mock |
| `jarvis_chat_bypass.py` | 1595-1609 / 1641-1651 / 6132-6161 | `fast_call_attempt` + `mirror_fast_call_skipped` + `turn_complete` hook |

---

## 6. 限制 / 边界 / 后续 TODO

### 6.0 ⚠️ Mirror = 软件 sandbox, **不是数字孪生** (Sir 2026-05-28 23:25 确认 §准则 5)

Cascade (含未来 session 接手的我) 看 mirror 前 **必读这一节**, 不要误以为 mirror 能复现所有
实机 BUG. Sir 选了"接受边界" 而非"加 ASR/TTS 真链", 所以 mirror 永远是软件层 sandbox.

#### ✅ Mirror **能测** (Cascade 替 Sir 跑回归)

- 主脑 reply 逻辑 / prompt 拼接 / vocab 持久化 (准则 6)
- 工具调 (FAST_CALL) 链: `organ.command` + params + result parse
- LLM 输出 parse / circuit breaker / `stream_chat_local` 13 个 return path
- Sentinel daemon 启动行为 (Conductor / NudgeGate / Wellness / SmartNudge / SoulEvaluator)
- IntentResolver / SWM publish 链 / β.6 统一思考层
- 配置 CLI 工具 (`scripts/*_dump.py`) 行为
- L4-L7 Reflector LLM-propose 链

#### ❌ Mirror **测不到** (Sir 必须主程序真测)

| BUG 类 | 为什么测不到 |
|---|---|
| ASR 转录错 (Whisper 把 "remind" 听成 "remained") | mirror 跳 ASR, `_mirror_input.jsonl` 直接给 text |
| `wake_word` "Hey Jarvis" 触发 | mirror 没真麦克风 |
| VAD 切句 BUG (太敏感 / 漏切) | mirror 没 VAD |
| CosyVoice GPU OOM / model load fail / GPU timeout | `MockVocalCord` 不真打 GPU |
| TTS 音质 (多音字读错 / 停顿不自然) | mirror 不真生成 audio |
| audio device 占用冲突 / 中断打断真链 | mirror 不碰 sounddevice |
| TTFT 真实数据 (验证准则 1 `< 5s`) | mirror 跳 ASR ~1-2s, 数据失真 |
| UI 卡顿 / Qt event loop block | UI 全 no-op |
| dashboard WebSocket / 端口冲突 | `dashboard_open` 被短路 (port 8765 撞主) |
| 时间敏感 daemon 真实状态 | sentinel 看复制时刻**快照**, 非主程实时 |
| 真实环境干扰 (多人 / 噪音 / 网络抖动) | mirror 是干净沙盒 |

#### 4 类与主程序的差异本质

| 维度 | 主程序 | Mirror | 差异严重度 |
|---|---|---|---|
| **输入侧** | 麦克风 → VAD → ASR → text | `_mirror_input.jsonl` 直接给 text | ⚠️ **大** |
| **输出侧** | VocalCord → CosyVoice GPU → audio device | `MockVocalCord` → 写 jsonl + dummy bytes | ⚠️ **大** |
| **UI 侧** | BreathingLightUI + SubtitleOverlay (PyQt5 真窗) | `MirrorBreathingLightUI/Overlay` no-op | 中 |
| **数据侧** | `memory_pool/*.json` + `jarvis.db` 实时主程 | 复制时刻**快照**, mirror 写不回主 | 中 |

### 6.1 已知运行限制

1. **LLM key 共享** (mirror subprocess 继承主进程 env, 包括 OPENROUTER_MAIN/GEMINI). 镜像
   测试会真烧 LLM tokens. Cascade 自觉省着用, 或加 `--llm-mock` 开关 (TODO).
2. **`_mirror_input.jsonl` poll 间隔 1s** (`MirrorVoiceWorker.poll_interval=1.0`, launcher 改成
   0.5s 加速). 注入到主脑收到有 ~0.5-1s lag, 不影响功能 audit.
3. **`_legacy/` / `.git/` / `CosyVoice/` / `ffmpeg.exe` / `ffprobe.exe` 默认不复制**. 如需测视频
   时长之类用 `--include-models` 把 ffmpeg 也复制 (会多 200MB).
4. **dashboard_open** 在 mirror mode 被短路 (port 8765 撞主进程). 镜像看不到 dashboard, 但
   主脑 reply chain 不受影响.
5. **runtime_logs/ 默 不复制** (镜像从空 log 起, 干净一点). `--keep-runtime-logs` 可保留.
6. **PromiseLog / hippocampus 数据库** 会被复制 (`memory_pool/*.json` / `jarvis.db`). 镜像写
   不影响主. 测完 `rmdir` 整盘清掉就好.

### 6.2 TODO 后续可加

- [ ] **`--llm-mock`**: env JARVIS_MIRROR_LLM_MOCK=1, `safe_openrouter_call` 顶返 mock reply,
      不烧真 token. 加在 `jarvis_utils.safe_openrouter_call` (类似 fix45 的 mock 模式)
- [ ] **mirror dashboard port offset**: env JARVIS_MIRROR_DASHBOARD_PORT, 让 mirror dashboard 跑
      8766 而不是撞 8765
- [ ] **mirror 自动 cleanup**: 加 `scripts/jarvis_mirror_clean.py`, 列出所有 D:/jarvis_mirror_*
      + age + size + 一键 rm
- [ ] **mirror 多轮 batch test**: 加 `scripts/jarvis_mirror_batch.py`, 读 yaml/json 一组 sir
      utterance + expected substring, 自动跑 + assert, 给 Cascade 做 regression test

---

## 7. 设计准则对应

| 准则 | 体现 |
|---|---|
| **6 数据强耦合** | 所有 mirror event → publish to `_mirror_output.jsonl` (= mirror 的 SWM proxy), Cascade tail 看 |
| **6 配置持久化** | `_mirror_meta.json` task + ts + pid 持久化, CLI 工具 (`scripts/jarvis_mirror*.py`) 可读改 |
| **6 + 8 拒绝硬编码** | env JARVIS_MIRROR=1 单一 gate, 全部 mock 通过 factory / class 切, 0 if-else 散在主链 |
| **7 Sir 元否决** | Sir 不喜欢? `git revert` 删 4 个 hook + 删 `jarvis_mirror_mode.py` 即可, 主路径 0 残留 |
| **8 优雅** | 4 hook 点 + cwd 隔离 + 主进程 env JARVIS_MIRROR 不 set 时所有 mock 0 触发 (`is_mirror_mode()` short circuit) |

---

## 8. 历史

| 时间 | 事件 |
|---|---|
| 2026-05-28 22:00 | Sir fix49 提需求 (隔离 sandbox + 文本注入 + 全 audit + 不影响主) |
| 2026-05-28 22:30 | Cascade 实现 P1 `jarvis_mirror_mode.py` (env gate / mocks / factory) |
| 2026-05-28 22:45 | Cascade 实现 P2 4 hook 点 (nerve + central_nerve + chat_bypass) |
| 2026-05-28 23:00 | Cascade 实现 P3 launcher + CLI 注入 / tail + 本文档 + 测试 |
