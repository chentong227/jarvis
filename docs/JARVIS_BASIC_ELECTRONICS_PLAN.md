# JARVIS_BASIC_ELECTRONICS_PLAN

> **Sir 2026-05-20 13:01 设计目标**:
> 入职事业编前, Jarvis = **陪伴管家 + 基础电脑操作**, 不做 agent 自动化 (那让 Cascade/Claude 干).
> Sir 给一句话 → Jarvis 单步骤执行 (e.g. "打开钉钉" / "给王科长发 '收到了'" / "切到 Excel").
>
> 本 doc 是 Sir 入职前的工程蓝图. **大部分内容等 Sir 实测稳定 + 提供单位 / 软件 / 别名信息后再确定**.
> 完成时机: Sir 实测 β.5.34/35/36 完成 + 提供单位环境信息后, Cascade 据此填具体优先级 + 实现.

---

## 一. 设计哲学 (Sir 拍板)

| 维度 | 决策 | 理由 |
|---|---|---|
| **不做 agent 自动化** | Jarvis 不做 ReAct / multi-step task / OAuth / 复杂工作流 | 那是 Cascade/Claude 的活, Sir 直接调他们 |
| **做单步骤命令** | Sir 一句话 → 1 个 tool call → 立即执行 → 反馈结果 | 类似 Siri/小爱同学但更准更懂 Sir |
| **复用现有架构** | 走 `intent_to_tool_map` (β.5.36-E) + `IntentRouter` (β.5.36-G) + 新加 hands | 已有桥, 不重复造 |
| **Sir 别名优先** | "钉钉"/"OA系统"/"那个表" 走 fuzzy_resolver + Sir 习惯 vocab | 不强迫 Sir 说精确指令 |
| **失败优雅降级** | 不能做的事直接说 "Sir 我做不到" + 引导 Sir 去手动 | 准则 5 言出必行, 不假装 |

---

## 二. 候选操作清单 (5 类, 详见 §五等 Sir 拍板)

### 🪟 桌面 / 窗口
- 切到指定应用 / 全屏 / 最小化
- 打开 / 关闭具体应用 (按别名 vocab)
- 锁屏 / 待机 / 重启
- 截图 (全屏 / 区域 → 剪贴板 / 文件)

### 📁 文件
- 按名找 / 打开文件 (Everything 或 es CLI 即时搜)
- 打开最近文件 (recent files OS 接口)
- 打开 Sir 定义的快捷文件夹 (vocab: "我的工作文件夹"→D:\工作)

### 💬 通讯 (单条, 不做对话自动化)
- 微信 / 企业微信 / 钉钉 / 飞书 发单条消息 (Sir 选环境)
- 发邮件 (Outlook COM / 默认邮件客户端 mailto)
- 拨号 (Sir 接管对话, Jarvis 只发起)

### 🌐 浏览器 / 信息
- 打开 URL (Sir 别名 vocab: "市政府门户" → 真 URL)
- 单步搜索 (打开浏览器 + URL 搜索 query)
- 朗读选中文本 (Sir 看页面 → 让 Jarvis 朗读, 复用 vocal.say)

### 🎵 多媒体
- 已有: 音量 / 静音 / 播放暂停
- 新加: 启动音乐应用 + 自动播 (网易云 / Spotify / 本地播放器)

---

## 三. 实现技术栈选择

| 类别 | 候选库 | 优先 | 备注 |
|---|---|---|---|
| 桌面通用 | PyAutoGUI / Win32 API | Win32 API | 已有依赖, 更稳 |
| 应用 launching | `subprocess.Popen` + Sir 别名 vocab | ✅ | 简单, 现有 process_hands 已支持 |
| 应用 fuzzy match | `Levenshtein` / `fuzzywuzzy` + 现有 fuzzy_resolver | 复用现有 | 加 vocab JSON |
| 文件搜索 | Everything (`es.exe` CLI) / Windows Search | Everything | 即时索引, 1ms 搜全盘 |
| 微信发消息 | itchat / wxauto / 鼠标键盘模拟 | wxauto | itchat 网页版已禁用 |
| 企业微信 | 企业微信 API (需 corpid/secret) / wxauto | wxauto | 简单 |
| 钉钉 | 钉钉 OA SDK / 鼠标键盘模拟 | SDK | 政务用得多 |
| 飞书 | 飞书 OpenAPI | OpenAPI | 较先进 |
| Outlook | `pywin32` Outlook COM | ✅ | 工业标准 |
| 通用 mailto | `webbrowser.open('mailto:...')` | fallback | 通用 |
| 浏览器控制 | `webbrowser` 模块 / Selenium | webbrowser | 单步骤够用 |
| 截图 | `mss` / Win32 PrintWindow | mss | 简单跨屏 |
| OCR (可选) | PaddleOCR (已用) | ✅ | 截图 + 朗读 |

---

## 四. 复用现有架构 (零成本接入)

```
Sir 一句话
    ↓
ASR → text_ready → ChatBypass.stream_chat
    ↓
LLM 主脑看 SEMANTIC CAPABILITIES (β.5.36-F)
    ↓
emit <TOOL_CALL>{"intent": "send_wechat_msg", "args": {"contact": "王科长", "content": "收到了"}}
    ↓
IntentRouter (β.5.36-G) 翻 intent → tool_name → fast_call_executor
    ↓
新 hands 模块执行 → 返结果
    ↓
event_bus publish → SWM evidence
    ↓
LLM 下一轮 prompt 看到 → 报告 Sir
```

**新加部分**:
1. `memory_pool/intent_to_tool_map.json` 加 Sir 选的 intent (e.g. `send_wechat_msg`)
2. `l4_hands_pool/l4_wechat_hands.py` (类) 实现 wxauto 调用
3. `memory_pool/sir_app_aliases.json` 别名 vocab (e.g. "记事本"→`notepad.exe`, "钉钉"→`DingTalk.exe`)
4. `memory_pool/sir_url_vocab.json` URL 别名 (e.g. "市政府门户"→真 URL)
5. `memory_pool/sir_contacts.json` 联系人别名 (e.g. "王科长"→真 contact ID)

**全部 vocab 持久化 + CLI 管理 (准则 6)**.

---

## 五. [WAITING FOR SIR INPUT] — Sir 提供的信息

> **Sir 实测 β.5.34/35/36 完成后, 在此填:**

### 5.1 单位环境 (硬件 / OS)
- [ ] 工作机 OS: ______ (Win11 / Win10 / 政务 Linux)
- [ ] 是否有 admin 权限: ______
- [ ] 有几台显示器: ______
- [ ] 是否能装 Python / 第三方库: ______

### 5.2 通讯软件 (单位用什么)
- [ ] 微信 (个人): 是 / 否
- [ ] 企业微信: 是 / 否, corpid 是否能拿到 ______
- [ ] 钉钉: 是 / 否
- [ ] 飞书: 是 / 否
- [ ] OA 系统: 名称 ______, 是否有 API ______

### 5.3 邮箱
- [ ] Outlook 桌面版: 是 / 否
- [ ] Foxmail: 是 / 否
- [ ] 网页邮箱 (单位邮箱 URL): ______

### 5.4 浏览器 / 政务系统
- [ ] 主用浏览器 (Edge / Chrome / 单位指定): ______
- [ ] 政务系统名称 + URL (5 个高频):
  - 1. ______ → ______
  - 2. ______ → ______
  - 3. ______ → ______
  - 4. ______ → ______
  - 5. ______ → ______

### 5.5 文档 / 工作流
- [ ] 主用 Office (微软 / WPS / OnlyOffice): ______
- [ ] 高频文件夹路径 (5 个):
  - 1. "我的工作文件夹" → ______
  - 2. "本周通知" → ______
  - 3. "会议记录" → ______
  - 4. "待办" → ______
  - 5. "归档" → ______

### 5.6 别名习惯 (Sir 平时怎么称呼)
- [ ] "记事本" / "Word" / "笔记" — 各对应什么真应用?
- [ ] "邮箱" — 是哪个客户端?
- [ ] "聊天软件" / "微信" / "工作群" — 各对应?
- [ ] 联系人称呼 (e.g. "王科长" "张主任" "小李") — 真姓名 / 真 ID?

### 5.7 高频场景 (Sir 想 Jarvis 一句话搞定的事, 排序)
> Sir 列 10-20 个最高频日常需求, 按重要性排:
- 1. _____________________ (例: "给王科长发收到了")
- 2. _____________________
- 3. _____________________
- ...

### 5.8 安全 / 隐私边界
- [ ] 哪些事 Jarvis **不准做** (e.g. 涉密文件 / 财务操作 / 群发消息)?
- [ ] 哪些事必须 **二次确认** (类似当前 dangerous_flag)?
- [ ] 是否担心 ASR 误识别 (e.g. "删除文件 X" 误听成 "删除文件 Y")?

---

## 六. 落地优先顺序 (Sir 信息齐后填)

### 阶段 A (~1 周): 应用 launcher + 文件检索
- l4_app_launcher_hands (基于 Sir 别名 vocab)
- l4_file_finder_hands (Everything / es CLI)
- intent_to_tool_map 扩 ~10 intent

### 阶段 B (~1 周): 通讯 (按 Sir 单位选)
- l4_wechat_hands / l4_wecom_hands / l4_dingtalk_hands (按 Sir 选)
- l4_email_hands (Outlook COM 或 mailto)
- 联系人 vocab + 模糊匹配

### 阶段 C (~3 天): 浏览器 + URL
- l4_browser_hands (基于 webbrowser 模块)
- url_vocab + 政务系统快捷
- 单步搜索 ("搜一下 X" → 浏览器开 + 自动 query)

### 阶段 D (~3 天): 截图 + 朗读 + 多媒体
- l4_screenshot_hands (mss)
- l4_speak_selection_hands (剪贴板朗读)
- 音乐 launcher

### 阶段 E (~3 天): 安全 + 测试
- 二次确认机制 (dangerous_flag 已有, 接 Sir 自定义 list)
- 端到端 testcase
- 真机 dogfood

**总计 ~3-4 周, 看 Sir 阶段 A 实测反馈后决定 B-E 调整**.

---

## 七. 风险 / 反例

| 风险 | 缓解 |
|---|---|
| Sir 误识别 (ASR 转写错 → 误执行 dangerous 动作) | 所有 risky/dangerous 动作必须 Sir 二次语音确认; 走 PROMISE tag 路径 (现有) |
| Sir 别名冲突 (e.g. "记事本"既指 notepad 也指 OneNote) | 别名 vocab 加上下文 priority + Sir 拒绝时学习 |
| 单位电脑不能装 Python | 整个 Jarvis 跑 Sir 私机, 远程控制单位电脑 (需 Sir 决断) — 或退出范围 |
| 政务系统 API 不开放 (常见) | wxauto / pyautogui 鼠标键盘模拟 (慢 + 不稳, 但能用) |
| 微信 wxauto 被封 (微信反自动化) | 准备 fallback (鼠标模拟 + 用户主操作 + Jarvis 提示) |

---

## 八. Sir 拍板路径

**Sir 实测 β.5.34/35/36 + 4 fix 稳定后, 步骤**:

1. Sir 填 §五 [WAITING FOR SIR INPUT] 表格 (5.1-5.8)
2. Cascade 据此填 §六 阶段 A 优先 intent + hands 实现细节
3. Sir 拍板阶段 A 优先级 → 落地
4. Sir 真机 dogfood 阶段 A 一周 → 反馈
5. Cascade 修 + 进阶段 B
6. 循环到入职前所有 Sir 高频场景覆盖

---

**当前状态**: ⏸️ 等 Sir 实测稳定 + 信息填表. Sir 给我 §五 信息后立刻动 §六.
