# J.A.R.V.I.S. — 个人桌面 AI 助理

> 仿钢铁侠 J.A.R.V.I.S. 的 Windows 本地 AI 助理。
> 语音唤醒、英语对话、桌面操作、长期记忆、智能轻推。

---

## ⚠️ 安装前必读：你的电脑能跑吗？

J.A.R.V.I.S. 不是普通聊天 App，对硬件和网络有要求。**5 个条件必须全部满足**：

| 要求 | 检查办法 |
|---|---|
| **Windows 10/11 64 位** | 设置 → 系统 → 关于 → "64 位操作系统" |
| **NVIDIA 显卡 + 8GB+ 显存** | 任务管理器 → 性能 → GPU 0 → 看品牌和显存（推荐 RTX 3060 12G / 4060Ti / 4070 SUPER 这类） |
| **CUDA 12.1 兼容驱动** | 在 NVIDIA 官网装最新驱动即可，通常自带 |
| **16GB+ 内存** | 任务管理器 → 性能 → 内存 |
| **能访问 Google API** | 在浏览器打开 https://ai.google.dev，能打开就 OK；中国大陆需要代理 |

❌ **以下情况跑不起来**：
- 没有 NVIDIA 显卡（只有核显 / AMD / Mac）
- 显存 4GB 以下
- Windows 7 / 8 / 32 位系统
- 完全不能访问 Google

如果你不满足，建议放弃，找别的 AI 助理项目。

---

## 🚀 安装步骤（4 步）

### 第 1 步：装 Python 3.9

> 已经有 Python 3.9 或 3.10 的话可以跳过。

1. 打开浏览器访问 https://www.python.org/downloads/release/python-3913/
2. 下滑到 **"Files"** 区域
3. 点击 **"Windows installer (64-bit)"** 下载（约 28MB）
4. 双击下载的安装包
5. **务必勾选**："Add Python to PATH"（在窗口下方）
6. 点 "Install Now"，等 1-2 分钟装完

### 第 2 步：申请 API Keys

J.A.R.V.I.S. 是基于大模型的，所以你需要两个家的 API key：

#### 🔑 OpenRouter（5 个 key）—— 用于主脑对话

1. 浏览器打开 https://openrouter.ai/keys
2. 用 Google 账号或 GitHub 账号登录
3. 点击 **"Create Key"** 按钮，重复 5 次，每次起个名字（如 jarvis_1 ~ jarvis_5）
4. 每个 key 生成后**立刻复制**到记事本（关掉就再也看不到了）
5. 充值 $5-10 即可玩很久（每个对话约 $0.001）

#### 🔑 Google AI Studio（3 个 key）—— 用于记忆 embedding 和小调用

1. 浏览器打开 https://aistudio.google.com/apikey
2. 用 Google 账号登录
3. 点击 **"Get API Key"** → **"Create API key"**
4. 重复 3 次（最好用 3 个不同 Google 账号或不同 Project，避免一个被封全废）
5. 复制 3 个 key 到记事本

### 第 3 步：双击 `install.bat`

1. 解压收到的 zip 到一个文件夹（建议 `D:\Jarvis`，避免中文路径）
2. 进入文件夹，**双击 `install.bat`**
3. 跟着提示走，大约 10-15 分钟（首次装 PyTorch 慢，约 2GB）
4. 安装末尾会自动打开 `.env` 文件 —— 把 8 处 `REPLACE_ME` 换成你刚刚复制的真实 key
5. 保存关闭

### 第 4 步：双击 `run.bat` 启动

J.A.R.V.I.S. 启动后会显示一个"呼吸灯"窗口，对它说英语即可对话：

- "Jarvis, what time is it?"
- "Remind me to drink water at 3 PM"
- "Open Chrome"
- "How's my system running?"

退出：点窗口关闭按钮 或 按 Ctrl+C。

---

## 🐛 常见问题

### Q: 双击 install.bat 后窗口一闪就没了

**A:** 你的 Windows 把 `.bat` 当病毒拦了。右键 install.bat → "以管理员身份运行"。如果还不行，右键 → 属性 → 解除锁定。

### Q: 报错 "请先装 Python 3.9 或 3.10"

**A:** 按照第 1 步重新装 Python，**一定要勾选 "Add Python to PATH"**。

### Q: PyTorch 下载超慢 / 失败

**A:** 网络问题。可以：
1. 挂代理后重试
2. 或换网络（手机热点 / 公司网络）
3. 或一直等（慢但能成）

### Q: 启动后报错 "CUDA out of memory"

**A:** 显存不够。关掉其他占显存的程序（游戏 / Chrome / Stable Diffusion 等）。如果显存只有 6GB 以下，J.A.R.V.I.S. 跑不动。

### Q: J.A.R.V.I.S. 听不到我说话 / 不回应

**A:** 检查：
1. 麦克风权限：Windows 设置 → 隐私 → 麦克风 → 允许桌面应用访问
2. 默认麦克风：右键音量图标 → "声音设置" → 输入设备选你的麦克风
3. 说话用英语（J.A.R.V.I.S. 主语英语）

### Q: 听不到 J.A.R.V.I.S. 说话

**A:** 检查：
1. 系统音量没静音
2. 默认播放设备选对了
3. 第一次启动需要等 30 秒加载 TTS 模型，请耐心

### Q: API 错误 / "403 Permission Denied"

**A:** 你的 API key 配额用完或被封。去 OpenRouter / Google AI Studio 控制台检查。Google 的 key 偶尔会因为账号问题被封整个 Project，所以建议第 2 步申请时**用不同 Google 账号**。

### Q: 我没有 NVIDIA 显卡能跑吗？

**A:** 不行。J.A.R.V.I.S. 的语音合成（CosyVoice）必须 GPU。CPU 版本没做也跑不动。

### Q: 必须每次双击 run.bat 才能用？能不能开机自启？

**A:** 现在版本必须手动启动。后续可能会加托盘常驻模式（路线 B / 轴 4）。

### Q: 我的对话历史会上传到云端吗？

**A:** 不会。J.A.R.V.I.S. 的"记忆"全部存在本地 `memory_pool/jarvis_memory.db` 文件里（SQLite 数据库）。但你说的话会发送给 OpenRouter / Google API 用于生成回复，那部分隐私规则参考它们的政策。

---

## 📁 文件结构（你需要知道的）

```
Jarvis/
├── install.bat              ← 双击装依赖（首次用）
├── run.bat                  ← 双击启动 J.A.R.V.I.S.
├── README.md                ← 本文件
├── .env.example             ← API key 模板
├── .env                     ← 装完后会创建，你填的真实 key 在这里
│                              ⚠️ 永远不要把这个文件发给别人！
├── requirements.txt         ← 依赖清单
├── jarvis_nerve.py          ← 主程序
├── jarvis_*.py / l*_*.py    ← 各种"器官"模块（左脑/右脑/眼睛/手）
└── memory_pool/             ← 你的对话历史和记忆（SQLite 数据库）
```

---

## ⚠️ 隐私 & 安全

- **永远不要分享 `.env` 文件**：里面是你的 API key，等于你的钱
- **永远不要分享 `memory_pool/` 目录**：里面是你和 J.A.R.V.I.S. 的对话历史
- **永远不要分享 `jarvis_config/sir_profile.json`**：里面是 J.A.R.V.I.S. 总结的你的画像（可能包含个人信息）
- **分享/打包前**：双击 `make_release.bat`（如果有），它会自动生成"干净版"压缩包，排除上面这些私人数据

---

## 🔗 致谢

- **CosyVoice**（语音合成）：https://github.com/FunAudioLLM/CosyVoice
- **funasr / SenseVoice**（语音识别）：https://github.com/modelscope/FunASR
- **OpenRouter**（LLM 路由）：https://openrouter.ai
- **Google Gemini**：https://aistudio.google.com

---

> 这个项目是单人开发的"垂直 AI 助理"，不是通用 AGI 框架。
> 它做一件事：在 Windows 桌面环境，做一个能"言出必行"、不撒谎、记得住、懂主人的 J.A.R.V.I.S.。
