# 一键启动 Jarvis Web Dashboard
# 用法: 双击此 .ps1 或在 PowerShell 跑 .\dashboard.ps1
# 会自动开浏览器到 http://127.0.0.1:8765
$env:PYTHONIOENCODING = 'utf-8'
Set-Location $PSScriptRoot
python scripts/jarvis_dashboard_web.py
