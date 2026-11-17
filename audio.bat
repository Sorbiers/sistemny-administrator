@echo off
rem Builds the audio version: chapters\NN.md -> site\audio\NN.mp3
rem with the Russian TTS of Gogolium (F:\Gogol: num2ru + stress dictionary + Silero, voice eugene).
rem Resumable: already voiced paragraphs are kept in audio_cache and skipped.
rem Usage:  audio            all chapters
rem         audio 1-3        chapters 1..3
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PY=F:\Gogol\app\tts\venv\Scripts\python.exe
if not exist "%PY%" (
  echo Gogolium TTS environment not found: %PY%
  pause
  exit /b 1
)
if "%~1"=="" (
  "%PY%" build_audio.py
) else (
  "%PY%" build_audio.py --chapters %1
)
if errorlevel 1 (
  echo Audio build failed.
  pause
  exit /b 1
)
python build_site.py
pause
