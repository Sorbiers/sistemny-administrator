@echo off
rem Rebuilds the site from chapters and serves it locally.
rem Stop the server: close this window or press Ctrl+C.
cd /d "%~dp0"

set PORT=8765

where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install Python 3 from python.org and tick "Add to PATH".
  pause
  exit /b 1
)

set PYTHONIOENCODING=utf-8
python build_site.py
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)

echo.
echo Site: http://127.0.0.1:%PORT%/
echo To stop: close this window or press Ctrl+C.
echo.
start "" "http://127.0.0.1:%PORT%/"
python -m http.server %PORT% --bind 127.0.0.1 --directory site
