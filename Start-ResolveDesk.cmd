@echo off
setlocal
cd /d "%~dp0"
title ResolveDesk - Local Support Workspace
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
  "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" launcher.py start --open
) else (
  python launcher.py start --open
)
if errorlevel 1 (
  echo.
  echo Setup help: open README.md and follow Start here.
  pause
)
