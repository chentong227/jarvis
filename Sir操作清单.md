# Sir 操作清单

> 不用看代码也能用 Jarvis。这份清单只给你（Sir）看，**人话，不黑话**。
> 最后更新：2026-05-17

---

## 🚨 紧急：Python 进程音量被锁在 1% 听不见声音

**症状**：Windows 应用音量混合器里 `Python` 这一行滑块灰色，锁死 1%，拖不动。

**一次性修法**（不用重启 Jarvis）：
```powershell
python scripts\unlock_python_volume.py
```
跑完看到 `✅ 恢复了 N 个 Python 进程的音量` 就好了。Windows 滑块会恢复正常。

**长期防御**：Jarvis 启动时自动跑同样的修复（不用每次手动）。如果你重启 Jarvis 启动 log 里看到 `🔊 [VolumeRecover] python.exe ...` 那就是它自己救自己。

---

## 我每周/平时要做什么？分 3 件事，按重要顺序

### 1️⃣ 给 Jarvis 添加"我们之间的故事"（最重要，最常做）

**为什么要做**：Jarvis 现在的"灵魂"里有 3 类东西需要你喂养。不喂他不知道。
- **我们的内部梗**（inside_joke）：比如你笑他啰嗦时说的"lecture mode"
- **我们的默契规则**（protocol）：比如"我说 deep work 时你别啰嗦"
- **没办完的事**（unfinished）：比如你答应写但没写的那篇 postmortem

**怎么做**：
```powershell
# 加一个梗
python scripts\relational_dump.py --add-joke "lecture mode" --tone "recurring" --context "我笑他啰嗦时这么说"

# 加一条默契
python scripts\relational_dump.py --add-protocol "我说 deep work 时回复必须 ≤ 1 句话不带中文"

# 加一件没办完的事
python scripts\relational_dump.py --add-unfinished "5/14 答应写的那篇 postmortem"

# 看现在所有的故事
python scripts\relational_dump.py
```

**怎么观察有没有效果**：
- 看 Jarvis 实测对话，他主动 reference 这些梗的时候你会感觉"哎他记着"
- 直接看 `memory_pool\relational_state.json` 文件，里面是你录入的内容

---

### 2️⃣ 每周看一次"Jarvis 自己想新关心点什么"

**为什么要做**：Jarvis 每 7 天会反思最近 50 轮对话，自己提议"我应该开始关心 XX"。这些提议不会自动生效，要你拍板。

**怎么做**：
```powershell
# 看待审核的提议
python scripts\concerns_dump.py --review
```

**看到什么**：会列出 Jarvis 提议的新关心点，比如：
```
- proposed: sir_premiere_export_efficiency
  what: Sir 经常在导出视频时遇到内存不足
  why_i_care: 影响 Sir 的工作流和我的响应速度
  状态: 等待你拍板
```

**怎么处理**（暂时还没有 --approve / --reject CLI，需要的话告诉我加上）：
- 觉得有道理 → 编辑 `memory_pool\concerns.json` 把 `state` 从 `"review"` 改成 `"active"`
- 觉得没必要 → 编辑同文件把 `state` 改成 `"archived"`

---

### 3️⃣ 偶尔看看"Jarvis 现在到底关心什么"

```powershell
python scripts\concerns_dump.py
```
列出当前所有 active 关心点 + 每条的"严重度"（severity 0-1）。比如你最近熬夜聊得多，`sir_sleep_streak` 这条 severity 会涨。

---

## Jarvis 自己跑的部分（你不用管）

| 是什么 | 它干啥 |
|---|---|
| L0 自我状态 | 每次回话都自动报"我现在已经聊了 12 轮 / API 健康 / 心情 alert" |
| L3 注意力 | 每次自动从 L1+L2 里挑 top-3 关心 + top-1 梗给主脑 |
| L4 信号采集 | 你说"熬夜" → sir_sleep_streak 自动 +severity，你说"cursor 续费" → sir_cursor_payment +signal |
| L5 自评 | 每轮回话末尾异步评一次"我这次有没有按 self_model 回话"，结果写回 L1 |

这些都是后台跑的，**你看不见但它在动**。
真要看后台动作，启动 Jarvis 后看终端的 `bg_log`：
- `🪞 [SOUL inject] L0=900c L1=600c L2=388c L3=285c` ← 这轮注入了多少灵魂内容
- `🪞 [Nudge SOUL inject] mode=nudge prompt_len=7857c` ← SmartNudge 也走了灵魂注入
- `🪞 [SoulEvaluator] turn_xxx → alignment=yes` ← 这轮 Jarvis 自评合格

---

## Jarvis 出问题时

### 没声音
1. 先跑 `python scripts\unlock_python_volume.py`
2. 还没声 → 检查 Windows 主音量、默认输出设备（扬声器/蓝牙耳机切换过吗）
3. 看启动 log 有 `✅ [声带器官] 显存预热完毕！` 吗？没有就是 cosyvoice 没加载

### 突然变成模板感不像人了
说明灵魂注入没起作用。重启 Jarvis 看启动 log：
- 必须有 `🪞 [SelfAnchor] Layer 0 ready`
- 必须有 `🌱 [ConcernsLedger] active=5 review=2 (灵魂工程 Layer 1 已激活)`
- 必须有 `💞 [RelationalState] jokes=N protocols=N unfinished=N (灵魂工程 Layer 2 已激活)`
- 必须有 `🎯 [Attention] Layer 3 ready`
- 必须有 `🪞 [SoulEvaluator] Layer 5 ready`
- 必须有 `🌙 [Reflectors] ConcernsReflector + WeeklyReflector ready`

缺哪一条说明哪层没启动，跟我说我看代码。

### SmartNudge 长得像之前的固定模板
理论上现在 SmartNudge 也走灵魂注入（Phase 1 已上线）。
- 看 log 有没有 `🪞 [Nudge SOUL inject] mode=nudge prompt_len=...`
- 有这条 → 注入了但 LLM 没引用（可能是 [RULES] 太严，需要进一步调）
- 没这条 → Phase 1 没生效，跟我说

### 重启 Jarvis 后想跑全测确认
```powershell
.\tests\_runall.ps1
```
看末尾 `REGRESSION SUMMARY: 64 / 64 OK, 0 FAIL` 就是绿的。

---

## 看上次跑测结果
```powershell
Get-Content tests\last_run.json | Select-String -Pattern "passed|failed|duration"
```

## 看 Jarvis 此刻最新日志
```powershell
Get-Content (Get-Content docs\runtime_logs\latest.txt) -Tail 30
```

---

**最后一句**：你不必记 L0-L5 的字母编号。记住三件事就够 —
1. 加梗/规则/未办事用 `relational_dump.py --add-*`
2. 每周看一次 `concerns_dump.py --review` 拍板
3. 没声音跑 `unlock_python_volume.py`
其他全部 Jarvis 自己跑。
