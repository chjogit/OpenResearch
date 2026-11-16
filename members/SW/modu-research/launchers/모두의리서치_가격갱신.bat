@echo off
rem 가격 사본 갱신(연구용): 한국투자증권 일별 시세로 빈 날을 채운 새 사본을 만든다. 원래 사본은 그대로
set "R=D:\AI\Projects\2차_모두의리서치_cluade"
cd /d "%R%\modu-research-nodes"
if exist local-env.cmd call local-env.cmd
chcp 65001 >nul
".venv\Scripts\python.exe" -X utf8 "%R%\_tools\price_refresh\price_refresh.py"
echo.
pause
