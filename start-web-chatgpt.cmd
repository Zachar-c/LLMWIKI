@echo off
cd /d "%~dp0"
set "SYSTEM_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%SYSTEM_PYTHON%" (
  echo Python 3.12 was not found. See the startup guide.
  pause
  exit /b 1
)
if not exist "backend\.venv\Lib\site-packages\uvicorn" (
  echo Backend dependencies are missing. See the startup guide.
  pause
  exit /b 1
)
if not exist "frontend\dist\index.html" (
  echo Build the frontend first with npm run build.
  pause
  exit /b 1
)
where codex >nul 2>nul
if errorlevel 1 (
  if not defined GRADUATION_CODEX_CLI (
    echo Codex was not found. Install Codex or set GRADUATION_CODEX_CLI.
    pause
    exit /b 1
  )
)
set "PYTHONPATH=%CD%\backend\.venv\Lib\site-packages"
echo Starting graduation assistant with ChatGPT / GPT-6 Luna at http://127.0.0.1:8012/
"%SYSTEM_PYTHON%" -m uvicorn backend.app.web_chatgpt:app --host 127.0.0.1 --port 8012
pause
