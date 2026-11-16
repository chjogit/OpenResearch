@echo off
cd /d "%~dp0"
if exist local-env.cmd call local-env.cmd
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\manage.ps1 start
