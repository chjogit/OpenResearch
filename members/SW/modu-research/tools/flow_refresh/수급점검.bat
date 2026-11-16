@echo off
rem 수급 KIS 점검(Plan B 1단계): 받아서 대조만 하고 아무것도 쓰지 않음
set "R=D:\AI\Projects\2차_모두의리서치_cluade"
cd /d "%R%\modu-research-nodes"
if exist local-env.cmd call local-env.cmd
chcp 65001 >nul
".venv\Scripts\python.exe" -X utf8 "%R%\_tools\flow_refresh\flow_probe.py"
echo.
pause
