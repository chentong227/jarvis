@echo off
REM [P0+20-β.2.9.13 / 2026-05-18] Sir 实测痛点修: pythonw 静默失败 Sir 看不到窗口
REM
REM 默认: python.exe + 普通 console (有 error 能看见 + 看到启动 log)
REM --quiet 选项: 用 pythonw.exe 隐藏 console (适合稳定后日常用)
REM
REM 用法:
REM   双击 scripts\jarvis_dashboard.cmd        ← 带 console, 首次/排错用
REM   scripts\jarvis_dashboard.cmd --quiet     ← pythonw, 隐藏 console

cd /d "%~dp0\.."

REM 解析 --quiet 选项 (放任意位置都行)
set USE_PYW=0
set ARGS=
:argloop
if "%~1"=="" goto :done
if /i "%~1"=="--quiet" (
    set USE_PYW=1
) else (
    set ARGS=%ARGS% %1
)
shift
goto :argloop
:done

if "%USE_PYW%"=="1" (
    where pythonw.exe >nul 2>&1
    if not errorlevel 1 (
        echo [启动] pythonw.exe 隐藏模式 ^(无 console^)...
        start "" pythonw.exe scripts\jarvis_dashboard.py %ARGS%
        goto :eof
    )
    echo [警告] 未找到 pythonw.exe, 回退 python.exe 带 console
)

REM 默认路径 — python.exe 带 console, Sir 能看见 stdout + error
echo ====================================================================
echo  J.A.R.V.I.S. Dashboard 启动 (python.exe 带 console)
echo  console 显示启动 log + error. 稳定后用 --quiet 隐藏.
echo ====================================================================
python.exe scripts\jarvis_dashboard.py %ARGS%
if errorlevel 1 (
    echo.
    echo ====================================================================
    echo  [错误] dashboard 启动失败, exit code %errorlevel%
    echo  上面 stdout/stderr 应有详细错误.
    echo ====================================================================
    pause
)
