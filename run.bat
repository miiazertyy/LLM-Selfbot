@echo off
REM run.bat — Start the LLM Selfbot on Windows
REM
REM Usage:
REM   run.bat            -> auto-detect mode from config.yaml
REM   run.bat discord    -> Discord only
REM   run.bat snapchat   -> Snapchat (Python bridge + Node.js runner)
REM   run.bat both       -> Discord + Snapchat

setlocal
set MODE=%1
if "%MODE%"=="" set MODE=auto

cd /d "%~dp0"

REM ── Python deps ──────────────────────────────────────────────────────────────
python -c "import discord" 2>nul || (
    echo [run.bat] Installing Python dependencies...
    call pip install -r requirements.txt
)

REM ── Telegram controller ──────────────────────────────────────────────────────
REM main.py launches it in THIS same console (alongside the bot) when a token is
REM set — no separate window. Disable via TELEGRAM_AUTOSTART=false in .env.

REM ── Mode dispatch ─────────────────────────────────────────────────────────────
if /i "%MODE%"=="discord" goto :run_discord
if /i "%MODE%"=="snapchat" goto :run_snapchat
if /i "%MODE%"=="both" goto :run_both
if /i "%MODE%"=="auto" goto :run_auto

echo Usage: run.bat [discord^|snapchat^|both]
exit /b 1

:run_discord
echo [run.bat] Starting Discord platform...
python main.py discord
goto :end

:run_snapchat
echo [run.bat] Installing Node.js deps if needed...
if not exist "platforms\snapchat\node_modules" (
    cd platforms\snapchat
    call npm install
    cd ..\..
)
echo [run.bat] Starting Snapchat (bridge + browser runner in one window)...
REM main.py launches the Node runner itself, so everything shares this console.
python main.py snapchat
goto :end

:run_both
echo [run.bat] Installing Node.js deps if needed...
if not exist "platforms\snapchat\node_modules" (
    cd platforms\snapchat
    call npm install
    cd ..\..
)
echo [run.bat] Starting Discord + Snapchat (bridge launches the browser runner)...
REM main.py launches the Snapchat Node runner itself — no separate window needed.
python main.py both
goto :end

:run_auto
REM Ask Python what mode config.yaml says, then dispatch properly
for /f "delims=" %%M in ('python -c "from utils.helpers import load_config; c=load_config(); s=c.get('snapchat',{}).get('enabled',False); d=c.get('discord',{}).get('enabled',True); print('both' if s and d else 'snapchat' if s else 'discord')"') do set DETECTED_MODE=%%M
echo [run.bat] Auto-detected mode: %DETECTED_MODE%
if /i "%DETECTED_MODE%"=="discord"  goto :run_discord
if /i "%DETECTED_MODE%"=="snapchat" goto :run_snapchat
if /i "%DETECTED_MODE%"=="both"     goto :run_both
REM fallback
python main.py
goto :end

:end
endlocal
