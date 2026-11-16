@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0..\..\modu-research-nodes"
".venv\Scripts\python.exe" -m mrn.dartdocs status
".venv\Scripts\python.exe" -m mrn.dartdocs verify
pause
