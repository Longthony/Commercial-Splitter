@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
title Commercial Splitter 4.9.0 Build
where py >nul 2>&1
if not errorlevel 1 (set "PY=py -3") else (set "PY=python")
%PY% -m venv .build-venv || goto fail
".build-venv\Scripts\python.exe" -m pip install -r requirements.txt "pyinstaller>=6.10,<7" || goto fail
set "BIN="
if exist "tools\ffmpeg.exe" set "BIN=--add-binary=tools\ffmpeg.exe;tools"
if exist "tools\ffprobe.exe" set "BIN=%BIN% --add-binary=tools\ffprobe.exe;tools"
if exist "tools\ffplay.exe" set "BIN=%BIN% --add-binary=tools\ffplay.exe;tools"
".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name "Commercial Splitter" --icon=assets\commercial_splitter.ico --add-data "assets\commercial_splitter.ico;." --collect-all PySide6.QtMultimedia --collect-all PySide6.QtMultimediaWidgets %BIN% src\Commercial_Splitter.py || goto fail
echo Build complete: dist\Commercial Splitter.exe
pause
exit /b 0
:fail
echo Build failed.
pause
exit /b 1
