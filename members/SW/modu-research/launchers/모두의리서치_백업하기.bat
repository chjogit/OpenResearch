@echo off
rem 어디에 두어도 작동: 실제 위치는 아래 경로로 고정. 원본은 읽기만 하고 바꾸지 않음
set "R=D:\AI\Projects\2차_모두의리서치_cluade"
chcp 65001 >nul
"%R%\modu-research-nodes\.venv\Scripts\python.exe" -X utf8 "%R%\_tools\backup\backup.py"
echo.
pause
