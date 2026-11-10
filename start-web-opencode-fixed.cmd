@echo off
cd /d "%~dp0"
set "SYSTEM_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%SYSTEM_PYTHON%" (
  echo Python 3.12 was not found at %SYSTEM_PYTHON%.
  pause
  exit /b 1
)
if not exist "backend\.venv\Lib\site-packages\uvicorn" (
  echo Backend dependencies are missing. See the web OpenCode guide.
  pause
  exit /b 1
)
if not exist "frontend\dist\index.html" (
  echo The frontend has not been built. See the web OpenCode guide.
  pause
  exit /b 1
)
set "PYTHONPATH=%CD%\backend\.venv\Lib\site-packages"
echo Starting graduation assistant at http://127.0.0.1:8012/
"%SYSTEM_PYTHON%" -m uvicorn backend.app.web_opencode_fixed:app --host 127.0.0.1 --port 8012
pause
