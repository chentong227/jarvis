@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

REM ============================================================================
REM   J.A.R.V.I.S. - 打包给朋友的 "干净版"
REM   双击即可，自动排除你的私人数据（聊天记录 / API key / 个人画像 / B 站凭证）
REM ============================================================================

cd /d "%~dp0"
title J.A.R.V.I.S. - 打包发布

echo.
echo ================================================
echo    J.A.R.V.I.S. 打包发布工具
echo ================================================
echo.
echo  这个工具会：
echo    1. 自动创建一个 "干净版" 副本
echo    2. 排除你的私人数据（聊天历史 / API key / 个人信息 / B 站凭证）
echo    3. 压缩成 zip 发给朋友
echo.
echo  排除清单：
echo    - .env                          ^(你的真实 API key^)
echo    - memory_pool/*.db              ^(你和 J.A.R.V.I.S. 的对话历史^)
echo    - jarvis_config/sir_profile.*   ^(J.A.R.V.I.S. 对你的画像^)
echo    - jarvis_config/bilibili_*      ^(B 站登录态^)
echo    - jarvis_config/screenshots/    ^(屏幕截图缓存^)
echo    - docs/runtime_logs/            ^(运行日志^)
echo    - docs/TODO_ARCHIVE.md          ^(你的开发笔记^)
echo    - .venv/  __pycache__/  .git/   ^(临时和环境产物^)
echo    - ffmpeg.exe / ffprobe.exe      ^(让朋友自己下载，太大^)
echo.
pause


REM ============================================================================
REM 计算输出目录名（带日期戳）
REM ============================================================================
for /f "tokens=2 delims==." %%I in ('"wmic os get localdatetime /value | findstr LocalDateTime"') do set DATESTAMP=%%I
set DATESTAMP=!DATESTAMP:~0,8!
set RELEASE_DIR=jarvis_release_!DATESTAMP!
set RELEASE_ZIP=jarvis_release_!DATESTAMP!.zip

REM 如果已存在，加随机后缀
if exist "!RELEASE_DIR!" (
    set RELEASE_DIR=!RELEASE_DIR!_!RANDOM!
    set RELEASE_ZIP=!RELEASE_DIR!.zip
)

echo.
echo [1/4] 准备输出目录: !RELEASE_DIR!
mkdir "!RELEASE_DIR!" 2>nul


REM ============================================================================
REM [2/4] 复制安全的文件（白名单）
REM ============================================================================
echo.
echo [2/4] 复制源码和必需文件...

REM === Python 源码（根目录）===
copy /Y jarvis_blood.py            "!RELEASE_DIR!\" > nul
copy /Y jarvis_enhanced.py         "!RELEASE_DIR!\" > nul
copy /Y jarvis_fuzzy_resolver.py   "!RELEASE_DIR!\" > nul
copy /Y jarvis_hippocampus.py      "!RELEASE_DIR!\" > nul
copy /Y jarvis_nerve.py            "!RELEASE_DIR!\" > nul
copy /Y jarvis_skill_registry.py   "!RELEASE_DIR!\" > nul
copy /Y jarvis_utils.py            "!RELEASE_DIR!\" > nul
copy /Y jarvis_vocal_cord.py       "!RELEASE_DIR!\" > nul
copy /Y l1_right_brain.py          "!RELEASE_DIR!\" > nul
copy /Y l3_left_brain.py           "!RELEASE_DIR!\" > nul
copy /Y l5_reflection_brain.py     "!RELEASE_DIR!\" > nul
echo     OK: 根目录 Python 源码

REM 如果拆分批次已完工，复制新文件
for %%f in (jarvis_safety.py jarvis_key_router.py jarvis_llm_reflector.py jarvis_env_probe.py jarvis_sensors.py jarvis_routing.py jarvis_memory_core.py jarvis_sentinels.py jarvis_conductor.py jarvis_return_sentinel.py jarvis_commitment_watcher.py jarvis_smart_nudge.py jarvis_chat_bypass.py jarvis_central_nerve.py jarvis_worker.py jarvis_ui.py) do (
    if exist "%%f" copy /Y "%%f" "!RELEASE_DIR!\" > nul
)

REM === l2_eyes_pool / l4_hands_pool / tools ===
xcopy /E /I /Y /Q l2_eyes_pool      "!RELEASE_DIR!\l2_eyes_pool"      > nul
xcopy /E /I /Y /Q l4_hands_pool     "!RELEASE_DIR!\l4_hands_pool"     > nul
if exist tools (
    xcopy /E /I /Y /Q tools         "!RELEASE_DIR!\tools"             > nul
)
echo     OK: 器官池目录

REM === tests/ 整个复制（朋友也可能想跑测试验证）===
xcopy /E /I /Y /Q tests             "!RELEASE_DIR!\tests"             > nul
echo     OK: 测试套件

REM === jarvis_config/ 只复制必需文件，跳过敏感数据 ===
mkdir "!RELEASE_DIR!\jarvis_config" 2>nul
if exist jarvis_config\os_landmarks.json (
    copy /Y jarvis_config\os_landmarks.json "!RELEASE_DIR!\jarvis_config\" > nul
)
echo     OK: jarvis_config 干净版（已排除 sir_profile / bilibili_auth 等）

REM === 安装 / 启动脚本 + 配置 + 文档 ===
copy /Y install.bat                "!RELEASE_DIR!\" > nul
copy /Y run.bat                    "!RELEASE_DIR!\" > nul
copy /Y make_release.bat           "!RELEASE_DIR!\" > nul
copy /Y README.md                  "!RELEASE_DIR!\" > nul
copy /Y requirements.txt           "!RELEASE_DIR!\" > nul
copy /Y requirements-dev.txt       "!RELEASE_DIR!\" > nul
copy /Y pyproject.toml             "!RELEASE_DIR!\" > nul
copy /Y .env.example               "!RELEASE_DIR!\" > nul
copy /Y .gitignore                 "!RELEASE_DIR!\" > nul
if exist jarvis_prompt.wav (
    copy /Y jarvis_prompt.wav      "!RELEASE_DIR!\" > nul
)
echo     OK: 配置文件 + 启动脚本 + README

REM === scripts/ 目录 ===
if exist scripts (
    xcopy /E /I /Y /Q scripts      "!RELEASE_DIR!\scripts"            > nul
    echo     OK: scripts 目录
)

REM === docs/ 只复制 README 类、跳过运行日志和归档 ===
mkdir "!RELEASE_DIR!\docs" 2>nul
REM 不复制 TODO_ARCHIVE.md（开发笔记）/ runtime_logs / funnel_logs
echo     OK: docs 干净版（已排除运行日志和开发归档）

REM === 创建空 memory_pool / 让朋友首次启动自动生成 ===
mkdir "!RELEASE_DIR!\memory_pool" 2>nul
echo. > "!RELEASE_DIR!\memory_pool\.gitkeep"
echo     OK: memory_pool 空目录（朋友首次启动自动创建数据库）


REM ============================================================================
REM [3/4] 安全检查 - 确保没有敏感文件混进去
REM ============================================================================
echo.
echo [3/4] 安全检查...

set SECURITY_VIOLATION=0
if exist "!RELEASE_DIR!\.env" (
    echo     危险: .env 进了 release！立即删除
    del /F /Q "!RELEASE_DIR!\.env"
    set SECURITY_VIOLATION=1
)
if exist "!RELEASE_DIR!\jarvis_config\sir_profile.json" (
    echo     危险: sir_profile.json 进了 release！立即删除
    del /F /Q "!RELEASE_DIR!\jarvis_config\sir_profile.json"
    set SECURITY_VIOLATION=1
)
if exist "!RELEASE_DIR!\jarvis_config\bilibili_auth.json" (
    echo     危险: bilibili_auth.json 进了 release！立即删除
    del /F /Q "!RELEASE_DIR!\jarvis_config\bilibili_auth.json"
    set SECURITY_VIOLATION=1
)
if exist "!RELEASE_DIR!\memory_pool\jarvis_memory.db" (
    echo     危险: 对话历史进了 release！立即删除
    del /F /Q "!RELEASE_DIR!\memory_pool\jarvis_memory.db"
    set SECURITY_VIOLATION=1
)

REM 清理所有 __pycache__
for /d /r "!RELEASE_DIR!" %%d in (__pycache__) do (
    if exist "%%d" rmdir /S /Q "%%d" 2>nul
)

if !SECURITY_VIOLATION! EQU 0 (
    echo     OK: 没有敏感文件混入
) else (
    echo     ^! 有问题但已清理完，请检查 install.bat / make_release.bat 白名单逻辑
)


REM ============================================================================
REM [4/4] 压缩成 zip
REM ============================================================================
echo.
echo [4/4] 压缩成 zip...
where tar > nul 2>&1
if errorlevel 1 (
    echo     警告: 你的 Windows 没有 tar 命令（需要 Win10 1803+）
    echo     已生成目录 "!RELEASE_DIR!"，请手动右键压缩成 zip
) else (
    tar -caf "!RELEASE_ZIP!" "!RELEASE_DIR!"
    if errorlevel 1 (
        echo     压缩失败，但目录 "!RELEASE_DIR!" 已生成，可手动压缩
    ) else (
        echo     OK: !RELEASE_ZIP! 已生成
        REM 计算 zip 大小
        for %%A in ("!RELEASE_ZIP!") do set ZIP_SIZE=%%~zA
        set /a ZIP_MB=!ZIP_SIZE!/1048576
        echo     大小: 约 !ZIP_MB! MB
    )
)


REM ============================================================================
REM 完工提示
REM ============================================================================
echo.
echo ================================================
echo    打包完成！
echo ================================================
echo.
echo  产物位置：
echo    目录: !CD!\!RELEASE_DIR!
if exist "!RELEASE_ZIP!" echo    压缩: !CD!\!RELEASE_ZIP!
echo.
echo  下一步：
echo    1. 把 !RELEASE_ZIP! 发给朋友
echo    2. 朋友解压后双击 install.bat 即可
echo.
echo  发送前最后检查（重要）：
echo    用记事本打开 !RELEASE_DIR!\.env.example
echo    确认里面全部都是 REPLACE_ME，没有你的真实 key
echo.
echo  即将打开 release 目录...
echo.
pause

start "" "!CD!\!RELEASE_DIR!"

exit /b 0
