@echo off
rem 모두의리서치 화면 자동 녹화(보이지 않는 창). 시연이 켜져 있어야 합니다
set "R=D:\AI\Projects\2차_모두의리서치_cluade"
chcp 65001 >nul
cd /d "%R%\_tools\recorder"
".venv\Scripts\python.exe" -X utf8 record_demo.py %*
echo.
start "" "%R%\_tools\recorder\out"
pause
