@echo off
REM scripts/run.bat, Start the LLMSelfbot on Windows
REM
REM Usage:
REM   scripts\run.bat              -> supervisor (web UI + platform workers)
REM   scripts\run.bat discord      -> Discord only (no web UI)
REM   scripts\run.bat snapchat     -> Snapchat only (no web UI)
REM   scripts\run.bat both         -> Discord + Snapchat (no web UI)

setlocal
set MODE=%1

REM Anchor to the repo root (this file lives in scripts/)
cd /d "%~dp0.."

REM ── Python deps ──────────────────────────────────────────────────────────────
python -c "import discord" 2>nul || (
    echo [run.bat] Installing Python dependencies...
    call pip install -r requirements.txt
)

REM ── Mode dispatch ─────────────────────────────────────────────────────────────
if /i "%MODE%"=="discord" goto :run_discord
if /i "%MODE%"=="snapchat" goto :run_snapchat
if /i "%MODE%"=="both" goto :run_both
if /i "%MODE%"=="auto" goto :run_auto
if /i "%MODE%"=="" goto :run_supervisor

echo Usage: run.bat [discord^|snapchat^|both]
exit /b 1

:run_supervisor
echo [run.bat] Starting supervisor (web UI + workers)...
python main.py
goto :end

:run_discord
echo [run.bat] Starting Discord platform...
python main.py discord
goto :end

:run_snapchat
echo [run.bat] Installing Node.js deps if needed...
if not exist "app\platforms\snapchat\node_modules" (
    cd app\platforms\snapchat
    call npm install
    cd ..\..\..
)
echo [run.bat] Starting Snapchat (bridge + browser runner in one window)...
python main.py snapchat
goto :end

:run_both
echo [run.bat] Installing Node.js deps if needed...
if not exist "app\platforms\snapchat\node_modules" (
    cd app\platforms\snapchat
    call npm install
    cd ..\..\..
)
echo [run.bat] Starting Discord + Snapchat (bridge launches the browser runner)...
python main.py both
goto :end

:run_auto
REM Ask Python what mode config.yaml says, then dispatch properly
for /f "delims=" %%M in ('python -c "from app.utils.helpers import load_config; c=load_config(); s=c.get('snapchat',{}).get('enabled',False); d=c.get('discord',{}).get('enabled',True); print('both' if s and d else 'snapchat' if s else 'discord')"') do set DETECTED_MODE=%%M
echo [run.bat] Auto-detected mode: %DETECTED_MODE%
if /i "%DETECTED_MODE%"=="discord"  goto :run_discord
if /i "%DETECTED_MODE%"=="snapchat" goto :run_snapchat
if /i "%DETECTED_MODE%"=="both"     goto :run_both
REM fallback
python main.py
goto :end

:end
endlocal
