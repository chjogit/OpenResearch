@echo off
rem 원천 자료(_sources) 보관본을 만들어 구글 드라이브에 둡니다. 원본은 읽기만 하고 바꾸지 않음
set "R=D:\AI\Projects\2차_모두의리서치_cluade"
chcp 65001 >nul
"%R%\modu-research-nodes\.venv\Scripts\python.exe" -X utf8 "%R%\_tools\backup\backup_sources.py"
echo.
pause
