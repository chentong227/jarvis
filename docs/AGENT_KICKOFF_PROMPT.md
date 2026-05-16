# Jarvis Agent Kickoff Prompt — 开新窗口告诉 Agent 这段

> **用法**：在 Cursor 中打开新对话窗口，把下面「📋 Sir 复制粘贴版」整段贴给 Agent。
> Agent 会自己读 `TODO.md` + `docs/NERVE_SPLIT_PLAN.md` 然后按 sub-step 顺序往下推。

---

## 📋 Sir 复制粘贴版（基础版）

```
按 TODO.md「下一轮规划：P0+19 — Nerve 拆分 + 依赖锁定」段的 17 个 sub-step 顺序往下推。

具体规则：
1. 先读 TODO.md 全文 + docs/NERVE_SPLIT_PLAN.md（design doc）找到下一个 ⏳ 的 sub-step
2. 按 design doc 里描述的步骤做这一个 sub-step（不要跳步、不要并行做多个）
3. 完成后：
   - 跑 python -c "import jarvis_nerve" 冒烟（5s 内必通）
   - 跑 pytest tests/ 全测全绿
   - 把 TODO.md 该 sub-step 状态改 ✅ + 加完工日期
   - git commit -m "[P0+19-X] <主题> — 净减 N 行"
4. 如果跑测失败：git reset --hard HEAD~1 回滚 + 在 TODO.md 该 sub-step 备注里写失败原因 → 停下来等我介入
5. 遇到这 3 件事必须停下来等我手动做：
   - rotate API keys（OpenRouter / Google 控制台）
   - 填 .env 真实 keys
   - 启动 Jarvis 实测一轮对话（验收用）
6. 每个 sub-step 之间汇报一次进度
```

---

## 📋 Sir 复制粘贴版（详细版 — 指定具体 sub-step）

如果想让 Agent 只做某一步（比如只跑 deps 收尾或只跑 split 中间某批）：

```
请你只做 TODO.md 的 sub-step <P0+19-X>。

要求：
- 严格按 docs/NERVE_SPLIT_PLAN.md §<对应章节> 描述的步骤
- 完成所有 6 步「每批通用收尾」（搬代码 / 加垫层 / corpus 加文件名 / 冒烟 / 全测 / commit）
- 失败回滚不静默：git reset --hard HEAD~1 + TODO.md 写原因
- 完工后 stop 等我看下一步
```

---

## ⚠️ Sir 必须手动做的 3 件事（Agent 替不了）

### 1. API Key Rotate（在 P0+19-deps 阶段做）

打开浏览器：
- OpenRouter：https://openrouter.ai/keys
  - 创建 5 个新 key（不要先删旧的）
  - 验通新 key 后再删旧的
- Google AI Studio：https://aistudio.google.com/apikey
  - 创建 3 个新 key（来自**不同 Google Project** 以防 PROJECT_DENIED 一损俱损）
  - 验通新 key 后再删旧的

### 2. 编辑 .env 填真实 key

```powershell
# 在 d:\Jarvis 跑：
Copy-Item .env.example .env
notepad .env   # 把 8 个 REPLACE_ME 替换成真实 keys
```

### 3. 每批完工后的 Sir 实测

P0+19-final 验收必须 Sir 实际启动 Jarvis 跟它对话一轮：
- "现在几点"
- "明早 8 点提醒我做某事"
- "列出代办"

只有 Agent 跑测全绿是不够的（麦克风 / TTS 物理链路它测不了）。

---

## 🚀 第一次启动建议（首次跑 install.ps1）

如果是干净的新机器或新 venv：

```powershell
# 在 d:\Jarvis 根目录
.\scripts\install.ps1
```

如果当前 venv 已经有 torch 等大依赖、只想补齐新文件：

```powershell
.\scripts\install.ps1 -SkipTorch -DevOnly
```

完工后：

```powershell
git init                                  # 首次进入 git 管理
git add .gitignore                        # 先加 .gitignore 保护敏感文件
git status                                # 验证 .env / bilibili_auth.json 等已被排除
git add .
git commit -m "[P0+19-deps] init repo + lockfile + .env scaffold"
```

---

## 📦 当前 P0+19-deps 产物清单（已就绪，等你填 .env + rotate keys）

| 文件 | 用途 | 大小 |
|---|---|---|
| `requirements.txt` | 运行时依赖（25 个核心包，锁真实版本） | ✅ |
| `requirements-dev.txt` | 开发依赖（pytest + ruff） | ✅ |
| `pyproject.toml` | 项目元信息 + pytest / ruff 配置 | ✅ |
| `.env.example` | 8 个 API key 模板（5 OR + 3 Google） | ✅ |
| `.env` | **Sir 需手动从 example 复制并填真实 key** | ⏳ |
| `.gitignore` | 排除 secrets / runtime / 大资产 / venv | ✅ |
| `scripts/install.ps1` | PowerShell 一键安装脚本 | ✅ |
| `jarvis_config/keys.py` | 从 .env 加载 keys 的 loader（带友好错误提示） | ✅ |
| `requirements.frozen.txt` | pip freeze 全量备份（391 包，本地参考用，**不入 git**） | ✅ |

剩下 Sir 需要做：
1. ⏳ rotate 8 个旧 keys（OpenRouter 控制台 5 + Google Console 3）
2. ⏳ `Copy-Item .env.example .env` + 填真实 keys
3. ⏳ 验证：`python -c "from jarvis_config.keys import load_keys; print(load_keys())"`
4. ⏳ `git init && git add . && git commit -m "[P0+19-deps] init"`
5. ⏳ 把旧硬编码 key（`jarvis_nerve.py:17445-17452`）改为从 `keys.py` 读取
   - 这一步可以让 Agent 做（很机械），但要 Sir 已经填好 .env 才能跑通
