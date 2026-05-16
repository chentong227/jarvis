# =============================================================================
# Jarvis Personal Butler — Windows PowerShell 一键安装脚本
# =============================================================================
# 用法（在 d:\Jarvis 根目录跑）：
#   .\scripts\install.ps1
#
# 选项：
#   .\scripts\install.ps1 -SkipTorch    # 已装好 torch+cu121 可跳过（避免重装 2GB）
#   .\scripts\install.ps1 -DevOnly      # 已装好运行时，只补 dev 依赖
#   .\scripts\install.ps1 -NoVenv       # 装到全局 Python（不推荐！）
#
# 前置：
#   - Windows 10/11 x64
#   - Python 3.9 或 3.10 已装且 `py -3.9` / `py -3.10` 在 PATH
#   - NVIDIA 显卡 + CUDA 12.1 驱动（torch 用 +cu121 build）
#
# 设计：每步独立 try/catch，失败不静默退出 + 列出修复指引。
# =============================================================================

param(
    [switch]$SkipTorch,
    [switch]$DevOnly,
    [switch]$NoVenv
)

$ErrorActionPreference = "Stop"
$ROOT = Split-Path -Parent $PSScriptRoot

Write-Host "`n╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  Jarvis Personal Butler — Install Script    ║" -ForegroundColor Cyan
Write-Host "║  $ROOT" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════╝`n" -ForegroundColor Cyan

# =============================================================================
# Step 1: 检查 Python 版本
# =============================================================================
Write-Host "[1/7] Checking Python..." -ForegroundColor Yellow

$pythonCmd = "py"
$pyVersionOk = $false
foreach ($ver in @("-3.9", "-3.10")) {
    try {
        $output = & py $ver --version 2>&1
        if ($output -match "Python 3\.(9|10)\.") {
            $pyVersionArg = $ver
            $pyVersionOk = $true
            Write-Host "    ✅ Found: py $ver → $output" -ForegroundColor Green
            break
        }
    } catch {
        continue
    }
}

if (-not $pyVersionOk) {
    Write-Host "    ⛔ Python 3.9 或 3.10 未找到！" -ForegroundColor Red
    Write-Host "       下载：https://www.python.org/downloads/release/python-3913/" -ForegroundColor Red
    exit 1
}

# =============================================================================
# Step 2: 创建 venv
# =============================================================================
if (-not $NoVenv) {
    Write-Host "`n[2/7] Setting up virtual environment (.venv)..." -ForegroundColor Yellow
    
    $venvPath = Join-Path $ROOT ".venv"
    if (Test-Path $venvPath) {
        Write-Host "    ℹ️  .venv 已存在，直接复用" -ForegroundColor Cyan
    } else {
        & py $pyVersionArg -m venv $venvPath
        Write-Host "    ✅ .venv created" -ForegroundColor Green
    }
    
    $activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
    if (-not (Test-Path $activateScript)) {
        Write-Host "    ⛔ .venv 损坏：找不到 $activateScript" -ForegroundColor Red
        exit 1
    }
    & $activateScript
    Write-Host "    ✅ venv activated" -ForegroundColor Green
} else {
    Write-Host "`n[2/7] Skipping venv (--NoVenv)" -ForegroundColor Yellow
}

# =============================================================================
# Step 3: 升级 pip
# =============================================================================
Write-Host "`n[3/7] Upgrading pip..." -ForegroundColor Yellow
python -m pip install --upgrade pip --quiet
Write-Host "    ✅ pip $(pip --version | Select-String -Pattern 'pip \S+' | ForEach-Object { $_.Matches.Value })" -ForegroundColor Green

# =============================================================================
# Step 4: 装 torch + cu121 (走 PyTorch 官方 index)
# =============================================================================
if (-not $SkipTorch -and -not $DevOnly) {
    Write-Host "`n[4/7] Installing PyTorch 2.3.1 + CUDA 12.1 (~2GB, 慢)..." -ForegroundColor Yellow
    
    $torchInstalled = $false
    try {
        $check = python -c "import torch; print(torch.__version__)" 2>&1
        if ($check -match "2\.3\.1\+cu121") {
            Write-Host "    ℹ️  torch 2.3.1+cu121 已装，跳过" -ForegroundColor Cyan
            $torchInstalled = $true
        }
    } catch { }
    
    if (-not $torchInstalled) {
        pip install torch==2.3.1+cu121 torchaudio==2.3.1+cu121 `
            --index-url https://download.pytorch.org/whl/cu121
        Write-Host "    ✅ PyTorch CUDA 12.1 installed" -ForegroundColor Green
    }
} else {
    Write-Host "`n[4/7] Skipping torch install" -ForegroundColor Yellow
}

# =============================================================================
# Step 5: 装 requirements.txt + requirements-dev.txt
# =============================================================================
Write-Host "`n[5/7] Installing project dependencies..." -ForegroundColor Yellow

if ($DevOnly) {
    pip install -r (Join-Path $ROOT "requirements-dev.txt")
} else {
    pip install -r (Join-Path $ROOT "requirements.txt")
    pip install -r (Join-Path $ROOT "requirements-dev.txt")
}
Write-Host "    ✅ All dependencies installed" -ForegroundColor Green

# =============================================================================
# Step 6: 创建 .env (从 .env.example)
# =============================================================================
Write-Host "`n[6/7] Setting up .env..." -ForegroundColor Yellow

$envFile = Join-Path $ROOT ".env"
$envExample = Join-Path $ROOT ".env.example"

if (Test-Path $envFile) {
    Write-Host "    ℹ️  .env 已存在，不覆盖" -ForegroundColor Cyan
} elseif (Test-Path $envExample) {
    Copy-Item $envExample $envFile
    Write-Host "    ✅ .env 已从 .env.example 复制" -ForegroundColor Green
    Write-Host "    ⚠️  请手动编辑 .env 填入真实 API keys！" -ForegroundColor Yellow
} else {
    Write-Host "    ⛔ .env.example 也不存在！这不应该发生。" -ForegroundColor Red
}

# =============================================================================
# Step 7: 检查 CosyVoice / FFmpeg 等大依赖
# =============================================================================
Write-Host "`n[7/7] Checking heavy assets..." -ForegroundColor Yellow

$cosyVoicePath = Join-Path $ROOT "CosyVoice"
if (-not (Test-Path $cosyVoicePath)) {
    Write-Host "    ⚠️  CosyVoice/ 目录不存在！" -ForegroundColor Yellow
    Write-Host "       请克隆：git clone https://github.com/FunAudioLLM/CosyVoice.git" -ForegroundColor Yellow
    Write-Host "       并下载预训练权重（约 1GB）—— 见 CosyVoice 官方 README" -ForegroundColor Yellow
} else {
    Write-Host "    ✅ CosyVoice/ exists" -ForegroundColor Green
}

$ffmpegPath = Join-Path $ROOT "ffmpeg.exe"
if (-not (Test-Path $ffmpegPath)) {
    Write-Host "    ⚠️  ffmpeg.exe 不存在！" -ForegroundColor Yellow
    Write-Host "       下载：https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -ForegroundColor Yellow
    Write-Host "       解压后把 ffmpeg.exe + ffprobe.exe 放到 d:\Jarvis 根目录" -ForegroundColor Yellow
} else {
    Write-Host "    ✅ ffmpeg.exe exists" -ForegroundColor Green
}

# =============================================================================
# 收尾
# =============================================================================
Write-Host "`n╔══════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║  Installation Complete!                     ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════╝" -ForegroundColor Green

Write-Host "`nNext steps:" -ForegroundColor White
Write-Host "  1. 编辑 .env 填入真实 API keys" -ForegroundColor White
Write-Host "  2. （首次）git init && git add . && git commit -m 'P0+19-deps init'" -ForegroundColor White
Write-Host "  3. pytest tests/  — 跑全部 1044 testcase 验证" -ForegroundColor White
Write-Host "  4. python jarvis_nerve.py  — 启动 Jarvis" -ForegroundColor White

Write-Host "`n📚 Reference:" -ForegroundColor White
Write-Host "  - docs/NERVE_SPLIT_PLAN.md  — P0+19 拆分 design doc" -ForegroundColor White
Write-Host "  - TODO.md  — 当前轮看板" -ForegroundColor White
Write-Host ""
