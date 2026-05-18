@echo off
REM [P0+20-β.2.9.9 / 2026-05-18] 贾维斯看板启动器 — 无 console / 不抢焦点
REM Sir 10:43 反馈: "PowerShell 窗口不隐藏" — 用 pythonw.exe 不拉黑窗口
REM
REM 用法: 双击此 .cmd 或 `scripts\jarvis_dashboard.cmd`

cd /d "%~dp0\.."

REM 优先 pythonw.exe (无 console). 系统 PATH 上一般有.
where pythonw.exe >nul 2>&1
if %ERRORLEVEL%==0 (
    start "" pythonw.exe scripts\jarvis_dashboard.py %*
) else (
    REM fallback: python.exe + WindowStyle=Minimized
    start /min "" python.exe scripts\jarvis_dashboard.py %*
)
